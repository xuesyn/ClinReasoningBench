import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from .graph_tool import GraphTool
import re

class DataProcessor:
    def __init__(self, gt_path: str, graph_def_path: str, reference_map_path: str = None, prompt_template_path: str = None, reference_guideline_name: str = None, task: str = None):
        if isinstance(gt_path, str):
            self.gt_paths = [gt_path]
        else:
            self.gt_paths = gt_path
        self.graph_tool = GraphTool(graph_def_path)
        self.graph_kv_instruction = self.graph_tool.build_kv_instruction()
        self.rules = self.graph_tool.get_rules_description()
        self.gt_data = []
        self.task = task
        for path in self.gt_paths:
            logging.info(f"Loading data from: {path}")
            self.gt_data.extend(self._load_jsonl(path))
        logging.info(f"Total loaded samples: {len(self.gt_data)}")
        self.prompt_template = "{INPUT_DATA}"
        if prompt_template_path and os.path.exists(prompt_template_path):
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                self.prompt_template = f.read()
        if reference_map_path:
            self.reference_map = self._load_jsonl(reference_map_path)
            self.ref_map_dict = [{
                'id': item['id'],
                'condition': item['condition'],
            } for item in self.reference_map]
        else:
            self.ref_map_dict = []
        if reference_guideline_name:
            self.reference_guideline_name = reference_guideline_name
        else:
            self.reference_guideline_name = ""

    def _load_jsonl(self, file_path: str):
        data = []
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return data
        # with open(file_path, 'r', encoding='utf-8') as f:
        #     return [json.loads(line) for line in f]

    def _process_single(self, sample: dict):
        """
        处理单条数据：提取 question, answer, 并生成子图
        """
        try:
            # 你需要根据你的 gt.jsonl 格式来定义如何提取 question 和 answer
            # 这里假设 gt.jsonl 每行是一个字典，包含 "prompt" 和 "response"
            basic_info = sample.get("emr", "")
            answer = sample.get("thinking_tag", "")
            treatment = sample["meta_data"]["seer_data"].get("predicted_treatment", "None")

            if self.task == "survival":
                question = question = self.prompt_template.replace("{TREATMENT}", str(treatment)).replace("{INPUT_DATA}", str(basic_info))
            else:
                if self.ref_map_dict:
                    question = self.prompt_template.replace("{REFERENCE_TREE}", str(self.graph_kv_instruction)).replace("{REFERENCE_RULE}", str(self.rules)).replace("{REFERENCE_INDEX}", str(self.ref_map_dict)).replace("{INPUT_DATA}", str(basic_info))
                else:
                    question = self.prompt_template.replace("{REFERENCE_TREE}", str(self.graph_kv_instruction)).replace("{REFERENCE_RULE}", str(self.rules)).replace("{REFERENCE_NAME}", str(self.reference_guideline_name)).replace("{INPUT_DATA}", str(basic_info))
            subgraph = self.graph_tool.build_subgraph(answer)

            processed_sample = {
                "uuid": sample.get("uuid"),
                "conversations": [
                    {"role": "user", "text": question},
                    {"role": "assistant", "text": answer}
                ],
                "metadata": {
                    "category": sample.get("category", "default"),
                    "gt_knowledge_map": subgraph,
                    "scores": sample.get("scores", {}),
                    "original_data": sample # 保留原始数据
                }
            }
            return processed_sample
        except Exception as e:
            logging.error(f"Error processing sample {sample.get('uuid')}: {e}")
            return None


    def process_and_save(self, output_path: str, num_workers: int = 8):
        # 1. 检查已处理的数据
        existing_uuids = set()
        invalid_count = 0
        
        if os.path.exists(output_path):
            logging.info(f"Checking existing meta file: {output_path}")
            with open(output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        if 'uuid' in item:
                            # --- 关键修改：增加有效性校验 ---
                            existing_uuids.add(item['uuid'])
                    except json.JSONDecodeError:
                        pass
            
            logging.info(f"Found {len(existing_uuids)} valid samples.")

        # 2. 过滤掉已处理的数据
        to_process = [s for s in self.gt_data if s.get('uuid') not in existing_uuids]
        
        if not to_process:
            logging.info(f"All data in {self.gt_paths} already processed.")
            return

        logging.info(f"Processing {len(to_process)} new samples...")
        
        # 3. 并行处理
        processed_data = []
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(self._process_single, sample) for sample in to_process]
            for future in tqdm(as_completed(futures), total=len(to_process), desc="Processing GT data"):
                result = future.result()
                if result:
                    processed_data.append(result)

        # 4. 追加写入文件
        with open(output_path, 'a', encoding='utf-8') as f:
            for item in processed_data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        logging.info(f"Appended {len(processed_data)} samples to {output_path}")
        # processed_data = []
        # with ThreadPoolExecutor(max_workers=num_workers) as executor:
        #     futures = [executor.submit(self._process_single, sample) for sample in self.gt_data]
        #     for future in tqdm(as_completed(futures), total=len(self.gt_data), desc="Processing GT data"):
        #         result = future.result()
        #         if result:
        #             processed_data.append(result)

        # with open(output_path, 'w', encoding='utf-8') as f:
        #     for item in processed_data:
        #         f.write(json.dumps(item, ensure_ascii=False) + '\n')
