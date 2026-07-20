from typing import Dict, Any, List

class BaseMetric:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def aggregate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        默认聚合方法：计算所有数值型字段的平均值。
        """
        aggregated = {}
        if not results:
            return aggregated
        
        keys = set()
        for r in results:
            keys.update([k for k, v in r.items() if isinstance(v, (int, float))])
        
        for k in keys:
            values = [r[k] for r in results if k in r and isinstance(r[k], (int, float))]
            if values:
                aggregated[f"avg_{k}"] = sum(values) / len(values)
        return aggregated
    
    def _get_gt_value(self, gt_sample: Dict[str, Any], key: str, default=None):
        """
        辅助函数：尝试从 gt_sample 的不同位置获取 Ground Truth 值。
        """
        if key in gt_sample:
            return gt_sample[key]
        if 'metadata' in gt_sample:
            meta = gt_sample['metadata']
            if key in meta:
                return meta[key]
            if 'original_data' in meta and key in meta['original_data']:
                return meta['original_data'][key]
        return default
