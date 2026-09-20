#!/usr/bin/env python3
"""
main.py

CLI-Einstiegspunkt: laedt config/models.yaml, ruft jede aktivierte Quelle
auf (aktuell nur kleinanzeigen.de - weitere Quellen kommen als eigene Module
in sources/ dazu, siehe Auftragstext: erst eine Quelle fertig, dann die
naechste), gibt die Treffer sortiert als Tabelle aus und schreibt sie als
JSON mit Zeitstempel nach results/.

Start:
    venv/bin/python3 main.py <modell-id>
    venv/bin/python3 main.py cube-ams-hybrid-one44-c68x-race
    venv/bin/python3 main.py --list-models
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from sources.base import Listing, ScraperBlocked
from sources.kleinanzeigen import KleinanzeigenSource
from sources.bikemarkt import BikemarktSource
from sources.buycycle import BuycycleSource
from sources.upway import UpwaySource
from sources.jobrad import JobradSource
from sources.moehrle import MoehrleSource
from sources.mtbmania import MtbManiaSource
from sources.rebike import RebikeSource

REPO = Path(__file__).parent
CONFIG_PATH = REPO / "config" / "models.yaml"
RESULTS_DIR = REPO / "results"

# Jede Quelle hier eintragen, sobald ihr Modul steht - main.py ruft sie alle
# der Reihe nach auf und faengt Fehler einzeln ab.
SOURCES = [
    KleinanzeigenSource(),
    BikemarktSource(),
    BuycycleSource(),
    UpwaySource(),
    JobradSource(),
    MoehrleSource(),
    MtbManiaSource(),
    RebikeSource(),
]

console = Console()


def modelle_laden() -> list[dict]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["models"]


def modell_finden(modelle: list[dict], modell_id: str) -> dict:
    for m in modelle:
        if m["id"] == modell_id:
            return m
    verfuegbar = ", ".join(m["id"] for m in modelle)
    raise SystemExit(f"Unbekannte Modell-id '{modell_id}'. Verfuegbar: {verfuegbar}")


def quellen_abfragen(modell: dict) -> list[Listing]:
    alle_treffer: list[Listing] = []

    for source in SOURCES:
        console.print(f"[bold cyan]-> frage {source.name} ab...[/bold cyan]")
        try:
            treffer = source.search(
                search_terms=modell["search_terms"],
                match_required=modell["match_required"],
                match_boost=modell["match_boost"],
                min_score=modell["min_score"],
            )
            console.print(f"   {len(treffer)} passende Treffer bei {source.name}")
            alle_treffer.extend(treffer)
        except ScraperBlocked as e:
            console.print(f"   [yellow]{source.name} blockt gerade: {e}[/yellow]")
        except Exception as e:
            # Eine Quelle darf die anderen nicht abschiessen (siehe Auftragstext).
            console.print(f"   [red]Fehler bei {source.name}: {e}[/red]")

    return alle_treffer


def tabelle_ausgeben(treffer: list[Listing]) -> None:
    if not treffer:
        console.print("[yellow]Keine Treffer.[/yellow]")
        return

    treffer_sortiert = sorted(
        treffer, key=lambda t: (t.price_eur is None, t.price_eur)
    )

    table = Table(show_lines=False)
    table.add_column("Preis", justify="right", no_wrap=True)
    table.add_column("Zustand", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    table.add_column("Titel", max_width=45, no_wrap=True, overflow="ellipsis")
    table.add_column("Ort", max_width=20, no_wrap=True, overflow="ellipsis")
    table.add_column("Datum", no_wrap=True)
    table.add_column("Quelle", no_wrap=True)
    table.add_column("URL", max_width=40, no_wrap=True, overflow="ellipsis")

    for t in treffer_sortiert:
        preis = f"{t.price_eur:,.0f} €".replace(",", ".") if t.price_eur is not None else "-"
        score = f"{t.match_score:.0f}" if t.match_score is not None else "-"
        table.add_row(
            preis, t.condition, score, t.title, t.location or "-", t.date_text or "-",
            t.source, t.url,
        )

    console.print(table)


def json_speichern(modell_id: str, treffer: list[Listing]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    zeitstempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    pfad = RESULTS_DIR / f"{modell_id}_{zeitstempel}.json"
    daten = {
        "modell_id": modell_id,
        "abgefragt_am": datetime.now().isoformat(timespec="seconds"),
        "anzahl_treffer": len(treffer),
        "treffer": [asdict(t) for t in treffer],
    }
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)
    return pfad


def main() -> None:
    parser = argparse.ArgumentParser(description="Preis-Scanner fuer Fahrraeder")
    parser.add_argument("modell_id", nargs="?", help="id aus config/models.yaml")
    parser.add_argument("--list-models", action="store_true", help="verfuegbare Modell-ids auflisten")
    args = parser.parse_args()

    modelle = modelle_laden()

    if args.list_models or not args.modell_id:
        console.print("[bold]Verfuegbare Modelle:[/bold]")
        for m in modelle:
            console.print(f"  {m['id']}  ({m['display_name']})")
        if not args.modell_id:
            sys.exit(0 if args.list_models else 1)

    modell = modell_finden(modelle, args.modell_id)
    console.print(f"[bold]Suche: {modell['display_name']}[/bold]\n")

    treffer = quellen_abfragen(modell)
    console.print()
    tabelle_ausgeben(treffer)

    pfad = json_speichern(args.modell_id, treffer)
    console.print(f"\n[dim]Ergebnis gespeichert: {pfad}[/dim]")


if __name__ == "__main__":
    main()
