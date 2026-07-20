import json
import os
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import pandas as pd
from datetime import datetime

from .models.base_api import BaseAPI
from .metrics.calculator import MetricCalculator

class Evaluator:
    def __init__(self, config: dict):
        self.config = config
        self.models_config = config['models']
        self.datasets_config = config['datasets']
        self.eval_params = config['evaluation_params']
        self.output_dir = config['output_dir']
        
        # 新增：从配置读取保存间隔，默认为 10 条
        self.save_interval = self.eval_params.get('save_interval', 10)

    def _is_valid_existing_data(self, item: dict) -> bool:
        content_str = None

        if "predictions" in item and isinstance(item["predictions"], list) and len(item["predictions"]) > 0:
            content_str = item["predictions"][0]
        else:
            return False

        if not content_str or not isinstance(content_str, str):
            return False

        if "Error code:" in content_str or "new_api_error" in content_str or "model_not_found" in content_str:
            return False

        if self.eval_params.get('strict_checkpoint_validation', False):
            try:
                clean_str = content_str.strip()
                clean_str = re.sub(r'^```json\s*', '', clean_str, flags=re.IGNORECASE)
                clean_str = re.sub(r'^```\s*', '', clean_str)
                clean_str = re.sub(r'\s*```$', '', clean_str)
                parsed_json = json.loads(clean_str)
                if isinstance(parsed_json, dict):
                    if any(k in parsed_json for k in ('thinking', 'scores', 'survival_month', 'suggested_treatment_list')):
                        return True
                return False
            except (json.JSONDecodeError, TypeError):
                return False

        return True

    def _get_model_instance(self, model_name: str) -> BaseAPI:
        model_conf = self.models_config[model_name]
        model_type = model_conf['type']
        try:
            module = __import__(f"med_eval_pipeline.models.api_{model_type}", fromlist=[f"API_{model_type}"])
            model_class = getattr(module, f"API_{model_type}")
            return model_class(model_conf)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Model type '{model_type}' is not supported. Error: {e}")

    def _run_inference_on_sample(self, model: BaseAPI, sample: dict, pass_k: int):
        question = sample['conversations'][0]['text']
        predictions = model.generate(question, n=pass_k)
        sample_with_pred = sample.copy()
        sample_with_pred['predictions'] = predictions
        return sample_with_pred

    def _run_scoring_on_sample(self, calculator: MetricCalculator, sample: dict):
        predictions = sample.get('predictions', [])
        best_result = {}
        
        for i, pred_text in enumerate(predictions):
            res = calculator.calculate_scores(pred_text, sample)
            if i == 0:
                best_result = res
            else:
                for k, v in res.items():
                    if isinstance(v, (int, float)) and k in best_result:
                        if any(x in k for x in ['score', 'accuracy', 'precision', 'recall', 'f1', 'match']):
                            if v > best_result[k]:
                                best_result[k] = v
        
        sample_with_score = sample.copy()
        sample_with_score['score_results'] = best_result
        return sample_with_score
    
    def _load_jsonl_as_dict(self, path: str, key_field: str = 'uuid', validate_func=None):
        data_dict = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        if key_field in item:
                            # 如果传入了校验函数且校验不通过，则跳过该条数据
                            if validate_func and not validate_func(item):
                                continue
                            data_dict[item[key_field]] = item
                    except json.JSONDecodeError:
                        pass
        return data_dict

    def _append_batch_to_jsonl(self, filepath: str, batch_data: list):
        """辅助函数：将一批数据追加写入文件"""
        if not batch_data:
            return
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                for sample in batch_data:
                    f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        except Exception as e:
            logging.error(f"Failed to write batch to {filepath}: {e}")

    def run(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for db_name, db_conf in self.datasets_config.items():
            logging.info(f"--- Evaluating on Dataset: {db_name} ---")
            
            # ==========================================
            # 🚨 1. 加载数据逻辑 (优先使用 union_meta_path)
            # ==========================================
            union_meta_path = db_conf.get('union_meta_path')
            meta_path = db_conf.get('meta_path')
            
            if union_meta_path and os.path.exists(union_meta_path):
                anchor_path = union_meta_path
                logging.info(f"🚨 ITT Mode Active: Using UNION META ROSTER from {anchor_path}")
            else:
                anchor_path = meta_path
                logging.info(f"Standard Mode: Using base meta from {anchor_path}")

            all_samples_dict = self._load_jsonl_as_dict(anchor_path, 'uuid')
            all_samples = list(all_samples_dict.values())
            
            if not all_samples:
                logging.warning(f"No samples found in {anchor_path}. Skipping.")
                continue

            for model_name in self.models_config.keys():
                logging.info(f"--- Using Model: {model_name} ---")
                model_instance = self._get_model_instance(model_name)
                
                inference_path = os.path.join(self.output_dir, f"{db_name}_{model_name}@inference.jsonl")
                scores_path = os.path.join(self.output_dir, f"{db_name}_{model_name}@scores.jsonl")

                # ==========================================
                # --- Step 1: Inference (With Checkpoint) ---
                # ==========================================
                existing_inference = self._load_jsonl_as_dict(
                    inference_path, 
                    'uuid', 
                    validate_func=self._is_valid_existing_data
                )
                logging.info(f"Loaded {len(existing_inference)} existing inference results.")

                samples_to_infer = [s for s in all_samples if s['uuid'] not in existing_inference]
                
                if samples_to_infer and not self.eval_params.get('skip_inference', False):
                    logging.info(f"Running inference on {len(samples_to_infer)} samples...")
                    
                    batch_buffer = []  # 临时缓冲区
                    
                    with ThreadPoolExecutor(max_workers=self.eval_params['num_workers']) as executor:
                        futures = {executor.submit(self._run_inference_on_sample, model_instance, s, self.eval_params['pass_k']): s for s in samples_to_infer}
                        
                        for future in tqdm(as_completed(futures), total=len(samples_to_infer), desc=f"Inferring {model_name}"):
                            try:
                                res = future.result()
                                batch_buffer.append(res)
                                
                                # Checkpoint: 当缓冲区达到阈值，写入文件并清空
                                if len(batch_buffer) >= self.save_interval:
                                    self._append_batch_to_jsonl(inference_path, batch_buffer)
                                    # 同时更新内存中的字典，确保后续逻辑正确
                                    for s in batch_buffer:
                                        existing_inference[s['uuid']] = s
                                    batch_buffer = []  # 清空缓冲区
                                    
                            except Exception as e:
                                logging.error(f"Inference failed for a sample: {e}")

                    # Loop 结束后，写入剩余的数据
                    if batch_buffer:
                        self._append_batch_to_jsonl(inference_path, batch_buffer)
                        for s in batch_buffer:
                            existing_inference[s['uuid']] = s
                        batch_buffer = [] # 清理

                elif self.eval_params.get('skip_inference', False):
                    logging.info("Skipping inference as per config.")

                # ==========================================
                # 🚨 2. ITT 拦截：补齐全集，惩罚缺失样本
                # ==========================================
                inferred_samples_list = []
                for s in all_samples:
                    if s['uuid'] in existing_inference:
                        # 正常交卷的样本
                        inferred_samples_list.append(existing_inference[s['uuid']])
                    else:
                        # 逃考或解析彻底失败的坏样本，施加惩罚
                        logging.warning(f"ITT Penalty Applied: Missing inference for UUID {s['uuid']}")
                        dummy_sample = s.copy()
                        # 强制注入空字符串，精准触发 MetricCalculator 的 _parse_failed
                        dummy_sample['predictions'] = [""] 
                        inferred_samples_list.append(dummy_sample)

                # ==========================================
                # --- Step 2: Scoring (With Checkpoint) ---
                # ==========================================
                existing_scores = self._load_jsonl_as_dict(
                    scores_path, 
                    'uuid',
                    validate_func=self._is_valid_existing_data
                )
                logging.info(f"Loaded {len(existing_scores)} existing score results.")

                samples_to_score = [s for s in inferred_samples_list if s['uuid'] not in existing_scores]

                if samples_to_score:
                    logging.info(f"Running scoring on {len(samples_to_score)} samples...")
                    metrics_config = self.config.get('metrics', {})
                    calculator = MetricCalculator(metrics_config)
                    
                    batch_buffer = [] # 临时缓冲区
                    
                    with ThreadPoolExecutor(max_workers=self.eval_params['num_workers']) as executor:
                        futures = {executor.submit(self._run_scoring_on_sample, calculator, s): s for s in samples_to_score}
                        
                        for future in tqdm(as_completed(futures), total=len(samples_to_score), desc=f"Scoring {model_name}"):
                            try:
                                res = future.result()
                                batch_buffer.append(res)
                                
                                # Checkpoint: 增量写入
                                if len(batch_buffer) >= self.save_interval:
                                    self._append_batch_to_jsonl(scores_path, batch_buffer)
                                    for s in batch_buffer:
                                        existing_scores[s['uuid']] = s
                                    batch_buffer = []
                                    
                            except Exception as e:
                                logging.error(f"Scoring failed for a sample: {e}")

                    # Loop 结束后，写入剩余分数
                    if batch_buffer:
                        self._append_batch_to_jsonl(scores_path, batch_buffer)
                        for s in batch_buffer:
                            existing_scores[s['uuid']] = s
                        batch_buffer = []

                # --- Step 3: Aggregation ---
                final_scored_list = []
                for s in all_samples:
                    if s['uuid'] in existing_scores:
                        final_scored_list.append(existing_scores[s['uuid']])
                    else:
                        # 兜底：如果 Scoring 环节意外没存下来，给一个终极缺省惩罚
                        logging.warning(f"Fatal Scoring Error: UUID {s['uuid']} missed. Applying worst-case penalty.")
                        dummy_score = s.copy()
                        dummy_score['score_results'] = {'meta_parse_failed': True}
                        final_scored_list.append(dummy_score)
                
                if final_scored_list:
                    all_results = [s.get('score_results', {}) for s in final_scored_list]
                    calculator = MetricCalculator(self.config.get('metrics', {}))
                    aggregated_scores = calculator.aggregate(all_results)
                    
                    summary = {
                        "model": model_name,
                        "dataset": db_name,
                        "num_samples": len(final_scored_list),  # 这里的长度现在永远等于花名册全长！
                        "scores": aggregated_scores
                    }
                    logging.info(f"Evaluation Summary: {summary}")

                    summary_path = os.path.join(self.output_dir, f"score_{timestamp}.jsonl")
                    with open(summary_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(summary, ensure_ascii=False) + '\n')
                else:
                    logging.warning(f"No scores available for {model_name} on {db_name}.")