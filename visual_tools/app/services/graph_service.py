from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config import ROOT_DIR

mpl_cache_dir = ROOT_DIR / ".mpl-cache"
mpl_cache_dir.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache_dir))

from app.graph_tool_v3 import graph_tools
from app.services.reference_service import get_reference_bundle, load_guidance_map


@dataclass
class GraphRuntime:
    reference_id: str
    gt: graph_tools


@lru_cache(maxsize=16)
def get_graph_runtime(reference_id: str) -> GraphRuntime:
    bundle = get_reference_bundle(reference_id)
    return GraphRuntime(reference_id=reference_id, gt=graph_tools(graph_path=str(bundle.graph_path)))


def build_graph_payload(reference_id: str, thinking_tag_text: str) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    runtime = get_graph_runtime(reference_id)
    text = thinking_tag_text or ""
    has_conflict, violations = runtime.gt.check_gt(text=text)
    subgraph = runtime.gt.build_subgraph(text=text)
    return bool(has_conflict), violations, subgraph


def _normalize_node_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        normalized_items = [_normalize_node_value(item) for item in value]
        return tuple(sorted(normalized_items, key=lambda item: str(item)))
    return value


def _values_match(left: Any, right: Any) -> bool:
    return _normalize_node_value(left) == _normalize_node_value(right)


def _treatment_values_overlap(left: Any, right: Any) -> bool:
    def as_set(value: Any) -> set[Any]:
        normalized = _normalize_node_value(value)
        if isinstance(normalized, tuple):
            return {item for item in normalized}
        return {normalized}

    return bool(as_set(left) & as_set(right))


def _copy_subgraph(subgraph: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": [dict(node) for node in subgraph.get("nodes", [])],
        "routes": [dict(route) for route in subgraph.get("routes", [])],
    }


def annotate_subgraph_matches(
    reference_id: str,
    gt_subgraph: dict[str, Any],
    pred_subgraph: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    runtime = get_graph_runtime(reference_id)
    gt_graph = _copy_subgraph(gt_subgraph)
    pred_graph = _copy_subgraph(pred_subgraph)

    gt_nodes_by_key = {node.get("key"): node for node in gt_graph.get("nodes", []) if node.get("key")}
    pred_nodes_by_key = {node.get("key"): node for node in pred_graph.get("nodes", []) if node.get("key")}

    exact_match_keys: set[str] = set()
    wrong_value_keys: set[str] = set()

    for key, gt_node in gt_nodes_by_key.items():
        pred_node = pred_nodes_by_key.get(key)
        if not pred_node:
            continue
        if key == "treatment":
            is_match = _treatment_values_overlap(gt_node.get("value"), pred_node.get("value"))
        else:
            is_match = _values_match(gt_node.get("value"), pred_node.get("value"))
        if is_match:
            exact_match_keys.add(key)
        else:
            wrong_value_keys.add(key)

    blocked_keys: set[str] = set()
    for wrong_key in wrong_value_keys:
        descendants = runtime.gt.get_descendants(graph_input=gt_graph, key=wrong_key)
        blocked_keys.update(
            node.get("key")
            for node in descendants
            if node.get("key")
        )

    matched_keys = exact_match_keys - blocked_keys

    for node in gt_graph.get("nodes", []):
        node["matched"] = bool(node.get("key") in matched_keys)
    for node in pred_graph.get("nodes", []):
        node["matched"] = bool(node.get("key") in matched_keys)

    return gt_graph, pred_graph, sorted(matched_keys)


def get_guidance_detail(reference_id: str, guidance_id: str) -> dict[str, Any] | None:
    return load_guidance_map(reference_id).get(guidance_id)
