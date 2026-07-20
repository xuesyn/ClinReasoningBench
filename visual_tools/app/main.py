from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.data import router as data_router
from app.api.gt import router as gt_router
from app.api.results import router as results_router
from app.config import FRONTEND_DIR


app = FastAPI(title="ClinReasoningBench Visualizer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(data_router)
app.include_router(gt_router)
app.include_router(results_router)

assets_dir = FRONTEND_DIR / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


def _frontend_file(*parts: str) -> Path:
    return FRONTEND_DIR.joinpath(*parts)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(_frontend_file("index.html"))


@app.get("/gt")
def gt_page() -> FileResponse:
    return FileResponse(_frontend_file("gt", "index.html"))


@app.get("/reference")
def reference_page() -> FileResponse:
    return FileResponse(_frontend_file("reference", "index.html"))


@app.get("/data")
def data_page() -> FileResponse:
    return FileResponse(_frontend_file("data", "index.html"))


@app.get("/results")
def results_page() -> FileResponse:
    return FileResponse(_frontend_file("results", "index.html"))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=2028, reload=True)
