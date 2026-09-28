import asyncio
import json
import math
import re
import threading
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile as StarletteUpload

from llm import agent, second_opinion, worker

from . import brief, db, ratelimit, serving, store
from .access import HIDDEN_ROLES, Viewer, in_scope, need, viewer
from .auth import sessions
from .live import opinions, portals, research, scheduler, scout, watcher
from .schemas import (
    AgencyMatrix,
    Alert,
    AlertKind,
    AlertPage,
    ApprovalRequest,
    BottleneckDetail,
    BottleneckPage,
    CHAT_TEXT_MAX,
    BriefOut,
    ChatRequest,
    DispatchDraft,
    ExternalSummary,
    Flag,
    Forecast,
    Ingested,
    JobRun,
    JobStarted,
    LiveStatus,
    MapPage,
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
    SecondOpinionNone,
    SecondOpinionOut,
    SecondOpinionRejected,
    SecondOpinionUnavailable,
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
# who is asking: the signed-in account of the session cookie, or the public without one (backend/access.py)
Anyone = Depends(viewer)
# the numbers policy (backend/serving.py, docs/ACCESS_CONTROL.md): a viewer without the `numbers` feature gets every
# read below through serving.plain_* (the model's numbers null, words kept); v.can("numbers") decides
# input bounds: a project key is PRJ- and six digits (400 otherwise, before any lookup); every free-text query or
# path parameter has a length limit (422 past it), and paging is 1..100 rows a page
KEY_RX = re.compile(r"PRJ-\d{6}")
NAME_MAX, SECTOR_MAX, ID_MAX = 100, 60, 64   # a ministry or agency name, a sector or state, a bottleneck id


def _key(key: str, v: Viewer | None = None) -> str:
    """Canonical key; 400 when it does not look like a project key, 404 when unknown or (with a viewer) outside
    the viewer's scope."""
    if not KEY_RX.fullmatch(key or ""):
        raise HTTPException(status_code=400, detail="a project key looks like PRJ-000123")
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
def get_portfolio(ministry: str | None = Query(None, max_length=NAME_MAX),
                  sector: str | None = Query(None, max_length=SECTOR_MAX),
                  state: str | None = Query(None, max_length=SECTOR_MAX), tier: Tier | None = None,
                  v: Viewer = Anyone):
    out = serving.portfolio(ministry, sector, state, tier, scope=v.scope)
    return out if v.can("numbers") else serving.plain_portfolio(out)


@router.get("/projects", response_model=ProjectPage)
def get_projects(q: str | None = Query(None, max_length=100), ministry: str | None = Query(None, max_length=NAME_MAX),
                 sector: str | None = Query(None, max_length=SECTOR_MAX),
                 state: str | None = Query(None, max_length=SECTOR_MAX), tier: Tier | None = None,
                 flag: Flag | None = None, sort: Sort = "risk", order: Literal["asc", "desc"] | None = None,
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100), near_complete: bool = False,
                 v: Viewer = Anyone):
    """near_complete: 80-99% done and not past the anticipated completion (the public Home's short list)."""
    out = serving.projects(q, ministry, sector, state, tier, flag, sort, order, page, size, scope=v.scope,
                           near_complete=near_complete)
    out = out if v.can("insights") else serving.public_page(out)
    return out if v.can("numbers") else serving.plain_page(out)


@router.get("/projects/map", response_model=MapPage)
def get_projects_map(q: str | None = Query(None, max_length=100),
                     ministry: str | None = Query(None, max_length=NAME_MAX),
                     sector: str | None = Query(None, max_length=SECTOR_MAX),
                     state: str | None = Query(None, max_length=SECTOR_MAX), tier: Tier | None = None,
                     flag: Flag | None = None, near_complete: bool = False, v: Viewer = Anyone):
    """The command centre's risk map: every current project in scope matching the filters of /projects, unpaged
    (at most serving.MAP_MAX), as MapRow; no model number for anyone."""
    out = serving.projects_map(q, ministry, sector, state, tier, flag, scope=v.scope, near_complete=near_complete)
    return out if v.can("insights") else serving.public_map(out)


