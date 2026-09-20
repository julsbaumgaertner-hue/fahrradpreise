"""
Quelle: bikeflip.com (Marktplatz fuer Fachhandel-Gebrauchtraeder).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Next.js mit klassischem __NEXT_DATA__ (kein RSC-Streaming wie bei
  buycycle/upway) - Trefferliste liegt sauber strukturiert unter
  props.pageProps.data.data, jedes Item hat "bike_brand.name",
  "bike_model_text", "price", "condition" (REFURBISHED/USED/FAIR/
  ALMOST_NEW - explizites Zustandsfeld, kein Raten noetig!),
  "model_year", "sizes[0].value" (S/M/L/XL).
- ABER: der Volltextsuche-Parameter der UI (?q=...) filtert NICHT
  serverseitig (live getestet: liefert immer den kompletten
  12000+-Artikel-Katalog unveraendert zurueck) - stattdessen wird ueber
  ?bike_brand=<numerische ID> gefiltert. Die ID-Liste steht komplett
  (886 Marken) in props.pageProps.filtersInitData (key="bike_brand").
  Die fuer unsere Modelle benoetigten IDs wurden daraus einmalig
  extrahiert und unten fest hinterlegt (BRAND_IDS) - genau wie bei
  match_required in config/models.yaml ist das erste match_required-
  Token praktisch immer der Markenname/-schluessel.
- Ohne bekannte Marken-ID (match_required fehlt oder Marke nicht in
  BRAND_IDS) liefert diese Quelle bewusst 0 Treffer statt den ganzen
  12000er-Katalog zu durchsuchen.
- Detailseiten-URL: https://www.bikeflip.com/de/bikes/<id>

Bekannte Grenze (nicht bikeflip-spezifisch, aber hier live beobachtet):
bei sehr kargen Titeln ohne jede Variantenangabe (z.B. nur "Trek Fuel Ex"
ohne Modellnummer) kann matcher.score_title() ein kurzes
Unterscheidungs-Token wie "exe" faelschlich durchlassen (partial_ratio
steigt bei sehr kurzen Titeln generell an - "exe" gg. "trek fuel ex" =
80, gg. "trek fuel exe 9.8..." = 100, beide ueber der 75er-Schwelle).
Betrifft nur Faelle mit minimalem Titeltext; bei allen bisher gesehenen
Titeln mit Modellnummer/Ausstattung faellt die Unterscheidung sauber
unter die Schwelle. Kein Fix hier, da eine globale Verschaerfung von
matcher.py alle anderen Quellen/Modelle mit betreffen wuerde.
"""

from __future__ import annotations

import re
import time

import requests

from matcher import guess_color, score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://www.bikeflip.com"
SEARCH_PATH = "/de/search/bikes"
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

# Live aus props.pageProps.filtersInitData (key="bike_brand") extrahiert,
# Schluessel entsprechen dem ersten match_required-Token je Modell in
# config/models.yaml.
BRAND_IDS = {
    "cube": 10,
    "canyon": 5,
    "ktm": 19,
    "bulls": 126,
    "flyer": 206,
    "simplon": 38,
    "trek": 44,
    "specialized": 120,
    "focus": 64,
    "cruz": 36,  # Santa Cruz
    "haibike": 194,
    "mondraker": 116,
    "scott": 37,
    "orbea": 29,
    "rotwild": 119,
}

_ZUSTAND_CODES = {
    "REFURBISHED": "refurbished",
    "ALMOST_NEW": "gebraucht",
    "USED": "gebraucht",
    "FAIR": "gebraucht",
}

_NEXT_DATA_MUSTER = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


class BikeflipSource(Source):
    name = "bikeflip.com"

    def __init__(self) -> None:
        super().__init__(name="bikeflip.com")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, brand_id: int, page: int) -> list[dict]:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH,
            params={"bike_brand": brand_id, "page": page},
            timeout=15,
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"bikeflip.com blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"

        m = _NEXT_DATA_MUSTER.search(resp.text)
        if not m:
            return []
        import json

        data = json.loads(m.group(1))
        try:
            return data["props"]["pageProps"]["data"]["data"]
        except (KeyError, TypeError):
            return []

    def _parse_item(self, item: dict) -> Listing | None:
        brand = (item.get("bike_brand") or {}).get("name") or ""
        model = item.get("bike_model_text") or ""
        title = f"{brand} {model}".strip()
        if not title:
            return None

        sizes = item.get("sizes") or []
        frame_size = sizes[0].get("value") if sizes else None

        return Listing(
            source=self.name,
            title=title,
            price_eur=float(item["price"]) if item.get("price") is not None else None,
            condition=_ZUSTAND_CODES.get(item.get("condition"), "unbekannt"),
            url=f"{BASE_URL}/de/bikes/{item['id']}",
            location=None,
            date_text=None,
            frame_size=frame_size,
            model_year=str(item["model_year"]) if item.get("model_year") else None,
            color=guess_color(title),
        )

    def _bestand_fuer_marke(self, brand_id: int) -> list[Listing]:
        ergebnisse: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            items = self._fetch_page(brand_id, page)
            if not items:
                break
            for item in items:
                listing = self._parse_item(item)
                if listing:
                    ergebnisse.append(listing)
            time.sleep(self.base_delay_s)
            if len(items) < 28:
                break
        return ergebnisse

    def search(
        self,
        search_terms: list[str],
        match_required: list[str] | None = None,
        match_boost: list[str] | None = None,
        min_score: float = 0,
    ) -> list[Listing]:
        if not match_required:
            return []
        brand_id = BRAND_IDS.get(match_required[0].lower())
        if brand_id is None:
            return []

        gesehen_urls: set[str] = set()
        treffer: list[Listing] = []

        for listing in self._bestand_fuer_marke(brand_id):
            if listing.url in gesehen_urls:
                continue
            gesehen_urls.add(listing.url)

            score = score_title(listing.title, match_required, match_boost or [])
            if score is None or score < min_score:
                continue
            listing.match_score = score

            treffer.append(listing)

        return treffer
