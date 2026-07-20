from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.data_service import (
    close_session,
    create_session,
    get_prediction_text,
    get_prompt,
    get_session,
    list_data_files,
    normalize_prediction_thinking,
    parse_prediction_payload,
)
from app.services.graph_service import annotate_subgraph_matches, build_graph_payload
from app.services.gt_service import get_thinking_tag
from app.services.reference_service import get_reference_bundle


router = APIRouter(prefix="/api", tags=["data"])


class OpenDataSessionRequest(BaseModel):
    reference_id: str
    data_filename: str


@router.get("/data/options")
def data_options() -> dict[str, Any]:
    return {"items": [{"filename": path.name} for path in list_data_files()]}


@router.post("/data/session/open")
def open_data_session(req: OpenDataSessionRequest) -> dict[str, Any]:
    try:
        get_reference_bundle(req.reference_id)
        session = create_session(req.reference_id, req.data_filename)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "session_id": session.session_id,
        "reference_id": session.reference_id,
        "data_filename": session.data_file.name,
        "total": session.total,
    }


@router.delete("/data/session/{session_id}")
def close_data_session(session_id: str) -> dict[str, Any]:
    try:
        close_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/data/session/{session_id}/record")
def get_data_record(
    session_id: str,
    pos: int = Query(1, ge=1),
) -> dict[str, Any]:
    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    valid_records = [record for record in session.records if not record.get("__parse_error")]
    if not valid_records:
        raise HTTPException(status_code=404, detail="No usable entries in the data file.")

    pos = min(pos, len(valid_records))
    raw_record = valid_records[pos - 1]
    raw_index = session.records.index(raw_record) + 1

    original_data = raw_record.get("metadata", {}).get("original_data", {})
    gt_thinking_tag = get_thinking_tag(original_data)
    gt_has_conflict, gt_violations, gt_subgraph = build_graph_payload(session.reference_id, gt_thinking_tag)

    prediction_text = get_prediction_text(raw_record)
    prediction_parsed = parse_prediction_payload(prediction_text)
    prediction_thinking = normalize_prediction_thinking(prediction_parsed.get("thinking", ""))
    pred_has_conflict, pred_violations, pred_subgraph = build_graph_payload(session.reference_id, prediction_thinking)
    gt_subgraph, pred_subgraph, matched_keys = annotate_subgraph_matches(
        session.reference_id,
        gt_subgraph,
        pred_subgraph,
    )

    return {
        "session_id": session.session_id,
        "reference_id": session.reference_id,
        "data_filename": session.data_file.name,
        "total": session.total,
        "pos": pos,
        "raw_index": raw_index,
        "uuid": raw_record.get("uuid"),
        "record": raw_record,
        "prompt": get_prompt(raw_record),
        "prediction_text": prediction_text,
        "prediction_parsed": prediction_parsed,
        "prediction_thinking": prediction_thinking,
        "gt_thinking_tag": gt_thinking_tag,
        "gt_has_conflict": gt_has_conflict,
        "gt_violations": gt_violations,
        "gt_subgraph": gt_subgraph,
        "gt_knowledge_map": raw_record.get("metadata", {}).get("gt_knowledge_map", {}),
        "pred_has_conflict": pred_has_conflict,
        "pred_violations": pred_violations,
        "pred_subgraph": pred_subgraph,
        "matched_keys": matched_keys,
        "score_results": raw_record.get("score_results", {}),
    }


@router.get("/data/session/{session_id}/random")
def random_data_record(session_id: str) -> dict[str, Any]:
    import random

    try:
        session = get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    valid_count = len([record for record in session.records if not record.get("__parse_error")])
    if valid_count == 0:
        raise HTTPException(status_code=404, detail="No usable entries in the data file.")

    picked = random.randint(1, valid_count)
    return get_data_record(session_id=session_id, pos=picked)
