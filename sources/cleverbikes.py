"""
Quelle: cleverbikes.de (Haendler fuer generalueberholte/refurbished
E-Bikes, gefunden ueber Kleinanzeigen-Verkaeuferprofile).

Struktur echt gegen die Live-Seite geprueft (Stand 21.09.2026):
- Shopify-Shop. Die normale Volltextsuche /search?q=<begriff>&type=product
  filtert NICHT serverseitig (live getestet: "cube" und "cube ams hybrid
  one44" lieferten identische 68 Treffer, darunter ein voellig fremdes
  "Bulls Sturmvogel EVO 5F Belt") - stattdessen wird die eingebaute
  Predictive-Search-JSON-Schnittstelle genutzt:
  /search/suggest.json?q=<begriff>&resources[type]=product&resources[limit]=10
  Die filtert korrekt (live gegen "santa cruz heckler" -> 1 Treffer,
  "zzz_kein_treffer_xyz123" -> 0 Treffer bestaetigt) und liefert Titel,
  Preis, Handle/URL, Vendor - ABER kein Zustand und keine Rahmengroesse.
  resources[limit] wird von Shopify fuer diesen Endpunkt hart auf 10
  gedeckelt (auch mit limit=50 kamen nur 10 zurueck) - bei den engen,
  modellspezifischen Suchbegriffen aus config/models.yaml bisher nie ein
  Problem, da die echten Treffer weit unter 10 liegen.
- Zustand + Rahmengroesse stehen nur auf der Produktseite: eine Tabelle
  mit <span class="cbp__sr-l">Label</span><span class="cbp__sr-v">Wert</span>
  -Paaren enthaelt u.a. "Zustand" (Freitext wie "Gut") und "Rahmengroesse"
  (in cm, z.B. "42 cm" - kein Buchstaben-Groesse wie S/M/L). Ausserdem
  liegt ein <script type="application/ld+json"> mit @type "Product" vor
  (schema.org), das den exakten Preis (offers.price) und
  itemCondition="https://schema.org/RefurbishedCondition" strukturiert
  liefert - itemCondition ist bei allen bisher geprueften Artikeln
  identisch (die Seite wirbt site-weit mit "1 Jahr Garantie auf alle
  refurbished Bikes"), daher wie bei anderen reinen Refurbished-Haendlern
  (rebike.com, staterabikes.de) hart auf "refurbished" gesetzt statt das
  Feld bei jedem Artikel neu zu pruefen.
- Da suggest.json weder Zustand noch Rahmengroesse liefert, wird fuer
  jeden Titel-Treffer (nach score_title-Filter, um unnoetige Requests zu
  vermeiden) zusaetzlich die Produktseite abgerufen.
"""

from __future__ import annotations

import json
import re
import time

import requests

from matcher import guess_color, score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://cleverbikes.de"
SUGGEST_PATH = "/search/suggest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")
_LDJSON_MUSTER = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)
_SPEC_MUSTER = re.compile(
    r'cbp__sr-l">([^<]+)</span><span class="cbp__sr-v">([^<]+)</span>'
)


class CleverbikesSource(Source):
    name = "cleverbikes.de"

    def __init__(self) -> None:
        super().__init__(name="cleverbikes.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _suggest(self, query: str) -> list[dict]:
        resp = self._session.get(
            BASE_URL + SUGGEST_PATH,
            params={
                "q": query,
                "resources[type]": "product",
                "resources[limit]": 10,
            },
            timeout=15,
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"cleverbikes.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        try:
            return resp.json()["resources"]["results"]["products"]
        except (KeyError, TypeError):
            return []

    def _produktseite_anreichern(self, listing: Listing) -> None:
        """Holt Zustand + Rahmengroesse + exakten Preis von der
        Produktseite nach - steht nicht in suggest.json, siehe Moduldoc."""
        resp = self._session.get(listing.url, timeout=15)
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"cleverbikes.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        text = resp.text

        for block in _LDJSON_MUSTER.findall(text):
            try:
                daten = json.loads(block)
            except json.JSONDecodeError:
                continue
            if daten.get("@type") != "Product":
                continue
            preis = (daten.get("offers") or {}).get("price")
            if preis is not None:
                listing.price_eur = float(preis)
            break

        specs = dict(_SPEC_MUSTER.findall(text))
        groesse = specs.get("Rahmengröße")
        if groesse:
            listing.frame_size = groesse.replace(" ", "")

    def _parse_suggestion(self, item: dict) -> Listing | None:
        title = item.get("title")
        if not title:
            return None
        url_pfad = (item.get("url") or "").split("?")[0]
        if not url_pfad:
            return None

        return Listing(
            source=self.name,
            title=title,
            price_eur=float(item["price"]) if item.get("price") is not None else None,
            condition="refurbished",
            url=BASE_URL + url_pfad,
            location=None,
            date_text=None,
            frame_size=None,
            model_year=(
                _JAHR_MUSTER.search(title).group(1)
                if _JAHR_MUSTER.search(title)
                else None
            ),
            color=guess_color(title),
        )

    def search(
        self,
        search_terms: list[str],
        match_required: list[str] | None = None,
        match_boost: list[str] | None = None,
        min_score: float = 0,
    ) -> list[Listing]:
        gesehen_urls: set[str] = set()
        treffer: list[Listing] = []

        for term in search_terms:
            for item in self._suggest(term):
                listing = self._parse_suggestion(item)
                if listing is None or listing.url in gesehen_urls:
                    continue

                if match_required is not None:
                    score = score_title(listing.title, match_required, match_boost or [])
                    if score is None or score < min_score:
                        continue
                    listing.match_score = score

                gesehen_urls.add(listing.url)
                self._produktseite_anreichern(listing)
                time.sleep(self.base_delay_s)
                treffer.append(listing)

            time.sleep(self.base_delay_s)

        return treffer
