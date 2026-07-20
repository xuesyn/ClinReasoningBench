

# ClinReasonBench

A clinical reasoning benchmark for evaluating LLMs on treatment decision-making, guideline adherence, and survival prediction across 5 disease types.

## Leaderboard & Model Submission

**Live leaderboard:** https://leaderboard.clinreasoningbench.org/

Want your model evaluated and added to the leaderboard? We run the full evaluation
on the held-out benchmark for you — you don't need the ground-truth data.

**➡️ [Submit your model here](https://docs.google.com/forms/d/e/1FAIpQLSdIQ0Na0vcc0U0zf6xxlBlZdG46DBKz_swL1KdB5CqH54twhA/viewform)**

Please be ready to provide:

- **Model name and version**
- **Submitter / organization** and a **contact email**
- **Access type** — either:
  - *Open weights*: Hugging Face repo or download link (+ license), or
  - *Hosted API*: endpoint URL, model id, and how to authenticate
- **Inference details**: context window, chat template / required system prompt,
  recommended decoding parameters, and any rate limits
- **Chinese support**: confirmation the model handles Chinese clinical text
  (the benchmark is bilingual — Chinese guidelines with English-labeled metrics)
- *(Optional)* a short description or paper/model-card link

Once we validate access we run the evaluation and add your results to the
leaderboard (typically within a few weeks). Questions: [dongjiahong@mail.tsinghua.edu.cn](mailto:dongjiahong@mail.tsinghua.edu.cn).

## Supported Diseases & Guidelines

| Disease | Guideline | Tasks |
|---------|-----------|-------|
| BCLC | Barcelona Clinic Liver Cancer 2022 | Treatment Decision + Survival Prediction |
| CNLC | 原发性肝癌诊疗指南（2024年版） | Treatment Decision + Survival Prediction |
| NSCLC | 中华医学会肺癌临床诊疗指南（2024版） | Treatment Decision + Survival Prediction |
| ACS | 2025 ACC/AHA ACS Guideline | Treatment Decision (Set) + Survival Prediction |
| AIS | AHA/ASA Acute Ischemic Stroke 2019 | Treatment Decision (Set) + Survival Prediction |

## Setup

```bash
conda create --name cdBench python=3.10
conda activate cdBench
pip install -r requirements.txt
mkdir ckpt
python tools/download_ckpt.py
```

## Data Availability

The evaluation datasets in this benchmark are derived from two restricted-access sources:

- **Cancer cohorts (BCLC, CNLC, NSCLC)** — derived from the [SEER Research Database](https://seer.cancer.gov/data-software/), which requires a signed [SEER Research Data Agreement](https://seer.cancer.gov/data/access.html) for access to individual-level records.
- **Emergency cohorts (ACS, AIS)** — derived from [MIMIC-IV](https://physionet.org/content/mimiciv/), which requires a PhysioNet credentialed user account and a signed data use agreement.

Because both source DUAs restrict redistribution of individual-level records, **we do not host the full evaluation GT files in this repository**. To reproduce the paper's numbers:

1. Obtain the underlying data through the standard channels above (SEER-Stat or PhysioNet).
2. Contact the corresponding author (see [Citation](#citation)) after confirming your access — we will share the derived GT JSONL files for verified DUA holders.
3. Alternatively, generate your own GT files from any patient-record cohort using the [`gt_generation/`](gt_generation/README.md) pipeline in this repo (guidelines, graph definitions, and prompts are all included).

For pipeline smoke-testing without any data access, a few **fully synthetic** sample records (fabricated values — not real patients and not derived from SEER/MIMIC) are bundled at `eval_data/test_subset_50/test.jsonl`. They exist only to verify the evaluation pipeline runs end-to-end and are **not** suitable for benchmark comparison.

## Quick Start

### Single experiment (legacy config)

```bash
# Edit configs/eval_config_bclc.yaml with your API key and model settings
python eval.py --config configs/eval_config_bclc.yaml
```

### Batch evaluation (recommended)

```bash
# Single experiment via unified runner
python run_batch.py -c configs/eval_config_bclc.yaml

# Batch config with multiple models × diseases
python run_batch.py -c configs/batch_all.yaml --parallel 3

# Re-score existing inference results (skip API calls)
python run_batch.py -c configs/eval_config_bclc.yaml --skip-inference --rescore
```

## Additional Modules

### Ground Truth Generation

The repository now includes a standalone GT generation pipeline under `gt_generation/`.

Typical usage:

```bash
python gt_generation/generate.py \
  --input data.jsonl \
  --graph data/CNLC/cnlc_graph_beta_v1.json \
  --guidance data/CNLC/cnlc_guidance.jsonl \
  --disease-type cancer \
  --output gt.jsonl \
  --api-key $OPENAI_API_KEY \
  --mode one-step
```

See `gt_generation/README.md` for the full workflow, including one-step vs two-step generation and QC-aware resume behavior.

### Visual Inspection Tools

The repository also includes a lightweight visual workspace under `visual_tools/` for browsing data, GT annotations, references, and model outputs. The sample records bundled under `visual_tools/data/` and `visual_tools/ground_truth/` are **fully synthetic** (fabricated, not SEER/MIMIC-derived) and exist only to demonstrate the tool.

See:
- `visual_tools/README.md`
- `visual_tools/README_zh.md`

## Configuration

### Legacy format (one model × one dataset per YAML)

```yaml
experiment_name: bclc_eval_exp_v1
output_dir: outputs

models:
  gpt-5.2:
    type: openai
    model_name: "gpt-5.2"
    api_key: "YOUR_API_KEY_HERE"
    base_url: "https://api.openai.com/v1"
    max_tokens: 8192
    temperature: 0.1
    max_retry: 3
    timeout: 120

datasets:
  BCLC:
    gt_path: ["eval_data/labeled_bclc_gt_treatment/filtered_part_0_gt.jsonl"]
    graph_def_path: "data/BCLC/bclc_graph_beta_v2.json"
    prompt_template_path: "prompts/thinking_all_task_cite_version_bclc.txt"
    reference_guideline_name: "BCLC 2022 update"
    task: "treatment"  # or "survival"

evaluation_params:
  pass_k: 1
  num_workers: 8
  skip_inference: false
  save_interval: 10

metrics:
  GraphBasedMetric: { ... }
  treatment_score: { threshold: 0.5 }
  staging_score: { allowed_stagings: ['0', 'a', 'b', 'c', 'd'] }
  Indication_and_contraindication_score: {}
  treatment_calibration: { threshold: 0.5, k: null, top_m: 3, tau: 1, use_position_weighting: true }
```

### Batch format (multiple experiments in one YAML)

```yaml
project_root: "."
output_base_dir: "outputs"

models:
  gpt-5.2:
    type: openai
    model_name: "gpt-5.2"
    api_key: "${MEDEVAL_API_KEY}"     # environment variable support
    base_url: "https://api.openai.com/v1"

experiments:
  - disease: bclc
    task: treatment               # treatment / survival_gt / survival_model
    models: [gpt-5.2]
    gt_paths: [...]
    version: "v1"

  - disease: bclc
    task: survival_gt
    models: [gpt-5.2]
    gt_paths: [...]
    version: "v1"

  - disease: bclc
    task: survival_model
    models: [gpt-5.2]
    treatment_source_experiments:
      gpt-5.2: "bclc_eval_exp_v1_gpt-5.2_treatment"
    gt_paths: [...]
    version: "v1"

evaluation_params:
  pass_k: 1
  num_workers: 8
  save_interval: 10

itt:
  enabled: true
  union_meta_base_dir: "eval_data/unfiltered_meta"
```

## Evaluation Pipeline

```
Patient EMR + Clinical Guideline
            │
            ▼
┌──────────────────────────────────┐
│  Task 1: Treatment Decision      │
│  Model outputs structured JSON:  │
│  - thinking (with <tag> markup)  │
│  - treatment scores / list       │
│  - staging, indication/contra    │
│  - <cite> guideline references   │
├──────────────────────────────────┤
│  Metrics:                        │
│  ├ Graph-based reasoning score   │
│  ├ Citation semantic matching    │
│  ├ Treatment NDCG / F1 overlap   │
│  ├ Staging accuracy              │
│  ├ Indication/contraindication   │
│  └ Calibration ECE               │
└────────────┬─────────────────────┘
             │ treatment predictions
             ▼
┌──────────────────────────────────┐
│  Task 2: Survival Prediction     │
│  Two variants:                   │
│  ├ GT Treatment → predict surv   │
│  └ Model Treatment → predict surv│
├──────────────────────────────────┤
│  Metrics:                        │
│  ├ C-index                       │
│  ├ IPCW-MAE (censoring-adjusted) │
│  ├ AURC (selective prediction)   │
│  └ Stage-wise subgroup analysis  │
└──────────────────────────────────┘
```

## Metrics Reference

### Treatment Decision

| Metric | Config Key | Cancer | Emergency | Description |
|--------|-----------|--------|-----------|-------------|
| GraphBasedMetric | `GraphBasedMetric` | ✓ | ✓ | Knowledge graph node matching + citation semantic matching |
| TreatmentNDCG | `treatment_score` | ✓ | | Ranking quality of treatment recommendations |
| TreatmentOverlapMetrics | `treatment_set_score` | | ✓ | Set overlap (medication + procedure) |
| StagingScore | `staging_score` | ✓ | | Clinical staging accuracy |
| Indication/Contraindication | `Indication_and_contraindication_score` | ✓ | ✓ | Guideline adherence |
| TreatmentCalibration | `treatment_calibration` | ✓ | | ECE of treatment confidence |
| SetCalibrationECE | `set_calibration` | | ✓ | ECE for set-based predictions |

### Survival Prediction

| Metric | Config Key | Description |
|--------|-----------|-------------|
| SurvivalConfidenceScore | `survival_calibration` | C-index, IPCW-MAE, AURC, selective gain |
| SurvivalScore | `survival_score` | Basic concordance index |

## Disease Registry

All per-disease configuration is centralized in `med_eval_pipeline/disease_registry.py`:
- Data paths (knowledge graph, guidance, embeddings)
- Prompt templates
- Staging configuration
- Metrics configuration (treatment + survival)

To add a new disease/guideline, add a `DiseaseConfig` entry to `DISEASE_REGISTRY`.

## Output Files

| File | Description |
|------|-------------|
| `*@inference.jsonl` | Raw model outputs (uuid, predictions) |
| `*@scores.jsonl` | Per-sample metric scores |
| `score_{timestamp}.jsonl` | Aggregated summary scores |
| `*_meta.jsonl` | Preprocessed GT data with knowledge subgraphs |

## Project Structure

```
ClinReasonBench/
├── eval.py                          # Single-experiment entry point
├── run_batch.py                     # Unified batch runner (recommended)
├── med_eval_pipeline/
│   ├── evaluator.py                 # Inference + scoring orchestration
│   ├── data_processor.py            # Data loading + prompt generation
│   ├── graph_tool.py                # Knowledge graph construction
│   ├── disease_registry.py          # Centralized disease configuration
│   ├── config_loader.py             # YAML loading + env var expansion
│   ├── treatment_labeler.py         # Survival data preparation
│   ├── models/
│   │   ├── base_api.py              # Abstract API with retry
│   │   ├── api_openai.py            # OpenAI-compatible client
│   │   └── api_vllm.py              # vLLM client
│   └── metrics/
│       ├── base.py                  # BaseMetric abstract class
│       ├── calculator.py            # MetricCalculator orchestration
│       ├── clinical.py              # All clinical metric classes
│       └── graph_based_metric.py    # Semantic/ID-based graph matching
├── configs/                         # Example YAML configurations
├── data/                            # Knowledge graphs + guidelines
├── gt_generation/                   # GT generation pipeline
├── visual_tools/                    # Visual inspection workspace
├── prompts/                         # Prompt templates per disease
├── tools/
│   └── download_ckpt.py             # Download embedding model checkpoint
└── requirements.txt
```

## Citation

The accompanying paper is currently under submission. If you use this benchmark in your research, please cite this repository for now (see [`CITATION.cff`](CITATION.cff) or use the "Cite this repository" button on GitHub). We will update this section with the paper's BibTeX entry once it is publicly available (e.g. on arXiv).

## License

Code in this repository is released under the [MIT License](LICENSE).

The upstream data (SEER, MIMIC-IV) and their re-distribution constraints are covered by their respective data-use agreements — see the [Data Availability](#data-availability) section above.