@router.get("/projects/{key}", response_model=ProjectDetail)
def get_project(key: str, v: Viewer = Anyone):
    """The project page; for the public without drivers, intervals and provenance (serving.public_project), without
    the model's numbers for anyone but the developer (serving.plain_project)."""
    out = serving.project(_key(key, v))
    out = out if v.can("insights") else serving.public_project(out)
    return out if v.can("numbers") else serving.plain_project(out)


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
    return out if v.can("numbers") else serving.plain_forecast(out)


@router.get("/projects/{key}/brief", response_model=BriefOut,
            responses={404: {"description": "not in the scored portfolio"},
                       422: {"description": "status 'rejected' with reasons: numbers not in the payload"},
                       503: {"description": "status 'llm_unavailable': LM Studio is not reachable"}})
def get_brief(key: str, v: Viewer = Depends(need("insights"))):
    """Two paragraphs from the local LLM citing only the payload's numbers (backend/brief.py), cached per
    (project, asof, model_version, view): the model's numbers for the developer, the outlook words for the rest."""
    out = brief.generate(_key(key, v), numbers=v.can("numbers"))
    if out["status"] == "not_scored":
        raise HTTPException(status_code=404, detail=out["detail"])
    if out["status"] != "ok":
        return JSONResponse(status_code=503 if out["status"] == "llm_unavailable" else 422, content=out)
    return out


@router.get("/projects/{key}/second-opinion", response_model=SecondOpinionOut | SecondOpinionNone,
            responses={404: {"description": "not in the scored portfolio"},
                       422: {"model": SecondOpinionRejected, "description": "status 'rejected' with reasons"},
                       503: {"model": SecondOpinionUnavailable,
                             "description": "status 'llm_unavailable': LM Studio is not reachable or busy"}})
def get_second_opinion(key: str, cached: bool = False, v: Viewer = Depends(need("insights"))):
    """The local LLM's cited second opinion on the project's evidence (llm/second_opinion.py): generated on demand
    and stored per evidence version; ?cached=1 never generates and says status 'none' when there is none. It never
    changes the tier."""
    k, numbers = _key(key, v), v.can("numbers")   # each view is its own pack and cache (llm/second_opinion.py)
    if cached:
        out = second_opinion.cached(k, numbers=numbers)
        if out is not None:
            return out
        if second_opinion.pack(k, numbers=numbers) is None:
            raise HTTPException(status_code=404, detail=f"project {key} is not in the current scored portfolio")
        return {"status": "none", "key": k, "detail": "no second opinion for the current evidence yet"}
    out = second_opinion.generate(k, numbers=numbers)
    if out["status"] == "not_scored":
        raise HTTPException(status_code=404, detail=out["detail"])
    if out["status"] == "rejected":
        return JSONResponse(status_code=422, content=SecondOpinionRejected(**out).model_dump(by_alias=True))
    if out["status"] != "ok":
        return JSONResponse(status_code=503, content=SecondOpinionUnavailable(**out).model_dump(by_alias=True))
    return out


@router.get("/agencies/matrix", response_model=AgencyMatrix)
def get_agency_matrix(sector: str | None = Query(None, max_length=SECTOR_MAX),
                      ministry: str | None = Query(None, max_length=NAME_MAX), include_hidden: bool = False,
                      v: Viewer = Depends(need("agencies"))):
    """Agency Performance Matrix: one point per canonical agency (n >= 5 unless include_hidden); a ministry
    official sees the agencies of their ministry, an agency official every agency with their own is_self."""
    out = serving.agency_matrix(sector, ministry, include_hidden, scope=v.scope)
    return out if v.can("numbers") else serving.plain_agency_matrix(out)


@router.get("/agencies/{agency}/projects", response_model=ProjectPage)
def get_agency_projects(agency: str = Path(max_length=NAME_MAX), page: int = Query(1, ge=1),
                        size: int = Query(50, ge=1, le=100), v: Viewer = Depends(need("agencies"))):
    """Current projects of one canonical agency (every printed name that maps to it) in the viewer's scope,
    riskiest first."""
    name = agency.strip().upper()
    if not serving.agency_known(name):
        raise HTTPException(status_code=404, detail=f"agency {agency} not found")
    out = serving.projects(agency=name, page=page, size=size, scope=v.scope)
    return out if v.can("numbers") else serving.plain_page(out)


