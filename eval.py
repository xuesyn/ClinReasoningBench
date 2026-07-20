import yaml
import argparse
import os
import logging

from med_eval_pipeline.data_processor import DataProcessor
from med_eval_pipeline.evaluator import Evaluator

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(description="Medical Text Decision Making Evaluation Pipeline")
    parser.add_argument('--config', '-c', type=str, default='configs/eval_config.yaml',
                        help="Path to the YAML config file.")
    args = parser.parse_args()

    # 1. 加载配置
    logging.info(f"Loading configuration from: {args.config}")
    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 创建输出目录
    exp_name = config.get('experiment_name', 'default_exp')
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # output_dir = os.path.join(config.get('output_dir', 'outputs'), f"{exp_name}_{timestamp}")
    output_dir = os.path.join(config.get('output_dir', 'outputs'), f"{exp_name}")
    os.makedirs(output_dir, exist_ok=True)
    config['output_dir'] = output_dir
    logging.info(f"Output will be saved to: {output_dir}")

    # 2. 数据预处理：生成 meta.jsonl
    # 遍历所有数据集配置，为其生成处理后的 meta 文件
    for db_name, db_config in config['datasets'].items():
        logging.info(f"Processing dataset: {db_name}")
        processor = DataProcessor(
            gt_path=db_config['gt_path'],
            graph_def_path=db_config['graph_def_path'],
            reference_map_path=db_config.get('reference_map_path', None),
            prompt_template_path=db_config.get('prompt_template_path', None),
            reference_guideline_name=db_config.get('reference_guideline_name', None),
            task=db_config.get('task', None)
        )
        meta_path = os.path.join(output_dir, f"{db_name}_meta.jsonl")
        processor.process_and_save(meta_path)
        db_config['meta_path'] = meta_path # 将处理好的文件路径更新回配置中
        logging.info(f"Processed meta file saved to: {meta_path}")

    # 3. 运行评测
    evaluator = Evaluator(config)
    logging.info("Starting evaluation...")
    evaluator.run()
    logging.info("Evaluation finished.")

if __name__ == "__main__":
    main()
