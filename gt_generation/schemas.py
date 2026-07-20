"""
Schema validation helpers for GT generation outputs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


XML_LIKE_TAG_RE = re.compile(r"</?[A-Za-z_][A-Za-z0-9_\-]*(?:[\s=][^>]*)?>")

# <knowledge_id='...'> tags are guideline-citation markers, not
# patient-fact tags. They are required in BOTH one-step and two-step
# modes, so the "two-step must not contain XML-like tags" check must
# ignore them.
KNOWLEDGE_ID_TAG_RE = re.compile(r"<knowledge_id\s*=\s*'[^']*'>", re.IGNORECASE)


class OutputValidationError(ValueError):
    """Raised when an LLM output does not satisfy the expected schema."""


def contains_xml_like_tags(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return bool(XML_LIKE_TAG_RE.search(text))


def contains_non_citation_xml_tags(text: str) -> bool:
    """True iff `text` contains any XML-like tag other than <knowledge_id='...'>."""
    if not isinstance(text, str):
        return False
    stripped = KNOWLEDGE_ID_TAG_RE.sub("", text)
    return bool(XML_LIKE_TAG_RE.search(stripped))


def validate_generation_output(
    parsed: Dict[str, Any],
    *,
    disease_type: str,
    treatments: List[str],
    mode: str,
    strict_schema: bool = True,
) -> None:
    if disease_type == "cancer":
        validate_cancer_generation_output(
            parsed,
            treatments=treatments,
            mode=mode,
            strict_schema=strict_schema,
        )
        return

    validate_emergency_generation_output(
        parsed,
        treatments=treatments,
        mode=mode,
        strict_schema=strict_schema,
    )


def validate_cancer_generation_output(
    parsed: Dict[str, Any],
    *,
    treatments: List[str],
    mode: str,
    strict_schema: bool = True,
) -> None:
    _ensure_required_fields(
        parsed,
        [
            "thinking",
            "check_for_thinking",
            "scores",
            "recommended_list",
            "staging",
            "indication",
            "contraindication",
        ],
    )
    _validate_thinking_text(parsed["thinking"], mode=mode, strict_schema=strict_schema)
    _validate_scores(parsed["scores"], treatments=treatments, strict_schema=strict_schema)
    _validate_recommended_list(parsed["recommended_list"], treatments=treatments)
    _validate_boolean_mapping(
        parsed["indication"],
        treatments=treatments,
        field_name="indication",
        strict_schema=strict_schema,
    )
    _validate_boolean_mapping(
        parsed["contraindication"],
        treatments=treatments,
        field_name="contraindication",
        strict_schema=strict_schema,
    )
    _ensure_non_empty_string(parsed["staging"], "staging")
    _ensure_non_empty_string(parsed["check_for_thinking"], "check_for_thinking")


def validate_emergency_generation_output(
    parsed: Dict[str, Any],
    *,
    treatments: List[str],
    mode: str,
    strict_schema: bool = True,
) -> None:
    _ensure_required_fields(
        parsed,
        [
            "thinking",
            "check_for_thinking",
            "suggested_treatment_list",
            "confidence_score",
            "indication",
            "contraindication",
        ],
    )
    _validate_thinking_text(parsed["thinking"], mode=mode, strict_schema=strict_schema)
    _validate_recommended_list(
        parsed["suggested_treatment_list"],
        treatments=treatments,
        field_name="suggested_treatment_list",
    )
    _validate_confidence_score(parsed["confidence_score"])
    _validate_boolean_mapping(
        parsed["indication"],
        treatments=treatments,
        field_name="indication",
        strict_schema=strict_schema,
    )
    _validate_boolean_mapping(
        parsed["contraindication"],
        treatments=treatments,
        field_name="contraindication",
        strict_schema=strict_schema,
    )
    _ensure_non_empty_string(parsed["check_for_thinking"], "check_for_thinking")


def validate_tagging_output(parsed: Dict[str, Any]) -> None:
    _ensure_required_fields(parsed, ["thinking", "result"])
    _ensure_non_empty_string(parsed["thinking"], "thinking")
    _ensure_non_empty_string(parsed["result"], "result")
    if not contains_xml_like_tags(parsed["result"]):
        raise OutputValidationError("tagging result does not contain XML-like tags")


def _ensure_required_fields(parsed: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in parsed]
    if missing:
        raise OutputValidationError(f"json missing fields: {missing}")


def _ensure_non_empty_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise OutputValidationError(f"{field_name} must be a non-empty string")


def _validate_thinking_text(text: Any, *, mode: str, strict_schema: bool) -> None:
    _ensure_non_empty_string(text, "thinking")
    if not strict_schema:
        return

    if mode == "one-step" and not contains_xml_like_tags(text):
        raise OutputValidationError("one-step thinking must already contain tags")
    # In two-step mode, <knowledge_id='...'> citation tags ARE expected in
    # the first pass -- only patient-fact / staging / treatment / <cite>
    # tags are deferred to the tagger, so ignore knowledge_id tags here.
    if mode == "two-step" and contains_non_citation_xml_tags(text):
        raise OutputValidationError("two-step generation thinking must not contain XML-like tags other than <knowledge_id='...'>")


def _validate_scores(scores: Any, *, treatments: List[str], strict_schema: bool) -> None:
    if not isinstance(scores, dict):
        raise OutputValidationError("scores not dict")

    missing_treatments = [t for t in treatments if t not in scores]
    if missing_treatments:
        raise OutputValidationError(f"treatment not match: missing {missing_treatments}")

    unknown_treatments = [t for t in scores if t not in treatments]
    if unknown_treatments and strict_schema:
        raise OutputValidationError(f"unexpected treatments in scores: {unknown_treatments}")

    for treatment in treatments:
        entry = scores.get(treatment)
        if not isinstance(entry, dict):
            raise OutputValidationError(f"score entry {treatment} must be a dict")
        if "Comprehensive_Score" not in entry:
            raise OutputValidationError(f"score entry {treatment} missing Comprehensive_Score")
        _validate_numeric_score(entry["Comprehensive_Score"], f"scores[{treatment}].Comprehensive_Score")


def _validate_boolean_mapping(
    mapping: Any,
    *,
    treatments: List[str],
    field_name: str,
    strict_schema: bool,
) -> None:
    if not isinstance(mapping, dict):
        raise OutputValidationError(f"{field_name} must be a dict")

    missing_treatments = [t for t in treatments if t not in mapping]
    if missing_treatments and strict_schema:
        raise OutputValidationError(f"{field_name} missing treatments: {missing_treatments}")

    unknown_treatments = [t for t in mapping if t not in treatments]
    if unknown_treatments and strict_schema:
        raise OutputValidationError(f"{field_name} has unexpected treatments: {unknown_treatments}")

    for treatment, value in mapping.items():
        normalized = str(value).lower()
        if normalized not in ("true", "false"):
            raise OutputValidationError(f"{field_name}[{treatment}] must be true/false")


def _validate_recommended_list(
    value: Any,
    *,
    treatments: List[str],
    field_name: str = "recommended_list",
) -> None:
    if not isinstance(value, list):
        raise OutputValidationError(f"{field_name} must be a list")

    invalid = [item for item in value if item not in treatments]
    if invalid:
        raise OutputValidationError(f"Invalid treatment in {field_name}: {invalid}")


def _validate_confidence_score(value: Any) -> None:
    _validate_numeric_score(value, "confidence_score")


def _validate_numeric_score(value: Any, field_name: str) -> None:
    if not isinstance(value, (int, float)):
        raise OutputValidationError(f"{field_name} must be numeric")
    if value < 0 or value > 1:
        raise OutputValidationError(f"{field_name} must be within [0, 1]")
