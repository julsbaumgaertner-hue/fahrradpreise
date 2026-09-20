"""
Quelle: upway.de (Haendler fuer generaluberholte E-Bikes, u.a. Cube).

Struktur echt gegen die Live-Seite geprueft (Stand 2026-09-20):
- Volltextsuche funktioniert direkt ueber ?q=<begriff> (kein Cloudflare-
  Block, keine JS-Interaktion noetig fuer den Request selbst).
- Die Seite ist ein Shopify-Hydrogen-Storefront (React Router SSR), die
  Trefferliste steckt NICHT als klassisches HTML mit <a href="/products/...">
  im Markup (es gibt keine einzige /products/-URL im Rohdokument), sondern
  im React-Router-"turbo-stream"-SSR-Payload
  (<script>window.__reactRouterContext.streamController.enqueue("...")</script>).
  Das ist ein referenzbasiertes Flight-Format (wiederholte Objekt-Keys
  werden per Index dedupliziert), kein normales JSON - daher wird hier
  gezielt mit Regex je Produkt geparst statt versucht, das ganze Format
  generisch zu deserialisieren.
- Je Treffer im "products"-Array: Handle, "gid://shopify/Product/<id>",
  ISO-Datum, Titel, ... Bild-URL (cdn.shopify.com), ..., Preis als
  {"amount":"<X>.<Y>","currencyCode":"EUR"}, optional compareAtPrice
  (Upway-eigener Vergleichs-/Neupreis, nicht der Marktplatzpreis).
- Upway verkauft ausschliesslich generaluberholte Rader (siehe eigene
  Beschreibung "generalueberholt") - es gibt kein separates Zustandsfeld
  je Treffer in diesem Payload, daher condition hart auf "refurbished".
- Keine Pagination noetig fuer unsere Zwecke: Modellname ist so spezifisch,
  dass alle Treffer auf einer Seite liegen (in der Praxis <20 Treffer).
"""

from __future__ import annotations

import codecs
import re
import time

import requests

from matcher import score_title
from sources.base import Listing, ScraperBlocked, Source

BASE_URL = "https://upway.de"
SEARCH_PATH = "/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_ENQUEUE_MUSTER = re.compile(r'streamController\.enqueue\("(.*?)"\)', re.DOTALL)
_HANDLE_MUSTER = re.compile(r'"([a-z0-9-]+)","gid://shopify/Product/(\d+)"')
_DETAIL_MUSTER = re.compile(
    r'(?:"publishedAt",)?"(\d{4}-\d{2}-\d{2}T[0-9:.]+Z)","([^"]+)".*?'
    r'(https://cdn\.shopify\.com/[^"]+?\.(?:jpg|png|webp)[^"]*)".*?'
    r'"(\d+\.\d+)"(?:,\{[^}]*\},"(\d+\.\d+)")?',
    re.DOTALL,
)
_DETAIL_WINDOW = 1200  # Zeichen nach dem Handle-Treffer, in denen das Detail-Muster gesucht wird
_JAHR_MUSTER = re.compile(r"\b(20[12]\d)\b")


class UpwaySource(Source):
    name = "upway.de"

    def __init__(self) -> None:
        super().__init__(name="upway.de")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_raw(self, query: str) -> str:
        resp = self._session.get(
            BASE_URL + SEARCH_PATH, params={"q": query}, timeout=15
        )
        if resp.status_code in (403, 429):
            raise ScraperBlocked(f"upway.de blockt (HTTP {resp.status_code})")
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text

    def _extrahiere_treffer(self, html: str) -> list[Listing]:
        bloecke = _ENQUEUE_MUSTER.findall(html)
        try:
            voller_text = "".join(codecs.decode(b, "unicode_escape") for b in bloecke)
        except Exception:
            return []

        treffer: list[Listing] = []
        for hm in _HANDLE_MUSTER.finditer(voller_text):
            handle = hm.group(1)
            fenster = voller_text[hm.end() : hm.end() + _DETAIL_WINDOW]
            dm = _DETAIL_MUSTER.search(fenster)
            if not dm:
                continue
            _datum, title, image_url, preis, vergleichspreis = dm.groups()

            jahr_match = _JAHR_MUSTER.search(title)

            treffer.append(
                Listing(
                    source=self.name,
                    title=title,
                    price_eur=float(preis),
                    condition="refurbished",
                    url=f"{BASE_URL}/products/{handle}",
                    location=None,
                    date_text=None,
                    frame_size=None,
                    model_year=jahr_match.group(1) if jahr_match else None,
                )
            )
        return treffer

    def _search_one_term(self, term: str) -> list[Listing]:
        html = self._fetch_raw(term)
        return self._extrahiere_treffer(html)

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
