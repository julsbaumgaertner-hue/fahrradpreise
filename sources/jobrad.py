"""
Quelle: jobrad-loop.com (Rueckkaeufer-Plattform fuer JobRad-Leasingrueckl:aeufer).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Volltextsuche laeuft ganz normal ueber ?q=<begriff>, Server-Side-Rendering
  (Next.js Pages Router), kein Cloudflare-Block.
- Trefferliste steckt sauber strukturiert im klassischen
  <script id="__NEXT_DATA__"> als JSON:
  props.pageProps.data.data.dataSources.__master.items[]
  Jedes Item hat "name", "_url" (Pfad relativ zur Domain), und
  "variants"[0] mit "price" (centAmount/currencyCode) und
  "attributes.condition_optical" (deutscher Klartext: "Sehr Gut",
  "Gut", "In Ordnung", ...). Rahmengroesse steckt strukturiert in
  "attributes.frame_height_manufacturer" (S/M/L/XL, gegen echte Treffer
  verifiziert) - kein Text-Raten wie bei kleinanzeigen/bikemarkt noetig.
  Ein Gewichtsfeld gibt es in den >90 Attributen dagegen nicht (live
  geprueft) - daher wie bei den anderen Quellen nur Best-Effort aus dem
  Titel, der bei jobrad-loop aber praktisch nie ein Gewicht enthaelt.
- __master.total kann weit ueber der Anzahl der zurueckgegebenen "items"
  liegen (Server liefert nur eine erste Seite, z.B. 24 von 303) - die
  Suche ist eine lockere OR-Verknuepfung ueber alle Suchbegriffe und wird
  nach Relevanz sortiert (sortAttributes.score: desc), daher reicht die
  erste Seite fuer ein so spezifisches Modell in der Praxis aus; weitere
  Seiten wuerden zunehmend irrelevantere Cube-Modelle liefern, die vom
  eigenen match_required-Filter ohnehin rausfallen wuerden.
"""

from __future__ import annotations

import json
import re
import time

import requests

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://jobrad-loop.com"
SEARCH_PATH = "/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_NEXT_DATA_MUSTER = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")
_GEWICHT_MUSTER = re.compile(r"(\d{1,2}[,.]\d{1,2})\s*kg", re.IGNORECASE)


def _gewicht_parsen(title: str) -> float | None:
    m = _GEWICHT_MUSTER.search(title)
    return float(m.group(1).replace(",", ".")) if m else None

_ZUSTAND_MUSTER = {
    "neu": re.compile(r"\bneu\b|neuwertig", re.IGNORECASE),
    "gebraucht": re.compile(r"sehr gut|\bgut\b|in ordnung|gebraucht", re.IGNORECASE),
}


def _zustand_erraten(text: str | None) -> str:
    if not text:
        return "unbekannt"
    for zustand, muster in _ZUSTAND_MUSTER.items():
        if muster.search(text):
            return zustand
    return "unbekannt"


class JobradSource(Source):
    name = "jobrad-loop.com"

    def __init__(self) -> None:
        super().__init__(name="jobrad-loop.com")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_items(self, query: str) -> list[dict]:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH, params={"q": query}, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"jobrad-loop.com blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"

        m = _NEXT_DATA_MUSTER.search(resp.text)
        if not m:
            return []
        data = json.loads(m.group(1))
        try:
            return data["props"]["pageProps"]["data"]["data"]["dataSources"][
                "__master"
            ]["items"]
        except (KeyError, TypeError):
            return []

    def _parse_item(self, item: dict) -> Listing | None:
        title = item.get("name")
        url_pfad = item.get("_url")
        if not title or not url_pfad:
            return None

        variants = item.get("variants") or []
        variant = variants[0] if variants else {}
        preis_info = variant.get("price") or {}
        price = (
            preis_info["centAmount"] / 100
            if preis_info.get("currencyCode") == "EUR"
            and preis_info.get("centAmount") is not None
            else None
        )

        attributes = variant.get("attributes") or {}
        condition_text = attributes.get("condition_optical", [None])[0]
        frame_size = attributes.get("frame_height_manufacturer", [None])[0]

        jahr_match = _JAHR_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=price,
            condition=_zustand_erraten(condition_text),
            url=BASE_URL + url_pfad,
            location=None,
            date_text=None,
            frame_size=frame_size,
            model_year=jahr_match.group(1) if jahr_match else None,
            weight_kg=_gewicht_parsen(title),
        )

    def _search_one_term(self, term: str) -> list[Listing]:
        ergebnisse: list[Listing] = []
        for item in self._fetch_items(term):
            listing = self._parse_item(item)
            if listing:
                ergebnisse.append(listing)
        return ergebnisse

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
            for listing in self._search_one_term(term):
                if listing.url in gesehen_urls:
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
