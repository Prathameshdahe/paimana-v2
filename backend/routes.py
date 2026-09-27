from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from llm import worker

from . import db, serving, store
from .live import scheduler, scout, watcher
from .schemas import (
    Alert,
    AlertKind,
    AlertPage,
    ApprovalRequest,
    DispatchDraft,
    ExternalSummary,
    Flag,
    Forecast,
    Ingested,
    JobRun,
    JobStarted,
    LiveStatus,
    Meta,
    ModelsOut,
    Portfolio,
    ProjectDetail,
    ProjectPage,
    ProjectSignals,
    Role,
    RoleBody,
    SignalFeed,
    Sort,
    Tier,
    Timeline,
    TriggerResult,
    Watchlist,
    WatchRequest,
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


# ---------- app state (SQLite) ----------

@router.get("/alerts", response_model=AlertPage)
def get_alerts(since: datetime | None = None, kind: AlertKind | None = None, acked: bool | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100)):
    return db.alerts(since and since.isoformat(), kind, acked, page, size)


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
def post_alert_ack(alert_id: int, body: RoleBody):
    out = db.ack(alert_id, body.role)
    if out is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return out


@router.get("/watchlist", response_model=Watchlist)
def get_watchlist(role: Role):
    return db.watchlist(role)


@router.post("/watchlist", response_model=Watchlist)
def post_watchlist(body: WatchRequest):
    db.watch(body.role, _key(body.project_key))
    return db.watchlist(body.role)


@router.delete("/watchlist", response_model=Watchlist)
def delete_watchlist(role: Role, project_key: str = Query(max_length=32)):
    db.unwatch(role, serving.canonical(project_key) or project_key)
    return db.watchlist(role)


@router.get("/jobs", response_model=list[JobRun])
def get_jobs():
    return db.latest_jobs()


@router.post("/jobs/ingest", response_model=Ingested)
def post_ingest(file: UploadFile, role: Role | None = None):
    """Save a report into dataset/raw/inbox/; the watcher ingests it on its next run (or POST /api/jobs/watch)."""
    try:
        out = watcher.save_upload(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.audit(role, "jobs.ingest", out["saved_as"] or file.filename, out["sha256"])
    return out


@router.post("/jobs/watch", response_model=JobStarted)
def post_watch(background: BackgroundTasks, role: Role | None = None):
    """Run the inbox watcher now, in the background; the result shows in /api/jobs and the alert feed."""
    if watcher.busy():
        return {"started": False, "detail": "a watch run is already in progress"}
    n = len(watcher.pending())
    db.audit(role, "jobs.watch", "inbox", f"{n} pending")
    background.add_task(watcher.watch_once)
    return {"started": True, "detail": f"{n} inbox file(s) to ingest", "pending": n}


@router.post("/jobs/scout", response_model=JobStarted)
def post_scout(background: BackgroundTasks, project_key: str | None = Query(None, max_length=32),
               role: Role | None = None):
    """Scout one current project now (and return its counts), or start a batch run in the background."""
    if scout.busy():
        return {"started": False, "detail": "a scout run is already in progress"}
    if project_key:
        k = _key(project_key)
        if k not in scout.index()["projects"]:
            raise HTTPException(status_code=404, detail=f"project {project_key} is not in the current portfolio")
        db.audit(role, "jobs.scout", k)
        out = scout.run([k], pib=False)
        return {"started": not out.get("busy"), "detail": f"scouted {k}", "summary": out}
    keys = scout.batch_keys()
    db.audit(role, "jobs.scout", "batch", f"{len(keys)} projects")
    background.add_task(scout.run, keys)
    return {"started": True, "detail": f"scouting {len(keys)} projects in the background", "pending": len(keys)}


@router.get("/signals/feed", response_model=SignalFeed)
def get_signal_feed(since: datetime | None = None, category: str | None = Query(None, max_length=40),
                    state: str | None = Query(None, max_length=60), severity: int | None = Query(None, ge=1, le=3),
                    linked: bool | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100)):
    """External Evidence Radar: one page of signals (severity = at least) and the state heat."""
    return scout.feed(since and since.isoformat(), category, state, severity, linked, page, size)


@router.get("/live/status", response_model=LiveStatus)
def get_live_status():
    return scheduler.status()


@router.get("/stream")
async def get_stream(request: Request, after: int | None = Query(None, ge=0)):
    """Server-Sent Events: each new alert as `event: alert` (id = alert id, data = the alert JSON), a comment line
    every 15 s. Resumes after Last-Event-ID (EventSource sends it on reconnect) or ?after=, else from now."""
    last = request.headers.get("last-event-id")
    start = after if after is not None else int(last) if last and last.isdigit() else None
    return StreamingResponse(scheduler.alert_stream(start), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/projects/{key}/signals", response_model=ProjectSignals)
def get_project_signals(key: str):
    out = db.project_signals(_key(key))
    for s in out["items"]:
        s.update(scout.lead_time(out["key"], s["published_at"]))
    return out


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
    db.audit(body.role, f"dispatch.{body.decision}", body.draft_id)
    return updated


@router.post("/worker-runs/trigger", response_model=TriggerResult)
def trigger_worker_cycle():
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.audit(None, "worker.trigger", "worker_cycle")  # the trigger button sends no role yet
    try:
        out = worker.run_worker_cycle()
    except Exception as e:
        db.record_job("worker_cycle", started, "error", {"error": str(e)})
        raise
    db.record_job("worker_cycle", started, "ok", {"dispatch_drafts": len(out["dispatch_drafts"])})
    return out
