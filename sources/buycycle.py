"""
Quelle: buycycle.com (europaischer Gebrauchtrad-Marktplatz).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Die Produktseiten sind eine Next.js-App mit RSC-Streaming-Payload (kein
  klassisches __NEXT_DATA__), Fundtitel/Preise stecken dort nicht sauber
  extrahierbar drin. Stattdessen nutzt buycycle im Frontend eine oeffentliche
  Search-API von Constructor.io (cnstrc.com) - das eingebundene Tracking-JS
  (https://cnstrc.com/js/cust/buycycle_chOSop.js) enthaelt den oeffentlichen
  "prod"-Search-Key. Das ist ein regulaerer client-seitiger Read-only-Key
  (identisch zu dem, den jeder Browser beim Seitenaufruf mitschickt), kein
  Auth-Bypass.
- Endpoint: https://ac.cnstrc.com/search/<query>?key=...&filters[brand_slug]=cube&filters[main-type]=bikes
  Ohne Marken-/Typ-Filter liefert die Volltextsuche auch branchenfremde
  Treffer (Schuhe, Schlaeger etc.) ueber Embedding-Matching - Filter sind
  daher kein Nice-to-have, sondern noetig fuer sinnvolle Treffer.
- Titel steht im Feld "value", nicht in "data" (dort gibt es keine
  eigene title-Property fuer bikes).
- Preise sind pro Angebot in unterschiedlicher Waehrung hinterlegt
  (data.currency_code, z.B. auch USD/GBP) - price_eur wird nur fuer
  currency_code == "EUR" gesetzt, um keine geratenen Wechselkurse
  einzubauen; andere Waehrungen laufen als "price_eur": None durch (Preis
  bleibt aus dem sort/Filter raus, Titel/URL/Zustand bleiben trotzdem
  sichtbar).
- Zustands-Codes (data.condition_code) gegen mehrere echte Produktseiten
  verifiziert (data2-Meta-Tag "Zustand"): 1=Fair, 2=Gut, 3=Sehr gut, 4=Neu.
"""

from __future__ import annotations

import re
import time

import requests

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

SEARCH_URL = "https://ac.cnstrc.com/search/{query}"
# Oeffentlicher client-seitiger "prod"-Search-Key aus buycycles eigenem
# Tracking-Bundle (cnstrc.com/js/cust/buycycle_chOSop.js) - wird bei jedem
# normalen Seitenaufruf im Browser genauso mitgeschickt.
API_KEY = "key_hooA497Bwe5EMdLb"
RESULTS_PER_PAGE = 40

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_ZUSTAND_CODES = {
    "1": "gebraucht",  # Fair
    "2": "gebraucht",  # Gut
    "3": "gebraucht",  # Sehr gut
    "4": "neu",  # Neu
}

# buycycle liefert kein strukturiertes Gewichtsfeld - nur bestenfalls aus dem
# Titel, wenn ein Verkaeufer es selbst reinschreibt.
_GEWICHT_MUSTER = re.compile(r"(\d{1,2}[,.]\d{1,2})\s*kg", re.IGNORECASE)


def _gewicht_parsen(title: str) -> float | None:
    m = _GEWICHT_MUSTER.search(title)
    return float(m.group(1).replace(",", ".")) if m else None


class BuycycleSource(Source):
    name = "buycycle.com"

    def __init__(self) -> None:
        super().__init__(name="buycycle.com")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _search_raw(self, query: str) -> list[dict]:
        params = {
            "key": API_KEY,
            "i": "fahrradpreise-scanner",
            "s": "1",
            "c": "ciojs-client-2.0.0",
            "section": "Products",
            "filters[brand_slug]": "cube",
            "filters[main-type]": "bikes",
            "num_results_per_page": RESULTS_PER_PAGE,
        }
        resp = self._session.get(
            SEARCH_URL.format(query=query), params=params, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"buycycle.com blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", {}).get("results", [])

    def _parse_result(self, res: dict) -> Listing | None:
        d = res.get("data", {})
        title = res.get("value")
        url = d.get("url")
        if not title or not url:
            return None

        currency = d.get("currency_code")
        price = d.get("price")
        price_eur = float(price) if currency == "EUR" and price is not None else None

        condition = _ZUSTAND_CODES.get(str(d.get("condition_code")), "unbekannt")

        return Listing(
            source=self.name,
            title=title,
            price_eur=price_eur,
            condition=condition,
            url=url,
            location=None,  # buycycle zeigt in der Trefferliste keinen Ort
            date_text=None,
            frame_size=d.get("frame_size_in_string") or d.get("product_size"),
            model_year=str(d.get("year")) if d.get("year") else None,
            weight_kg=_gewicht_parsen(title),
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
            for res in self._search_raw(term):
                listing = self._parse_result(res)
                if not listing or listing.url in gesehen_urls:
                    continue
                gesehen_urls.add(listing.url)

                if match_required is not None:
                    score = score_title(listing.title, match_required, match_boost or [])
                    if score is None or score < min_score:
                        continue
                    listing.match_score = score

                treffer.append(listing)

            time.sleep(self.base_delay_s)

        return treffer
