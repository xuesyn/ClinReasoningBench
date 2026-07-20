"""
Treatment labeling for survival prediction experiments.

Two modes:
1. GT Treatment: Label each patient with their ground-truth treatment from SEER/clinical data.
2. Model Treatment: Extract model-predicted treatments from a treatment-decision experiment's
   scores/inference files and inject them into patient records.

This module consolidates the logic from:
- tools/add_gt_treatment_bclc.py
- tools/add_gt_treatment_cnlc.py
- tools/add_gt_treatment_nsclc.py
- tools/add_gt_treatment_mi.py
- tools/add_gt_treatment_stroke.py
- tools/add_treatment.py
"""

import json
import os
import glob
import logging
import tempfile
import shutil
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Disease-specific GT treatment derivation functions
# ============================================================

def _bclc_get_treatment(seer_info: dict, json_seer_data: dict) -> str:
    """BCLC treatment derivation from Excel surg codes + JSON seer_data."""
    surg_site = seer_info['surg_site']
    sys_seq = seer_info['sys_seq']

    try:
        radiation = int(json_seer_data.get("Radiation", 0))
    except (ValueError, TypeError):
        radiation = 0
    try:
        chemo = int(json_seer_data.get("Chemotherapy.recode", 0))
    except (ValueError, TypeError):
        chemo = 0

    ablation_codes = set(range(10, 18))
    resection_codes = set(list(range(20, 26)) + list(range(30, 38)) + list(range(50, 53)) + [90])
    transplant_codes = {60, 61}

    invalid_sys_seqs = {
        "No systemic therapy and/or surgical procedures",
        "Blank(s)",
        "Sequence unknown"
    }
    is_sys_valid = sys_seq not in invalid_sys_seqs

    if radiation == 1:
        return "systemic treatment"
    if chemo == 1:
        return "TACE"
    if surg_site in transplant_codes:
        return "transplant"
    if surg_site in resection_codes:
        return "resection"
    if surg_site in ablation_codes:
        return "ablation"
    if is_sys_valid:
        return "systemic treatment"
    return "best supportive care"


def _cnlc_get_treatment(seer_info: dict, json_seer_data: dict) -> str:
    """CNLC treatment derivation from Excel surg codes + JSON seer_data."""
    surg_site = seer_info['surg_site']
    sys_seq = seer_info['sys_seq']

    try:
        radiation = int(json_seer_data.get("Radiation", 0))
    except (ValueError, TypeError):
        radiation = 0
    try:
        chemo = int(json_seer_data.get("Chemotherapy.recode", 0))
    except (ValueError, TypeError):
        chemo = 0

    ablation_codes = set(range(10, 18))
    resection_codes = set(list(range(20, 26)) + list(range(30, 38)) + list(range(50, 53)) + [90])
    resection_ablation_codes = {26, 38, 59}
    transplant_codes = {60, 61}

    invalid_sys_seqs = {
        "No systemic therapy and/or surgical procedures",
        "Blank(s)",
        "Sequence unknown"
    }
    is_sys_valid = sys_seq not in invalid_sys_seqs

    if radiation == 1:
        return "放疗"
    if chemo == 1 and surg_site in ablation_codes:
        return "TACE + 消融"
    if chemo == 1 and is_sys_valid:
        return "TACE + 系统抗肿瘤治疗"
    if chemo == 1:
        return "TACE"
    if surg_site in resection_ablation_codes:
        return "手术切除 + 消融"
    if surg_site in transplant_codes:
        return "肝移植"
    if surg_site in resection_codes:
        return "手术切除"
    if surg_site in ablation_codes:
        return "消融"
    if is_sys_valid:
        return "系统抗肿瘤治疗"
    return "对症支持"


NSCLC_TREATMENT_MAPPING = {
    'Surgery_Adjuvant': '手术+辅助治疗',
    'Surgery_Lobectomy': '手术切除（肺叶切除）',
    'Surgery_Sublobar': '亚肺叶切除（楔形切除）',
    'Systemic_Therapy': '全身系统治疗',
    'Radical_ChemoRadiotherapy': '根治性化放疗',
    'Radical_Radiotherapy': '根治性放疗',
    'Other/Observation': '未进行治疗',
}


