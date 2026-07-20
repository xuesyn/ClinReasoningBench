import re
import json
import os
from typing import Dict, Any, List, Tuple, Optional
from math import sqrt
import numpy as np
from .base import BaseMetric

# 尝试导入 sentence_transformers，如果环境中没有安装需提示
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

class GraphBasedMetric(BaseMetric):
    def __init__(
        self, 
        args,
        # use_hard_check_score: bool = True,
        # knowledge_calc_method: str = 'semantic',  # 'id' (旧方法) 或 'semantic' (新方法)
        # knowledge_db_path: Optional[str] = None,
        # knowledge_key: str = 'original_text',
        # model_local_path: Optional[str] = None,
        # similarity_threshold: float = 0.8
    ):
        """
        Args:
            use_hard_check_score: 是否将 hard_check_score 纳入最终分数计算。
            knowledge_calc_method: 'id' 使用 <knowledge_id> 精确匹配; 'semantic' 使用 <cite> 语义匹配。
            knowledge_db_path: jsonl 文件路径，用于 semantic 模式下的知识库查找。
            knowledge_key: jsonl 中用于比较的字段名，如 'original_text'。
            model_local_path: SentenceTransformer 模型路径。
            similarity_threshold: 语义相似度判定为 hit 的阈值。
        """
        use_hard_check_score = args.get('use_hard_check_score', False)
        knowledge_calc_method = args.get('knowledge_calc_method', 'semantic')
        knowledge_db_path = args.get('knowledge_db_path', None)
        knowledge_key = args.get('knowledge_key', 'original_text')
        model_local_path = args.get('model_local_path', 'ckpt/bge-large-zh-v1.5')
        similarity_threshold = args.get('similarity_threshold', 0.8)

        self.use_hard_check_score = use_hard_check_score
        self.knowledge_calc_method = knowledge_calc_method
        self.knowledge_key = knowledge_key
        self.similarity_threshold = similarity_threshold
        
        # 初始化语义匹配相关资源
        if self.knowledge_calc_method == 'semantic':
            if SentenceTransformer is None:
                raise ImportError("需安装 sentence_transformers 库才能使用 semantic 模式: pip install sentence-transformers")
            
            if not model_local_path or not os.path.exists(model_local_path):
                raise FileNotFoundError(f"未找到本地模型路径: {model_local_path}")
            
            print(f"Loading embedding model from {model_local_path}...")
            # auto-device patch: prefer GPU when available
            import torch as _t
            _dev = "cuda" if _t.cuda.is_available() else "cpu"
            self.model = SentenceTransformer(model_local_path, device=_dev)
            print(f"  [GraphBasedMetric] using device={_dev}")
            
            if not knowledge_db_path or not os.path.exists(knowledge_db_path):
                raise FileNotFoundError(f"未找到知识库文件: {knowledge_db_path}")
            
            self.knowledge_db = self._load_knowledge_db(knowledge_db_path)

    def _load_knowledge_db(self, path: str) -> Dict[str, Dict]:
        """加载 jsonl 知识库为 id -> data 字典"""
        db = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    item = json.loads(line)
                    if 'id' in item:
                        db[str(item['id'])] = item
                except json.JSONDecodeError:
                    continue
        return db

    def parse_tags_from_text(self, text: str) -> Dict[str, Any]:
        """从预测文本中解析出 <tag>value</tag>"""
        pattern = re.compile(r"<([A-Za-z0-9_\-]+)>(.*?)</\1>", re.DOTALL)
        matches = pattern.findall(text)
        
        parsed_env = {}
        for tag_name, content in matches:
            key = tag_name.strip()
            value = content.strip()
            try:
                value = float(value)
                if value.is_integer():
                    value = int(value)
            except (ValueError, TypeError):
                pass

            if key == "treatment":
                if key not in parsed_env:
                    parsed_env[key] = []
                if value not in parsed_env[key]:
                    parsed_env[key].append(value)
            else:
                parsed_env[key] = value
        return parsed_env
    
    def _parse_json_text(self, text: str) -> Dict[str, Any]:
        """尝试从文本中提取 JSON 部分"""
        try:
            start_idx = text.index('{')
            end_idx = text.rindex('}') + 1
            json_str = text[start_idx:end_idx]
            return json.loads(json_str)
        except (ValueError, json.JSONDecodeError):
            raise ValueError("No valid JSON found in the text.")
            
    def parse_knowledge_ids_from_text(self, text: str) -> List[str]:
        """从文本中解析出所有 <knowledge_id='id'> (旧方法)"""
        pattern = re.compile(r"<knowledge_id='([^']+)'>")
        return pattern.findall(text)

    def parse_citations_from_text(self, text: str) -> List[str]:
        """从文本中解析出所有 <cite>content</cite> (新方法)"""
        pattern = re.compile(r"<cite>(.*?)</cite>", re.DOTALL)
        # 提取内容并去除首尾空白
        return [match.strip() for match in pattern.findall(text)]

    def _calc_corresponding_score(self, pred_env: Dict[str, Any], gt_subgraph: Dict[str, Any]) -> Tuple[Dict, float]:
        """计算单个预测与 GT 子图的对应分数"""
        gt_nodes = gt_subgraph.get('nodes', [])
        gt_routes = gt_subgraph.get('routes', [])

        if not gt_nodes:
            return {}, 1.0 if not pred_env else 0.0

        gt_node_map = {node['key_id']: node for node in gt_nodes}
        correctness: Dict[int, bool | None] = {node['key_id']: None for node in gt_nodes}
        
        # 1. 值匹配检查
        for key_id, node in gt_node_map.items():
            key = node['key']
            gt_value = node['value']
            
            if key not in pred_env:
                correctness[key_id] = None
                continue

            pred_value = pred_env[key]

            if isinstance(gt_value, list):
                try:
                    is_correct = sorted(str(v).lower() for v in gt_value) == sorted(str(v).lower() for v in pred_value) if isinstance(pred_value, list) else False
                except Exception:
                    is_correct = False
            else:
                try:
                    is_correct = type(gt_value)(pred_value) == gt_value
                except (ValueError, TypeError):
                    is_correct = str(pred_value) == str(gt_value)
                if not is_correct and isinstance(gt_value, str) and isinstance(pred_value, str):
                    is_correct = pred_value.lower() == gt_value.lower()

            correctness[key_id] = is_correct

        # 2. 依赖图构建
        adj: Dict[int, List[int]] = {}
        for route in gt_routes:
            if route['from'] not in adj:
                adj[route['from']] = []
            adj[route['from']].append(route['to'])

        # 3. 错误传播
        failed_nodes = {k for k, v in correctness.items() if v is False}
        queue = list(failed_nodes)
        visited_failed = set(failed_nodes)
        
        while queue:
            curr = queue.pop(0)
            if curr in adj:
                for neighbor in adj[curr]:
                    if neighbor not in visited_failed:
                        visited_failed.add(neighbor)
                        queue.append(neighbor)

        # 4. 计分
        node_scores: Dict[str, int] = {}
        for key_id, node in gt_node_map.items():
            key = node['key']
            if key_id in visited_failed:
                node_scores[key] = 0
            elif correctness[key_id] is not True:
                node_scores[key] = 0
            else:
                node_scores[key] = 1

        total_nodes = len(gt_nodes)
        total_correct = sum(node_scores.values())
        accuracy = total_correct / total_nodes if total_nodes > 0 else 1.0

        score_details = {
            "node_scores": node_scores,
            "accuracy": accuracy
        }
        return score_details, accuracy
    
    def _calc_hard_check_scores(self, pred_scores: Dict[str, Any], gt_scores: Dict[str, Any]) -> float:
        """
        计算 ranking 相关的 hard check score
        """
        total_score = sum(gt_scores.values())
        if total_score == 0: return 0.0 # 防止 GT 全 0
        weights = {k: v / total_score for k, v in gt_scores.items()}
        
        pred_ranks = {k: rank for rank, k in enumerate(sorted(pred_scores, key=pred_scores.get, reverse=True), start=1)}
        gt_ranks = {k: rank for rank, k in enumerate(sorted(gt_scores, key=gt_scores.get, reverse=True), start=1)}
        
        hard_check_score = 0.0
        for k in gt_scores.keys():
            pred_rank = pred_ranks.get(k, len(pred_scores) + 1)
            gt_rank = gt_ranks[k]
            rank_diff = abs(pred_rank - gt_rank)
            score_component = weights[k] * (1 / (2.71828 ** rank_diff))
            hard_check_score += score_component
        return hard_check_score
        
    def _calc_knowledge_id_score_simple(self, pred_k_ids: List[str], gt_k_ids: List[str]) -> Dict[str, float]:
        """
        [旧方法] 知识点 ID 精确匹配评分
        """
        pred_k_ids_set = set(pred_k_ids)
        gt_k_ids_set = set(gt_k_ids)
        
        hits = pred_k_ids_set.intersection(gt_k_ids_set)
        num_hits = len(hits)
        
        k_recall = num_hits / len(gt_k_ids_set) if gt_k_ids_set else 1.0
        k_precision = num_hits / len(pred_k_ids_set) if pred_k_ids_set else (1.0 if not gt_k_ids_set else 0.0)

        return {
            'recall': k_recall,
            'precision': k_precision,
            'final_score': k_recall * k_precision if (k_recall + k_precision) > 0 else 0.0
        }

    def _calc_knowledge_semantic_score(self, pred_texts: List[str], gt_ids: List[str]) -> Dict[str, float]:
        """
        [新方法] 基于语义相似度的评分
        """
        # 1. 准备 GT 文本列表
        gt_texts = []
        for gid in gt_ids:
            # 兼容 str/int ID 查找
            info = self.knowledge_db.get(str(gid))
            if info and self.knowledge_key in info:
                gt_texts.append(info[self.knowledge_key])
            else:
                # 如果找不到对应的 ID 或 key，这里可以选择跳过或填空字符串，这里选择跳过
                pass

        # 2. 边界情况处理
        if not gt_texts:
            # GT 为空，如果预测也为空则满分，否则0分（或视具体业务逻辑定）
            return {'recall': 1.0, 'precision': 1.0 if not pred_texts else 0.0, 'final_score': 1.0 if not pred_texts else 0.0}
        
        if not pred_texts:
            # GT 不为空，但预测为空
            return {'recall': 0.0, 'precision': 0.0, 'final_score': 0.0}

        # 3. 计算 Embedding
        # normalize_embeddings=True 使得点积等同于余弦相似度
        gt_embeddings = self.model.encode(gt_texts, normalize_embeddings=True, show_progress_bar=False)
        pred_embeddings = self.model.encode(pred_texts, normalize_embeddings=True, show_progress_bar=False)

        # 4. 计算相似度矩阵 (GT_num, Pred_num)
        # 使用 @ 进行矩阵乘法
        similarity_matrix = gt_embeddings @ pred_embeddings.T
        
        # 5. 计算 Recall (GT 覆盖率)
        # 对于每一个 GT，看是否在 Pred 中找到了相似度 > threshold 的
        # axis=1 求每一行(每个GT)的最大值
        max_sim_per_gt = np.max(similarity_matrix, axis=1)
        gt_hits = np.sum(max_sim_per_gt > self.similarity_threshold)
        recall = gt_hits / len(gt_texts)

        # 6. 计算 Precision (Pred 准确率)
        # 对于每一个 Pred，看是否命中 GT 中任意一个 > threshold
        # axis=0 求每一列(每个Pred)的最大值
        max_sim_per_pred = np.max(similarity_matrix, axis=0)
        pred_hits = np.sum(max_sim_per_pred > self.similarity_threshold)
        precision = pred_hits / len(pred_texts)

        return {
            'recall': float(recall),
            'precision': float(precision),
            'final_score': float(recall * precision) if (recall + precision) > 0 else 0.0
        }

    def _score_single_prediction(self, parsed_pred: Dict[str, Any], gt_subgraph: Dict[str, Any], gt_scores: Dict[str, Any]) -> Tuple[Dict, float]:
        """对单个预测文本进行评分"""
        try:
            pred_thinking = parsed_pred.get('thinking', "")
            if isinstance(pred_thinking, list):
                pred_thinking = "\n".join(str(item) for item in pred_thinking)
            elif not isinstance(pred_thinking, str):
                pred_thinking = str(pred_thinking) if pred_thinking is not None else ""
            pred_scores_dict = parsed_pred.get('scores', {})
            pred_env = self.parse_tags_from_text(pred_thinking)
        except ValueError:
            return {}, 0.0

        # --- Component 1: Node Correctness ---
        detail_corresponding_score, accuracy_corresponding = self._calc_corresponding_score(pred_env, gt_subgraph)
        
        # --- Component 2: Knowledge Score ---
        gt_k_ids = gt_subgraph.get('knowledge_ids', [])
        
        if self.knowledge_calc_method == 'semantic':
            # 新方法：解析 <cite> 并做语义匹配
            pred_citations = self.parse_citations_from_text(pred_thinking)
            knowledge_id_scores = self._calc_knowledge_semantic_score(pred_citations, gt_k_ids)
        else:
            # 旧方法：解析 <knowledge_id> 并做 ID 匹配
            pred_k_ids = self.parse_knowledge_ids_from_text(pred_thinking)
            knowledge_id_scores = self._calc_knowledge_id_score_simple(pred_k_ids, gt_k_ids)

        score_components = [
            accuracy_corresponding,
            knowledge_id_scores['final_score']
        ]
        
        details = {
            "corresponding_score": accuracy_corresponding,
            "knowledge_id_scores": knowledge_id_scores['final_score'],
            "hard_check_score": 0.0 # Default value for display
        }

        # --- Component 3: Hard Check Score (Optional) ---
        if self.use_hard_check_score:
            scores_hard_check = self._calc_hard_check_scores(pred_scores_dict, gt_scores)
            score_components.append(scores_hard_check)
            details["hard_check_score"] = scores_hard_check
            
        # --- Final Calculation ---
        final_score = sum(score_components) / len(score_components) if score_components else 0.0

        return details, final_score

    def calculate(self, parsed_pred: Dict[str, Any], gt_sample: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算单个样本的图谱相关评分。
        Args:
            parsed_pred: 模型预测的解析结果，包含 'thinking' 和 'scores'。
            gt_sample: 包含 GT 子图和 GT 分数的样本字典。
        Returns:
            包含评分详情和最终分数的字典。
        """
        gt_subgraph = self._get_gt_value(gt_sample, 'gt_knowledge_map', {})
        
        gt_scores = self._get_gt_value(gt_sample, 'treatment_gt', {})

        # if gt_response and 'scores' in gt_response:
        #     gt_scores = gt_response['scores']
        # else:
        #     gt_scores = {}
        
        details, final_score = self._score_single_prediction(parsed_pred, gt_subgraph, gt_scores)
        
        result = {
            "final_score": final_score,
            "corresponding_score": details["corresponding_score"],
            "knowledge_id_scores": details["knowledge_id_scores"],
            "hard_check_score": details["hard_check_score"]
        }
        return result