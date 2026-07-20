# visual_tools

This directory has two parts:

1. **`leaderboard/`** — a **static, deployable leaderboard** (HTML/JS + one
   pre-rendered `dashboard.json`, no backend). This is what you publish to
   Cloudflare Pages. See [`leaderboard/README.md`](./leaderboard/README.md).
2. **The local visualization tool** (`app/` + `frontend/`) — a FastAPI app for
   inspecting the benchmark internals. Run it locally; it is **not** meant to be
   deployed publicly because it reads unpublished data.

## 1. Leaderboard (public, static)

The final results live in `results/results_filtered_latest.xlsx`. Regenerate the
leaderboard data and deploy:

```bash
cd leaderboard
pip install openpyxl
python build_dashboard.py      # writes dashboard.json
```

Deployment (Cloudflare Pages, etc.) is documented in
[`leaderboard/README.md`](./leaderboard/README.md).

## 2. Local visualization tool

Used to locally inspect:

- `reference` graphs (graph definition, node rules, guidance entries)
- `ground_truth` annotation data (the clinician GT-check tool)
- `data` model output data (browse model predictions vs. ground truth)

It also serves the results dashboard locally at `/results` (same data as the
leaderboard), which is handy for a quick check before publishing.

### Setup and run

```bash
pip install fastapi uvicorn openpyxl
uvicorn app.main:app --host 127.0.0.1 --port 2028 --reload
```

Open these pages after startup:

- `http://127.0.0.1:2028/reference`
- `http://127.0.0.1:2028/gt`
- `http://127.0.0.1:2028/data`
- `http://127.0.0.1:2028/results`

### Data sources and how to replace them

The tool reads data directly from these folders under `visual_tools`:

- `reference/`: reference graphs and guidance files
- `ground_truth/`: GT annotation files
- `data/`: model output samples
- `results/results_filtered_latest.xlsx`: aggregated benchmark results

To replace the data, just replace the files in these locations. No frontend
changes are required.

- **`reference`**: add subdirectories under `reference/`; the page scans them
  automatically.
- **`ground_truth`**: add files under `ground_truth/`; the `gt` page loads the
  available file list automatically.
- **`data`**: add files under `data/`; the `data` page loads the available file
  list automatically.
- **`results`**: replace `results/results_filtered_latest.xlsx`. To refresh the
  public leaderboard afterwards, re-run `leaderboard/build_dashboard.py` and
  redeploy.
