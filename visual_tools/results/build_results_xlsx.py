#!/usr/bin/env python3
"""Build the leaderboard results workbook (input of ``visual_tools/leaderboard/build_dashboard.py``).

Every number is re-aggregated from per-case ``@scores.jsonl`` files that are listed explicitly in a
source manifest (no directory globbing, no modification-time heuristics), restricted to the
per-cohort case roster used in the paper:

    BCLC 3,689 · CNLC 4,103 · NSCLC 4,219 · ACS 3,611 · AIS 3,657   (16 models)

The per-case files, the roster (case UUIDs) and the manifest itself are not distributed in this
repository (see "Data Availability" in the top-level README); the script is published so the
aggregation is transparent and reproducible for verified data holders.

Manifest (JSON)::

    {"roster": "<path to {cohort: [uuid, ...]}>",
     "backfill": "<optional path: {cohort: {model: {field: value}}}>",
     "cells": [{"cohort": "bclc", "model": "GPT-5.2", "scores": "<path>/...@scores.jsonl"}, ...]}

``backfill`` supplies per-cell aggregates of fields that a slim export did not keep
(``ind_con_exact_match``, ``meta_missing_staging_pred``, ``meta_missing_staging_gt``).

Usage::

    python build_results_xlsx.py --manifest manifest.json --out results_paper_final.xlsx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

import openpyxl

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
from med_eval_pipeline.metrics.clinical import SetCalibrationECE, TreatmentCalibration  # noqa: E402

# paper model roster: canonical name -> leaderboard display name (order = column order)
MODELS = [
    ("GPT-5.2", "GPT-5.2"), ("Claude 4.5 Sonnet", "Claude 4.5 sonnet"), ("Gemini 3 Pro", "Gemini 3 pro preview"),
    ("Baichuan-M3-plus", "Baichuan-M3 (plus)"), ("MedGemma-27B", "medgemma"), ("GLM-4.7", "GLM-4.7"),
    ("Kimi-K2.5", "kimi-k2.5"), ("DeepSeek-V3.2", "Deepseek-v3.2"), ("Qwen-Max", "Qwen-Max"),
    ("Qwen3.5-Plus", "Qwen3.5-Plus"), ("GPT-5.6-sol", "GPT-5.6-sol"), ("Claude Opus 4.7", "Claude Opus 4.7"),
    ("DeepSeek-V4-Flash", "DeepSeek-V4-Flash"), ("GLM-5.2", "GLM-5.2"),
    ("GPT-6-sol", "GPT-6-sol"), ("Claude Sonnet 5", "Claude Sonnet 5"),
]
# (cohort id used in score files, sheet block header [数据集, 病种, 指南], roster size, family)
COHORTS = [
    ("cnlc", ["seer", "肝癌", "cnlc"], 4103, "onc"),
    ("bclc", [None, None, "bclc"], 3689, "onc"),
    ("nsclc", [None, "肺癌", "中国肺癌2024"], 4219, "onc"),
    ("mi", ["mimic", "心梗", "Aha https://www.ahajournals.org/doi/10.1161/CIR.0000000000001309"], 3611, "emg"),
    ("stroke", [None, "脑梗", "Aha https://www.ahajournals.org/doi/10.1161/STROKEAHA.119.027708"], 3657, "emg"),
]
ONC_PLAN = [("parse_error_rate", "parse_error_rate"), ("pw_ece_mem", "PW ECE Mem"), ("pw_ece_rt", "PW ECE RT"),
            ("ndcg_ece", "NDCG ECE"), ("ind_hit", "禁忌证和适应证(命中分)"), ("ind_exact", "禁忌证和适应证（完全匹配分）"),
            ("treatment_ndcg", "治疗 ndcg"), ("staging", None), ("pred_miss_stag", "Pred missing staging rate"),
            ("reasoning", "推理（graph+citation）")]
EMG_PLAN = [("parse_error_rate", "parse_error_rate"), ("iou_ece", "IOU ECE"), ("f1_ece", "F1 ECE"),
            ("ind_hit", "禁忌证和适应证(命中分)"), ("ind_exact", "禁忌证和适应证（完全匹配分）"),
            ("set_f1", "Treatment set-F1"),
            ("proc_acc", "治疗（proc_acc）"), ("proc_recall", "proc_recall"), ("med_acc", "med_acc"),
            ("med_recall", "med_recall"), ("all_acc", "all_acc"), ("all_recall", "all_recall"),
            ("reasoning", "推理（graph+citation）")]


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return sum(xs) / len(xs) if xs else None


def set_f1(sr):
    """Per-case set-F1 for acute cohorts from stored set precision (``treatment_total_acc``) and recall."""
    p, r = sr.get("treatment_total_acc"), sr.get("treatment_total_recall")
    if p is None or r is None or (p + r) == 0:
        return 0.0
    return 2 * p * r / (p + r)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cell(path, roster):
    """Per-case score_results on the roster, one record per UUID (last occurrence wins, as in the evaluator)."""
    by_uuid = {}
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                if rec.get("uuid") in roster:
                    by_uuid[rec["uuid"]] = rec.get("score_results", {})
    return list(by_uuid.values())


def aggregate(recs, family):
    m = {
        "n": len(recs),
        "parse_error_rate": mean([1.0 if r.get("meta_parse_failed") else 0.0 for r in recs]),
        "ind_hit": mean([r.get("ind_con_mean_score") for r in recs]),
        "ind_exact": mean([r.get("ind_con_exact_match") for r in recs]),
        "reasoning": mean([r.get("final_score") for r in recs]),
    }
    if family == "onc":
        agg = TreatmentCalibration({}).aggregate(recs)
        m.update({"pw_ece_mem": agg.get("pw_ece_mem"), "pw_ece_rt": agg.get("pw_ece_rt"), "ndcg_ece": agg.get("ndcg_ece"),
                  "treatment_ndcg": mean([r.get("treatment_ndcg") for r in recs]),
                  "staging": mean([r.get("staging_score") for r in recs]),
                  "gt_miss_stag": mean([r.get("meta_missing_staging_gt") for r in recs]),
                  "pred_miss_stag": mean([r.get("meta_missing_staging_pred") for r in recs])})
    else:
        agg = SetCalibrationECE({}).aggregate(recs)
        m.update({"iou_ece": agg.get("iou_ece"), "f1_ece": agg.get("f1_ece"),
                  "set_f1": mean([set_f1(r) for r in recs]),
                  "proc_acc": mean([r.get("treatment_proc_acc") for r in recs]),
                  "proc_recall": mean([r.get("treatment_proc_recall") for r in recs]),
                  "med_acc": mean([r.get("treatment_med_acc") for r in recs]),
                  "med_recall": mean([r.get("treatment_med_recall") for r in recs]),
                  "all_acc": mean([r.get("treatment_total_acc") for r in recs]),
                  "all_recall": mean([r.get("treatment_total_recall") for r in recs])})
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--provenance-out", help="optional JSON: per-cell file name, sha256, n (no local paths)")
    ap.add_argument("--no-set-f1", action="store_true", help="omit the acute set-F1 row (legacy layout)")
    args = ap.parse_args()
    man = json.load(open(args.manifest))
    roster = {k: set(v) for k, v in json.load(open(man["roster"])).items()}
    canon = [c for c, _ in MODELS]
    cells, prov = {}, []
    for cell in man["cells"]:
        cohort, model, path = cell["cohort"], cell["model"], cell["scores"]
        if model not in canon:
            raise SystemExit(f"model not in the paper roster: {model!r}")
        if (cohort, model) in cells:
            raise SystemExit(f"duplicate manifest cell: {cohort}/{model}")
        family = next(f for c, _h, _n, f in COHORTS if c == cohort)
        recs = load_cell(path, roster[cohort])
        cells[(cohort, model)] = aggregate(recs, family)
        prov.append({"cohort": cohort, "model": model, "file": os.path.basename(path), "sha256": sha256(path), "n": len(recs)})
    for cohort, _h, n_roster, _f in COHORTS:
        for model in canon:
            got = cells.get((cohort, model), {}).get("n")
            if got != n_roster:
                raise SystemExit(f"{cohort}/{model}: {got} roster cases found, expected {n_roster}")
    if man.get("backfill"):
        for cohort, per_model in json.load(open(man["backfill"])).items():
            for model, vals in per_model.items():
                cell = cells[(cohort, model)]
                for src, dst in (("ind_con_exact_match", "ind_exact"), ("meta_missing_staging_pred", "pred_miss_stag"),
                                 ("meta_missing_staging_gt", "gt_miss_stag")):
                    if vals.get(src) is not None:
                        cell[dst] = vals[src]

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sheet1"

    def put(vals, r):
        for c, v in enumerate(vals, start=1):
            if isinstance(v, float) and math.isnan(v):
                v = None
            ws.cell(r, c, v)

    put(["数据集", "病种", "指南", None] + [d for _c, d in MODELS], 1)
    r = 3
    for cohort, header, n_roster, family in COHORTS:
        put(header + ["总榜"], r); r += 1
        put([None, None, -n_roster], r); r += 1
        for key, label in (ONC_PLAN if family == "onc" else EMG_PLAN):
            if key == "set_f1" and args.no_set_f1:
                continue
            if label is None:   # staging label carries the GT missing-staging rate
                gtm = cells[(cohort, "GPT-5.2")].get("gt_miss_stag")
                label = f"分期(gt missing staging rate {gtm:.4f})" if gtm is not None else "分期"
            put([None, None, None, label] + [cells[(cohort, c)].get(key) for c in canon], r); r += 1
        r += 1
    wb.save(args.out)
    print(f"wrote {args.out}: {len(MODELS)} models x {len(COHORTS)} cohorts")
    if args.provenance_out:
        json.dump({"cells": prov}, open(args.provenance_out, "w"), indent=1)


if __name__ == "__main__":
    main()
