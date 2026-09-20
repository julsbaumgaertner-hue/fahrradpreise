"""
Quelle: rebike.com (bundesweiter Haendler fuer Leasingrueckklaeufer,
"Certified by Bosch").

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Normale Shopify-Volltextsuche: /search?q=<begriff>&type=product,
  Pagination ueber &page=N, 24 Treffer pro Seite.
- Trefferliste: <product-card data-product-id="..." data-body-height-min=
  ".." data-body-height-max="..">. Der Theme rendert Preise serverseitig
  trotz Web-Component-Wrapper (<product-price>) - kein JS-Rendering
  noetig, einfaches BeautifulSoup-Parsing reicht.
- Titel: <a class="product-card__link" href="/products/<slug>?..."> mit
  <span class="visually-hidden"> als Titeltext direkt darin. Tracking-
  Query-Parameter (?variant=...&_pos=...&_sid=...&_ss=r) werden aus der
  URL entfernt.
- Preis: <span class="price">€X.XXX,00</span> (aktueller/Angebotspreis,
  bei reduzierten Artikeln zusaetzlich <span class="compare-at-price">
  mit dem alten Preis - wird nicht gebraucht).
- Rebike ist ein reiner Rueckklaeufer-/Refurbished-Haendler (kein
  eigenes Zustandslabel pro Artikel gefunden) - condition daher hart auf
  "refurbished". Rahmengroesse steckt nicht im Titel, sondern in den
  data-body-height-min/max-Attributen (Koerpergroesse in cm, nicht
  S/M/L) - wird als "<min>-<max>cm" abgelegt.
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.rebike.com"
SEARCH_PATH = "/search"
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

# Anders als bei den meisten anderen Quellen steht das €-Zeichen hier VOR
# der Zahl ("€3.239,00" statt "3.239,00 €").
_PREIS_MUSTER = re.compile(r"€\s?([\d.]+),\d{2}")
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else None


class RebikeSource(Source):
    name = "rebike.com"

    def __init__(self) -> None:
        super().__init__(name="rebike.com")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, query: str, page: int) -> BeautifulSoup:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH,
            params={"q": query, "type": "product", "page": page},
            timeout=15,
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"rebike.com blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "lxml")

    def _parse_card(self, card) -> Listing | None:
        link = card.select_one("a.product-card__link")
        if not link or not link.get("href"):
            return None
        title_el = link.select_one("span.visually-hidden")
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
        if not title:
            return None

        url = BASE_URL + link["href"].split("?")[0]
        price_el = card.select_one("span.price")

        groesse_min = card.get("data-body-height-min")
        groesse_max = card.get("data-body-height-max")
        frame_size = f"{groesse_min}-{groesse_max}cm" if groesse_min and groesse_max else None

        jahr_match = _JAHR_MUSTER.search(card.get_text(" ", strip=True))

        return Listing(
            source=self.name,
            title=title,
            price_eur=_preis_parsen(price_el.get_text(strip=True) if price_el else None),
            condition="refurbished",
            url=url,
            location=None,
            date_text=None,
            frame_size=frame_size,
            model_year=jahr_match.group(1) if jahr_match else None,
        )

    def _search_one_term(self, term: str) -> list[Listing]:
        ergebnisse: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            soup = self._fetch_page(term, page)
            cards = soup.select("product-card")
            if not cards:
                break
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    ergebnisse.append(listing)
            time.sleep(self.base_delay_s)
            if len(cards) < 24:
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
