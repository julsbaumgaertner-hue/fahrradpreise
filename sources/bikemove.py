"""
Quelle: bikemove.de (Haendler, refurbished + B-Ware).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Wieder ein Shopware-6-Shop mit /search?search=<begriff>&p=N wie
  bike2future/statera - aber DRITTES Karten-Theme: das
  data-product-information-Attribut ist hier leer ({}), Titel kommt
  stattdessen aus <a class="product-name"> (Text UND title-Attribut,
  beide identisch).
- Preis: gleiche Form wie bei statera - Angebots- und Streichpreis ohne
  Trennzeichen hintereinander ("2.399,00 €*3.699,00 €*(Du sparst ..)"),
  Regex nimmt bewusst nur den ersten (niedrigeren) Preis; hier zusaetzlich
  ein "*" direkt nach dem €-Zeichen (Sternchen-Hinweis), die Preis-Regex
  ignoriert das ohnehin (verlangt nur Ziffern/Komma vor dem €).
- Groesse steht oft am Titelende ("... - 2023 - 50 cm" oder "... - 2023 -
  L") - zwei Muster werden versucht, kein hartes Scheitern wenn keins
  passt.
- Kein Zustandslabel pro Artikel gefunden - condition hart auf
  "refurbished" (dominante Kategorie laut Anbieterliste; B-Ware liesse
  sich ohne eigenes Feld nicht zuverlaessig unterscheiden).
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.bikemove.de"
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
_GROESSE_CM_MUSTER = re.compile(r"-\s*(\d{2})\s*cm\b", re.IGNORECASE)
_GROESSE_BUCHSTABE_MUSTER = re.compile(r"-\s*(XXS|XS|S|M|L|XL|XXL)\s*$", re.IGNORECASE)


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else None


def _groesse_erraten(title: str) -> str | None:
    m = _GROESSE_CM_MUSTER.search(title)
    if m:
        return m.group(1) + "cm"
    m = _GROESSE_BUCHSTABE_MUSTER.search(title)
    return m.group(1).upper() if m else None


class BikemoveSource(Source):
    name = "bikemove.de"

    def __init__(self) -> None:
        super().__init__(name="bikemove.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, query: str, page: int) -> BeautifulSoup:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH, params={"search": query, "p": page}, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"bikemove.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "lxml")

    def _parse_box(self, box) -> Listing | None:
        name_el = box.select_one("a.product-name")
        if not name_el or not name_el.get("href"):
            return None
        title = name_el.get_text(strip=True)
        if not title:
            return None

        price_el = box.select_one("span.product-price")
        jahr_match = _JAHR_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=_preis_parsen(price_el.get_text(strip=True) if price_el else None),
            condition="refurbished",
            url=name_el["href"],
            location=None,
            date_text=None,
            frame_size=_groesse_erraten(title),
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
