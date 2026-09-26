import json

from fastapi import APIRouter, HTTPException

from llm import worker

from . import data_access, store
from .schemas import (
    ApprovalRequest,
    DispatchDraft,
    ExplanationOut,
    ForecastOut,
    ProjectScore,
    TriggerResult,
    WorkerRun,
)

router = APIRouter(prefix="/api")


@router.get("/model-scores", response_model=list[ProjectScore])
def get_model_scores():
    """One-shot bulk export of every project's live model score, so the
    frontend can overlay real risk onto the existing dashboard instead of
    the heuristic composite score."""
    df = data_access.load_latest_features()
    out = []
    for _, row in df.iterrows():
        shap = json.loads(row.get("shap_top5_json") or "[]")
        out.append(
            ProjectScore(
                project_id=str(row["project_id"]),
                slip_probability=float(row["slip_probability"]),
                model_version=str(row.get("model_version") or ""),
                shap=shap,
            )
        )
    return out


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


@router.get("/projects/{project_id}/forecast", response_model=ForecastOut)
def get_forecast(project_id: str):
    row = data_access.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return ForecastOut(
        project_id=project_id,
        slip_probability=row["slip_probability"],
        risk_exposure_cr=row["risk_exposure_cr"],
        model_version=row["model_version"],
    )


@router.get("/projects/{project_id}/explanations", response_model=ExplanationOut)
def get_explanations(project_id: str):
    row = data_access.get_project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    shap = json.loads(row.get("shap_top5_json") or "[]")
    return ExplanationOut(project_id=project_id, shap=shap)


@router.post("/worker-runs/trigger", response_model=TriggerResult)
def trigger_worker_cycle():
    return worker.run_worker_cycle()