def _load_seer_excel(excel_path: str) -> Optional[Dict[str, dict]]:
    """Load SEER Excel and build Patient ID → surgery/systemic info mapping."""
    try:
        import pandas as pd
        df = pd.read_excel(excel_path, dtype={'Patient ID': str})
        df.columns = [c.strip() for c in df.columns]

        seer_db = {}
        for _, row in df.iterrows():
            pid = str(row['Patient ID']).strip()
            try:
                surg_site = int(row['RX Summ--Surg Prim Site (1998+)'])
            except (ValueError, TypeError):
                surg_site = -1
            sys_seq = str(row['RX Summ--Systemic/Sur Seq (2007+)']).strip()
            seer_db[pid] = {'surg_site': surg_site, 'sys_seq': sys_seq}

        logger.info(f"Loaded {len(seer_db)} records from Excel: {excel_path}")
        return seer_db
    except Exception as e:
        logger.error(f"Failed to load Excel {excel_path}: {e}")
        return None


# ============================================================
# Model-predicted treatment extraction (from add_treatment.py)
# ============================================================

MED_CATEGORIES = {
    "analgesics", "aspirin therapy", "P2Y12 inhibitors",
    "intravenous glycoprotein IIb/IIIa inhibitors",
    "parenteral anticoagulation", "lipid management",
    "beta-blocker therapy", "RAAS inhibitors",
    "IV_Alteplase", "IV_Tenecteplase", "IV_Alteplase_WakeUp",
    "Antiplatelet_Aspirin", "Dual_Antiplatelet", "Hemorrhagic_Management",
    "Oxygen_Therapy", "Hypoglycemia_Correction", "Hyperglycemia_Control",
    "Antipyretic_Therapy", "Fluid_Resuscitation_Pressors",
    "Antihypertensive_Pre_TPA", "Active_BP_Reduction",
}

PROC_CATEGORIES = {
    "PPCI", "urgent CABG surgery", "fibrinolytic therapy",
    "PCI", "CABG surgery", "immediate invasive",
    "early invasive", "routine invasive", "selective invasive",
    "Mechanical_Thrombectomy_StentRetriever",
    "Mechanical_Thrombectomy_Aspiration",
    "Intra_arterial_Fibrinolysis", "Emergency_CEA_CAS",
    "Airway_Intubation", "DVT_Prophylaxis_IPC", "NPO_Swallow_Precautions",
}


