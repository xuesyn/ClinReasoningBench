from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class DiseaseConfig:
    disease_key: str
    display_name: str

    knowledge_db_path: str
    graph_def_path: str
    embedding_model_path: str

    treatment_prompt_template: str
    survival_prompt_template: str

    reference_guideline_name: str

    cancer_type: str
    allowed_stagings: List[str] = field(default_factory=list)

    treatment_metrics: Dict[str, Any] = field(default_factory=dict)
    survival_metrics: Dict[str, Any] = field(default_factory=dict)

    gt_treatment_key: str = "treatment_label"
    gt_treatment_requires_excel: bool = False

    model_treatment_type: str = "TOPN"


DISEASE_REGISTRY: Dict[str, DiseaseConfig] = {
    "bclc": DiseaseConfig(
        disease_key="bclc",
        display_name="BCLC (Barcelona Clinic Liver Cancer)",
        knowledge_db_path="data/BCLC/bclc_guidance.jsonl",
        graph_def_path="data/BCLC/bclc_graph_beta_v2.json",
        embedding_model_path="ckpt/bge-large-zh-v1.5",
        treatment_prompt_template="prompts/thinking_all_task_cite_version_bclc.txt",
        survival_prompt_template="prompts/thinking_survival_time.txt",
        reference_guideline_name="BCLC strategy for prognosis prediction and treatment recommendation: The 2022 update",
        cancer_type="bclc",
        allowed_stagings=["0", "a", "b", "c", "d"],
        gt_treatment_requires_excel=True,
        model_treatment_type="TOPN",
        treatment_metrics={
            "GraphBasedMetric": {
                "use_hard_check_score": False,
                "knowledge_calc_method": "semantic",
                "knowledge_db_path": "data/BCLC/bclc_guidance.jsonl",
                "knowledge_key": "original_text",
                "model_local_path": "ckpt/bge-large-zh-v1.5",
                "similarity_threshold": 0.8,
            },
            "treatment_score": {"threshold": 0.5},
            "staging_score": {
                "allowed_stagings": ["0", "a", "b", "c", "d"],
            },
            "Indication_and_contraindication_score": {},
            "treatment_calibration": {
                "threshold": 0.5, "k": None, "top_m": 3, "tau": 1,
                "use_position_weighting": True,
            },
        },
        survival_metrics={
            "survival_calibration": {
                "ipcw_min_g": 0.05, "skip_zero_surv": True,
                "default_pred_surv": -1.0, "default_conf": 0.0,
                "cancer_type": "bclc",
            },
        },
    ),
    "cnlc": DiseaseConfig(
        disease_key="cnlc",
        display_name="CNLC (China National Liver Cancer)",
        knowledge_db_path="data/CNLC/cnlc_guidance.jsonl",
        graph_def_path="data/CNLC/cnlc_graph_beta_v1.json",
        embedding_model_path="ckpt/bge-large-zh-v1.5",
        treatment_prompt_template="prompts/thinking_all_task_cite_version.txt",
        survival_prompt_template="prompts/thinking_survival_time.txt",
        reference_guideline_name="原发性肝癌诊疗指南（2024 年版）",
        cancer_type="cnlc",
        allowed_stagings=["Ia", "Ib", "IIa", "IIb", "IIIa", "IIIb", "IV"],
        gt_treatment_requires_excel=True,
        model_treatment_type="TOPN",
        treatment_metrics={
            "GraphBasedMetric": {
                "use_hard_check_score": False,
                "knowledge_calc_method": "semantic",
                "knowledge_db_path": "data/CNLC/cnlc_guidance.jsonl",
                "knowledge_key": "original_text",
                "model_local_path": "ckpt/bge-large-zh-v1.5",
                "similarity_threshold": 0.8,
            },
            "treatment_score": {"threshold": 0.5},
            "staging_score": {
                "allowed_stagings": ["Ia", "Ib", "IIa", "IIb", "IIIa", "IIIb", "IV"],
            },
            "Indication_and_contraindication_score": {},
            "treatment_calibration": {
                "threshold": 0.5, "k": None, "top_m": 3, "tau": 1,
                "use_position_weighting": True,
            },
        },
        survival_metrics={
            "survival_calibration": {
                "ipcw_min_g": 0.05, "skip_zero_surv": True,
                "default_pred_surv": -1.0, "default_conf": 0.0,
                "cancer_type": "cnlc",
            },
        },
    ),
    "nsclc": DiseaseConfig(
        disease_key="nsclc",
        display_name="NSCLC (Non-Small Cell Lung Cancer)",
        knowledge_db_path="data/NSCLC/lungcancer_guidance_v2.jsonl",
        graph_def_path="data/NSCLC/lungcancer_graph_beta_tag.json",
        embedding_model_path="ckpt/bge-large-zh-v1.5",
        treatment_prompt_template="prompts/thinking_all_task_cite_version_nsclc.txt",
        survival_prompt_template="prompts/thinking_survival_time_nsclc.txt",
        reference_guideline_name="中华医学会肺癌临床诊疗指南（2024版）",
        cancer_type="nsclc",
        allowed_stagings=["Ia", "Ib", "II", "IIIa", "IIIb", "IIIc", "IV"],
        model_treatment_type="TOPN",
        treatment_metrics={
            "GraphBasedMetric": {
                "use_hard_check_score": False,
                "knowledge_calc_method": "semantic",
                "knowledge_db_path": "data/NSCLC/lungcancer_guidance_v2.jsonl",
                "knowledge_key": "original_text",
                "model_local_path": "ckpt/bge-large-zh-v1.5",
                "similarity_threshold": 0.8,
            },
            "treatment_score": {"threshold": 0.5},
            "staging_score": {
                "cancer_type": "nsclc",
                "allowed_stagings": ["Ia", "Ib", "II", "IIIa", "IIIb", "IIIc", "IV"],
            },
            "Indication_and_contraindication_score": {},
            "treatment_calibration": {
                "threshold": 0.5, "k": None, "top_m": 3, "tau": 1,
                "use_position_weighting": True,
            },
        },
        survival_metrics={
            "survival_calibration": {
                "ipcw_min_g": 0.05, "skip_zero_surv": True,
                "default_pred_surv": -1.0, "default_conf": 0.0,
                "cancer_type": "nsclc",
            },
        },
    ),
    "mi": DiseaseConfig(
        disease_key="mi",
        display_name="MI (Myocardial Infarction)",
        knowledge_db_path="data/MI/AMI_guidance.jsonl",
        graph_def_path="data/MI/AMI_graph_v2.json",
        embedding_model_path="ckpt/bge-large-zh-v1.5",
        treatment_prompt_template="prompts/thinking_all_task_cite_version_mi.txt",
        survival_prompt_template="prompts/thinking_survival_time_mi.txt",
        reference_guideline_name=(
            "2025 ACC/AHA/ACEP/NAEMSP/SCAI Guideline for the Management of "
            "Patients With Acute Coronary Syndromes"
        ),
        cancer_type="non-cancer",
        allowed_stagings=[],
        gt_treatment_key="treatment_label",
        model_treatment_type="LIST",
        treatment_metrics={
            "GraphBasedMetric": {
                "use_hard_check_score": False,
                "knowledge_calc_method": "semantic",
                "knowledge_db_path": "data/MI/AMI_guidance.jsonl",
                "knowledge_key": "original_text",
                "model_local_path": "ckpt/bge-large-zh-v1.5",
                "similarity_threshold": 0.8,
            },
            "treatment_set_score": {},
            "Indication_and_contraindication_score": {},
            "set_calibration": {},
        },
        survival_metrics={
            "survival_calibration": {
                "ipcw_min_g": 0.05, "skip_zero_surv": True,
                "default_pred_surv": -1.0, "default_conf": 0.0,
                "cancer_type": "non-cancer",
            },
        },
    ),
    "stroke": DiseaseConfig(
        disease_key="stroke",
        display_name="Stroke (Acute Ischemic Stroke)",
        knowledge_db_path="data/STROKE/stroke_guidance_output_v2.jsonl",
        graph_def_path="data/STROKE/stroke_graph.json",
        embedding_model_path="ckpt/bge-large-zh-v1.5",
        treatment_prompt_template="prompts/thinking_all_task_cite_version_stroke.txt",
        survival_prompt_template="prompts/thinking_survival_time_stroke.txt",
        reference_guideline_name=(
            "Guidelines for the Early Management of Patients With Acute "
            "Ischemic Stroke: 2019 Update"
        ),
        cancer_type="non-cancer",
        allowed_stagings=[],
        gt_treatment_key="treatment_label",
        model_treatment_type="LIST",
        treatment_metrics={
            "GraphBasedMetric": {
                "use_hard_check_score": False,
                "knowledge_calc_method": "semantic",
                "knowledge_db_path": "data/STROKE/stroke_guidance_output_v2.jsonl",
                "knowledge_key": "original_text",
                "model_local_path": "ckpt/bge-large-zh-v1.5",
                "similarity_threshold": 0.8,
            },
            "treatment_set_score": {},
            "Indication_and_contraindication_score": {},
            "set_calibration": {},
        },
        survival_metrics={
            "survival_calibration": {
                "ipcw_min_g": 0.05, "skip_zero_surv": True,
                "default_pred_surv": -1.0, "default_conf": 0.0,
                "cancer_type": "non-cancer",
            },
        },
    ),
}


def get_disease_config(disease_key: str) -> DiseaseConfig:
    key = disease_key.lower()
    if key not in DISEASE_REGISTRY:
        available = ", ".join(DISEASE_REGISTRY.keys())
        raise ValueError(f"Unknown disease '{disease_key}'. Available: {available}")
    return DISEASE_REGISTRY[key]
