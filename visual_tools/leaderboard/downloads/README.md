# ClinReasoningBench — paper result tables

Aggregate results behind the figures and tables of the paper. No patient-level records, model answers,
case identifiers or clinician annotations are included (see *Data Availability* in the repository README).
`manifest.json` lists every file with its SHA-256 and row count.

Conventions: proportions are on a 0–1 scale (multiply by 100 for %); survival errors are in months; empty
cells = not applicable. Cohorts: BCLC (n=3,689), CNLC (4,103), NSCLC (4,219), ACS (3,611), AIS (3,657) —
five guideline cohorts covering four diseases (HCC under two guidelines, NSCLC, ACS, AIS). 16 benchmark models.
`therapy`: *autonomous* = survival predicted under the model's own recommended treatment; *treatment_conditioned*
= survival predicted given the treatment actually administered.

| File | Content | Paper |
|---|---|---|
| `leaderboard_main_treatment.xlsx` | Workbook rendered by the online leaderboard (all per-cohort treatment-task metrics, ITT) | Leaderboard |
| `main_treatment_metrics.csv` | Reasoning score, node accuracy (`corresponding`), staging, indication/contraindication, treatment score (NDCG for oncology; set-F1 for ACS/AIS), calibration ECEs — ITT (primary) and parse-valid subset | Fig. 1d, Tables S11–S13 |
| `main_treatment_bootstrap_ci.csv` | Case-level bootstrap 95% CIs (B=1000, seed 628) | Table S19 |
| `main_reasoning_cross_cohort_mean.csv` | 5-cohort mean reasoning score with CI | Main text, Table S20 |
| `survival_cindex.csv` | Survival C-index (roster cases with a parseable prediction; zero follow-up excluded), bootstrap 95% CI | Fig. 1f, Table S17 |
| `survival_12m_mortality_acute.csv` | ACS/AIS 12-month mortality AUROC/AUPRC (primary acute survival endpoint) | Fig. 1f, Table S18 |
| `survival_risk_coverage_tieavg.csv` | Confidence risk–coverage scalars: AURC (1−C-index, IPCW-MAE), selective gain at 50%/20% coverage `[R(1)−R(c)]/R(1)`, Spearman ρ; each the mean over 30 random orders of equal-confidence cases | Fig. 2b-2, Fig. S3 |
| `stage_stratified_survival_error.csv` | Stage-stratified IPCW-MAE / censored MAE (parse-valid cases with known stage) | Fig. 2b-3, Fig. S4 |
| `stage_stratified_signed_residuals.csv` | Stage-stratified mean signed residual (predicted − true, months); the figure shows stages with n ≥ 20 for every model | Fig. S5 |
| `radar_axes.csv` | 8 radar axes (cross-cohort means; ECE shown as 1−ECE) and their unweighted mean | Fig. 1e |
| `sft_ablation_cnlc.csv` | CNLC SFT ablation: 6 models × {zero-shot, + guideline injection, SFT, knowledge-augmented SFT}, n=1,050 each, bootstrap 95% CIs | Fig. 2a, Table 1 |
| `single_centre_hcc_443.csv` | Separate single-centre HCC cohort (n=443): 10 LLMs + OpenEvidence × {treatment, treatment-conditioned survival, autonomous survival} | Tables S8–S10, Fig. S9 |
| `clinician_comparison_matched_subsets.csv` | Clinicians vs models on the same matched subsets (REAL20 single-centre HCC; SEER CNLC 40) | Fig. S11, Table S21 |
| `clinician3_tag_supplement_sensitivity.csv` | Sensitivity of clinician 3's REAL20 score to supplementing omitted objective tags (v1 is the reported value) | Table S22 |

Notes
- Reasoning score (per case) = mean of node accuracy along the guideline dependency graph and citation fidelity
  (precision × recall of BGE-matched guideline citations, cosine > 0.8), averaged over cases.
- Matched-subset clinician scores and single-centre results are **not** comparable to full-cohort leaderboard values.
- OpenEvidence was evaluated only on the single-centre cohort and is not part of the 16-model benchmark roster.
