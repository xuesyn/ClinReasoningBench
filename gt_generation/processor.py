"""
GT Processor: unified generation, post-processing, and QC pipeline.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from gt_generation.qc import check_conflict_with_seer, run_graph_check
from gt_generation.schemas import OutputValidationError, validate_generation_output, validate_tagging_output

logger = logging.getLogger(__name__)

REQUIRED_INPUT_FIELDS = ["uuid", "emr"]

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def validate_input_sample(sample: dict, disease_type: str, sample_index: int = 0):
    warnings = []
    for field in REQUIRED_INPUT_FIELDS:
        if field not in sample or not sample[field]:
            warnings.append(f"Missing required field: '{field}'")

    meta = sample.get("meta_data", {})
    seer = meta.get("seer_data", {})

    if not meta:
        warnings.append("Missing 'meta_data' dict")
    if not seer:
        warnings.append("Missing 'meta_data.seer_data' dict")

    has_surv = any(k in seer for k in ["Survival.months", "Survival months", "Survival.days"])
    if not has_surv:
        warnings.append(
            "No survival fields found in seer_data (Survival.months / Survival.days). "
            "Survival prediction evaluation will not work without these."
        )

    has_event = any(k in seer for k in ["COD.to.site.recode", "COD to site recode", "Survival.days"])
    if not has_event:
        warnings.append(
            "No event/censoring indicator found in seer_data (COD.to.site.recode / Survival.days). "
            "Survival metrics (C-index, IPCW-MAE) require this."
        )

    if disease_type == "emergency" and "hadm_id" not in seer:
        warnings.append("Missing 'seer_data.hadm_id'. SOFA severity analysis will not work without this.")

    if warnings and sample_index == 0:
        logger.warning(f"Input data warnings (showing for first sample, uuid={sample.get('uuid', '?')}):")
        for warning in warnings:
            logger.warning(f"  - {warning}")
        logger.warning(
            "See gt_generation/README.md for required field documentation. "
            "These fields are needed by the evaluation pipeline (survival prediction, staging, SOFA analysis)."
        )
    return warnings


class GTProcessor:
    def __init__(
        self,
        graph_path: str,
        guidance_path: str,
        disease_type: str = "cancer",
        language: str = "en",
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        tag_model: Optional[str] = None,
        guideline_name: str = "",
        extra_treatments: Optional[List[str]] = None,
        example_path: Optional[str] = None,
        disease_domain: str = "",
        max_retries: int = 3,
        max_parse_retries: int = 5,
        med_categories: Optional[set] = None,
        proc_categories: Optional[set] = None,
        mode: str = "one-step",
        two_step: Optional[bool] = None,
        strict_schema: bool = True,
        keep_debug_fields: bool = True,
        enable_seer_qc: bool = True,
    ):
        if two_step is not None:
            mode = "two-step" if two_step else "one-step"
        if mode not in {"one-step", "two-step"}:
            raise ValueError("mode must be 'one-step' or 'two-step'")

        self.disease_type = disease_type
        self.language = language
        self.model = model
        self.tag_model = tag_model or model
        self.guideline_name = guideline_name or "Clinical Guideline"
        self.max_retries = max_retries
        self.max_parse_retries = max_parse_retries
        self.disease_domain = disease_domain or ("oncology" if disease_type == "cancer" else "emergency medicine")
        self.mode = mode
        self.strict_schema = strict_schema
        self.keep_debug_fields = keep_debug_fields
        self.enable_seer_qc = enable_seer_qc

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=300)

        with open(graph_path, "r", encoding="utf-8") as f:
            self.graph = json.load(f)

        self.treatments = self._extract_treatments()
        if extra_treatments:
            for treatment in extra_treatments:
                if treatment in self.treatments:
                    raise ValueError(f"Extra treatment '{treatment}' already exists in graph definition")
                self.treatments.append(treatment)

        self.node_guide = self._build_node_guide()
        self.rules = self._build_rules_text()
        self.reference = self._load_reference(guidance_path)
        self.prompt_template = self._load_prompt_template()
        self.tag_prompt_template = self._load_tag_prompt_template()

        self.example_text = ""
        if example_path and os.path.exists(example_path):
            with open(example_path, "r", encoding="utf-8") as f:
                self.example_text = f.read()

        if disease_type == "emergency":
            self.med_categories = med_categories or set()
            self.proc_categories = proc_categories or set()
            if not self.med_categories and not self.proc_categories:
                self._auto_classify_treatments()
        else:
            self.med_categories = set()
            self.proc_categories = set()

        try:
            import sys

            project_root = os.path.dirname(os.path.dirname(__file__))
            sys.path.insert(0, project_root)
            from med_eval_pipeline.graph_tool import GraphTool

            self.graph_tool = GraphTool(graph_path)
        except ImportError:
            self.graph_tool = None
            logger.warning("GraphTool not available, QC will mark samples as unchecked")

    def _load_prompt_template(self) -> str:
        prompt_name = "gt_prompt_cancer.txt" if self.disease_type == "cancer" else "gt_prompt_emergency.txt"
        with open(os.path.join(PROMPT_DIR, prompt_name), "r", encoding="utf-8") as f:
            return f.read()

    def _load_tag_prompt_template(self) -> str:
        with open(os.path.join(PROMPT_DIR, "gt_prompt_tagging.txt"), "r", encoding="utf-8") as f:
            return f.read()

    def _extract_treatments(self) -> List[str]:
        for node in self.graph.get("nodes", []):
            if node.get("key") == "treatment":
                return list(node.get("values", []))
        return []

    def _auto_classify_treatments(self):
        procedure_keywords = [
            "procedure",
            "surgery",
            "operation",
            "intervention",
            "stent",
            "thrombectomy",
            "pci",
            "tace",
            "ablation",
            "radiation",
            "放疗",
            "手术",
            "介入",
            "取栓",
            "支架",
            "消融",
        ]
        for treatment in self.treatments:
            lower_name = treatment.lower()
            if any(keyword in lower_name for keyword in procedure_keywords):
                self.proc_categories.add(treatment)
            else:
                self.med_categories.add(treatment)

    def _build_node_guide(self) -> str:
        lines = []
        for node in self.graph.get("nodes", []):
            key = node.get("key", "")
            parts = [f"- key: <{key}>"]
            if node.get("desc"):
                parts.append(f"description: {node['desc']}")
            parts.append(f"type: {node.get('type', '')}")
            unit = node.get("unit")
            if unit and unit != "NULL":
                parts.append(f"unit: {unit}")
            values = node.get("values") or []
            if values:
                parts.append(f"allowed values: {', '.join(map(str, values))}")
            lines.append("; ".join(parts))
        return "\n".join(lines)

    def _build_rules_text(self) -> str:
        return "\n".join(
            f"{i}. {rule.get('describe', '')}"
            for i, rule in enumerate(self.graph.get("rules", []), start=1)
        )

    def _load_reference(self, path: str) -> str:
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                parts = [f"{item.get('id', '')}:"]
                for key in [
                    "condition",
                    "recommendation",
                    "hint",
                    "evidence_level",
                    "recommended_level",
                    "category",
                    "source",
                    "original_text",
                ]:
                    if item.get(key):
                        parts.append(f"{key}={item[key]}")
                entries.append(" ".join(parts))
        return "\n".join(entries)

    def _build_generation_prompt(self, sample: Dict[str, Any]) -> str:
        if self.language == "zh":
            lang_instruction = "你的答案应使用中文。"
        else:
            lang_instruction = "Your answer should be in English."

        tagging_guidance = self._build_tagging_guidance()
        emr_value = sample.get("emr", "")
        if isinstance(emr_value, str):
            input_data = emr_value
        else:
            input_data = json.dumps(emr_value, ensure_ascii=False)

        prompt = self.prompt_template
        prompt = prompt.replace("{disease_domain}", self.disease_domain)
        prompt = prompt.replace("{guideline_name}", self.guideline_name)
        prompt = prompt.replace("{node_guide}", self.node_guide)
        prompt = prompt.replace("{rules}", self.rules)
        prompt = prompt.replace("{reference}", self.reference)
        prompt = prompt.replace("{language_instruction}", lang_instruction)
        prompt = prompt.replace("{input_data}", input_data)
        prompt = prompt.replace("{tagging_guidance}", tagging_guidance)

        if self.example_text:
            example_section = f"# Example Output\nBelow is a reference example (for format only):\n{self.example_text}"
        else:
            example_section = ""
        prompt = prompt.replace("{example_section}", example_section)

        if self.disease_type == "cancer":
            scores_template = []
            indication_template = []
            contraindication_template = []
            treatment_list = []
            for idx, treatment in enumerate(self.treatments, start=1):
                treatment_list.append(f"  {idx}. {treatment}")
                scores_template.append(
                    f'        "{treatment}": {{"Comprehensive_Score": <float>}}'
                )
                indication_template.append(f'        "{treatment}": "true/false"')
                contraindication_template.append(f'        "{treatment}": "true/false"')

            prompt = prompt.replace("{treatment_list_formatted}", "\n".join(treatment_list))
            prompt = prompt.replace("{scores_template}", ",\n".join(scores_template))
            prompt = prompt.replace("{ind_template}", ",\n".join(indication_template))
            prompt = prompt.replace("{contra_template}", ",\n".join(contraindication_template))
            return prompt

        med_list = "\n".join(f"  - {t}" for t in self.treatments if t in self.med_categories) or "  (none defined)"
        proc_list = "\n".join(f"  - {t}" for t in self.treatments if t in self.proc_categories) or "  (none defined)"
        if not self.med_categories and not self.proc_categories:
            med_list = "\n".join(f"  - {t}" for t in self.treatments)
            proc_list = "  (see medication list above)"

        indication_template = [f'        "{treatment}": "true/false"' for treatment in self.treatments]
        contraindication_template = [f'        "{treatment}": "true/false"' for treatment in self.treatments]
        prompt = prompt.replace("{medication_list}", med_list)
        prompt = prompt.replace("{procedure_list}", proc_list)
        prompt = prompt.replace("{ind_template}", ",\n".join(indication_template))
        prompt = prompt.replace("{contra_template}", ",\n".join(contraindication_template))
        return prompt

    def _build_tagging_guidance(self) -> str:
        # Citation rule applies to BOTH modes -- <knowledge_id> tags mark
        # which guideline entries were used as evidence, NOT patient facts,
        # so they must be present even when patient-fact tagging is
        # deferred to a second pass.
        cite_rule = (
            "- **Guideline citation (REQUIRED in BOTH modes)**: whenever the reasoning "
            "uses a knowledge entry from the provided reference guidelines, mark it inline "
            "with `<knowledge_id='XXXX'>` immediately after the cited claim, where XXXX is "
            "the knowledge entry id from the reference list (e.g. <knowledge_id='HCC-0023'>). "
            "Tag EVERY occurrence -- tagging the same id multiple times across different "
            "claims is expected. Use only ids that appear in the supplied reference list; "
            "do NOT invent ids."
        )
        if self.mode == "two-step":
            return (
                "- Write the reasoning as plain natural-language text.\n"
                "- Do NOT add patient-fact tags, staging tags, treatment tags, or <cite> tags -- "
                "those are inserted by the second-stage annotator.\n"
                f"{cite_rule}"
            )
        return (
            "- Tag confirmed patient facts using XML-like tags: <key>value</key>.\n"
            "- Tag definitive staging conclusions with <staging>value</staging>.\n"
            "- Tag recommended treatments with <treatment>name</treatment>.\n"
            "- Tag explicitly rejected treatments with <treatment_not_recommended>name</treatment_not_recommended>.\n"
            "- Tag inline guideline-text quotations with <cite>...</cite>.\n"
            f"{cite_rule}\n"
            "- Only tag confirmed patient facts (not guideline thresholds or hypothetical values)."
        )

    def _build_tag_prompt(self, thinking_text: str, recommended_list: List[str]) -> str:
        prompt = self.tag_prompt_template.replace("{node_guide}", self.node_guide)
        prompt = prompt.replace("{thinking_text}", thinking_text)
        prompt = prompt.replace("{recommended_list}", json.dumps(recommended_list, ensure_ascii=False))
        return prompt

    def _call_llm(self, prompt: str, model: Optional[str] = None) -> str:
        llm_model = model or self.model
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=16384,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"LLM call failed ({llm_model}) attempt {attempt + 1}/{self.max_retries}: {exc}")
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)
        return ""

    def _parse_json(self, text: str) -> Dict[str, Any]:
        if not text:
            return {}

        candidates = []
        cleaned = text.strip()
        candidates.append(cleaned)

        try:
            start = cleaned.index("{")
            end = cleaned.rindex("}") + 1
            candidates.append(cleaned[start:end])
        except ValueError:
            pass

        for candidate in candidates:
            normalized = re.sub(r"^```json\s*", "", candidate)
            normalized = re.sub(r"^```\s*", "", normalized)
            normalized = re.sub(r"\s*```$", "", normalized)

            for parser in (json.loads, ast.literal_eval):
                try:
                    return parser(normalized)
                except Exception:
                    continue

            repaired = normalized
            repaired = repaired.replace("```JSON", "").replace("```json", "").replace("```", "")
            repaired = re.sub(r"(\d),(\d)", r"\1\2", repaired)
            repaired = repaired.replace("，", ",").replace("：", ":").replace("“", '"').replace("”", '"')
            repaired = repaired.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            if repaired.startswith("{") or repaired.startswith("["):
                repaired = re.sub(r"'", '"', repaired)

            for parser in (json.loads, ast.literal_eval):
                try:
                    return parser(repaired)
                except Exception:
                    continue

        return {}

    def _run_generation_step(self, sample: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], bool, str, int]:
        prompt = self._build_generation_prompt(sample)
        last_err = ""
        response_text = ""
        for attempt in range(1, self.max_parse_retries + 1):
            response_text = self._call_llm(prompt, model=self.model)
            if not response_text:
                last_err = "Empty LLM response after all retries"
            else:
                try:
                    parsed = self._parse_json(response_text)
                    if not parsed:
                        raise OutputValidationError("Failed to parse JSON from response")
                    validate_generation_output(
                        parsed,
                        disease_type=self.disease_type,
                        treatments=self.treatments,
                        mode=self.mode,
                        strict_schema=self.strict_schema,
                    )
                    return prompt, response_text, parsed, True, "", attempt
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)
            logger.warning(
                f"Generation parse attempt {attempt}/{self.max_parse_retries} failed for uuid={sample.get('uuid', '?')}: {last_err}"
            )
            if attempt < self.max_parse_retries:
                time.sleep(0.5)
        return prompt, response_text, {}, False, last_err, self.max_parse_retries

    def _run_tagging_step(
        self,
        *,
        thinking_text: str,
        recommended_list: List[str],
        sample: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], bool, str, str, int]:
        full_prompt = self._build_tag_prompt(thinking_text, recommended_list)
        last_err = ""
        response_text = ""
        for attempt in range(1, self.max_parse_retries + 1):
            response_text = self._call_llm(full_prompt, model=self.tag_model)
            if not response_text:
                last_err = "Empty tagging response after all retries"
            else:
                try:
                    parsed = self._parse_json(response_text)
                    if not parsed:
                        raise OutputValidationError("Failed to parse JSON from tagging response")
                    validate_tagging_output(parsed)
                    return response_text, parsed, True, full_prompt, "", attempt
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)
            logger.warning(
                f"Tagging parse attempt {attempt}/{self.max_parse_retries} failed for uuid={sample.get('uuid', '?')}: {last_err}"
            )
            if attempt < self.max_parse_retries:
                time.sleep(0.5)
        return response_text, {}, False, full_prompt, last_err, self.max_parse_retries

    def _build_empty_result(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "uuid": sample.get("uuid", ""),
            "emr": sample.get("emr", ""),
            "meta_data": sample.get("meta_data", {}),
            "response": "",
            "parsed_response": {},
            "thinking_tag": "",
            "add_tag_thinking": "",
            "tag_debug_response": "",
            "staging": "",
            "treatment_gt": {},
            "label": {},
            "auto_check_pass": 0,
            "manual_check": None,
            "think_error": "",
            "tag_error": "",
            "check_error": "",
            "comment": "",
            "think_attempt": 0,
            "tag_attempt": 0,
        }
        if self.keep_debug_fields:
            result["mode"] = self.mode
        return result

    def _extract_recommended_list(self, parsed: Dict[str, Any], treatment_gt: Dict[str, float]) -> List[str]:
        if self.disease_type == "cancer":
            recommended = parsed.get("recommended_list", [])
            if recommended:
                return recommended
            return sorted(treatment_gt.keys(), key=lambda item: treatment_gt[item], reverse=True)
        recommended = parsed.get("suggested_treatment_list", [])
        return recommended if isinstance(recommended, list) else []

    def _extract_treatment_gt(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        if self.disease_type == "cancer":
            treatment_gt = {}
            scores_raw = parsed.get("scores", {})
            for treatment, score_data in scores_raw.items():
                if isinstance(score_data, dict):
                    treatment_gt[treatment] = float(score_data.get("Comprehensive_Score", 0.0))
            return treatment_gt
        return parsed.get("suggested_treatment_list", [])

    def _build_label_map(self, parsed: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        indication_raw = parsed.get("indication", {})
        contraindication_raw = parsed.get("contraindication", {})
        label = {}
        for treatment in self.treatments:
            indication = str(indication_raw.get(treatment, "false")).lower()
            contraindication = str(contraindication_raw.get(treatment, "false")).lower()
            label[treatment] = {
                "indication": indication if indication in ("true", "false") else "false",
                "contraindication": contraindication if contraindication in ("true", "false") else "false",
            }
        return label

    def _extract_staging(self, parsed: Dict[str, Any], final_thinking: str, raw_thinking: str) -> str:
        staging = parsed.get("staging", "")
        if staging:
            return staging

        for text in (final_thinking, raw_thinking):
            staging_tags = re.findall(r"<staging>(.*?)</staging>", text)
            if staging_tags:
                return staging_tags[-1].strip()
        return ""

    def _build_parsed_response(
        self,
        parsed: Dict[str, Any],
        *,
        raw_thinking: str,
        recommended_list: List[str],
    ) -> Dict[str, Any]:
        response = {
            "thinking": raw_thinking,
            "check_for_thinking": parsed.get("check_for_thinking", ""),
            "recommended_list": recommended_list,
        }
        if self.disease_type == "cancer":
            response["scores"] = parsed.get("scores", {})
        else:
            response["suggested_treatment_list"] = parsed.get("suggested_treatment_list", [])
            response["confidence_score"] = parsed.get("confidence_score", 0.0)
        return response

    def process_single(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        result = self._build_empty_result(sample)

        _prompt, response_text, parsed, think_ok, think_err, think_attempt = self._run_generation_step(sample)
        result["response"] = response_text
        result["think_attempt"] = think_attempt

        if not think_ok:
            result["think_error"] = think_err
            return result

        raw_thinking = parsed.get("thinking", "")
        final_thinking = raw_thinking
        tag_response = ""
        tag_error = ""
        tag_attempt = 0
        tag_ok = self.mode == "one-step"
        tag_parsed: Dict[str, Any] = {}

        treatment_gt = self._extract_treatment_gt(parsed)
        recommended_list = self._extract_recommended_list(parsed, treatment_gt if isinstance(treatment_gt, dict) else {})

        if self.mode == "two-step":
            tag_response, tag_parsed, tag_ok, _tag_prompt, tag_error, tag_attempt = self._run_tagging_step(
                thinking_text=raw_thinking,
                recommended_list=recommended_list,
                sample=sample,
            )
            if tag_ok:
                final_thinking = tag_parsed["result"]
                result["add_tag_thinking"] = tag_parsed.get("thinking", "")
            else:
                final_thinking = raw_thinking
                result["think_error"] = "Tagging step failed, using untagged thinking"
                result["tag_error"] = tag_error

        result["tag_attempt"] = tag_attempt
        result["tag_debug_response"] = tag_response
        result["thinking_tag"] = final_thinking
        result["treatment_gt"] = treatment_gt
        result["label"] = self._build_label_map(parsed)
        result["staging"] = self._extract_staging(parsed, final_thinking, raw_thinking)
        result["parsed_response"] = self._build_parsed_response(
            parsed,
            raw_thinking=raw_thinking,
            recommended_list=recommended_list,
        )

        auto_check_pass, check_error = run_graph_check(
            self.graph_tool,
            final_thinking,
            require_tagged_text=True,
        )
        if self.mode == "two-step" and not tag_ok:
            auto_check_pass = 0
            if not check_error:
                check_error = "Tagging fallback used; final reasoning is untagged"

        result["auto_check_pass"] = auto_check_pass
        result["check_error"] = check_error

        if self.enable_seer_qc:
            conflict_with_seer, comment = check_conflict_with_seer(sample, recommended_list, self.disease_type)
            if conflict_with_seer:
                result["manual_check"] = 2
                result["comment"] = comment

        if self.keep_debug_fields:
            result["raw_generation_mode"] = self.mode

        return result
