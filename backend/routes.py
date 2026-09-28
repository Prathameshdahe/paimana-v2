from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from llm import worker

from . import brief, db, serving, store
from .access import Viewer, in_scope, need, stream_viewer, viewer
from .live import portals, research, scheduler, scout, watcher
from .schemas import (
    AgencyMatrix,
    Alert,
    AlertKind,
    AlertPage,
    ApprovalRequest,
    BottleneckDetail,
    BottleneckPage,
    BriefOut,
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
    ProjectResearch,
    ProjectSignals,
    RadarSummary,
    ResearchSummary,
    Role,
    RoleBody,
    Scopes,
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
# who is asking: role and scope from the X-Paimana-* headers (backend/access.py; prototype, no authentication)
Anyone = Depends(viewer)


def _key(key: str, v: Viewer | None = None) -> str:
    """Canonical key, 404 when unknown or (with a viewer) outside the viewer's scope."""
    k = serving.canonical(key)
    if k is None:
        raise HTTPException(status_code=404, detail=f"project {key} not found")
    return in_scope(v, k) if v else k


# ---------- read side (DuckDB over Parquet) ----------

@router.get("/meta", response_model=Meta)
def get_meta():
    return serving.meta()


@router.get("/scopes", response_model=Scopes)
def get_scopes():
    """Ministries and canonical agencies with their current project counts, for the sign-in picker."""
    return serving.scopes()


@router.get("/portfolio", response_model=Portfolio)
def get_portfolio(ministry: str | None = None, sector: str | None = None, state: str | None = None,
                  tier: Tier | None = None, v: Viewer = Anyone):
    return serving.portfolio(ministry, sector, state, tier, scope=v.scope)


@router.get("/projects", response_model=ProjectPage)
def get_projects(q: str | None = Query(None, max_length=100), ministry: str | None = None,
                 sector: str | None = None, state: str | None = None, tier: Tier | None = None,
                 flag: Flag | None = None, sort: Sort = "risk", order: Literal["asc", "desc"] | None = None,
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100), near_complete: bool = False,
                 v: Viewer = Anyone):
    """near_complete: 80-99% done and not past the anticipated completion (the public Home's short list)."""
    out = serving.projects(q, ministry, sector, state, tier, flag, sort, order, page, size, scope=v.scope,
                           near_complete=near_complete)
    return out if v.can("insights") else serving.public_page(out)


@router.get("/projects/{key}", response_model=ProjectDetail)
def get_project(key: str, v: Viewer = Anyone):
    """The project page; for the public without drivers, intervals and provenance (serving.public_project)."""
    out = serving.project(_key(key, v))
    return out if v.can("insights") else serving.public_project(out)


@router.get("/projects/{key}/timeline", response_model=Timeline)
def get_timeline(key: str, v: Viewer = Anyone):
    k = _key(key, v)
    points = serving.timeline(k)
    if not v.can("insights"):  # no source documents on the public page
        points = [{**p, "source_doc_id": None, "source_page": None} for p in points]
    return {"key": k, "points": points}


@router.get("/projects/{key}/research", response_model=ProjectResearch)
def get_project_research(key: str, v: Viewer = Anyone):
    """The project's web research: sweep facts (checked against their source) and the research agent's, newest
    first, with the latest status and the external block; for the public without match reasons."""
    out = serving.research(_key(key, v))
    return out if v.can("insights") else serving.public_research(out)


@router.get("/research/summary", response_model=ResearchSummary)
def get_research_summary(v: Viewer = Anyone):
    """Web research over the viewer's current projects: coverage, facts by category and state, the newest live
    blockers (the public: counts, and of the blockers only headline, URL and date)."""
    out = serving.research_summary(scope=v.scope)
    return out if v.can("insights") else serving.public_research_summary(out)


@router.get("/projects/{key}/forecast", response_model=Forecast)
def get_forecast(key: str, v: Viewer = Depends(need("insights"))):
    out = serving.forecast(_key(key, v))
    if out is None:
        raise HTTPException(status_code=404, detail=f"project {key} is not in the current scored portfolio")
    return out


@router.get("/projects/{key}/brief", response_model=BriefOut,
            responses={404: {"description": "not in the scored portfolio"},
                       422: {"description": "status 'rejected' with reasons: numbers not in the payload"},
                       503: {"description": "status 'llm_unavailable': LM Studio is not reachable"}})