@router.get("/bottlenecks", response_model=BottleneckPage)
def get_bottlenecks(category: str | None = Query(None, max_length=40),
                    state: str | None = Query(None, max_length=SECTOR_MAX),
                    min_projects: int | None = Query(None, ge=1), level: Literal["authority", "state"] | None = None,
                    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                    v: Viewer = Depends(need("bottlenecks"))):
    """Bottleneck Intelligence: clusters by capital exposed, each with its top 5 members (members in scope)."""
    out = serving.bottlenecks(category, state, min_projects, level, page, size, scope=v.scope)
    return out if v.can("numbers") else serving.plain_bottlenecks(out)


@router.get("/bottlenecks/{bottleneck_id}", response_model=BottleneckDetail)
def get_bottleneck(bottleneck_id: str = Path(max_length=ID_MAX), page: int = Query(1, ge=1),
                   size: int = Query(50, ge=1, le=100), v: Viewer = Depends(need("bottlenecks"))):
    out = serving.bottleneck(bottleneck_id, page, size, scope=v.scope)
    if out is None:
        raise HTTPException(status_code=404, detail=f"bottleneck {bottleneck_id} not found")
    return out if v.can("numbers") else serving.plain_bottleneck(out)


@router.get("/external/summary", response_model=ExternalSummary)
def get_external_summary(v: Viewer = Anyone):
    out = serving.external_summary(scope=v.scope)
    out = out if v.can("insights") else serving.public_external(out)
    return out if v.can("numbers") else serving.plain_external(out)


@router.get("/models", response_model=ModelsOut)
def get_models(_: Viewer = Depends(need("models"))):
    return serving.models()


# ---------- app state (PostgreSQL, backend/db) ----------

@router.get("/alerts", response_model=AlertPage)
def get_alerts(since: datetime | None = None, kind: AlertKind | None = None, acked: bool | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
               v: Viewer = Depends(need("alerts"))):
    """Alerts on the viewer's projects (project-less pipeline errors: IPMD only)."""
    out = db.alerts(since and since.isoformat(), kind, acked, page, size, keys=v.keys)
    return out if v.can("numbers") else {**out, "items": [serving.plain_alert(a) for a in out["items"]]}


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
def post_alert_ack(alert_id: int, body: RoleBody | None = None, v: Viewer = Depends(need("ack"))):
    role = v.acting_as(body and body.role)
    out = db.ack(alert_id, role, keys=v.keys, actor=v.actor, named=role not in HIDDEN_ROLES)
    if out is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return out if v.can("numbers") else serving.plain_alert(out)


def _watchlist(v: Viewer, role: str) -> dict:
    out = db.watchlist(role)
    if not v.can("numbers"):
        out = {**out, "items": [{**i, "project": i["project"] and serving.plain_row(i["project"])}
                                for i in out["items"]]}
    if v.scope is None:
        return out
    # one list per role, cut to the viewer's scope (docs/ACCESS_CONTROL.md, Scope)
    items = [i for i in out["items"] if v.sees(i["project_key"])]
    return {"total": len(items), "items": items}


@router.get("/watchlist", response_model=Watchlist)
def get_watchlist(role: Role | None = None, v: Viewer = Depends(need("watchlist"))):
    return _watchlist(v, v.acting_as(role))


@router.post("/watchlist", response_model=Watchlist)
def post_watchlist(body: WatchRequest, v: Viewer = Depends(need("watchlist"))):
    role = v.acting_as(body.role)
    db.watch(role, _key(body.project_key, v), actor=v.actor)
    return _watchlist(v, role)


@router.delete("/watchlist", response_model=Watchlist)
def delete_watchlist(role: Role | None = None, project_key: str = Query(max_length=32),
                     v: Viewer = Depends(need("watchlist"))):
    role = v.acting_as(role)
    db.unwatch(role, _key(project_key, v), actor=v.actor)
    return _watchlist(v, role)


# job-summary fields that name projects or carry per-project text: a scoped viewer never gets them (the jobs record
# counts only; this is the second line, for older rows and any job that adds such a field)
PER_PROJECT = frozenset({"keys", "key", "project_key", "project_keys", "errors", "error", "detail"})


