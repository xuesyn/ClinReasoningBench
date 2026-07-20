import json
from typing import Dict, Any, List
from .graph_based_metric import GraphBasedMetric
from .clinical import (
    TreatmentNDCG, StagingScore, IndicationAndContraindicationScore,
    RecurrenceScore, ComplicationScore, SurvivalScore, TreatmentOverlapMetrics,TreatmentCalibration,SetCalibrationECE,SurvivalConfidenceScore
)

class MetricCalculator:
    def __init__(self, metric_configs: Dict[str, Any]):
        self.metrics = []
        self.metric_map = {
            'GraphBasedMetric': GraphBasedMetric,
            'treatment_score': TreatmentNDCG,
            'treatment_set_score': TreatmentOverlapMetrics,
            'staging_score': StagingScore,
            'Indication_and_contraindication_score': IndicationAndContraindicationScore,
            'survival_score': SurvivalScore,
            'recurrence_score': RecurrenceScore,
            'complication_score': ComplicationScore,
            'treatment_calibration': TreatmentCalibration,
            'set_calibration': SetCalibrationECE,
            'survival_calibration': SurvivalConfidenceScore,
        }
        
        for name, conf in metric_configs.items():
            if name in self.metric_map:
                self.metrics.append(self.metric_map[name](conf))
            else:
                print(f"Warning: Metric {name} not found.")

    def calculate_scores(self, pred_text: str, gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        parsed_pred = self._parse_json_text(pred_text)
        results = {}
        
        # 🌟 核心改动 1：将样本级别的解析状态记录下来，打上烙印
        results['meta_parse_failed'] = parsed_pred.get('_parse_failed', False)

        for metric in self.metrics:
            try:
                res = metric.calculate(parsed_pred, gt_sample)
                # 只有当 Metric 正常返回数据时（而不是因为 GT 缺失返回 None 时），才更新字典
                if res is not None:
                    results.update(res)
            except Exception as e:
                print(f"Error calculating metric {metric.__class__.__name__}: {e}")
                pass
        return results

    def aggregate(self, all_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        aggregated = {}
        
        # 🌟 核心改动 2：统计全局的解析失败率（Instruction Following 失败率）
        total_samples = len(all_results)
        failed_parses = sum(1 for r in all_results if r.get('meta_parse_failed', False))
        
        aggregated['meta_total_evaluated_samples'] = total_samples
        aggregated['meta_parse_fail_rate'] = failed_parses / total_samples if total_samples > 0 else 0.0

        for metric in self.metrics:
            try:
                res = metric.aggregate(all_results)
                # 增加判空保护，防止某些 metric 在没有任何有效样本时返回空值
                if res:
                    aggregated.update(res)
            except Exception as e:
                print(f"Error aggregating metric {metric.__class__.__name__}: {e}")
                pass
        return aggregated
        
    @staticmethod
    def _parse_json_text(text: str) -> Dict[str, Any]:
        if not text or not isinstance(text, str):
            return {"_parse_failed": True}

        try:
            start_idx = text.index('{')
            end_idx = text.rindex('}') + 1
            json_str = text[start_idx:end_idx]
        except (ValueError, IndexError, AttributeError):
            return {"_parse_failed": True}

        # 1st try: strict
        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, dict):
                return {"_parse_failed": True}
            return parsed
        except (ValueError, json.JSONDecodeError):
            pass

        # 2nd try: repair Claude-style un-escaped inner double quotes (e.g.
        # `"thinking": "...（"快进快出"）..."` — the inner ASCII " breaks JSON).
        # Heuristic: any `"` whose neither side reaches a JSON-structural
        # token ({ [ , : on the left, or : , } ] on the right, skipping
        # whitespace) is treated as an inner quote and replaced with a
        # full-width substitute. Backslash-escaped \" are skipped.
        def _is_structural(s, i):
            j = i - 1
            while j >= 0 and s[j] in ' \t\n\r': j -= 1
            left = s[j] if j >= 0 else ''
            j = i + 1
            while j < len(s) and s[j] in ' \t\n\r': j += 1
            right = s[j] if j < len(s) else ''
            return (left in '{[,:') or (right in ':,}]')

        chars = list(json_str)
        for i, c in enumerate(chars):
            if c != '"': continue
            if i > 0 and chars[i-1] == '\\': continue
            if not _is_structural(json_str, i):
                chars[i] = '”'
        repaired = ''.join(chars)
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, json.JSONDecodeError):
            pass

        return {"_parse_failed": True}