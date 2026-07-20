import re
import json
import math
import numpy as np
from typing import Dict, Any, List, Set
from .base import BaseMetric

try:
    from lifelines.utils import concordance_index
except ImportError:
    concordance_index = None

# ==========================================
# 独立的基础统计函数 (无外部依赖的 Spearman)
# ==========================================
def _rankdata_average_ties(x: np.ndarray) -> np.ndarray:
    """计算带平局（Ties）平均排名的秩"""
    x = np.asarray(x)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(len(x), dtype=float)

    sx = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            avg = (i + j) / 2.0
            ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks

def spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    """计算 Spearman 秩相关系数"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    rx = _rankdata_average_ties(x)
    ry = _rankdata_average_ties(y)

    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


# ==========================================
# 核心评估类 (包含缺省惩罚机制)
# ==========================================

class SurvivalConfidenceScore(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        """
        初始化评估器，支持通过 params 传入鲁棒性配置
        """
        params = params or {}
        
        self.ipcw_min_g = params.get('ipcw_min_g', 0.05)
        if not isinstance(self.ipcw_min_g, (int, float)) or self.ipcw_min_g <= 0.0 or self.ipcw_min_g >= 1.0:
            self.ipcw_min_g = 0.05
            
        self.min_pred_surv = params.get('min_pred_surv', 0.1)
        if not isinstance(self.min_pred_surv, (int, float)):
            self.min_pred_surv = 0.1
            
        self.skip_zero_surv = params.get('skip_zero_surv', True)
        self.cancer_type = params.get('cancer_type', '').lower()
        
        # 新增：解析失败时的惩罚缺省值
        self.default_pred_surv = float(params.get('default_pred_surv', -1.0))
        self.default_conf = float(params.get('default_conf', 0.0))

    # ================= 分期解析辅助函数 =================
    def _normalize_staging(self, staging_val: Any) -> str:
        if staging_val is None:
            return ""
        val_str = str(staging_val).strip()
        if not val_str or val_str.lower() == 'none':
            return ""
        val_str = re.sub(r'</?staging>', '', val_str, flags=re.IGNORECASE)
        val_str = val_str.replace('_', '')
        val_str = val_str.upper().strip()
        return val_str

    def _calculate_nsclc_staging(self, t: str, n: str, m: str) -> str:
        if not t and not n and not m:
            return ""
        t, n, m = t.strip(), n.strip(), m.strip()

        if m in ['M1a', 'M1b', 'M1c', 'M1']: return "IV"
        if m == 'M0':
            if n == 'N0' and t in ['T1mi', 'T1a', 'T1b', 'T1c']: return "IA"
            if n == 'N0' and t == 'T2a': return "IB"
            if (t == 'T2b' and n == 'N0') or \
               (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N1') or \
               (t == 'T3' and n == 'N0'): return "II"
            if (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N2') or \
               (t == 'T3' and n == 'N1') or \
               (t == 'T4' and n in ['N0', 'N1']): return "IIIA"
            if (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N3') or \
               (t == 'T3' and n == 'N2') or \
               (t == 'T4' and n == 'N2'): return "IIIB"
            if (t in ['T3', 'T4'] and n == 'N3'): return "IIIC"
        return ""

    # ================= 核心计算逻辑 =================
    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        gt_data = self._get_gt_value(gt_sample, "meta_data")
        if not gt_data or "seer_data" not in gt_data:
            return None
            
        seer_data = gt_data["seer_data"]

        # 1. 解析真实生存时间和事件 (保留你原有的逻辑)
        if "COD.to.site.recode" in seer_data:
            event = 1 if seer_data["COD.to.site.recode"] != "Alive" else 0
        elif "COD to site recode" in seer_data:
            event = 1 if seer_data["COD to site recode"] != "Alive" else 0
        elif "Survival.days" in seer_data:
            event = 1
        else:
            return None 

        if "Survival.months" in seer_data:
            if (seer_data["Survival.months"] is None) and ("Survival.days" in seer_data):
                gt_surv = 12.0
                event = 0
            else:
                gt_surv = float(seer_data["Survival.months"])
        elif "Survival months" in seer_data:
            gt_surv = float(seer_data["Survival months"])
        else:
            return None 

        # 2. 引入惩罚逻辑获取预测值
        if parsed_pred.get('_parse_failed', False):
            pred_surv = self.default_pred_surv
            conf_score = self.default_conf
        else:
            pred_surv = parsed_pred.get('survival_month', self.default_pred_surv)
            conf_score = parsed_pred.get('confidence', self.default_conf)
            try: pred_surv = float(pred_surv)
            except: pred_surv = self.default_pred_surv
            try: conf_score = float(conf_score)
            except: conf_score = self.default_conf

        # 🌟 3. 提取分期信息 (参考 StagingScore 逻辑)
        stage = "Unknown"
        if self.cancer_type == 'nsclc':
            t_cat = seer_data.get("Derived EOD 2018 T Recode (2018+)", "")
            n_cat = seer_data.get("Derived EOD 2018 N Recode (2018+)", "")
            m_cat = seer_data.get("Derived EOD 2018 M Recode (2018+)", "")
            raw_stage = self._calculate_nsclc_staging(t_cat, n_cat, m_cat)
            stage = self._normalize_staging(raw_stage)
        elif self.cancer_type in ['bclc', 'cnlc']:
            # 兼容 BCLC, CNLC 及其他病种
            raw_stage = self._get_gt_value(gt_sample, 'staging')
            if not raw_stage:
                raw_stage = seer_data.get("BCLC_stage") or seer_data.get("BCLC") or \
                            seer_data.get("AJCC.stage.3rd.ed") or seer_data.get("Derived.AJCC.Stage.Grp.7th.ed")
            stage = self._normalize_staging(raw_stage)
        else:
            stage = "Non-Cancer"
            
        if not stage:
            stage = "Unknown"

        return {
            "pred_survival": pred_surv,
            "gt_survival": gt_surv,
            "event": event,
            "confidence": conf_score,
            "stage": stage # 🌟 输出分期供 aggregate 使用
        }

    def _calc_c_index(self, p_arr: np.ndarray, t_arr: np.ndarray, e_arr: np.ndarray) -> float:
        if len(p_arr) < 2:
            return 0.0
        if concordance_index is None:
            raise ImportError("lifelines is required for survival metrics. Install it with `pip install lifelines`.")
        try:
            return concordance_index(t_arr, p_arr, e_arr)
        except ZeroDivisionError:
            # "No admissable pairs" -- happens when the subset has no
            # comparable event pairs (e.g. all censored, or N==1).
            # Conventional fall-back: 0.5 = random ordering.
            return 0.5

    def _fit_censoring_km(self, t_arr: np.ndarray, e_arr: np.ndarray) -> Dict[float, float]:
        times_cens = sorted(zip(t_arr, 1 - e_arr), key=lambda x: x[0])
        km_dict = {}
        n_at_risk = len(times_cens)
        current_g = 1.0
        
        for t, is_censored in times_cens:
            if is_censored == 1 and n_at_risk > 0:
                current_g *= (1.0 - 1.0 / n_at_risk)
            km_dict[t] = current_g
            n_at_risk -= 1
            if n_at_risk == 0: 
                break
                
        return km_dict

    def _calc_ipcw_mae(self, p_arr: np.ndarray, t_arr: np.ndarray, e_arr: np.ndarray, g_weights_dict: Dict[float, float]) -> float:
        event_mask = (e_arr == 1)
        if not np.any(event_mask): 
            return 0.0
        
        p_events = p_arr[event_mask]
        t_events = t_arr[event_mask]
        
        weights = np.array([
            1.0 / max(g_weights_dict.get(t, self.ipcw_min_g), self.ipcw_min_g) 
            for t in t_events
        ])
        
        errors = np.abs(p_events - t_events)
        return float(np.sum(weights * errors) / np.sum(weights))

    def aggregate(self, results: List[Dict[str, Any]], coverage_grid: np.ndarray = None) -> Dict[str, Any]:
        valid_data = []
        zero_surv_count = 0
        clipped_pred_count = 0
        
        # 1. 过滤并清洗数据，同时提取 stage
        for r in results:
            if not r: continue
            p = float(r.get('pred_survival', self.default_pred_surv))
            t = float(r.get('gt_survival', 0.0))
            e = int(r.get('event', 0))
            c = float(r.get('confidence', 0.0))
            s = str(r.get('stage', 'Unknown')) # 获取分期
            
            if t == 0.0 and self.skip_zero_surv:
                zero_surv_count += 1
                continue
            if p < self.min_pred_surv:
                clipped_pred_count += 1
                p = self.min_pred_surv
                
            valid_data.append([p, t, e, c, s]) # 注意这里存入了 5 个元素
            
        if not valid_data: return {}
        
        # 为了方便全局矩阵计算，先把前 4 个数值型列提出来
        data_mat = np.array([row[:4] for row in valid_data], dtype=float)
        n = len(data_mat)
        
        # 拟合 全局 IPCW 权重 (重要：必须使用全局权重，不能按分期拆分拟合)
        g_weights = self._fit_censoring_km(data_mat[:, 1], data_mat[:, 2])

        # 按 Confidence 降序排列 (最自信的排前面)
        order = np.argsort(-data_mat[:, 3])
        data_mat = data_mat[order]
        
        p_sorted = data_mat[:, 0]
        t_sorted = data_mat[:, 1]
        e_sorted = data_mat[:, 2]
        c_sorted = data_mat[:, 3]

        censored_mae_arr = np.where( # 换个名字避免冲突
            e_sorted == 1,
            np.abs(p_sorted - t_sorted),
            np.maximum(0, t_sorted - p_sorted) 
        )
        rho = spearman_corr(c_sorted, censored_mae_arr)

        if coverage_grid is None:
            coverage_grid = np.linspace(0.05, 1.0, 20)
        
        coverages = []
        rc_cindex = []
        rc_ipcw = []
        rc_cens_mae = [] # 🌟 新增：包含删失患者的真实 MAE
        
        for gamma in coverage_grid:
            k = max(1, int(math.ceil(gamma * n)))
            coverages.append(k / n) 
            
            p_sub = p_sorted[:k]
            t_sub = t_sorted[:k]
            e_sub = e_sorted[:k]
            
            rc_cindex.append(1.0 - self._calc_c_index(p_sub, t_sub, e_sub))
            rc_ipcw.append(self._calc_ipcw_mae(p_sub, t_sub, e_sub, g_weights))
            rc_cens_mae.append(float(np.mean(censored_mae_arr[:k]))) # 🌟 新增

        coverages = np.array(coverages)
        rc_cindex = np.array(rc_cindex)
        rc_ipcw = np.array(rc_ipcw)

        aurc_cindex = float(np.trapz(rc_cindex, coverages))
        aurc_ipcw = float(np.trapz(rc_ipcw, coverages))

        # 3. 计算 Selective Gain (分别计算 IPCW 和 C-index, 包含 50% 和 20%)
        idx_100 = np.argmin(np.abs(coverages - 1.0))
        idx_50 = np.argmin(np.abs(coverages - 0.5))
        idx_20 = np.argmin(np.abs(coverages - 0.2))

        risk_100_ipcw = rc_ipcw[idx_100]
        gain_50_ipcw = float((risk_100_ipcw - rc_ipcw[idx_50]) / risk_100_ipcw) if risk_100_ipcw > 0 else 0.0
        gain_20_ipcw = float((risk_100_ipcw - rc_ipcw[idx_20]) / risk_100_ipcw) if risk_100_ipcw > 0 else 0.0

        risk_100_cindex = rc_cindex[idx_100]
        gain_50_cindex = float((risk_100_cindex - rc_cindex[idx_50]) / risk_100_cindex) if risk_100_cindex > 0 else 0.0
        gain_20_cindex = float((risk_100_cindex - rc_cindex[idx_20]) / risk_100_cindex) if risk_100_cindex > 0 else 0.0

        risk_100_cens_mae = rc_cens_mae[idx_100]
        gain_50_cens_mae = float((risk_100_cens_mae - rc_cens_mae[idx_50]) / risk_100_cens_mae) if risk_100_cens_mae > 0 else 0.0
        gain_20_cens_mae = float((risk_100_cens_mae - rc_cens_mae[idx_20]) / risk_100_cens_mae) if risk_100_cens_mae > 0 else 0.0
        
        # 4. 计算 Random Baseline (MC Average, 默认做 30 次随机洗牌)
        n_mc = 30
        all_random_ipcw = np.zeros((n_mc, len(coverage_grid)))
        all_random_cindex = np.zeros((n_mc, len(coverage_grid)))
        all_random_cens_mae = np.zeros((n_mc, len(coverage_grid))) 
        
        for m in range(n_mc):
            rng = np.random.default_rng(m)
            rand_order = rng.permutation(n)
            
            for j, gamma in enumerate(coverage_grid):
                k = max(1, int(math.ceil(gamma * n)))
                idx_subset = rand_order[:k]
                
                p_sub = data_mat[idx_subset, 0]
                t_sub = data_mat[idx_subset, 1]
                e_sub = data_mat[idx_subset, 2]
                
                all_random_ipcw[m, j] = self._calc_ipcw_mae(p_sub, t_sub, e_sub, g_weights)
                all_random_cindex[m, j] = 1.0 - self._calc_c_index(p_sub, t_sub, e_sub)
                rand_cens_mae_arr = np.where(
                    e_sub == 1,
                    np.abs(p_sub - t_sub),
                    np.maximum(0, t_sub - p_sub)
                )
                all_random_cens_mae[m, j] = float(np.mean(rand_cens_mae_arr))

        rc_ipcw_random = np.nanmean(all_random_ipcw, axis=0)
        rc_cindex_random = np.nanmean(all_random_cindex, axis=0)
        rc_cens_mae_random = np.nanmean(all_random_cens_mae, axis=0)
        aurc_ipcw_random = float(np.trapz(rc_ipcw_random, coverages))
        aurc_cindex_random = float(np.trapz(rc_cindex_random, coverages))
        aurc_cens_mae_random = float(np.trapz(rc_cens_mae_random, coverages))
        
        # 分期统计
        stage_metrics = {}
        # a. 按分期重组数据字典
        stage_groups = {}
        for row in valid_data:
            p_val, t_val, e_val, c_val, s_val = row[0], row[1], row[2], row[3], row[4]
            if s_val not in stage_groups:
                stage_groups[s_val] = {'p': [], 't': [], 'e': [], 'c': []}
            stage_groups[s_val]['p'].append(p_val)
            stage_groups[s_val]['t'].append(t_val)
            stage_groups[s_val]['e'].append(e_val)
            stage_groups[s_val]['c'].append(c_val)

        # b. 遍历每个分期，分别计算三大指标
        for s_name, s_data in stage_groups.items():
            s_p = np.array(s_data['p'])
            s_t = np.array(s_data['t'])
            s_e = np.array(s_data['e'])
            s_c = np.array(s_data['c'])

            n_stage = len(s_p)
            cens_rate = 1.0 - (np.sum(s_e) / n_stage) if n_stage > 0 else 0.0

            # 1. Censored-MAE (分期独立计算)
            s_cens_mae_arr = np.where(s_e == 1, np.abs(s_p - s_t), np.maximum(0, s_t - s_p))
            s_avg_cens_mae = float(np.mean(s_cens_mae_arr))

            # 2. IPCW-MAE (使用全局 g_weights)
            s_ipcw = self._calc_ipcw_mae(s_p, s_t, s_e, g_weights)

            # 3. C-index (防御性计算)
            # C-index 必须要有至少一个明确死亡事件，且需要有配对。如果全都活着，算不出有意义的排序。
            if np.sum(s_e) > 0:
                s_cindex = self._calc_c_index(s_p, s_t, s_e)
            else:
                s_cindex = None # 该分期完全删失，无法计算 C-index

            stage_metrics[s_name] = {
                "count": int(n_stage),
                "censoring_rate": float(cens_rate),
                "avg_confidence": float(np.mean(s_c)),
                "c_index": float(s_cindex) if s_cindex is not None else None,
                "ipcw_mae": float(s_ipcw),
                "censored_mae": float(s_avg_cens_mae)
            }

        # 5. 无损合并返回所有数据
        return {
            "aurc_1_minus_cindex": aurc_cindex,
            "aurc_ipcw_mae": aurc_ipcw,
            "aurc_1_minus_cindex_random": aurc_cindex_random,
            "aurc_ipcw_mae_random": aurc_ipcw_random,
            "aurc_censored_mae_random": aurc_cens_mae_random,

            "selective_gain_50_ipcw": gain_50_ipcw,
            "selective_gain_20_ipcw": gain_20_ipcw,
            "selective_gain_50_cindex": gain_50_cindex,
            "selective_gain_20_cindex": gain_20_cindex,
            "selective_gain_50_cens_mae": gain_50_cens_mae,
            "selective_gain_20_cens_mae": gain_20_cens_mae,
            
            "spearman_rho_censored_mae": rho,
            "full_c_index": 1.0 - rc_cindex[-1],
            
            "stage_wise_metrics": stage_metrics, 
            "stats": {
                "total_valid_samples": n,
                "skipped_zero_surv_samples": zero_surv_count,
                "clipped_pred_samples": clipped_pred_count
            },
            
            "plot_data": {
                "coverages": coverages.tolist(),
                "rc_1_minus_cindex": rc_cindex.tolist(),
                "rc_ipcw_mae": rc_ipcw.tolist(),
                "rc_1_minus_cindex_random": rc_cindex_random.tolist(),
                "rc_censored_mae": rc_cens_mae, 
                "rc_ipcw_mae_random": rc_ipcw_random.tolist(),
                "rc_censored_mae_random": rc_cens_mae_random.tolist()
            }
        }


class SetCalibrationECE(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # 1. 解析 GT 集合
        gt_data = getattr(self, '_get_gt_value', lambda s, k: s.get(k))(gt_sample, 'parsed_response')
        if isinstance(gt_data, dict):
            gt_list = gt_data.get('recommended_list', [])
        else:
            gt_list = getattr(self, '_get_gt_value', lambda s, k: s.get(k))(gt_sample, 'treatment_list') or []
            
        if not isinstance(gt_list, list):
            gt_list = []
            
        gt_set = set(gt_list)

        # 2. 验证 Pred 集合并施加惩罚
        if parsed_pred.get('_parse_failed', False):
            # 解析失败：强行赋予极高置信度(1.0)和零准确率(0.0)以最大化 ECE 惩罚
            return {
                "calibration_items": [{
                    "conf": 1.0,
                    "weight": 1.0, 
                    "iou": 0.0,
                    "f1": 0.0
                }]
            }

        pred_list = parsed_pred.get('suggested_treatment_list', [])
        conf = parsed_pred.get('confidence_score')
        
        # 字段缺失同样视作严重错误
        if conf is None or not isinstance(pred_list, list):
            return {
                "calibration_items": [{
                    "conf": 1.0,
                    "weight": 1.0, 
                    "iou": 0.0,
                    "f1": 0.0
                }]
            }
            
        try:
            conf = float(conf)
            conf = min(max(conf, 0.0), 1.0)
        except (ValueError, TypeError):
            conf = 1.0

        pred_set = set(pred_list)

        # 3. 计算 IoU 和 F1
        if len(pred_set) == 0 and len(gt_set) == 0:
            iou = 1.0
            f1 = 1.0
        else:
            inter_len = len(pred_set & gt_set)
            union_len = len(pred_set | gt_set)
            denom_len = len(pred_set) + len(gt_set)
            
            iou = inter_len / union_len if union_len > 0 else 0.0
            f1 = (2.0 * inter_len) / denom_len if denom_len > 0 else 0.0

        return {
            "calibration_items": [{
                "conf": conf,
                "weight": 1.0, 
                "iou": iou,
                "f1": f1
            }]
        }

    def aggregate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        Wb = [0.0] * 10
        sum_conf = [0.0] * 10
        sum_iou = [0.0] * 10
        sum_f1 = [0.0] * 10

        for res in results:
            items = res.get("calibration_items", [])
            for item in items:
                c = item["conf"]
                w = item["weight"]
                
                b = int(c * 10.0)
                if b >= 10: b = 9
                elif b < 0: b = 0

                Wb[b] += w
                sum_conf[b] += w * c
                sum_iou[b] += w * item["iou"]
                sum_f1[b] += w * item["f1"]

        W_total = sum(Wb)
        
        # 异常情况返回空结构
        if W_total == 0:
            return {
                "iou_ece": 0.0,
                "f1_ece": 0.0,
                "plot_data": {
                    "iou_bins": [],
                    "f1_bins": []
                }
            }

        iou_ece = 0.0
        f1_ece = 0.0
        iou_bins = []
        f1_bins = []

        for b in range(10):
            if Wb[b] > 0:
                avg_conf = sum_conf[b] / Wb[b]
                avg_iou = sum_iou[b] / Wb[b]
                avg_f1 = sum_f1[b] / Wb[b]
                weight_ratio = Wb[b] / W_total
                
                iou_ece += weight_ratio * abs(avg_iou - avg_conf)
                f1_ece += weight_ratio * abs(avg_f1 - avg_conf)
                
                # 保存用于画图的每个 Bin 的统计信息
                iou_bins.append({
                    "bin_id": b, 
                    "avg_conf": avg_conf, 
                    "avg_target": avg_iou, 
                    "weight": Wb[b]
                })
                f1_bins.append({
                    "bin_id": b, 
                    "avg_conf": avg_conf, 
                    "avg_target": avg_f1, 
                    "weight": Wb[b]
                })

        return {
            "iou_ece": iou_ece,
            "f1_ece": f1_ece,
            "plot_data": {
                "iou_bins": iou_bins,
                "f1_bins": f1_bins
            }
        }

class TreatmentCalibration(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        params = params or {}
        self.threshold = float(params.get('threshold', 0.0))
        k_val = params.get('k', None)
        if k_val == 'None':
            k_val = None
        self.k = int(k_val) if k_val is not None else None
        self.top_m = int(params.get('top_m', 3))
        self.tau = int(params.get('tau', 0))
        self.use_position_weighting = bool(params.get('use_position_weighting', True))

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # 1. 获取 GT 数据
        gt_data = self._get_gt_value(gt_sample, 'parsed_response')
        if isinstance(gt_data, dict):
            gt_list = gt_data.get('recommended_list', [])
        else:
            gt_list = []

        # 2. 惩罚逻辑
        if parsed_pred.get('_parse_failed', False) or not isinstance(parsed_pred.get('scores'), dict):
            # 若解析彻底失败，强行注入一条错误记录以扩大 ECE
            return {
                "calibration_items": [{
                    "conf": 1.0,
                    "weight": 1.0,
                    "y_mem": 0.0,
                    "y_rt": 0.0,
                    "u": 0.0
                }]
            }

        pred_scores_map = parsed_pred.get('scores', {})

        valid_preds = [
            (treatment, score) 
            for treatment, score in pred_scores_map.items() 
            if score > self.threshold
        ]
        sorted_preds = sorted(valid_preds, key=lambda x: x[1], reverse=True)
        if self.k is not None:
            sorted_preds = sorted_preds[:self.k]

        gt_rank = {item: idx + 1 for idx, item in enumerate(gt_list)}
        m_eff = min(self.top_m, len(gt_rank))
        gt_top_set = set(gt_list[:m_eff])

        sample_items = []

        for i, (treatment, conf) in enumerate(sorted_preds):
            rank_pred = i + 1 
            try:
                c = float(min(max(conf, 0.0), 1.0))
            except (ValueError, TypeError):
                c = 1.0 # 如果自信度给了一堆乱码，按最高自信处理以惩罚

            w = (1.0 / math.log2(rank_pred + 1.0)) if self.use_position_weighting else 1.0
            y_mem = 1.0 if treatment in gt_top_set else 0.0
            
            y_rt = 0.0
            if treatment in gt_top_set and treatment in gt_rank:
                if abs(rank_pred - gt_rank[treatment]) <= self.tau:
                    y_rt = 1.0

            u = 0.0
            if treatment in gt_top_set and treatment in gt_rank:
                u = 1.0 / math.log2(gt_rank[treatment] + 1.0)

            sample_items.append({
                "conf": c,
                "weight": w,
                "y_mem": y_mem,
                "y_rt": y_rt,
                "u": u
            })

        # 如果有效预测为空，同样按失败处理
        if not sample_items:
             sample_items.append({
                "conf": 1.0,
                "weight": 1.0,
                "y_mem": 0.0,
                "y_rt": 0.0,
                "u": 0.0
            })

        return {"calibration_items": sample_items}

    def aggregate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        Wb = [0.0] * 10
        sum_conf = [0.0] * 10
        sum_y_mem = [0.0] * 10
        sum_y_rt = [0.0] * 10
        sum_u = [0.0] * 10

        for res in results:
            items = res.get("calibration_items", [])
            for item in items:
                c = item["conf"]
                w = item["weight"]
                
                b = int(c * 10.0)
                if b >= 10: b = 9
                elif b < 0: b = 0

                Wb[b] += w
                sum_conf[b] += w * c
                sum_y_mem[b] += w * item["y_mem"]
                sum_y_rt[b] += w * item["y_rt"]
                sum_u[b] += w * item["u"]

        W_total = sum(Wb)
        
        # 异常情况返回空结构
        if W_total == 0:
            return {
                "pw_ece_mem": 0.0,
                "pw_ece_rt": 0.0,
                "ndcg_ece": 0.0,
                "plot_data": {
                    "pw_mem_bins": [],
                    "pw_rt_bins": [],
                    "ndcg_bins": []
                }
            }

        pw_ece_mem = 0.0
        pw_ece_rt = 0.0
        ndcg_ece = 0.0
        pw_mem_bins = []
        pw_rt_bins = []
        ndcg_bins = []

        for b in range(10):
            if Wb[b] > 0:
                avg_conf = sum_conf[b] / Wb[b]
                avg_y_mem = sum_y_mem[b] / Wb[b]
                avg_y_rt = sum_y_rt[b] / Wb[b]
                avg_u = sum_u[b] / Wb[b]
                weight_ratio = Wb[b] / W_total
                
                pw_ece_mem += weight_ratio * abs(avg_y_mem - avg_conf)
                pw_ece_rt += weight_ratio * abs(avg_y_rt - avg_conf)
                ndcg_ece += weight_ratio * abs(avg_u - avg_conf)

                # 保存画图数据
                pw_mem_bins.append({"bin_id": b, "avg_conf": avg_conf, "avg_target": avg_y_mem, "weight": Wb[b]})
                pw_rt_bins.append({"bin_id": b, "avg_conf": avg_conf, "avg_target": avg_y_rt, "weight": Wb[b]})
                ndcg_bins.append({"bin_id": b, "avg_conf": avg_conf, "avg_target": avg_u, "weight": Wb[b]})

        return {
            "pw_ece_mem": pw_ece_mem,
            "pw_ece_rt": pw_ece_rt,
            "ndcg_ece": ndcg_ece,
            "plot_data": {
                "pw_mem_bins": pw_mem_bins,
                "pw_rt_bins": pw_rt_bins,
                "ndcg_bins": ndcg_bins
            }
        }


class TreatmentOverlapMetrics(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        self.MED_CATEGORIES = {
            "analgesics", "aspirin therapy", "P2Y12 inhibitors",
            "intravenous glycoprotein IIb/IIIa inhibitors",
            "parenteral anticoagulation", "lipid management",
            "beta-blocker therapy", "RAAS inhibitors",
            "IV_Alteplase", 
            "IV_Tenecteplase", 
            "IV_Alteplase_WakeUp",
            "Antiplatelet_Aspirin", 
            "Dual_Antiplatelet", 
            "Hemorrhagic_Management",
            "Oxygen_Therapy",
            "Hypoglycemia_Correction",
            "Hyperglycemia_Control",
            "Antipyretic_Therapy",
            "Fluid_Resuscitation_Pressors",
            "Antihypertensive_Pre_TPA",
            "Active_BP_Reduction"
        }
        
        self.PROC_CATEGORIES = {
            "PPCI", "urgent CABG surgery", "fibrinolytic therapy",
            "PCI", "CABG surgery", "immediate invasive",
            "early invasive", "routine invasive", "selective invasive",
            "Mechanical_Thrombectomy_StentRetriever", 
            "Mechanical_Thrombectomy_Aspiration", 
            "Intra_arterial_Fibrinolysis", 
            "Emergency_CEA_CAS", 
            "Airway_Intubation",
            "DVT_Prophylaxis_IPC",
            "NPO_Swallow_Precautions"
        }

    def _calculate_stats(self, pred_set: Set[str], gt_set: Set[str]) -> Dict[str, float]:
        if not pred_set and not gt_set:
            return {"acc": 1.0, "recall": 1.0} 
        
        tp = len(pred_set.intersection(gt_set))
        acc = tp / len(pred_set) if len(pred_set) > 0 else 0.0
        recall = tp / len(gt_set) if len(gt_set) > 0 else 0.0
        
        return {"acc": acc, "recall": recall}

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # 获取 GT 数据
        gt_data = self._get_gt_value(gt_sample, 'parsed_response')
        gt_list = gt_data.get('recommended_list', []) if isinstance(gt_data, dict) else []
        gt_set = set(gt_list)

        # 惩罚逻辑：解析失败视为空集预测
        if parsed_pred.get('_parse_failed', False):
            pred_list = []
        else:
            pred_list = parsed_pred.get('suggested_treatment_list', [])
            
        if not isinstance(pred_list, list):
            pred_list = []
            
        pred_set = set(pred_list)

        pred_med = {item for item in pred_set if item in self.MED_CATEGORIES}
        pred_proc = {item for item in pred_set if item in self.PROC_CATEGORIES}
        
        gt_med = {item for item in gt_set if item in self.MED_CATEGORIES}
        gt_proc = {item for item in gt_set if item in self.PROC_CATEGORIES}

        total_metrics = self._calculate_stats(pred_set, gt_set)
        med_metrics = self._calculate_stats(pred_med, gt_med)
        proc_metrics = self._calculate_stats(pred_proc, gt_proc)

        return {
            "treatment_total_acc": total_metrics["acc"],
            "treatment_total_recall": total_metrics["recall"],
            "treatment_med_acc": med_metrics["acc"],
            "treatment_med_recall": med_metrics["recall"],
            "treatment_proc_acc": proc_metrics["acc"],
            "treatment_proc_recall": proc_metrics["recall"],
            "meta_pred_count": len(pred_set),
            "meta_gt_count": len(gt_set)
        }


class TreatmentNDCG(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        """
        :param threshold: pred分数截断阈值，低于此分数的治疗方案不参与排序
        :param k: 如果只想计算 NDCG@K (例如前3个)，可以设置此值。
        """
        params = params or {}
        self.threshold = float(params.get('threshold', 0.5)) if params.get('threshold') else 0.5
        self.k = params.get('k', None)

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # 1. 获取 GT 数据
        gt_data = self._get_gt_value(gt_sample, 'parsed_response')
        if isinstance(gt_data, dict):
            gt_list = gt_data.get('recommended_list', [])
        else:
            gt_list = []
            
        if not gt_list:
            return {"treatment_ndcg": 0.0}

        # ---------------------------------------------------------
        # 步骤 A: 构建 GT 的相关性分数 (Relevance)
        # ---------------------------------------------------------
        gt_relevance = {item: (len(gt_list) - i) for i, item in enumerate(gt_list)}

        # ---------------------------------------------------------
        # 步骤 B: 处理 Pred 列表 (并加入惩罚逻辑)
        # ---------------------------------------------------------
        if parsed_pred.get('_parse_failed', False):
            pred_scores_map = {}
        else:
            pred_scores_map = parsed_pred.get('scores', {})
            
        if not isinstance(pred_scores_map, dict):
            pred_scores_map = {}

        valid_preds = [
            (treatment, score) 
            for treatment, score in pred_scores_map.items() 
            if score > self.threshold
        ]
        sorted_preds = sorted(valid_preds, key=lambda x: x[1], reverse=True)
        
        if self.k is not None:
            sorted_preds = sorted_preds[:self.k]

        # ---------------------------------------------------------
        # 步骤 C: 计算 DCG (Discounted Cumulative Gain)
        # ---------------------------------------------------------
        dcg = 0.0
        for i, (treatment, score) in enumerate(sorted_preds):
            rel = gt_relevance.get(treatment, 0.0)
            gain = (2 ** rel) - 1
            discount = math.log2((i + 1) + 1)
            dcg += gain / discount

        # ---------------------------------------------------------
        # 步骤 D: 计算 IDCG (Ideal DCG)
        # ---------------------------------------------------------
        idcg = 0.0
        ideal_rels = sorted(gt_relevance.values(), reverse=True)
        if self.k is not None:
            ideal_rels = ideal_rels[:self.k]

        for i, rel in enumerate(ideal_rels):
            gain = (2 ** rel) - 1
            discount = math.log2((i + 1) + 1)
            idcg += gain / discount

        # ---------------------------------------------------------
        # 步骤 E: 计算 NDCG
        # ---------------------------------------------------------
        if idcg == 0:
            ndcg_score = 0.0
        else:
            ndcg_score = dcg / idcg

        return {
            "treatment_ndcg": ndcg_score,
            "meta_pred_treatment": sorted_preds,
        }


class TreatmentScore(BaseMetric):
    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        gt_scores = self._get_gt_value(gt_sample, 'scores', {})
        
        if not gt_scores or not isinstance(gt_scores, dict):
            return {"treatment_score": 0.0}

        total_score = sum(gt_scores.values())
        if total_score == 0: 
            weights = {k: 0 for k in gt_scores}
        else: 
            weights = {k: v / total_score for k, v in gt_scores.items()}
        
        # 惩罚逻辑
        if parsed_pred.get('_parse_failed', False):
            pred_scores = {}
        else:
            pred_scores = parsed_pred.get('scores', {})
            
        if not isinstance(pred_scores, dict): 
            pred_scores = {}

        pred_ranks = {k: rank for rank, k in enumerate(sorted(pred_scores, key=pred_scores.get, reverse=True), start=1)}
        gt_ranks = {k: rank for rank, k in enumerate(sorted(gt_scores, key=gt_scores.get, reverse=True), start=1)}
        
        hard_check_score = 0.0
        for k in gt_scores.keys():
            pred_rank = pred_ranks.get(k, len(pred_scores) + 1)
            gt_rank = gt_ranks[k]
            rank_diff = abs(pred_rank - gt_rank)
            score_component = weights[k] * (1 / (2.71828 ** rank_diff))
            hard_check_score += score_component
            
        return {"treatment_score": hard_check_score}


class StagingScore(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        params = params or {}
        allowed_stagings = params.get('allowed_stagings', [])
        
        # 新增：接收 cancer_type 参数，用于判断是否使用 TNM 推导规则
        self.cancer_type = params.get('cancer_type', '').lower()
        
        self.allowed_stagings_norm = set(
            self._normalize_staging(s) for s in allowed_stagings if s
        )
        self.allowed_stagings_norm.discard("") 

    def _normalize_staging(self, staging_val: Any) -> str:
        if staging_val is None:
            return ""
            
        val_str = str(staging_val).strip()
        if not val_str or val_str.lower() == 'none':
            return ""
            
        val_str = re.sub(r'</?staging>', '', val_str, flags=re.IGNORECASE)
        val_str = val_str.replace('_', '')
        val_str = val_str.upper().strip()
        
        return val_str

    def _calculate_nsclc_staging(self, t: str, n: str, m: str) -> str:
        """
        根据 NSCLC 的 T, N, M 分期计算总体分期 (Staging)
        """
        if not t and not n and not m:
            return ""
            
        # 清理可能携带的空格
        t, n, m = t.strip(), n.strip(), m.strip()

        # Rule 1: IV 期 (补充了 'M1'，以覆盖统计数据中出现的 71 次广义 M1)
        if m in ['M1a', 'M1b', 'M1c', 'M1']:
            return "IV"

        if m == 'M0':
            # Rule 2: IA 期
            if n == 'N0' and t in ['T1mi', 'T1a', 'T1b', 'T1c']:
                return "IA"
            
            # Rule 3: IB 期
            if n == 'N0' and t == 'T2a':
                return "IB"
                
            # Rule 4: II 期
            if (t == 'T2b' and n == 'N0') or \
               (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N1') or \
               (t == 'T3' and n == 'N0'):
                return "II"
                
            # Rule 5: IIIA 期
            if (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N2') or \
               (t == 'T3' and n == 'N1') or \
               (t == 'T4' and n in ['N0', 'N1']):
                return "IIIA"
                
            # Rule 6: IIIB 期
            if (t in ['T1a', 'T1b', 'T1c', 'T2a', 'T2b'] and n == 'N3') or \
               (t == 'T3' and n == 'N2') or \
               (t == 'T4' and n == 'N2'):
                return "IIIB"
                
            # Rule 7: IIIC 期
            if (t in ['T3', 'T4'] and n == 'N3'):
                return "IIIC"

        # 如果遇到不满足任何规则的数据（例如 T0, Tis 或解析异常的杂数据），返回空
        return None

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # --- 核心改动：根据 cancer_type 决定 gt_staging 的获取来源 ---
        if self.cancer_type == 'nsclc':
            # 安全地从多层级字典中获取数据
            meta_data = self._get_gt_value(gt_sample, "meta_data") or {}
            seer_data = meta_data.get("seer_data", {})
            
            t_cat = seer_data.get("Derived EOD 2018 T Recode (2018+)", "")
            n_cat = seer_data.get("Derived EOD 2018 N Recode (2018+)", "")
            m_cat = seer_data.get("Derived EOD 2018 M Recode (2018+)", "")
            
            gt_staging = self._calculate_nsclc_staging(t_cat, n_cat, m_cat)
        else:
            # 兼容其他病种的默认逻辑
            gt_staging = self._get_gt_value(gt_sample, 'staging')

        gt_norm = self._normalize_staging(gt_staging)

        # 惩罚逻辑
        if parsed_pred.get('_parse_failed', False):
            pred_staging = None
        else:
            pred_staging = parsed_pred.get('staging')
            
        pred_norm = self._normalize_staging(pred_staging)
        
        meta_missing_staging_gt = 0
        meta_missing_staging_pred = 0
        score = 0.0
        
        if not pred_norm or (self.allowed_stagings_norm and pred_norm not in self.allowed_stagings_norm):
            meta_missing_staging_pred = 1
            
        if not gt_norm:
            meta_missing_staging_gt = 1
            # GT 缺失时，默认给分为 1.0 (根据你原有的逻辑保持不变)
            score = 1.0
        else:
            if pred_norm == gt_norm:
                score = 1.0
                
        return {
            "staging_score": score,
            "meta_missing_staging_gt": meta_missing_staging_gt,
            "meta_missing_staging_pred": meta_missing_staging_pred
        }


class IndicationAndContraindicationScore(BaseMetric):
    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        # 1. 获取 GT
        gt_labels = self._get_gt_value(gt_sample, 'label')
        if not gt_labels: 
            return None 
            
        pred_labels = self._get_gt_value(gt_sample, "llm_ind_cond")

        pred_ind_dict = {}
        pred_con_dict = {}
        
        # 惩罚逻辑：只有成功解析才去提取预测值
        if not parsed_pred.get('_parse_failed', False):
            if pred_labels: 
                for treatment, pred_values in pred_labels.items():
                    pred_ind_dict[treatment] = pred_values.get('indication')
                    pred_con_dict[treatment] = pred_values.get('contraindication')
            else:
                pred_ind_dict = parsed_pred.get('indication', {})
                pred_con_dict = parsed_pred.get('contraindication', {})
        
        val_map = {"Yes": "true", "No": "false", "true": "true", "false": "false"}
        
        ind_scores = []
        con_scores = []
        
        for treatment, gt_values in gt_labels.items():
            gt_ind = gt_values.get('indication')
            gt_con = gt_values.get('contraindication')
            
            if gt_ind in ["true", "false"]:
                pred_ind_raw = pred_ind_dict.get(treatment)
                pred_ind_mapped = val_map.get(pred_ind_raw)
                ind_scores.append(1.0 if pred_ind_mapped == gt_ind else 0.0)
                
            if gt_con in ["true", "false"]:
                pred_con_raw = pred_con_dict.get(treatment)
                pred_con_mapped = val_map.get(pred_con_raw)
                con_scores.append(1.0 if pred_con_mapped == gt_con else 0.0)

        all_scores = ind_scores + con_scores
        mean_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        exact_match = 1.0 if all_scores and all(s == 1.0 for s in all_scores) else 0.0
        
        return {
            "ind_con_mean_score": mean_score,
            "ind_con_exact_match": exact_match,
            "metadata": {
                "evaluated_items_count": len(all_scores),
                "gt_labels": gt_labels
            }
        }


class RecurrenceScore(BaseMetric):
    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        gt_rec = self._get_gt_value(gt_sample, 'if_recurrence')
        if gt_rec is None:
            return None
            
        # 惩罚逻辑
        if parsed_pred.get('_parse_failed', False):
            pred_rec = None
        else:
            pred_rec = parsed_pred.get('if_recurrence')
            
        score = 1.0 if str(pred_rec).strip() == str(gt_rec).strip() else 0.0
        return {"recurrence_score": score}


class ComplicationScore(BaseMetric):
    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        elected = self.config.get('elected_complication', [])
        if not elected:
            return {"complication_mean_score": 0.0, "complication_exact_match": 0.0}
        
        matches = 0
        for comp_key in elected:
            gt_val = self._get_gt_value(gt_sample, comp_key)
            
            # 惩罚逻辑
            if parsed_pred.get('_parse_failed', False):
                pred_val = None
            else:
                pred_val = parsed_pred.get(comp_key)
                
            if str(pred_val).strip() == str(gt_val).strip():
                matches += 1
        
        mean_score = matches / len(elected) if elected else 0.0
        exact_match = 1.0 if matches == len(elected) and elected else 0.0
        
        return {
            "complication_mean_score": mean_score,
            "complication_exact_match": exact_match
        }


class SurvivalScore(BaseMetric):
    def __init__(self, params: Dict[str, Any] = None):
        params = params or {}
        self.default_pred_surv = float(params.get('default_pred_surv', -1.0))

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        gt_data = self._get_gt_value(gt_sample, "meta_data")
        if not gt_data or "seer_data" not in gt_data:
            return None
            
        seer = gt_data["seer_data"]

        if "Survival.months" in seer:
            if (seer["Survival.months"] is None) and ("Survival.days" in seer):
                gt_surv = 12.0
                event = 0
            else:
                gt_surv = float(seer["Survival.months"])
        elif "Survival months" in seer:
            gt_surv = float(seer["Survival months"])
        else:
            return None

        if "COD.to.site.recode" in seer:
            event = 1 if seer["COD.to.site.recode"] != "Alive" else 0
        elif "COD to site recode" in seer:
            event = 1 if seer["COD to site recode"] != "Alive" else 0
        elif "Survival.days" in seer:
            event = 1
        else:
            return None
        
        # 惩罚逻辑
        if parsed_pred.get('_parse_failed', False):
            pred_surv = self.default_pred_surv
        else:
            try:
                pred_surv = float(parsed_pred.get('survival_month', self.default_pred_surv))
            except (ValueError, TypeError):
                pred_surv = self.default_pred_surv
        
        return {
            "pred_survival": pred_surv,
            "gt_survival": gt_surv,
            "event": event
        }

    def aggregate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        valid_data = []
        for r in results:
            if r is None: 
                continue
                
            p = r.get('pred_survival')
            t = r.get('gt_survival')
            e = r.get('event')
            
            if p is not None and t is not None and e is not None:
                valid_data.append((float(p), float(t), int(e)))
        
        if not valid_data:
            return {"c_index": 0.0}
            
        n = len(valid_data)
        concordant = 0
        permissible = 0
        
        for i in range(n):
            for j in range(i + 1, n):
                p_i, t_i, e_i = valid_data[i]
                p_j, t_j, e_j = valid_data[j]
                
                comparable = False
                shorter_idx = -1
                
                if e_i == 1 and e_j == 1:
                    comparable = True
                    if t_i < t_j: shorter_idx = i
                    elif t_i > t_j: shorter_idx = j
                    else: comparable = False
                elif e_i == 1 and e_j == 0:
                    if t_i < t_j: 
                        comparable = True
                        shorter_idx = i
                elif e_i == 0 and e_j == 1:
                    if t_j < t_i:
                        comparable = True
                        shorter_idx = j
                
                if comparable:
                    permissible += 1
                    longer_idx = j if shorter_idx == i else i
                    
                    if valid_data[shorter_idx][0] < valid_data[longer_idx][0]:
                        concordant += 1
                    elif valid_data[shorter_idx][0] == valid_data[longer_idx][0]:
                        concordant += 0.5
                        
        c_index = concordant / permissible if permissible > 0 else 0.0
        return {"c_index": c_index}
