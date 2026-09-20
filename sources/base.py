"""
Gemeinsames Datenmodell + Basis-Klasse fuer alle Quellen-Module.

Jede Quelle bekommt ihr eigenes Modul (kleinanzeigen.py, bikemarkt.py, ...)
mit einer Klasse, die von Source erbt. main.py ruft jede Quelle in einem
try/except auf - ein Fehler in einer Quelle (Timeout, Blockade, geaendertes
HTML) darf die anderen Quellen nicht abschiessen, siehe run_source() in
main.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    source: str
    title: str
    price_eur: float | None
    condition: str  # "neu" | "gebraucht" | "refurbished" | "unbekannt"
    url: str
    location: str | None = None
    date_text: str | None = None  # Datum als Rohtext vom Inserat, nicht geparst
    frame_size: str | None = None
    model_year: str | None = None
    match_score: float | None = None


class ScraperBlocked(Exception):
    """Quelle blockt aktiv (z.B. 403, Captcha-Redirect, Cloudflare-Wall).
    main.py meldet das sauber statt es zu umgehen - siehe Auftragstext:
    'wenn eine Seite aktiv blockt: nicht umgehen, sondern sauber melden'."""


@dataclass
class Source:
    name: str
    base_delay_s: float = 2.0  # Pause zwischen Requests innerhalb dieser Quelle

    def search(self, search_terms: list[str]) -> list[Listing]:
        raise NotImplementedError