def _scrub(summary, v: Viewer):
    """A job summary as this viewer may read it: whole for a viewer without a scope, else without PER_PROJECT fields
    and without any other value that names a project key."""
    if v.scope is None or not isinstance(summary, dict):
        return summary
    return {k: x for k, x in summary.items()
            if k not in PER_PROJECT and not KEY_RX.search(json.dumps(x, default=str))}


def _scrubbed_run(run: dict | None, v: Viewer) -> dict | None:
    return None if run is None else {**run, "summary": _scrub(run.get("summary"), v)}


@router.get("/jobs", response_model=list[JobRun])
def get_jobs(v: Viewer = Depends(need("live"))):
    return [_scrubbed_run(r, v) for r in db.latest_jobs()]


# the upload's body as OpenAPI shows it: post_ingest reads the form itself (below), so FastAPI does not describe it
UPLOAD_BODY = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}}}}}}}


@router.post("/jobs/ingest", response_model=Ingested, openapi_extra=UPLOAD_BODY)
async def post_ingest(request: Request, v: Viewer = Depends(need("jobs"))):
    """Save a report (the multipart field `file`) into dataset/raw/inbox/; the watcher ingests it on its next run (or
    POST /api/jobs/watch). The form is read here, after the access check: FastAPI parses a form parameter before it
    runs the dependencies, which would spool a caller's whole upload before telling them 403."""
    async with request.form(max_files=1, max_fields=5) as form:
        file = form.get("file")
        if not isinstance(file, StarletteUpload):
            raise HTTPException(status_code=422, detail="send the report as the multipart form field 'file'")
        try:
            out = await run_in_threadpool(watcher.save_upload, file.filename, file.file)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        await run_in_threadpool(db.audit, v.role, "jobs.ingest", out["saved_as"] or file.filename, out["sha256"],
                                v.actor)
    return out


@router.post("/jobs/watch", response_model=JobStarted)
def post_watch(background: BackgroundTasks, v: Viewer = Depends(need("jobs"))):
    """Run the inbox watcher now, in the background; the result shows in /api/jobs and the alert feed."""
    if watcher.busy():
        return {"started": False, "detail": "a watch run is already in progress"}
    n = len(watcher.pending())
    db.audit(v.role, "jobs.watch", "inbox", f"{n} pending", v.actor)
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
        db.audit(v.role, "jobs.scout", k, actor=v.actor)
        out = scout.run([k], pib=False)
        return {"started": not out.get("busy"), "detail": f"scouted {k}", "summary": out}
    keys = scout.batch_keys()
    db.audit(v.role, "jobs.scout", "batch", f"{len(keys)} projects", v.actor)
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
    db.audit(v.role, "jobs.research", keys[0] if project_key else "batch", f"{len(keys)} projects", v.actor)
    background.add_task(research.run, keys)
    return {"started": True, "detail": f"researching {keys[0] if project_key else f'{len(keys)} projects'} in the "
                                       "background", "pending": len(keys)}


@router.post("/jobs/second-opinion", response_model=JobStarted)
def post_second_opinion(background: BackgroundTasks, project_key: str | None = Query(None, max_length=32),
                        v: Viewer = Depends(need("jobs"))):
    """Run the second-opinion job now, in the background (it waits for the local LLM): one current project, or the
    next batch (Critical / High / Watch with evidence and no opinion for it yet, least recently asked first). A
    project whose current evidence already has an opinion under the current prompt is skipped."""
    if opinions.busy():
        return {"started": False, "detail": "a second-opinion run is already in progress"}
    if project_key:
        k = _key(project_key)
        if not serving.rows_for_keys((k,)):
            raise HTTPException(status_code=404, detail=f"project {project_key} is not in the current portfolio")
        db.audit(v.role, "jobs.second_opinion", k, actor=v.actor)
        background.add_task(opinions.run, [k])
        return {"started": True, "detail": f"asking for a second opinion on {k} in the background", "pending": 1}
    keys, n = opinions.batch_keys(), opinions.per_run()
    db.audit(v.role, "jobs.second_opinion", "batch", f"up to {n} of {len(keys)} projects", v.actor)
    background.add_task(opinions.run, keys, n)
    return {"started": True, "detail": f"asking for up to {n} second opinions in the background", "pending": n}


