"""
Quelle: mtbmania-winnenden.de (reiner Gebrauchtrad-Haendler, Winnenden,
Rems-Murr-Kreis).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- WooCommerce-Shop, kompletter Bestand ausschliesslich Gebrauchtware
  (Shop-Beschreibung: "Gebrauchte E-Bikes & Fahrraeder wie neu!").
- Die WordPress-Standardsuche (/?s=<begriff>&post_type=product) liefert
  0 Produkt-Treffer trotz vorhandener passender Artikel (live getestet) -
  offenbar nicht sauber verdrahtet. Stattdessen wird /shop/ Seite fuer
  Seite durchpagiert (/shop/page/2/, /3/, ...) und lokal gefiltert, wie
  bei moehrle-bikes/bikemarkt.
- Trefferliste: <li class="product_item ... type-product ...">
- Titel: <h2 class="woocommerce-loop-product__title">, Link direkt davor
  in <a class="title" href="...">.
- Preis: <span class="price"> enthaelt bei reduzierten Artikeln sowohl
  <del> (UVP/alter Preis) als auch <ins> (aktueller Preis) - <ins> hat
  Vorrang; ohne Rabatt gibt es nur einen einzelnen
  .woocommerce-Price-amount-Span.
- Rahmengroesse/Groesse wird sehr uneinheitlich in den Titel geschrieben
  ("Groesse: M", "/ L /", "S5", "54cm", "XL- Rahmen") - mehrere Muster
  werden nacheinander versucht, bestenfalls; kein hartes Scheitern, wenn
  keins passt.
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://mtbmania-winnenden.de"
SHOP_PATH = "/shop/"
MAX_PAGES = 12  # Bestand lag beim Testen bei ~10 Seiten a 12 Artikeln

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_PREIS_MUSTER = re.compile(r"([\d.]+),\d{2}\s*€")
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")
_GEWICHT_MUSTER = re.compile(r"(\d{1,2}[,.]\d{1,2})\s*kg", re.IGNORECASE)

_GROESSE_MUSTER_LISTE = [
    re.compile(r"Gr(?:\.|ö\w*)\s*:?\s*([SMLX]{1,3})\b", re.IGNORECASE),
    re.compile(r"(?:^|/)\s*(XXS|XS|S|M|L|XL|XXL)\s*(?:/|-|$)", re.IGNORECASE),
    re.compile(r"\b(\d{2})\s*cm\b", re.IGNORECASE),
]


def _preis_parsen(text: str | None) -> float | None:
    if not text:
        return None
    m = _PREIS_MUSTER.search(text.replace("\xa0", " "))
    return float(m.group(1).replace(".", "")) if m else None


def _zustand_erraten(title: str) -> str:
    if re.search(r"neuwertig|originalverpackt|\bovp\b", title, re.IGNORECASE):
        return "neu"
    return "gebraucht"  # der ganze Shop fuehrt nur Gebrauchtware


def _groesse_erraten(title: str) -> str | None:
    for muster in _GROESSE_MUSTER_LISTE:
        m = muster.search(title)
        if m:
            wert = m.group(1)
            return wert.upper() if not wert.isdigit() else wert + "cm"
    return None


class MtbManiaSource(Source):
    name = "mtbmania-winnenden.de"

    def __init__(self) -> None:
        super().__init__(name="mtbmania-winnenden.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, page: int) -> BeautifulSoup:
        url = BASE_URL + SHOP_PATH if page == 1 else f"{BASE_URL}{SHOP_PATH}page/{page}/"
        resp = self._session.get(url, timeout=15)
        if resp.status_code == 404:
            return BeautifulSoup("", "lxml")  # letzte Seite ueberschritten
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"mtbmania-winnenden.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "lxml")

    def _parse_item(self, li) -> Listing | None:
        title_el = li.select_one("h2.woocommerce-loop-product__title")
        link_el = li.select_one("a.title")
        if not title_el or not link_el:
            return None
        title = title_el.get_text(strip=True)
        url = link_el.get("href")

        price_block = li.select_one("span.price")
        preis_text = None
        if price_block:
            amount_el = (
                price_block.select_one("ins .woocommerce-Price-amount")
                or price_block.select_one(".woocommerce-Price-amount")
            )
            preis_text = amount_el.get_text(strip=True) if amount_el else None

        jahr_match = _JAHR_MUSTER.search(title)
        gewicht_match = _GEWICHT_MUSTER.search(title)

        return Listing(
            source=self.name,
            title=title,
            price_eur=_preis_parsen(preis_text),
            condition=_zustand_erraten(title),
            url=url,
            location=None,
            date_text=None,
            frame_size=_groesse_erraten(title),
            model_year=jahr_match.group(1) if jahr_match else None,
            weight_kg=float(gewicht_match.group(1).replace(",", ".")) if gewicht_match else None,
        )

    def _fetch_bestand(self) -> list[Listing]:
        alle: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            soup = self._fetch_page(page)
            items = soup.select("li.product_item")
            if not items:
                break
            for li in items:
                listing = self._parse_item(li)
                if listing:
                    alle.append(listing)
            time.sleep(self.base_delay_s)
        return alle

    def search(
        self,
        search_terms: list[str],
        match_required: list[str] | None = None,
        match_boost: list[str] | None = None,
        min_score: float = 0,
    ) -> list[Listing]:
        # Kein funktionierender Suchparameter (siehe Docstring) - kompletter
        # Bestand wird einmal durchpaginiert und lokal gefiltert, unabhaengig
        # von den einzelnen search_terms.
        treffer: list[Listing] = []
        for listing in self._fetch_bestand():
            if match_required is not None:
                score = score_title(listing.title, match_required, match_boost or [])
                if score is None or score < min_score:
                    continue
                listing.match_score = score
            treffer.append(listing)
        return treffer
