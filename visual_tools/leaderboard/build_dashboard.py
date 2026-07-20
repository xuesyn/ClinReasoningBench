#!/usr/bin/env python3
"""Pre-render the leaderboard dashboard JSON from the results spreadsheet.

The deployed leaderboard is a fully static site (HTML + JS + one JSON file), so
there is no server at runtime. This script parses the results Excel file into the
same JSON payload the FastAPI backend used to serve at ``/api/results/dashboard``
and writes it to ``dashboard.json`` next to ``index.html``.

Re-run this whenever the results spreadsheet changes, then redeploy the folder.

Usage:
    python build_dashboard.py
    python build_dashboard.py --excel ../results/results_filtered_latest.xlsx --out dashboard.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LEADERBOARD_DIR = Path(__file__).resolve().parent
VISUAL_TOOLS_DIR = LEADERBOARD_DIR.parent

# Reuse the single source of truth for parsing (app/services/results_service.py)
# so the leaderboard and the local viz tool never drift apart.
sys.path.insert(0, str(VISUAL_TOOLS_DIR))
from app.services.results_service import _build_results_dashboard  # noqa: E402

DEFAULT_EXCEL = VISUAL_TOOLS_DIR / "results" / "results_filtered_latest.xlsx"
DEFAULT_OUT = LEADERBOARD_DIR / "dashboard.json"


def build(excel_path: Path, out_path: Path) -> None:
    if not excel_path.exists():
        raise SystemExit(f"Excel file not found: {excel_path}")

    payload = _build_results_dashboard(excel_path)
    # Do not leak the local absolute path into a public artifact.
    payload["source_file"] = excel_path.name

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    models = len(payload["models"])
    datasets = len(payload["datasets"])
    metrics = len(payload["metric_catalog"])
    print(f"Wrote {out_path} ({models} models, {datasets} datasets, {metrics} metrics)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL, help="Path to the results .xlsx file")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output JSON path")
    args = parser.parse_args()
    build(args.excel.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
