"""
Quelle: kleinanzeigen.de (Volltextsuche in der Kategorie Fahrraeder).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Trefferliste: <article data-adid="..." data-href="/s-anzeige/...">
- Titel: erstes <h3> im Artikel
- Preis: <p class="text-title3 font-strong"> (naive Suche nach "erstes <p>
  mit €" greift bei manchen Shop-Inseraten faelschlich die Beschreibung ab,
  die Klassen-Kombination ist praeziser)
- Ort/Datum: <span> direkt nach dem <svg data-title="locationOutline"> bzw.
  "calendarOutline"> - ueber die SVG-data-title-Attribute verankert statt
  ueber die (vermutlich Tailwind-generierten, instabilen) Utility-Klassen
- Server liefert keinen Charset-Header -> requests faellt sonst auf
  ISO-8859-1 zurueck und zerhaeckselt Umlaute/Euro-Zeichen. r.encoding muss
  explizit gesetzt werden.
- Pagination: /s-fahrraeder/seite:N/<suchbegriff>/k0
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_PATH_TMPL = "/s-fahrraeder/{page_segment}{query}/k0"
MAX_PAGES = 3  # pro Suchbegriff - haelt die Anzahl Requests ueberschaubar

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_PREIS_MUSTER = re.compile(r"([\d.]+)\s*€")
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")
_GROESSE_MUSTER = re.compile(r"\bGr\.?\s*([SMLX]{1,3})\b", re.IGNORECASE)
_ZUSTAND_MUSTER = {
    "refurbished": re.compile(r"refurbish|generalÃ¼berholt|generaluberholt|aufbereitet", re.IGNORECASE),
    "neu": re.compile(r"\bneu\b|neuwertig|originalverpackt|\bovp\b", re.IGNORECASE),
    "gebraucht": re.compile(r"gebraucht|gepflegt|getragen|benutzt", re.IGNORECASE),
}


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(".", ""))


def _zustand_erraten(*texte: str | None) -> str:
    gesamt = " ".join(t for t in texte if t)
    for zustand, muster in _ZUSTAND_MUSTER.items():
        if muster.search(gesamt):
            return zustand
    return "unbekannt"


def _feld_neben_icon(article, icon_title: str) -> str | None:
    icon = article.find("svg", attrs={"data-title": icon_title})
    if not icon:
        return None
    parent = icon.find_parent("div")
    if not parent:
        return None
    span = parent.find("span")
    return span.get_text(strip=True) if span else None


class KleinanzeigenSource(Source):
    name = "kleinanzeigen.de"

    def __init__(self) -> None:
        super().__init__(name="kleinanzeigen.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch(self, url: str) -> BeautifulSoup:
        resp = self._session.get(url, timeout=15)
        if resp.status_code in (403, 429):
            raise ScraperBlocked(
                f"kleinanzeigen.de blockt (HTTP {resp.status_code}) bei {url}"
            )
        resp.raise_for_status()
        resp.encoding = "utf-8"  # Server sendet keinen Charset-Header, siehe Docstring
        return BeautifulSoup(resp.text, "lxml")

    def _parse_article(self, article) -> Listing | None:
        title_el = article.find("h3")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            return None

        href = article.get("data-href")
        url = BASE_URL + href if href and href.startswith("/") else href

        price_el = article.select_one("p.text-title3.font-strong")
        price_text = price_el.get_text(strip=True) if price_el else None
        price = _preis_parsen(price_text)

        desc_el = article.find("p", class_=re.compile("Subdued"))
        description = desc_el.get_text(strip=True) if desc_el else None

        location = _feld_neben_icon(article, "locationOutline")
        date_text = _feld_neben_icon(article, "calendarOutline")

        jahr_match = _JAHR_MUSTER.search(title)
        groesse_match = _GROESSE_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=price,
            condition=_zustand_erraten(title, description),
            url=url,
            location=location,
            date_text=date_text,
            frame_size=groesse_match.group(1).upper() if groesse_match else None,
            model_year=jahr_match.group(1) if jahr_match else None,
        )

    def _search_one_term(self, term: str) -> list[Listing]:
        query = term.strip().lower().replace(" ", "-")
        query = re.sub(r"[^a-z0-9\-:]", "", query)
        ergebnisse: list[Listing] = []

        for page in range(1, MAX_PAGES + 1):
            page_segment = "" if page == 1 else f"seite:{page}/"
            url = BASE_URL + SEARCH_PATH_TMPL.format(page_segment=page_segment, query=query)
            soup = self._fetch(url)
            articles = soup.select("article[data-adid]")
            if not articles:
                break

            for art in articles:
                listing = self._parse_article(art)
                if listing:
                    ergebnisse.append(listing)

            time.sleep(self.base_delay_s)

        return ergebnisse

    def search(
        self,
        search_terms: list[str],
        match_required: list[str] | None = None,
        match_boost: list[str] | None = None,
        min_score: float = 0,
    ) -> list[Listing]:
        gesehen_ids: set[str] = set()
        treffer: list[Listing] = []

        for term in search_terms:
            for listing in self._search_one_term(term):
                if listing.url in gesehen_ids:
                    continue
                gesehen_ids.add(listing.url)

                if match_required is not None:
                    score = score_title(listing.title, match_required, match_boost or [])
                    if score is None or score < min_score:
                        continue
                    listing.match_score = score

                treffer.append(listing)

            time.sleep(self.base_delay_s)

        return treffer
