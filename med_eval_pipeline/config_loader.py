import os
import re
import yaml
import logging
from typing import Dict, Any, List

from .disease_registry import get_disease_config

logger = logging.getLogger(__name__)


def resolve_env_vars(value):
    if isinstance(value, str):
        def _replace(m):
            var_name = m.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                logger.warning(f"Environment variable ${{{var_name}}} is not set")
                return m.group(0)
            return env_val
        return re.sub(r'\$\{([^}]+)\}', _replace, value)
    elif isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_env_vars(item) for item in value]
    return value


def detect_config_format(config: dict) -> str:
    if "experiments" in config:
        return "batch"
    if "experiment_name" in config and "models" in config and "datasets" in config:
        return "legacy"
    raise ValueError("Unrecognized config format: expected 'experiments' (batch) or 'experiment_name'+'models'+'datasets' (legacy)")


def load_config(config_path: str) -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    if not config:
        raise ValueError(f"Empty config file: {config_path}")
    return config


def expand_experiments(raw_config: dict, project_root: str = ".") -> List[Dict[str, Any]]:
    default_api = raw_config.get("default_api_settings", {})
    models_def = raw_config.get("models", {})
    eval_params = raw_config.get("evaluation_params", {})
    itt_conf = raw_config.get("itt", {})
    output_base = raw_config.get("output_base_dir", "outputs")

    experiments = []
    for exp_def in raw_config.get("experiments", []):
        disease_key = exp_def["disease"]
        disease_cfg = get_disease_config(disease_key)
        task = exp_def["task"]
        version = exp_def.get("version", "v0")
        gt_paths = exp_def.get("gt_paths", [])

        if "survival" in task:
            task_for_pipeline = "survival"
            metrics = dict(disease_cfg.survival_metrics)
            prompt_template = disease_cfg.survival_prompt_template
        else:
            task_for_pipeline = "treatment"
            metrics = dict(disease_cfg.treatment_metrics)
            prompt_template = disease_cfg.treatment_prompt_template

        for model_name in exp_def.get("models", []):
            if model_name not in models_def:
                logger.warning(f"Model '{model_name}' not found in models definition, skipping")
                continue

            model_conf = dict(default_api)
            model_conf.update(models_def[model_name])
            model_conf = resolve_env_vars(model_conf)

            name_tpl = exp_def.get(
                "experiment_name_template",
                "{disease}_eval_exp_{version}_{model}_{task}"
            )
            exp_name = name_tpl.format(
                disease=disease_key, version=version,
                model=model_name, task=task.replace("_", "_")
            )

            dataset_key = f"{disease_key.upper()}_v1"
            dataset_conf = {
                "gt_path": gt_paths,
                "graph_def_path": disease_cfg.graph_def_path,
                "prompt_template_path": prompt_template,
                "reference_guideline_name": disease_cfg.reference_guideline_name,
                "task": task_for_pipeline,
            }

            if exp_def.get("reference_map_path"):
                dataset_conf["reference_map_path"] = exp_def["reference_map_path"]

            if itt_conf.get("enabled"):
                base_dir = itt_conf.get("union_meta_base_dir", "")
                union_path = os.path.join(base_dir, f"{disease_key}_unfiltered_full_meta.jsonl")
                dataset_conf["union_meta_path"] = union_path

            single_config = {
                "experiment_name": exp_name,
                "output_dir": output_base,
                "models": {model_name: model_conf},
                "datasets": {dataset_key: dataset_conf},
                "evaluation_params": dict(eval_params),
                "metrics": metrics,
                "_disease_key": disease_key,
                "_task_variant": task,
                "_treatment_source_experiment": (
                    exp_def.get("treatment_source_experiments", {}).get(model_name)
                ),
                "_project_root": project_root,
            }

            local_eval_overrides = exp_def.get("evaluation_params", {})
            if local_eval_overrides:
                single_config["evaluation_params"].update(local_eval_overrides)

            experiments.append(single_config)

    return experiments


def legacy_config_to_single(config: dict) -> List[Dict[str, Any]]:
    return [config]
