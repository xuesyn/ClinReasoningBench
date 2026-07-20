from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.graph_service import build_graph_payload, get_guidance_detail
from app.services.gt_service import (
    close_session,
    create_session,
    filtered_indices,
    get_auto_check,
    get_comment,
    get_manual_check,
    get_session,
    get_thinking,
    get_thinking_tag,
    list_ground_truth_files,
    parse_auto,
    parse_manual,
)
from app.services.reference_service import (
    get_reference_bundle,
    load_graph_json,
    list_reference_bundles,
    load_guidance_items,
    load_graph_meta,
    serialize_reference_bundle,
)


router = APIRouter(prefix="/api", tags=["gt"])


class OpenSessionRequest(BaseModel):
    reference_id: str
    gt_filename: str


def _build_record_response(session_id: str, raw_index: int, filtered_total: int, pos: int) -> dict[str, Any]:
    session = get_session(session_id)
    record = session.records[raw_index - 1]
    thinking_tag = get_thinking_tag(record)
    has_conflict, violations, subgraph = build_graph_payload(session.reference_id, thinking_tag)

    return {
        "session_id": session.session_id,
        "reference_id": session.reference_id,
        "gt_filename": session.gt_file.name,
        "total": session.total,
        "filtered_total": filtered_total,
        "pos": pos,
        "raw_index": raw_index,
        "uuid": record.get("uuid"),
        "record": record,
        "thinking": get_thinking(record),
        "thinking_tag": thinking_tag,
        "auto_check_pass": parse_auto(get_auto_check(record)),
        "manual_check": parse_manual(get_manual_check(record)),
        "comment": get_comment(record),
        "has_conflict": has_conflict,
        "violations": violations,
        "subgraph": subgraph,
    }


@router.get("/reference/options")
def reference_options() -> dict[str, Any]:
    return {"items": [serialize_reference_bundle(bundle) for bundle in list_reference_bundles()]}


@router.get("/ground-truth/options")
def ground_truth_options() -> dict[str, Any]:
    return {
        "items": [
            {"filename": path.name}
            for path in list_ground_truth_files()
        ]
    }


@router.get("/reference/{reference_id}/graph-meta")
def reference_graph_meta(reference_id: str) -> dict[str, Any]:
    try:
        get_reference_bundle(reference_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"reference_id": reference_id, "nodes": load_graph_meta(reference_id)}


@router.get("/reference/{reference_id}/bundle")
def reference_bundle(reference_id: str) -> dict[str, Any]:
    try:
        bundle = get_reference_bundle(reference_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    graph = load_graph_json(reference_id)
    return {
        "reference_id": reference_id,
        "graph_file": bundle.graph_path.name,
        "guidance_file": bundle.guidance_path.name,
        "graph": graph,
        "guidance_items": load_guidance_items(reference_id),
    }


@router.get("/reference/{reference_id}/guidance/{guidance_id}")
def reference_guidance(reference_id: str, guidance_id: str) -> dict[str, Any]:
    try:
        get_reference_bundle(reference_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    detail = get_guidance_detail(reference_id, guidance_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No content found for this reference id")
    return detail


@router.post("/gt/session/open")
def gt_open_session(req: OpenSessionRequest) -> dict[str, Any]:
    try:
        get_reference_bundle(req.reference_id)
        session = create_session(req.reference_id, req.gt_filename)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "session_id": session.session_id,
        "reference_id": session.reference_id,
        "gt_filename": session.gt_file.name,
        "total": session.total,
    }


@router.delete("/gt/session/{session_id}")
def gt_close_session(session_id: str) -> dict[str, Any]:
    try:
        close_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/gt/session/{session_id}/record")
def gt_get_record(
    session_id: str,
    pos: int = Query(1, ge=1),
    auto: str = Query("all", pattern="^(all|0|1)$"),
    manual: str = Query("all", pattern="^(all|null|0|1|2|3)$"),
) -> dict[str, Any]:
    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    indices = filtered_indices(session, auto, manual)
    if not indices:
        raise HTTPException(status_code=404, detail="No entries match the current filters.")

    pos = min(pos, len(indices))
    raw_index = indices[pos - 1] + 1
    return _build_record_response(session_id, raw_index, len(indices), pos)


@router.get("/gt/session/{session_id}/random")
def gt_random_record(
    session_id: str,
    auto: str = Query("all", pattern="^(all|0|1)$"),
    manual: str = Query("all", pattern="^(all|null|0|1|2|3)$"),
) -> dict[str, Any]:
    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    indices = filtered_indices(session, auto, manual)
    if not indices:
        raise HTTPException(status_code=404, detail="No entries match the current filters.")

    picked = random.randrange(len(indices))
    raw_index = indices[picked] + 1
    return _build_record_response(session_id, raw_index, len(indices), picked + 1)
