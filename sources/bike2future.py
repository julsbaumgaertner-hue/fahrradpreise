"""
Quelle: bike2future.de (Bikeleasing-Tochter, Leasingrueckklaeufer-Haendler).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Shopware-6-Shop, Volltextsuche: /search?search=<begriff>.
- Trefferkarte traegt ihre Daten sauber als JSON im Attribut
  data-product-information='{"id":...,"name":...,"brand":...,"price":...}'
  - kein muehsames Text-Scraping fuer Titel/Preis noetig.
- Link steckt als eigenes <a href="https://www.bike2future.de/<slug>/<id>">
  im gleichen Kartenblock (nicht die Wunschlisten-Herz-Icons, die auch
  href-Attribute mit #icons-... haben).
- Kein Zustandslabel pro Artikel gefunden - condition hart auf
  "refurbished" (reiner Rueckklaeufer-Haendler wie Rebike/Upway).
- Pagination ueber ?p=N (Shopware-Standardparameter).
"""

from __future__ import annotations

import json
import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.bike2future.de"
SEARCH_PATH = "/search"
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")


class Bike2FutureSource(Source):
    name = "bike2future.de"

    def __init__(self) -> None:
        super().__init__(name="bike2future.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, query: str, page: int) -> BeautifulSoup:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH, params={"search": query, "p": page}, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"bike2future.de blockt (HTTP {resp.status_code})")
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
        price = info.get("price")
        if not title:
            return None

        link = box.find("a", href=lambda h: bool(h) and "icons-default" not in h)
        url = link["href"] if link else None
        if not url:
            return None

        jahr_match = _JAHR_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=float(price) if price is not None else None,
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
            if len(boxes) < 19:  # Standard-Seitengroesse beim Testen
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
