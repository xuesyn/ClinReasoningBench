from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.results_service import get_results_dashboard


router = APIRouter(prefix="/api", tags=["results"])


@router.get("/results/dashboard")
def results_dashboard() -> dict[str, Any]:
    try:
        return get_results_dashboard()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