@router.post("/jobs/parivesh-snapshot", response_model=JobStarted)
def post_parivesh_snapshot(background: BackgroundTasks, v: Viewer = Depends(need("jobs"))):
    """Archive today's PARIVESH 2.0 dashboard table now, in the background (once per date)."""
    if portals.snapshot_busy():
        return {"started": False, "detail": "a PARIVESH snapshot is already being taken"}
    path = portals.snapshot_path()
    if path.exists():
        return {"started": False, "detail": f"{path.name} is already archived"}
    db.audit(v.role, "jobs.parivesh_snapshot", path.name, actor=v.actor)
    background.add_task(portals.snapshot_once)
    return {"started": True, "detail": f"archiving the PARIVESH dashboard as {path.name}"}


@router.post("/jobs/bhoomi-pull", response_model=JobStarted)
def post_bhoomi_pull(background: BackgroundTasks, state: str | None = Query(None, max_length=SECTOR_MAX),
                     v: Viewer = Depends(need("jobs"))):
    """Pull the Bhoomi Rashi register (one state, or every state) now, in the background; only with BHOOMI_PULL=1."""
    if not scheduler.bhoomi_enabled():
        return {"started": False, "detail": "the Bhoomi Rashi pull is off (BHOOMI_PULL=0)"}
    if portals.pull_busy():
        return {"started": False, "detail": "a Bhoomi Rashi pull is already running"}
    states = [state.strip()] if state else None
    db.audit(v.role, "jobs.bhoomi_pull", state or "all states", actor=v.actor)
    background.add_task(portals.bhoomi_pull, states)
    return {"started": True, "detail": f"pulling {states[0] if states else 'every state'} in the background"}


@router.get("/signals/feed", response_model=SignalFeed)
def get_signal_feed(since: datetime | None = None, category: str | None = Query(None, max_length=40),
                    state: str | None = Query(None, max_length=SECTOR_MAX),
                    severity: int | None = Query(None, ge=1, le=3),
                    linked: bool | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
                    v: Viewer = Depends(need("radar"))):
    """External Evidence Radar: one page of signals (severity = at least) and the state heat. Only the developer
    sees the unlinked pool; everyone else the signals linked to their projects."""
    out = scout.feed(since and since.isoformat(), category, state, severity, linked, page, size,
                     keys=_signal_keys(v))
    return out if v.can("numbers") else {**out, "items": [serving.plain_signal(s) for s in out["items"]]}


def _signal_keys(v: Viewer) -> frozenset | None:
    """None (every signal, the unlinked pool too) with `unlinked_signals`, else the keys of the viewer's projects
    (every project's for a viewer without a scope): the signals linked to them."""
    if v.can("unlinked_signals"):
        return None
    return v.keys if v.scope is not None else serving.scope_keys(None)


@router.get("/radar/summary", response_model=RadarSummary)
def get_radar_summary(v: Viewer = Depends(need("radar"))):
    """External Evidence Radar rollup: last 90 days by category / severity / source, linked vs unlinked, lead time."""
    return scout.radar_summary(keys=_signal_keys(v))


def _scrubbed_job(x: dict, v: Viewer) -> dict:
    """One job's live status as this viewer may read it: the last run scrubbed (_scrub), and for a viewer with a scope
    the last error only as the fact of it (an exception's text can name any project, a key violation for one)."""
    out = {**x, "last_run": _scrubbed_run(x.get("last_run"), v)}
    if v.scope is not None and out.get("last_error") is not None:
        out["last_error"] = "the last run failed"
    return out


@router.get("/live/status", response_model=LiveStatus)
def get_live_status(v: Viewer = Depends(need("live"))):
    out = scheduler.status()
    return {k: _scrubbed_job(x, v) if isinstance(x, dict) else x for k, x in out.items()}