def get_brief(key: str, v: Viewer = Depends(need("insights"))):
    """Two paragraphs from the local LLM citing only the payload's numbers (backend/brief.py), cached per
    (project, asof, model_version)."""
    out = brief.generate(_key(key, v))
    if out["status"] == "not_scored":
        raise HTTPException(status_code=404, detail=out["detail"])
    if out["status"] != "ok":
        return JSONResponse(status_code=503 if out["status"] == "llm_unavailable" else 422, content=out)
    return out


@router.get("/agencies/matrix", response_model=AgencyMatrix)
def get_agency_matrix(sector: str | None = Query(None, max_length=60),
                      ministry: str | None = Query(None, max_length=100), include_hidden: bool = False,
                      v: Viewer = Depends(need("agencies"))):
    """Agency Performance Matrix: one point per canonical agency (n >= 5 unless include_hidden); a ministry
    official sees the agencies of their ministry, an agency official every agency with their own is_self."""
    return serving.agency_matrix(sector, ministry, include_hidden, scope=v.scope)


@router.get("/agencies/{agency}/projects", response_model=ProjectPage)
def get_agency_projects(agency: str, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                        v: Viewer = Depends(need("agencies"))):
    """Current projects of one canonical agency (every printed name that maps to it) in the viewer's scope,
    riskiest first."""
    name = agency.strip().upper()
    if not serving.agency_known(name):
        raise HTTPException(status_code=404, detail=f"agency {agency} not found")
    return serving.projects(agency=name, page=page, size=size, scope=v.scope)


@router.get("/bottlenecks", response_model=BottleneckPage)
def get_bottlenecks(category: str | None = Query(None, max_length=40), state: str | None = Query(None, max_length=60),
                    min_projects: int | None = Query(None, ge=1), level: Literal["authority", "state"] | None = None,
                    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                    v: Viewer = Depends(need("bottlenecks"))):
    """Bottleneck Intelligence: clusters by capital exposed, each with its top 5 members (members in scope)."""
    return serving.bottlenecks(category, state, min_projects, level, page, size, scope=v.scope)


@router.get("/bottlenecks/{bottleneck_id}", response_model=BottleneckDetail)
def get_bottleneck(bottleneck_id: str, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                   v: Viewer = Depends(need("bottlenecks"))):
    out = serving.bottleneck(bottleneck_id, page, size, scope=v.scope)
    if out is None:
        raise HTTPException(status_code=404, detail=f"bottleneck {bottleneck_id} not found")
    return out


@router.get("/external/summary", response_model=ExternalSummary)
def get_external_summary(v: Viewer = Anyone):
    out = serving.external_summary(scope=v.scope)
    return out if v.can("insights") else serving.public_external(out)


@router.get("/models", response_model=ModelsOut)
def get_models(_: Viewer = Depends(need("models"))):
    return serving.models()


# ---------- app state (SQLite) ----------

@router.get("/alerts", response_model=AlertPage)
def get_alerts(since: datetime | None = None, kind: AlertKind | None = None, acked: bool | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
               v: Viewer = Depends(need("alerts"))):
    """Alerts on the viewer's projects (project-less pipeline errors: IPMD only)."""
    return db.alerts(since and since.isoformat(), kind, acked, page, size, keys=v.keys)


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
def post_alert_ack(alert_id: int, body: RoleBody | None = None, v: Viewer = Depends(need("ack"))):
    out = db.ack(alert_id, v.acting_as(body and body.role), keys=v.keys)
    if out is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return out


def _watchlist(v: Viewer, role: str) -> dict:
    out = db.watchlist(role)
    if v.scope is None:
        return out
    # ponytail: one list per role cut to the viewer's scope; one per person once there is real sign-in
    items = [i for i in out["items"] if v.sees(i["project_key"])]
    return {"total": len(items), "items": items}


@router.get("/watchlist", response_model=Watchlist)
def get_watchlist(role: Role | None = None, v: Viewer = Depends(need("watchlist"))):
    return _watchlist(v, v.acting_as(role))


@router.post("/watchlist", response_model=Watchlist)
def post_watchlist(body: WatchRequest, v: Viewer = Depends(need("watchlist"))):
    role = v.acting_as(body.role)
    db.watch(role, _key(body.project_key, v))
    return _watchlist(v, role)


@router.delete("/watchlist", response_model=Watchlist)
def delete_watchlist(role: Role | None = None, project_key: str = Query(max_length=32),
                     v: Viewer = Depends(need("watchlist"))):
    role = v.acting_as(role)
    db.unwatch(role, _key(project_key, v))
    return _watchlist(v, role)


@router.get("/jobs", response_model=list[JobRun])
def get_jobs(_: Viewer = Depends(need("live"))):
    return db.latest_jobs()


