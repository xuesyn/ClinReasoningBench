from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import REFERENCE_DIR


@dataclass(frozen=True)
class ReferenceBundle:
    reference_id: str
    label: str
    directory: Path
    graph_path: Path
    guidance_path: Path


def _find_unique_file(directory: Path, suffix: str) -> Path | None:
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == suffix)
    if len(files) != 1:
        return None
    return files[0]


@lru_cache(maxsize=1)
def list_reference_bundles() -> list[ReferenceBundle]:
    bundles: list[ReferenceBundle] = []
    if not REFERENCE_DIR.exists():
        return bundles

    for entry in sorted(p for p in REFERENCE_DIR.iterdir() if p.is_dir()):
        graph_path = _find_unique_file(entry, ".json")
        guidance_path = _find_unique_file(entry, ".jsonl")
        if graph_path is None or guidance_path is None:
            continue

        bundles.append(
            ReferenceBundle(
                reference_id=entry.name,
                label=entry.name.upper(),
                directory=entry,
                graph_path=graph_path,
                guidance_path=guidance_path,
            )
        )

    return bundles


def get_reference_bundle(reference_id: str) -> ReferenceBundle:
    for bundle in list_reference_bundles():
        if bundle.reference_id == reference_id:
            return bundle
    raise KeyError(f"Unknown reference: {reference_id}")


def serialize_reference_bundle(bundle: ReferenceBundle) -> dict[str, Any]:
    return {
        "reference_id": bundle.reference_id,
        "label": bundle.label,
        "graph_file": bundle.graph_path.name,
        "guidance_file": bundle.guidance_path.name,
    }


@lru_cache(maxsize=16)
def load_graph_meta(reference_id: str) -> list[dict[str, Any]]:
    bundle = get_reference_bundle(reference_id)
    with bundle.graph_path.open("r", encoding="utf-8") as f:
        graph = json.load(f)
    return graph.get("nodes", [])


@lru_cache(maxsize=16)
def load_graph_json(reference_id: str) -> dict[str, Any]:
    bundle = get_reference_bundle(reference_id)
    with bundle.graph_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=16)
def load_guidance_map(reference_id: str) -> dict[str, dict[str, Any]]:
    bundle = get_reference_bundle(reference_id)
    data: dict[str, dict[str, Any]] = {}
    with bundle.guidance_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_id = item.get("id")
            if item_id:
                data[item_id] = item
    return data


@lru_cache(maxsize=16)
def load_guidance_items(reference_id: str) -> list[dict[str, Any]]:
    items = list(load_guidance_map(reference_id).values())
    items.sort(key=lambda item: str(item.get("id", "")))
    return items
