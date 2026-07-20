from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
REFERENCE_DIR = ROOT_DIR / "reference"
GROUND_TRUTH_DIR = ROOT_DIR / "ground_truth"
DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"

