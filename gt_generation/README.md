# Ground Truth Generation

Generate evaluation-ready ground truth JSONL for ClinReasonBench from patient data plus guideline knowledge.

## Core Workflow

The refactored pipeline now supports both generation styles while preserving the original QC behavior:

- `one-step`: one LLM call returns already-tagged reasoning plus structured fields
- `two-step`: first call returns plain-text reasoning plus structured fields, second call adds tags
- both modes share the same schema validation, post-processing, graph QC, SEER conflict check, and resume policy

The pipeline performs:

1. input validation
2. LLM generation with parse retries
3. schema validation
4. post-processing into `treatment_gt`, `label`, `staging`, and `parsed_response`
5. graph-based QC on the final reasoning text
6. optional SEER conflict QC
7. merged checkpoint writing with status-based resume

## Usage

### One-step mode

```bash
python gt_generation/generate.py \
  --input data.jsonl \
  --graph graph.json \
  --guidance guidance.jsonl \
  --disease-type cancer \
  --output gt.jsonl \
  --api-key $OPENAI_API_KEY \
  --mode one-step
```

### Two-step mode

```bash
python gt_generation/generate.py \
  --input data.jsonl \
  --graph graph.json \
  --guidance guidance.jsonl \
  --disease-type cancer \
  --output gt.jsonl \
  --api-key $OPENAI_API_KEY \
  --mode two-step
```

Backward-compatible alias:

```bash
python gt_generation/generate.py ... --two-step
```

## Main Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `one-step` | Generation mode: `one-step` or `two-step` |
| `--two-step` | off | Deprecated alias for `--mode two-step` |
| `--model` | `gpt-4o` | Model for the generation step |
| `--tag-model` | same as `--model` | Optional separate model for the tagging step |
| `--max-retries` | `3` | API retry count per LLM call |
| `--max-parse-retries` | `5` | Retry count when output parsing/schema validation fails |
| `--resume-policy` | `qc-pass-only` | Resume behavior: `qc-pass-only`, `uuid-exists`, or `force-rerun` |
| `--no-strict-schema` | off | Relax strict output-schema checks |
| `--no-debug-fields` | off | Drop debug fields from the final output |
| `--disable-seer-qc` | off | Disable SEER-based treatment conflict checks |

## Resume Policy

- `qc-pass-only`: skip only records that already passed QC, aligned with the original pipeline behavior
- `uuid-exists`: skip any UUID already present in the output file
- `force-rerun`: regenerate every sample

## Output Fields

The output keeps the original QC-oriented fields:

- `response`
- `parsed_response`
- `thinking_tag`
- `add_tag_thinking`
- `tag_debug_response`
- `staging`
- `treatment_gt`
- `label`
- `auto_check_pass`
- `manual_check`
- `think_error`
- `tag_error`
- `check_error`
- `comment`
- `think_attempt`
- `tag_attempt`

## Notes

- Graph QC is run on the final reasoning text, not the raw first-stage reasoning.
- In two-step mode, if the tagging stage fails, the pipeline falls back to the untagged reasoning but marks the sample as QC-failed.
- Output writing uses merged replacement by UUID, so reruns update records instead of endlessly appending duplicates.
