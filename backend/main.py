"""The FastAPI app: the lifespan (data, database, background jobs), the hardening middlewares
(backend/auth/middleware.py), the routes (backend/routes.py, backend/auth/routes.py) and the two probes.

Every route runs behind sessions.guard (the Origin and CSRF checks of a write). /healthz says the process is up (the
container's health check); /readyz says whether it can serve: the data version loaded and the database answering,
with the local LLM reported but not required (the app answers without it). Shutdown (uvicorn's graceful stop, then
the lifespan's end) sets the LLM jobs' stop flags before cancelling the loops (backend/live/scheduler.py stop()).
"""
import logging
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from llm import client as llm_client, rag, router as chat_router

from . import db, serving, settings as cfg
from .auth import middleware, sessions
from .auth.routes import router as auth_router
from .live import scheduler
from .routes import router
from .schemas import Health, Ready

log = logging.getLogger(__name__)
LLM_PROBE_S, LLM_PROBE_TTL_S = 1.5, 30.0
_llm_probe: dict = {"at": -1e9, "ok": False}


def _warm_chat() -> None:
    """The assistant's first question should not wait: the router's vocabulary now, and (with the live jobs on) the
    search index, loaded or rebuilt in its own background thread (llm/rag.py ensure_index)."""
    try:
        chat_router.vocab()
        if scheduler.enabled():
            rag.ensure_index(background=True)
    except Exception:  # noqa: BLE001 - a failed warm-up only means a slower first question
        log.exception("chat warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    serving.state()  # load the current data version before the first request
    db.init()
    if cfg.settings.demo_login:
        log.warning("DEMO_LOGIN is on: POST /api/auth/demo signs anyone in to a role without a password; "
                    "a prototype setting, never for a real deployment")
    # the six loops: report watcher, news scout, PARIVESH snapshot, Bhoomi Rashi pull, research agent, second
    # opinion (each with its own switch); LIVE_JOBS=0 starts none of them
    tasks = scheduler.start()
    threading.Thread(target=_warm_chat, name="chat-warmup", daemon=True).start()
    yield
    await scheduler.stop(tasks)


docs = cfg.settings.api_docs
app = FastAPI(title="PAIMANA Radar backend", lifespan=lifespan, dependencies=[Depends(sessions.guard)],
              docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
              openapi_url="/openapi.json" if docs else None)
middleware.install(app)
app.include_router(auth_router)
app.include_router(router)


@app.get("/healthz", response_model=Health, include_in_schema=False)
def healthz():
    return {"status": "ok"}


def _llm_reachable() -> bool:
    """LM Studio answers GET /models within LLM_PROBE_S (remembered LLM_PROBE_TTL_S; a recent failure of a real
    call counts as down)."""
    if llm_client.down_recently():
        return False
    if time.monotonic() - _llm_probe["at"] > LLM_PROBE_TTL_S:
        try:
            ok = httpx.get(f"{llm_client.LLM_BASE_URL.rstrip('/')}/models", timeout=LLM_PROBE_S).status_code == 200
        except httpx.HTTPError:
            ok = False
        _llm_probe.update(at=time.monotonic(), ok=ok)
    return _llm_probe["ok"]


@app.get("/readyz", response_model=Ready, include_in_schema=False, responses={503: {"model": Ready}})
def readyz():
    try:
        s = serving.state()
        data = f"{s['asof']} ({s['model_version']})"
    except Exception:  # noqa: BLE001 - not ready is the answer, not an error
        log.exception("readiness: the data version is not loaded")
        data = None
    database = db.healthy()
    out = Ready(ready=bool(data) and database, data=data, database=database,
                llm="reachable" if _llm_reachable() else "unreachable")
    return JSONResponse(out.model_dump(by_alias=True), status_code=200 if out.ready else 503)