@router.get("/stream")
async def get_stream(request: Request, after: int | None = Query(None, ge=0), v: Viewer = Depends(need("alerts"))):
    """Server-Sent Events: each new alert as `event: alert` (id = alert id, data = the alert JSON), a comment line
    every 15 s. Resumes after Last-Event-ID (EventSource sends it on reconnect) or ?after=, else from now. The viewer
    is the session cookie's (a same-origin EventSource sends it); only their projects' alerts. The session is checked
    again before alerts go out and at every heartbeat: sign-out, expiry, a disabled account or a changed role or
    scope ends the stream (scheduler.alert_stream)."""
    last = request.headers.get("last-event-id")
    start = after if after is not None else int(last) if last and last.isdigit() else None
    s = sessions.session_of(request)   # the one the viewer came from (cached on the request)
    alive = sessions.still_live(s) if s is not None else None
    redact = None if v.can("numbers") else serving.plain_alert
    return StreamingResponse(scheduler.alert_stream(start, v.keys, alive, redact), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/projects/{key}/signals", response_model=ProjectSignals)
def get_project_signals(key: str, v: Viewer = Depends(need("insights"))):
    out = db.project_signals(_key(key, v))
    for s in out["items"]:
        s.update(scout.lead_time(out["key"], s["published_at"]))
    return out if v.can("numbers") else {**out, "items": [serving.plain_signal(s) for s in out["items"]]}


# ---------- assistant (llm/agent.py; docs/AI_ASSISTANT.md) ----------

KEEPALIVE_S = 15.0


def _sse(ev: dict) -> str:
    data = json.dumps(ev["data"], ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {ev['event']}\ndata: {data}\n\n"


async def _chat_events(v: Viewer, messages: list[dict], key: str | None):
    """The agent's events as server-sent events. The agent runs in a thread of its own (it blocks on the LLM) and
    hands each event over as it comes; when the client goes away (the response task is cancelled) cancel is set,
    the agent stops at its next step and releases the LLM. A comment line every KEEPALIVE_S seconds while the model
    is thinking keeps proxies from closing the stream."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    cancel = threading.Event()

    def put(item):
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except RuntimeError:  # the event loop is gone (shutdown)
            cancel.set()

    def work():
        gen = agent.run(v, messages, key, cancel=cancel)
        try:
            for ev in gen:
                put(ev)
                if cancel.is_set():
                    break
        finally:
            gen.close()
            put(None)

    threading.Thread(target=work, name="chat-answer", daemon=True).start()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), KEEPALIVE_S)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if ev is None:
                break
            yield _sse(ev)
    finally:
        cancel.set()


@router.post("/chat", responses={
    200: {"content": {"text/event-stream": {}}, "description": "events status, tool, card, token, retry, done, error"},
    404: {"description": "projectKey unknown or outside the viewer's scope"},
    422: {"description": "messages: 1-12 turns, the last the user's question of 1-1000 characters"},
    429: {"description": "rate limit (per account, or per client address for the public); detail says when"}})
async def post_chat(body: ChatRequest, v: Viewer = Depends(need("chat"))):
    """The assistant (every role): a stream of server-sent events answering the last question from the tools this
    viewer may use (llm/tools.py), cut to their scope. Rate limited per account (the public: per client address)
    before streaming starts (backend/ratelimit.py). Nothing is stored and the question is not logged."""
    key = _key(body.project_key, v) if body.project_key else None  # a 404 uses no question of the limit
    wait = ratelimit.check(v.who, v.role)
    if wait is not None:
        return JSONResponse(status_code=429, content={"detail": ratelimit.message(v.role, wait)},
                            headers={"Retry-After": str(math.ceil(wait))})
    messages = [{"role": m.role, "content": m.content[:CHAT_TEXT_MAX]} for m in body.messages]
    return StreamingResponse(_chat_events(v, messages, key), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    """The memos addressed to the viewer; without `numbers` in words (serving.plain_draft: memos stored before the
    worker's analyst read words quote the model's probability)."""
    out = [d for d in store.load_dispatch_drafts() if _addressed(v, d)]
    return out if v.can("numbers") else [serving.plain_draft(d) for d in out]


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
    db.audit(role, f"dispatch.{body.decision}", body.draft_id, actor=v.actor)
    return updated if v.can("numbers") else serving.plain_draft(updated)


@router.post("/worker-runs/trigger", response_model=TriggerResult)
def trigger_worker_cycle(v: Viewer = Depends(need("workers"))):
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.audit(v.role, "worker.trigger", "worker_cycle", actor=v.actor)
    try:
        out = worker.run_worker_cycle()
    except Exception as e:
        db.record_job("worker_cycle", started, "error", {"error": str(e)})
        raise
    db.record_job("worker_cycle", started, "ok", {"dispatch_drafts": len(out["dispatch_drafts"])})
    return out