@router.post("/jobs/ingest", response_model=Ingested)
def post_ingest(file: UploadFile, v: Viewer = Depends(need("jobs"))):
    """Save a report into dataset/raw/inbox/; the watcher ingests it on its next run (or POST /api/jobs/watch)."""
    try:
        out = watcher.save_upload(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.audit(v.role, "jobs.ingest", out["saved_as"] or file.filename, out["sha256"])
    return out


@router.post("/jobs/watch", response_model=JobStarted)
def post_watch(background: BackgroundTasks, v: Viewer = Depends(need("jobs"))):
    """Run the inbox watcher now, in the background; the result shows in /api/jobs and the alert feed."""
    if watcher.busy():
        return {"started": False, "detail": "a watch run is already in progress"}
    n = len(watcher.pending())
    db.audit(v.role, "jobs.watch", "inbox", f"{n} pending")
    background.add_task(watcher.watch_once)
    return {"started": True, "detail": f"{n} inbox file(s) to ingest", "pending": n}


@router.post("/jobs/scout", response_model=JobStarted)
def post_scout(background: BackgroundTasks, project_key: str | None = Query(None, max_length=32),
               v: Viewer = Depends(need("jobs"))):
    """Scout one current project now (and return its counts), or start a batch run in the background."""
    if scout.busy():
        return {"started": False, "detail": "a scout run is already in progress"}
    if project_key:
        k = _key(project_key)
        if k not in scout.index()["projects"]:
            raise HTTPException(status_code=404, detail=f"project {project_key} is not in the current portfolio")
        db.audit(v.role, "jobs.scout", k)
        out = scout.run([k], pib=False)
        return {"started": not out.get("busy"), "detail": f"scouted {k}", "summary": out}
    keys = scout.batch_keys()
    db.audit(v.role, "jobs.scout", "batch", f"{len(keys)} projects")
    background.add_task(scout.run, keys)
    return {"started": True, "detail": f"scouting {len(keys)} projects in the background", "pending": len(keys)}


@router.post("/jobs/research", response_model=JobStarted)
def post_research(background: BackgroundTasks, project_key: str | None = Query(None, max_length=32),
                  v: Viewer = Depends(need("jobs"))):
    """Run the research agent now, in the background (it waits for the local LLM): one current project, or the next
    batch (watchlists, then Critical / High / Watch, least recently researched first)."""
    if research.busy():
        return {"started": False, "detail": "a research run is already in progress"}
    if project_key:
        k = _key(project_key)
        if k not in scout.index()["projects"]:
            raise HTTPException(status_code=404, detail=f"project {project_key} is not in the current portfolio")
        keys = [k]
    else:
        keys = research.batch_keys()
    db.audit(v.role, "jobs.research", keys[0] if project_key else "batch", f"{len(keys)} projects")
    background.add_task(research.run, keys)
    return {"started": True, "detail": f"researching {keys[0] if project_key else f'{len(keys)} projects'} in the "
                                       "background", "pending": len(keys)}


@router.post("/jobs/parivesh-snapshot", response_model=JobStarted)
def post_parivesh_snapshot(background: BackgroundTasks, v: Viewer = Depends(need("jobs"))):
    """Archive today's PARIVESH 2.0 dashboard table now, in the background (once per date)."""
    if portals.snapshot_busy():
        return {"started": False, "detail": "a PARIVESH snapshot is already being taken"}
    path = portals.snapshot_path()
    if path.exists():
        return {"started": False, "detail": f"{path.name} is already archived"}
    db.audit(v.role, "jobs.parivesh_snapshot", path.name)
    background.add_task(portals.snapshot_once)
    return {"started": True, "detail": f"archiving the PARIVESH dashboard as {path.name}"}


@router.post("/jobs/bhoomi-pull", response_model=JobStarted)
def post_bhoomi_pull(background: BackgroundTasks, state: str | None = Query(None, max_length=60),
                     v: Viewer = Depends(need("jobs"))):
    """Pull the Bhoomi Rashi register (one state, or every state) now, in the background; only with BHOOMI_PULL=1."""
    if not scheduler.bhoomi_enabled():
        return {"started": False, "detail": "the Bhoomi Rashi pull is off (BHOOMI_PULL=0)"}
    if portals.pull_busy():
        return {"started": False, "detail": "a Bhoomi Rashi pull is already running"}
    states = [state.strip()] if state else None
    db.audit(v.role, "jobs.bhoomi_pull", state or "all states")
    background.add_task(portals.bhoomi_pull, states)
    return {"started": True, "detail": f"pulling {states[0] if states else 'every state'} in the background"}


@router.get("/signals/feed", response_model=SignalFeed)
def get_signal_feed(since: datetime | None = None, category: str | None = Query(None, max_length=40),
                    state: str | None = Query(None, max_length=60), severity: int | None = Query(None, ge=1, le=3),
                    linked: bool | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                    v: Viewer = Depends(need("radar"))):
    """External Evidence Radar: one page of signals (severity = at least) and the state heat. Outside IPMD only the
    signals linked to the viewer's projects (no unlinked pool)."""
    return scout.feed(since and since.isoformat(), category, state, severity, linked, page, size,
                      keys=_signal_keys(v))


def _signal_keys(v: Viewer) -> frozenset | None:
    """None (every signal, the unlinked pool too) for IPMD, else the viewer's project keys."""
    return None if v.can("unlinked_signals") else v.keys or frozenset()


@router.get("/radar/summary", response_model=RadarSummary)
def get_radar_summary(v: Viewer = Depends(need("radar"))):
    """External Evidence Radar rollup: last 90 days by category / severity / source, linked vs unlinked, lead time."""
    return scout.radar_summary(keys=_signal_keys(v))


@router.get("/live/status", response_model=LiveStatus)
def get_live_status(_: Viewer = Depends(need("live"))):
    return scheduler.status()


@router.get("/stream")
async def get_stream(request: Request, after: int | None = Query(None, ge=0), v: Viewer = Depends(stream_viewer)):
    """Server-Sent Events: each new alert as `event: alert` (id = alert id, data = the alert JSON), a comment line
    every 15 s. Resumes after Last-Event-ID (EventSource sends it on reconnect) or ?after=, else from now. The
    viewer comes as ?role=&ministry=&agency= (EventSource sends no headers); only their projects' alerts."""
    if not v.can("alerts"):
        raise HTTPException(status_code=403, detail=f"the alert stream is not available to {v.role}")
    last = request.headers.get("last-event-id")
    start = after if after is not None else int(last) if last and last.isdigit() else None
    return StreamingResponse(scheduler.alert_stream(start, v.keys), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/projects/{key}/signals", response_model=ProjectSignals)
def get_project_signals(key: str, v: Viewer = Depends(need("insights"))):
    out = db.project_signals(_key(key, v))
    for s in out["items"]:
        s.update(scout.lead_time(out["key"], s["published_at"]))
    return out


# ---------- worker cell (JSON store) ----------

@router.get("/worker-runs", response_model=list[WorkerRun])
def get_worker_runs(_: Viewer = Depends(need("workers"))):
    runs = store.load_worker_runs()
    return sorted(runs, key=lambda r: r["timestamp"], reverse=True)


def _addressed(v: Viewer, d: dict) -> bool:
    """IPMD sees every memo; a ministry or agency official those addressed to their role on their projects."""
    if v.scope is None:
        return True
    k = serving.canonical(d["project_id"])
    return d["recommended_recipient_role"] == v.role and k is not None and v.sees(k)


@router.get("/dispatch", response_model=list[DispatchDraft])
def get_dispatch(v: Viewer = Depends(need("approvals"))):
    return [d for d in store.load_dispatch_drafts() if _addressed(v, d)]


@router.post("/approvals", response_model=DispatchDraft)
def post_approval(body: ApprovalRequest, v: Viewer = Depends(need("approvals"))):
    """Decide a memo: only the role it is addressed to (IPMD too decides only its own memos)."""
    role = v.acting_as(body.role)
    draft = next((d for d in store.load_dispatch_drafts() if d["id"] == body.draft_id and _addressed(v, d)), None)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"dispatch draft {body.draft_id} not found")
    if draft["recommended_recipient_role"] != role:
        raise HTTPException(status_code=403, detail=f"this memo is addressed to {draft['recommended_recipient_role']}")
    updated = store.update_dispatch_draft(body.draft_id, body.decision)
    db.audit(role, f"dispatch.{body.decision}", body.draft_id)
    return updated


@router.post("/worker-runs/trigger", response_model=TriggerResult)
def trigger_worker_cycle(v: Viewer = Depends(need("workers"))):
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.audit(v.role, "worker.trigger", "worker_cycle")
    try:
        out = worker.run_worker_cycle()
    except Exception as e:
        db.record_job("worker_cycle", started, "error", {"error": str(e)})
        raise
    db.record_job("worker_cycle", started, "ok", {"dispatch_drafts": len(out["dispatch_drafts"])})
    return out
