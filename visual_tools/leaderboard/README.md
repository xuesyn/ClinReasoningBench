# ClinReasoningBench Leaderboard (static)

A fully static leaderboard — plain HTML/CSS/JS plus a single pre-rendered
`dashboard.json`. There is **no backend at runtime**, so it deploys to Cloudflare
Pages (or any static host) for free. The only external dependency is D3, loaded
from the jsDelivr CDN.

```
leaderboard/
├── index.html            # the page
├── dashboard.json        # pre-rendered data (committed; regenerate when results change)
├── build_dashboard.py    # regenerates dashboard.json from the results spreadsheet
└── assets/
    ├── js/results-page.js
    └── styles/{base,site-shell,results}.css
```

## Update the numbers

The data is baked into `dashboard.json`, rendered from `../results/results_paper_final.xlsx`
(16 models). That workbook is produced by
`../results/build_results_xlsx.py` from an explicit manifest of per-case score files and the case roster
(not distributed; see the repository README). Its `.provenance.json` records the source file names and
SHA-256 hashes. Regenerate and redeploy whenever results change:

```bash
# from this leaderboard/ directory (needs: pip install openpyxl)
python build_dashboard.py
# custom input/output:
python build_dashboard.py --excel ../results/results_paper_final.xlsx --out dashboard.json
```

`dashboard.json` records `source_sha256` (of the workbook) and the leaderboard scope.
Acute cohorts (ACS, AIS) report `Treatment set-F1`, the paper's treatment metric; `all_acc` / `med_acc` /
`proc_acc` are set precisions and are not the same quantity. Aggregate tables for the other analyses in the
paper are in `downloads/` (see `downloads/README.md`).

The parser is shared with the local visualization tool
(`app/services/results_service.py`), so the two never drift apart.

## Deploy to Cloudflare Pages

Because `dashboard.json` is committed, **no build step is required** on Cloudflare.

**Option A — Git integration (recommended)**

1. Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git.
2. Pick the repository.
3. Build settings:
   - Framework preset: **None**
   - Build command: *(leave empty)*
   - Build output directory: `visual_tools/leaderboard`
4. Save and deploy. Every push that changes this folder redeploys automatically.

**Option B — Wrangler CLI (direct upload)**

```bash
npx wrangler pages deploy visual_tools/leaderboard --project-name clinreasoningbench-leaderboard
```

**Option C — Drag & drop**

Cloudflare dashboard → Pages → Upload assets → drag the `leaderboard/` folder.

## Local preview

```bash
python -m http.server 8000    # then open http://127.0.0.1:8000
```

Opening `index.html` via `file://` will not work — `fetch("./dashboard.json")`
requires an `http(s)` origin, so use a local server.
