"""
Quelle: bikemarkt.mtb-news.de.

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Die Suche laeuft NICHT ueber den nahliegenden Parameter "q" oder "s" -
  beide liefern nur die generische Landingpage (neueste/beliebteste Artikel,
  URL-Parameter wird ignoriert). Der echte Parameter heisst "q_ft" (gefunden
  ueber das name-Attribut des Suchfelds im DOM). Funktioniert als reiner
  GET-Request, kein Playwright noetig.
- Trefferliste: <li class="productItem" data-id="..." data-published="DD.MM.YYYY HH:MM">
- Titel/Link: <a> mit title-Attribut + <h2> im <article>
- Preis: <a class="... text-green-700 ..."> im selben Artikel
- Zustand/Kategorie/Verkaeufertyp: drei <span> in der Meta-Zeile ueber dem
  Titel (Reihenfolge: Kategorie, Zustand, Privat/Haendler) - Zustand wird
  ueber ein Schluesselwort-Set erkannt statt ueber Position, robuster gegen
  Layout-Aenderungen.
- Pagination: ?page=N
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import guess_color, score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://bikemarkt.mtb-news.de"
SEARCH_PATH = "/search"
MAX_PAGES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_PREIS_MUSTER = re.compile(r"([\d.]+),\d{2}\s*€")
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")
_GROESSE_MUSTER = re.compile(r"\bGr\.?\s*([SMLX]{1,3})\b", re.IGNORECASE)
_GEWICHT_MUSTER = re.compile(r"(\d{1,2}[,.]\d{1,2})\s*kg", re.IGNORECASE)

# bikemarkt hat (anders als kleinanzeigen.de) ein echtes Zustands-Tag in der
# Meta-Zeile - direkter Abgleich statt Text-Heuristik ueber die Beschreibung.
_ZUSTAND_TAGS = {
    "neu": "neu",
    "neuwertig": "neu",
    "gebraucht": "gebraucht",
    "defekt": "gebraucht",
}


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(".", ""))


def _gewicht_parsen(title: str) -> float | None:
    m = _GEWICHT_MUSTER.search(title)
    return float(m.group(1).replace(",", ".")) if m else None


class BikemarktSource(Source):
    name = "bikemarkt.mtb-news.de"

    def __init__(self) -> None:
        super().__init__(name="bikemarkt.mtb-news.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch(self, params: dict) -> BeautifulSoup:
        resp = self._session.get(BASE_URL + SEARCH_PATH, params=params, timeout=15)
        if resp.status_code in (403, 429):
            raise ScraperBlocked(
                f"bikemarkt.mtb-news.de blockt (HTTP {resp.status_code})"
            )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "lxml")

    def _parse_item(self, li) -> Listing | None:
        article = li.find("article")
        if not article:
            return None

        title_el = article.find("h2")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            return None

        link_el = article.find("a", href=re.compile(r"^/article/"))
        url = BASE_URL + link_el["href"] if link_el else None

        price_el = article.select_one("a.text-green-700")
        price = _preis_parsen(price_el.get_text(strip=True) if price_el else None)

        meta_texte = [
            s.get_text(strip=True).rstrip(",")
            for s in article.select("div.cssHighlightMeta span")
        ]
        condition = "unbekannt"
        for text in meta_texte:
            zustand = _ZUSTAND_TAGS.get(text.lower())
            if zustand:
                condition = zustand
                break

        date_text = li.get("data-published")

        jahr_match = _JAHR_MUSTER.search(title)
        groesse_match = _GROESSE_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=price,
            condition=condition,
            url=url,
            location=None,  # bikemarkt zeigt in der Trefferliste keinen Ort
            date_text=date_text,
            frame_size=groesse_match.group(1).upper() if groesse_match else None,
            model_year=jahr_match.group(1) if jahr_match else None,
            weight_kg=_gewicht_parsen(title),
            color=guess_color(title),
        )

    def _search_one_term(self, term: str) -> list[Listing]:
        ergebnisse: list[Listing] = []

        for page in range(1, MAX_PAGES + 1):
            soup = self._fetch({"q_ft": term, "page": page})
            items = soup.select("li.productItem")
            if not items:
                break

            for li in items:
                listing = self._parse_item(li)
                if listing:
                    ergebnisse.append(listing)

            time.sleep(self.base_delay_s)

            # "Seite 1 von 1" o.ae. - keine weitere Seite anfordern, wenn
            # weniger Treffer als eine volle Seite kamen.
            if len(items) < 20:
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
                if not listing.url or listing.url in gesehen_urls:
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
