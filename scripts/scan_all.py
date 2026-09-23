#!/usr/bin/env python3
"""
Fuer den GitHub-Actions-Workflow (.github/workflows/scan.yml): scannt Modelle
aus config/models.yaml ueber main.py's bestehende Pipeline (quellen_abfragen +
gewicht_schaetzen, inkl. Rahmen-only-/Preisfilter) und schreibt
scans_main.json, das das Preisradar-Artefakt per fetch() direkt von
raw.githubusercontent.com laedt.

Format je Eintrag: {model_id, display_name, abgefragt_am, anzahl_treffer,
treffer[]} - exakt das Format, das SEED_SCANS im Artefakt erwartet.

Unterstuetzt Sharding fuer parallele Matrix-Jobs (17 Modelle nacheinander
brauchen ~70-90 Min wegen base_delay_s-Ratenlimit je Quelle - live gegen
GitHub Actions getestet am 21.09.2026, 8 von 17 Modellen in 30 Min):
    python scan_all.py --shard 2 --shards 6 --out-dir shard-2
verarbeitet nur jedes 6. Modell (Index 2, 8, 14, ...) und schreibt in
--out-dir statt public/. Ohne Argumente: alle Modelle, Ausgabe nach public/
(unveraendertes Verhalten fuer lokale Einzellaeufe).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from main import gewicht_schaetzen, gewichtsreferenz_laden, modelle_laden, quellen_abfragen  # noqa: E402


def scan_modell(modell: dict, referenz: dict) -> dict:
    treffer = quellen_abfragen(modell)
    gewicht_schaetzen(treffer, modell["id"], referenz)
    return {
        "model_id": modell["id"],
        "display_name": modell["display_name"],
        "abgefragt_am": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anzahl_treffer": len(treffer),
        "treffer": [asdict(t) for t in treffer],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scannt (einen Anteil der) Modelle aus config/models.yaml")
    parser.add_argument("--shard", type=int, default=0, help="Index dieses Shards (0-basiert)")
    parser.add_argument("--shards", type=int, default=1, help="Gesamtzahl der Shards")
    parser.add_argument("--out-dir", type=Path, default=None, help="Ausgabeverzeichnis (Default: public/)")
    args = parser.parse_args()

    if not (0 <= args.shard < args.shards):
        parser.error("--shard muss zwischen 0 und --shards - 1 liegen")

    out_dir = args.out_dir or (REPO / "public")

    alle_modelle = modelle_laden()
    modelle = alle_modelle[args.shard :: args.shards]
    referenz = gewichtsreferenz_laden()

    scans_main: list[dict] = []

    for modell in modelle:
        print(f"[Shard {args.shard}/{args.shards}] Scanne {modell['display_name']}...", file=sys.stderr)
        scans_main.append(scan_modell(modell, referenz))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scans_main.json").write_text(
        json.dumps(scans_main, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"[Shard {args.shard}/{args.shards}] "
        f"{sum(s['anzahl_treffer'] for s in scans_main)} Treffer",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
