#!/usr/bin/env python3
"""Pre-render the leaderboard dashboard JSON from the results spreadsheet.

The deployed leaderboard is a fully static site (HTML + JS + one JSON file), so
there is no server at runtime. This script parses the results Excel file into the
same JSON payload the FastAPI backend used to serve at ``/api/results/dashboard``
and writes it to ``dashboard.json`` next to ``index.html``.

Re-run this whenever the results spreadsheet changes, then redeploy the folder.

Usage:
    python build_dashboard.py
    python build_dashboard.py --excel ../results/results_paper_final.xlsx --out dashboard.json

The SHA-256 of the input workbook is recorded in the payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

LEADERBOARD_DIR = Path(__file__).resolve().parent
VISUAL_TOOLS_DIR = LEADERBOARD_DIR.parent

# Reuse the single source of truth for parsing (app/services/results_service.py)
# so the leaderboard and the local viz tool never drift apart.
sys.path.insert(0, str(VISUAL_TOOLS_DIR))
from app.services.results_service import _build_results_dashboard  # noqa: E402

DEFAULT_EXCEL = VISUAL_TOOLS_DIR / "results" / "results_paper_final.xlsx"
DEFAULT_OUT = LEADERBOARD_DIR / "dashboard.json"

SCOPE_NOTE = (
    "Main-benchmark treatment-decision leaderboard: 16 models x 5 guideline cohorts (BCLC 3,689; CNLC 4,103; "
    "NSCLC 4,219; ACS 3,611; AIS 3,657 cases), intent-to-treat (parse failures count as errors). Survival, SFT, "
    "single-centre HCC and clinician-comparison results are provided as downloadable tables (downloads/)."
)


def _nan_to_none(obj):
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_to_none(v) for v in obj]
    return obj


def build(excel_path: Path, out_path: Path) -> None:
    if not excel_path.exists():
        raise SystemExit(f"Excel file not found: {excel_path}")

    payload = _build_results_dashboard(excel_path)
    # Do not leak the local absolute path into a public artifact.
    payload["source_file"] = excel_path.name
    payload["source_sha256"] = hashlib.sha256(excel_path.read_bytes()).hexdigest()
    payload["scope"] = SCOPE_NOTE
    payload = _nan_to_none(payload)

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

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
