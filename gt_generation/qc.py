"""
Quality-control helpers for GT generation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from gt_generation.schemas import contains_xml_like_tags


SURGERY_RELATED_TREATMENTS = {"手术切除", "手术切除 + 消融", "肝移植", "消融"}


def run_graph_check(graph_tool: Any, final_text: str, *, require_tagged_text: bool = True) -> Tuple[int, str]:
    if not final_text.strip():
        return 0, "Final reasoning is empty"
    if graph_tool is None:
        return 0, "GraphTool unavailable"

    missing_tags_error = ""
    if require_tagged_text and not contains_xml_like_tags(final_text):
        missing_tags_error = "Final reasoning does not contain XML-like tags"

    try:
        has_conflict, _violations = graph_tool.check_gt(text=final_text)
        if missing_tags_error:
            return 0, missing_tags_error
        return (0 if has_conflict else 1), ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def check_conflict_with_seer(sample: Dict[str, Any], recommended_list: List[str], disease_type: str) -> Tuple[bool, str]:
    if disease_type != "cancer":
        return False, ""

    seer_meta = (sample.get("meta_data") or {}).get("seer_data", {})
    surgery = _safe_int(seer_meta.get("Surgery", 0))
    radiation = _safe_int(seer_meta.get("Radiation", 0))
    chemotherapy = str(seer_meta.get("Chemotherapy.recode", "No/Unknown"))

    problems = []

    if surgery == 1 and not set(recommended_list).intersection(SURGERY_RELATED_TREATMENTS):
        problems.append("真实接受了手术切除但没有推荐。")

    if radiation == 1 and "放疗" not in recommended_list:
        problems.append("真实接受了放疗但没有推荐。")

    if chemotherapy == "Yes":
        chemo_related = {
            "系统抗肿瘤治疗",
            "TACE",
            "TACE + 消融",
            "TACE + 系统抗肿瘤治疗",
        }
        if not set(recommended_list).intersection(chemo_related):
            problems.append("真实接受了化疗但没有推荐。")

    if problems:
        return True, "；".join(problems)
    return False, ""


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