def _parse_json_from_text(text: str) -> dict:
    try:
        start_idx = text.index('{')
        end_idx = text.rindex('}') + 1
        return json.loads(text[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError, IndexError, AttributeError):
        return {}


def _extract_model_predictions(scores_path: str, treatment_type: str = "TOPN",
                                threshold: float = 0) -> Dict[str, str]:
    """Build uuid → predicted_treatment mapping from a scores.jsonl file."""
    pred_map = {}
    if not os.path.exists(scores_path):
        logger.error(f"Scores file not found: {scores_path}")
        return pred_map

    with open(scores_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                uuid = data.get("uuid")
                if not uuid:
                    continue

                score_results = data.get("score_results", {})

                if treatment_type == "TOPN":
                    meta_pred = score_results.get("meta_pred_treatment", [])
                    if not meta_pred:
                        pred_text = data.get("predictions", [""])[0]
                        parsed = _parse_json_from_text(pred_text)
                        pred_scores_map = parsed.get('scores', {})
                        if not isinstance(pred_scores_map, dict):
                            pred_scores_map = {}
                        valid_preds = [
                            (t, s) for t, s in pred_scores_map.items() if s > threshold
                        ]
                        meta_pred = sorted(valid_preds, key=lambda x: x[1], reverse=True)

                    if meta_pred and isinstance(meta_pred, list) and len(meta_pred) > 0:
                        first = meta_pred[0]
                        if isinstance(first, (list, tuple)) and len(first) > 0:
                            pred_map[uuid] = first[0]

                elif treatment_type == "LIST":
                    pred_text = data.get("predictions", [""])[0]
                    parsed = _parse_json_from_text(pred_text)
                    pred_list = parsed.get("suggested_treatment_list", [])
                    if pred_list and isinstance(pred_list, list):
                        pred_med = [i for i in pred_list if i in MED_CATEGORIES]
                        pred_proc = [i for i in pred_list if i in PROC_CATEGORIES]
                        pred_map[uuid] = json.dumps(
                            {'medication': pred_med, 'procedure': pred_proc},
                            ensure_ascii=False
                        )
            except Exception as e:
                logger.warning(f"Error parsing line in scores file: {e}")
                continue

    logger.info(f"Extracted {len(pred_map)} model predictions from {scores_path}")
    return pred_map


# ============================================================
# TreatmentLabeler class
# ============================================================

class TreatmentLabeler:
    """Handles injection of treatment labels into patient data for survival prediction."""

    def __init__(self, disease_key: str):
        self.disease_key = disease_key.lower()

    def label_gt_treatment(self, gt_paths: List[str],
                            output_dir: str,
                            excel_path: Optional[str] = None) -> List[str]:
        """
        Apply ground-truth treatment labels to patient data.
        Writes labeled copies to output_dir (never modifies originals).
        Returns list of output file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        seer_db = None

        if self.disease_key in ("bclc", "cnlc") and excel_path:
            seer_db = _load_seer_excel(excel_path)
            if seer_db is None:
                raise RuntimeError(f"Failed to load Excel for {self.disease_key}")

        output_paths = []
        for gt_path in gt_paths:
            out_path = os.path.join(output_dir, os.path.basename(gt_path))
            count = self._label_single_file_gt(gt_path, out_path, seer_db)
            logger.info(f"GT labeled {count} samples: {os.path.basename(gt_path)}")
            output_paths.append(out_path)

        return output_paths

    def _label_single_file_gt(self, input_path: str, output_path: str,
                               seer_db: Optional[dict]) -> int:
        """Label a single JSONL file with GT treatment."""
        count = 0
        with open(input_path, 'r', encoding='utf-8') as fin, \
             open(output_path, 'w', encoding='utf-8') as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    meta = data.get("meta_data", {}) or {}
                    seer_data = meta.get("seer_data", {}) or {}

                    treatment = self._derive_gt_treatment(data, meta, seer_data, seer_db)
                    if treatment is not None:
                        if "meta_data" not in data:
                            data["meta_data"] = {}
                        if "seer_data" not in data["meta_data"]:
                            data["meta_data"]["seer_data"] = {}
                        data["meta_data"]["seer_data"]["predicted_treatment"] = treatment
                        count += 1

                    fout.write(json.dumps(data, ensure_ascii=False) + '\n')
                except json.JSONDecodeError:
                    continue
        return count

    def _derive_gt_treatment(self, data: dict, meta: dict,
                              seer_data: dict, seer_db: Optional[dict]) -> Optional[str]:
        """Dispatch to disease-specific GT treatment logic."""
        if self.disease_key == "bclc":
            if seer_db is None:
                return "best supportive care"
            pid = str(seer_data.get("Patient.ID", "")).strip()
            seer_info = seer_db.get(pid)
            if seer_info:
                return _bclc_get_treatment(seer_info, seer_data)
            return "best supportive care"

        elif self.disease_key == "cnlc":
            if seer_db is None:
                return "对症支持"
            pid = str(seer_data.get("Patient.ID", "")).strip()
            seer_info = seer_db.get(pid)
            if seer_info:
                return _cnlc_get_treatment(seer_info, seer_data)
            return "对症支持"

        elif self.disease_key == "nsclc":
            label = seer_data.get("Treatment_Label")
            if label and label in NSCLC_TREATMENT_MAPPING:
                return NSCLC_TREATMENT_MAPPING[label]
            return label

        elif self.disease_key in ("mi", "stroke"):
            return meta.get("treatment_label")

        return None

    def label_model_treatment(self, gt_paths: List[str],
                               scores_path: str,
                               output_dir: str,
                               treatment_type: str = "TOPN",
                               threshold: float = 0) -> List[str]:
        """
        Extract model-predicted treatments from a scores file and inject into patient data.
        Writes labeled copies to output_dir (never modifies originals).
        Returns list of output file paths (only for samples with matched predictions).
        """
        os.makedirs(output_dir, exist_ok=True)
        pred_map = _extract_model_predictions(scores_path, treatment_type, threshold)

        if not pred_map:
            logger.warning("No predictions extracted, skipping model treatment labeling")
            return []

        output_paths = []
        for gt_path in gt_paths:
            out_path = os.path.join(output_dir, os.path.basename(gt_path))
            count = self._label_single_file_model(gt_path, out_path, pred_map)
            logger.info(f"Model-treatment labeled {count} samples: {os.path.basename(gt_path)}")
            output_paths.append(out_path)

        return output_paths

    def _label_single_file_model(self, input_path: str, output_path: str,
                                  pred_map: Dict[str, str]) -> int:
        """Label a single JSONL file with model-predicted treatment."""
        count = 0
        with open(input_path, 'r', encoding='utf-8') as fin, \
             open(output_path, 'w', encoding='utf-8') as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    uuid = data.get("uuid")
                    treatment = pred_map.get(uuid) if uuid else None

                    if treatment:
                        if "meta_data" not in data:
                            data["meta_data"] = {}
                        if data["meta_data"] is None:
                            data["meta_data"] = {}
                        if "seer_data" not in data["meta_data"]:
                            data["meta_data"]["seer_data"] = {}
                        data["meta_data"]["seer_data"]["predicted_treatment"] = treatment
                        fout.write(json.dumps(data, ensure_ascii=False) + '\n')
                        count += 1
                except json.JSONDecodeError:
                    continue
        return count
