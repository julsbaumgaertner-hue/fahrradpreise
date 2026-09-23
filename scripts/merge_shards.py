#!/usr/bin/env python3
"""
Fuegt die scans_main.json aus allen parallelen Shard-Jobs (siehe
scan_all.py --shard/--shards und der "merge"-Job in
.github/workflows/scan.yml) zur finalen public/scans_main.json zusammen. Jedes
Modell steckt in genau einem Shard, es gibt also keine Ueberschneidungen -
einfaches Zusammenhaengen reicht, keine Deduplizierung noetig.

Aufruf: python merge_shards.py <shard-dir> [<shard-dir> ...]
Jedes <shard-dir> enthaelt scans_main.json aus genau einem Shard-Lauf (von actions/download-artifact).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
PUBLIC_DIR = REPO / "public"


def main() -> None:
    shard_dirs = [Path(p) for p in sys.argv[1:]]
    if not shard_dirs:
        sys.exit("Usage: merge_shards.py <shard-dir> [<shard-dir> ...]")

    scans_main: list[dict] = []

    for d in shard_dirs:
        scans_main.extend(json.loads((d / "scans_main.json").read_text(encoding="utf-8")))

    PUBLIC_DIR.mkdir(exist_ok=True)
    (PUBLIC_DIR / "scans_main.json").write_text(
        json.dumps(scans_main, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"{len(scans_main)} Modelle gemergt, "
        f"{sum(s['anzahl_treffer'] for s in scans_main)} Treffer"
    )


if __name__ == "__main__":
    main()
