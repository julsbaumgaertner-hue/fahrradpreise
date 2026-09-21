#!/usr/bin/env python3
"""
Fuer den GitHub-Actions-Workflow (.github/workflows/scan.yml): scannt alle
Modelle aus config/models.yaml ueber main.py's bestehende Pipeline
(quellen_abfragen + gewicht_schaetzen, inkl. Rahmen-only-/Preisfilter) und
schreibt zwei JSON-Dateien nach public/, die das Preisradar-Artefakt per
fetch() direkt von raw.githubusercontent.com laedt:
- public/scans_main.json: alle Quellen AUSSER kleinanzeigen.de
- public/scans_kleinanzeigen.json: NUR kleinanzeigen.de

Format je Eintrag: {model_id, display_name, abgefragt_am, anzahl_treffer,
treffer[]} - exakt das Format, das SEED_SCANS im Artefakt erwartet.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from main import gewicht_schaetzen, gewichtsreferenz_laden, modelle_laden, quellen_abfragen  # noqa: E402

PUBLIC_DIR = REPO / "public"


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
    modelle = modelle_laden()
    referenz = gewichtsreferenz_laden()

    scans_main: list[dict] = []
    scans_kanz: list[dict] = []

    for modell in modelle:
        print(f"Scanne {modell['display_name']}...", file=sys.stderr)
        scan = scan_modell(modell, referenz)
        treffer = scan["treffer"]

        scan_main = {**scan, "treffer": [t for t in treffer if t["source"] != "kleinanzeigen.de"]}
        scan_main["anzahl_treffer"] = len(scan_main["treffer"])
        scans_main.append(scan_main)

        scan_kanz = {**scan, "treffer": [t for t in treffer if t["source"] == "kleinanzeigen.de"]}
        scan_kanz["anzahl_treffer"] = len(scan_kanz["treffer"])
        scans_kanz.append(scan_kanz)

    PUBLIC_DIR.mkdir(exist_ok=True)
    (PUBLIC_DIR / "scans_main.json").write_text(
        json.dumps(scans_main, ensure_ascii=False), encoding="utf-8"
    )
    (PUBLIC_DIR / "scans_kleinanzeigen.json").write_text(
        json.dumps(scans_kanz, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"{sum(s['anzahl_treffer'] for s in scans_main)} Treffer (ohne kleinanzeigen.de), "
        f"{sum(s['anzahl_treffer'] for s in scans_kanz)} Treffer (kleinanzeigen.de)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
