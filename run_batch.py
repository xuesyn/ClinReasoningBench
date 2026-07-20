"""
Unified batch evaluation runner for HCC-ClinReasoningBench.

Usage:
  python run_batch.py -c configs/batch_all.yaml [-p 3] [--skip-inference] [--rescore]
  python run_batch.py -c configs/eval_config_bclc.yaml   # Also works with legacy single-experiment configs
"""

import argparse
import os
import sys
import glob
import logging
import yaml
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from med_eval_pipeline.config_loader import (
    load_config, detect_config_format, expand_experiments, legacy_config_to_single
)
from med_eval_pipeline.data_processor import DataProcessor
from med_eval_pipeline.evaluator import Evaluator
from med_eval_pipeline.treatment_labeler import TreatmentLabeler
from med_eval_pipeline.disease_registry import get_disease_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def resolve_path(relative_path: str) -> str:
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(PROJECT_ROOT, relative_path)


def backup_score_files(output_dir: str):
    score_files = glob.glob(os.path.join(output_dir, "*@scores.jsonl"))
    for score_file in score_files:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{score_file}.{timestamp}.bak"
        try:
            os.rename(score_file, new_name)
            logger.info(f"Backed up existing score file: {os.path.basename(new_name)}")
        except Exception as e:
            logger.error(f"Failed to backup score file {score_file}: {e}")


def run_single_experiment(config: dict, rescore: bool = False):
    exp_name = config.get('experiment_name', 'default_exp')
    output_dir = os.path.join(
        resolve_path(config.get('output_dir', 'outputs')),
        exp_name
    )
    os.makedirs(output_dir, exist_ok=True)
    config['output_dir'] = output_dir

    task_variant = config.get('_task_variant', '')
    disease_key = config.get('_disease_key', '')

    logger.info(f"=== Experiment: {exp_name} ===")
    logger.info(f"    Output: {output_dir}")
    if task_variant:
        logger.info(f"    Task variant: {task_variant}")

    if rescore:
        backup_score_files(output_dir)

    # Step 0: Survival data preparation (automatic treatment labeling)
    if task_variant in ('survival_gt', 'survival_model') and disease_key:
        labeler = TreatmentLabeler(disease_key)
        labeled_dir = os.path.join(output_dir, "_labeled_data")

        for db_name, db_config in config['datasets'].items():
            gt_paths = db_config.get('gt_path', [])
            if isinstance(gt_paths, str):
                gt_paths = [gt_paths]
            gt_paths = [resolve_path(p) for p in gt_paths]

            if task_variant == 'survival_gt':
                excel_path = config.get('gt_treatment_excel_path')
                if excel_path:
                    excel_path = resolve_path(excel_path)
                labeled_paths = labeler.label_gt_treatment(
                    gt_paths, labeled_dir, excel_path=excel_path
                )
                db_config['gt_path'] = labeled_paths
                logger.info(f"    GT treatment labeled: {len(labeled_paths)} files")

            elif task_variant == 'survival_model':
                source_exp = config.get('_treatment_source_experiment')
                if source_exp:
                    model_name = list(config['models'].keys())[0]
                    source_output = resolve_path(
                        os.path.join(config.get('output_dir', 'outputs'), '..', source_exp)
                    )
                    scores_files = glob.glob(
                        os.path.join(source_output, f"*{model_name}@scores.jsonl")
                    )
                    if scores_files:
                        disease_cfg = get_disease_config(disease_key)
                        labeled_paths = labeler.label_model_treatment(
                            gt_paths, scores_files[0], labeled_dir,
                            treatment_type=disease_cfg.model_treatment_type
                        )
                        db_config['gt_path'] = labeled_paths
                        logger.info(f"    Model treatment labeled: {len(labeled_paths)} files")
                    else:
                        logger.warning(f"    No scores file found for source experiment: {source_exp}")
                else:
                    logger.warning("    No treatment_source_experiment specified for survival_model task")

    for db_name, db_config in config['datasets'].items():
        gt_path = db_config.get('gt_path')
        if isinstance(gt_path, list):
            db_config['gt_path'] = [resolve_path(p) for p in gt_path]
        elif isinstance(gt_path, str):
            db_config['gt_path'] = resolve_path(gt_path)

        for path_key in ['graph_def_path', 'prompt_template_path', 'reference_map_path', 'union_meta_path']:
            if path_key in db_config and db_config[path_key]:
                db_config[path_key] = resolve_path(db_config[path_key])

        processor = DataProcessor(
            gt_path=db_config['gt_path'],
            graph_def_path=db_config['graph_def_path'],
            reference_map_path=db_config.get('reference_map_path'),
            prompt_template_path=db_config.get('prompt_template_path'),
            reference_guideline_name=db_config.get('reference_guideline_name'),
            task=db_config.get('task')
        )
        meta_path = os.path.join(output_dir, f"{db_name}_meta.jsonl")
        processor.process_and_save(meta_path)
        db_config['meta_path'] = meta_path

    for name, model_conf in config.get('models', {}).items():
        if 'model_local_path' in model_conf:
            model_conf['model_local_path'] = resolve_path(model_conf['model_local_path'])

    metrics_conf = config.get('metrics', {})
    for metric_name, metric_params in metrics_conf.items():
        if isinstance(metric_params, dict):
            for path_key in ['knowledge_db_path', 'model_local_path']:
                if path_key in metric_params and metric_params[path_key]:
                    metric_params[path_key] = resolve_path(metric_params[path_key])

    evaluator = Evaluator(config)
    evaluator.run()
    logger.info(f"=== Completed: {exp_name} ===")


def main():
    parser = argparse.ArgumentParser(
        description="HCC-ClinReasoningBench Unified Batch Evaluation Runner"
    )
    parser.add_argument('--config', '-c', required=True,
                        help="Path to YAML config (batch or legacy format)")
    parser.add_argument('--parallel', '-p', type=int, default=1,
                        help="Max parallel experiments (default: 1)")
    parser.add_argument('--skip-inference', action='store_true',
                        help="Skip inference, only run scoring on existing results")
    parser.add_argument('--rescore', action='store_true',
                        help="Backup existing scores and re-score from inference")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    raw_config = load_config(args.config)
    fmt = detect_config_format(raw_config)

    if fmt == "batch":
        experiment_configs = expand_experiments(raw_config, project_root=PROJECT_ROOT)
        logger.info(f"Batch config detected: {len(experiment_configs)} experiments to run")
    else:
        experiment_configs = legacy_config_to_single(raw_config)
        logger.info("Legacy config detected: 1 experiment")

    for cfg in experiment_configs:
        if args.skip_inference:
            cfg.setdefault('evaluation_params', {})['skip_inference'] = True

    if not experiment_configs:
        logger.warning("No experiments to run.")
        return

    if args.parallel > 1 and len(experiment_configs) > 1:
        logger.info(f"Running {len(experiment_configs)} experiments with {args.parallel} workers")
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(run_single_experiment, cfg, args.rescore): cfg.get('experiment_name', '?')
                for cfg in experiment_configs
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Experiment '{name}' failed: {e}")
    else:
        for cfg in experiment_configs:
            try:
                run_single_experiment(cfg, rescore=args.rescore)
            except Exception as e:
                logger.error(f"Experiment '{cfg.get('experiment_name', '?')}' failed: {e}")


if __name__ == "__main__":
    main()
