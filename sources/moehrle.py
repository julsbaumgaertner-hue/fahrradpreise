"""
Quelle: moehrle-bikes.com (Fahrradhaendler Goeppingen, bedient den ganzen
Landkreis Goeppingen).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Eigene Kategorie fuer Gebrauchtraeder unter https://www.moehrle-bikes.com/Gebrauchte/
  (klassisches serverseitiges HTML, kein JS noetig). /Gebrauchte-E-Bikes/ ist
  nur eine Teilmenge davon (nur die E-Bikes) - /Gebrauchte/ allein reicht.
- Aktuell nur eine Handvoll Artikel im Bestand (4 zum Testzeitpunkt) - keine
  Suchfunktion/Query-Parameter noetig oder vorhanden, die Seite wird komplett
  geladen und lokal gegen die match_required/match_boost-Begriffe gefiltert
  (wie bei bikemarkt, nur ohne den Suchparameter, weil es keinen gibt).
- Trefferliste: <div class="artikel_liste container" data-produktid="...">
- Titel: <h2>...</h2>, enthaelt "gebraucht" immer als Teil des Freitexts
  (Kategorie ist ohnehin nur Gebrauchtware) - Zustand daher per Default
  "gebraucht", mit Override auf "neu" falls "neuwertig" im Titel steht.
- Preis: <span class="price">UNSER PREIS 2.390,00&nbsp;&euro;</span> - das
  "UNSER PREIS"-Praefix ist nicht immer da, die Regex zieht nur die Zahl.
- Link: <a class="titel" href="/Fahrraeder/...">.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from matcher import guess_color, score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.moehrle-bikes.com"
GEBRAUCHTE_PATH = "/Gebrauchte/"

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


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else None


def _zustand_erraten(title: str) -> str:
    if re.search(r"neuwertig|originalverpackt|\bovp\b", title, re.IGNORECASE):
        return "neu"
    return "gebraucht"  # /Gebrauchte/ listet nur Gebrauchtware


class MoehrleSource(Source):
    name = "moehrle-bikes.com"

    def __init__(self) -> None:
        super().__init__(name="moehrle-bikes.com")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_bestand(self) -> list[dict]:
        resp = self._session.get(BASE_URL + GEBRAUCHTE_PATH, timeout=15)
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"moehrle-bikes.com blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        artikel = []
        for block in soup.select("div.artikel_liste"):
            title_el = block.select_one("h2")
            link_el = block.select_one("a.titel")
            price_el = block.select_one("span.price")
            if not title_el or not link_el:
                continue
            artikel.append(
                {
                    "title": title_el.get_text(strip=True),
                    "url": BASE_URL + link_el["href"],
                    "price_text": price_el.get_text(strip=True) if price_el else None,
                }
            )
        return artikel

    def search(
        self,
        search_terms: list[str],
        match_required: list[str] | None = None,
        match_boost: list[str] | None = None,
        min_score: float = 0,
    ) -> list[Listing]:
        # Kein Suchparameter auf der Seite - der komplette (kleine) Gebraucht-
        # Bestand wird einmal geladen und lokal gefiltert, unabhaengig von den
        # einzelnen search_terms.
        artikel = self._fetch_bestand()
        treffer: list[Listing] = []

        for a in artikel:
            title = a["title"]
            jahr_match = _JAHR_MUSTER.search(title)
            groesse_match = _GROESSE_MUSTER.search(title)
            gewicht_match = _GEWICHT_MUSTER.search(title)

            listing = Listing(
                source=self.name,
                title=title,
                price_eur=_preis_parsen(a["price_text"]),
                condition=_zustand_erraten(title),
                url=a["url"],
                location=None,
                date_text=None,
                frame_size=groesse_match.group(1).upper() if groesse_match else None,
                model_year=jahr_match.group(1) if jahr_match else None,
                weight_kg=float(gewicht_match.group(1).replace(",", ".")) if gewicht_match else None,
                color=guess_color(title),
            )

            if match_required is not None:
                score = score_title(listing.title, match_required, match_boost or [])
                if score is None or score < min_score:
                    continue
                listing.match_score = score

            treffer.append(listing)

        return treffer
