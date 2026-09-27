from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from llm import worker

from . import serving, store
from .schemas import (
    ApprovalRequest,
    DispatchDraft,
    ExternalSummary,
    Flag,
    Forecast,
    Meta,
    ModelsOut,
    Portfolio,
    ProjectDetail,
    ProjectPage,
    Sort,
    Tier,
    Timeline,
    TriggerResult,
    WorkerRun,
)

router = APIRouter(prefix="/api")


def _key(key: str) -> str:
    k = serving.canonical(key)
    if k is None:
        raise HTTPException(status_code=404, detail=f"project {key} not found")
    return k


# ---------- read side (DuckDB over Parquet) ----------

@router.get("/meta", response_model=Meta)
def get_meta():
    return serving.meta()


@router.get("/portfolio", response_model=Portfolio)
def get_portfolio(ministry: str | None = None, sector: str | None = None, state: str | None = None,
                  tier: Tier | None = None):
    return serving.portfolio(ministry, sector, state, tier)


@router.get("/projects", response_model=ProjectPage)
def get_projects(q: str | None = Query(None, max_length=100), ministry: str | None = None,
                 sector: str | None = None, state: str | None = None, tier: Tier | None = None,
                 flag: Flag | None = None, sort: Sort = "risk", order: Literal["asc", "desc"] | None = None,
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100)):
    return serving.projects(q, ministry, sector, state, tier, flag, sort, order, page, size)


@router.get("/projects/{key}", response_model=ProjectDetail)
def get_project(key: str):
    return serving.project(_key(key))


@router.get("/projects/{key}/timeline", response_model=Timeline)
def get_timeline(key: str):
    k = _key(key)
    return {"key": k, "points": serving.timeline(k)}


@router.get("/projects/{key}/forecast", response_model=Forecast)
def get_forecast(key: str):
    out = serving.forecast(_key(key))
    if out is None:
        raise HTTPException(status_code=404, detail=f"project {key} is not in the current scored portfolio")
    return out


@router.get("/external/summary", response_model=ExternalSummary)
def get_external_summary():
    return serving.external_summary()


@router.get("/models", response_model=ModelsOut)
def get_models():
    return serving.models()


# ---------- worker cell (JSON store) ----------

@router.get("/worker-runs", response_model=list[WorkerRun])
def get_worker_runs():
    runs = store.load_worker_runs()
    return sorted(runs, key=lambda r: r["timestamp"], reverse=True)


@router.get("/dispatch", response_model=list[DispatchDraft])
def get_dispatch():
    return store.load_dispatch_drafts()


@router.post("/approvals", response_model=DispatchDraft)
def post_approval(body: ApprovalRequest):
    updated = store.update_dispatch_draft(body.draft_id, body.decision)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"dispatch draft {body.draft_id} not found")
    return updated


@router.post("/worker-runs/trigger", response_model=TriggerResult)
def trigger_worker_cycle():
    return worker.run_worker_cycle()
