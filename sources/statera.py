"""
Quelle: staterabikes.de (Haendler, refurbished/generalueberholte Raeder).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Shopware-6-Shop wie bike2future.de, gleiche Volltextsuche
  /search?search=<begriff>&p=N - ABER anderes Karten-Theme ("box-minimal"
  statt "box-standard"): data-product-information enthaelt hier nur
  {"id":...,"name":...}, KEIN Preis und keine Marke - Preis muss separat
  aus <span class="product-price"> gezogen werden (Waehrungszeichen nach
  der Zahl, wie bei bikemarkt/kleinanzeigen).
- Bei reduzierten Artikeln stehen Angebots- und Streichpreis ohne
  Trennzeichen direkt hintereinander im Text ("2.799,00 €3.499,00 €") -
  die Regex nimmt bewusst nur den ERSTEN (=aktuellen/niedrigeren) Preis.
- Katalog enthaelt auch Zubehoer (z.B. Handyhalterungen), nicht nur
  Fahrraeder - wird ueber match_required/score_title sauber rausgefiltert,
  keine serverseitige Kategorie-Einschraenkung noetig.
- Kein Zustandslabel pro Artikel gefunden - condition hart auf
  "refurbished" (laut Anbieterliste ein reiner Refurbished-Haendler).
"""

from __future__ import annotations

import json
import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.staterabikes.de"
SEARCH_PATH = "/search"
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_PREIS_MUSTER = re.compile(r"([\d.]+),\d{2}\s*€")
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else None


class StateraSource(Source):
    name = "staterabikes.de"

    def __init__(self) -> None:
        super().__init__(name="staterabikes.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, query: str, page: int) -> BeautifulSoup:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH, params={"search": query, "p": page}, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"staterabikes.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "lxml")

    def _parse_box(self, box) -> Listing | None:
        raw_info = box.get("data-product-information")
        if not raw_info:
            return None
        try:
            info = json.loads(raw_info)
        except json.JSONDecodeError:
            return None

        title = info.get("name")
        if not title:
            return None

        link = box.select_one("a[href]")
        url = link["href"] if link else None
        if not url:
            return None

        price_el = box.select_one("span.product-price")
        jahr_match = _JAHR_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=_preis_parsen(price_el.get_text(strip=True) if price_el else None),
            condition="refurbished",
            url=url,
            location=None,
            date_text=None,
            frame_size=None,
            model_year=jahr_match.group(1) if jahr_match else None,
        )

    def _search_one_term(self, term: str) -> list[Listing]:
        ergebnisse: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            soup = self._fetch_page(term, page)
            boxes = soup.select("div.product-box")
            if not boxes:
                break
            for box in boxes:
                listing = self._parse_box(box)
                if listing:
                    ergebnisse.append(listing)
            time.sleep(self.base_delay_s)
            if len(boxes) < 24:
                break
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
