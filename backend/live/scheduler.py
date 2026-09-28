"""Background jobs inside the backend process (docs/IMPLEMENTATION_GUIDE_v2.md A.2: in-process scheduler, no broker)
and the alert stream.

start() runs the inbox watcher every WATCH_INTERVAL_S seconds (default 60, first tick at start), the scout batch
every SCOUT_INTERVAL_H hours (default 24, first run SCOUT_FIRST_DELAY_S after start) and the public-portal jobs of
backend/live/portals.py: the PARIVESH dashboard snapshot every PARIVESH_SNAPSHOT_INTERVAL_H hours (default 6; a
date already archived is not fetched again, so this is one fetch a day with same-day retries; PARIVESH_SNAPSHOT=0
turns it off) and, only with BHOOMI_PULL=1, a daily check that pulls the Bhoomi Rashi register when the newest pull
is BHOOMI_PULL_EVERY_D days old (default 91, quarterly), and the research agent (backend/live/research.py) every
RESEARCH_INTERVAL_H hours (default 24, first run RESEARCH_FIRST_DELAY_S after start; RESEARCH_AGENT=0 turns it off),
up to RESEARCH_PER_RUN projects a run. LIVE_JOBS=0 starts none of them (the tests). The blocking
work runs in a thread (asyncio.to_thread), and every job holds its own lock, so a scheduled run never overlaps one
started from the API. A run that ingests, scouts or fetches writes its job_runs row; an idle tick (nothing in the
inbox, today already archived, pull not due) only updates STATUS.

alert_stream() is the Server-Sent Events body of GET /api/stream: it polls SQLite every POLL_S seconds for alerts
with an id above the last one sent and writes a comment line every HEARTBEAT_S seconds so proxies keep it open.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from backend import db
from backend.schemas import Alert

from . import portals, research, scout, watcher

SCOUT_FIRST_DELAY_S = 600
PORTALS_FIRST_DELAY_S = 120
RESEARCH_FIRST_DELAY_S = 1800
POLL_S, HEARTBEAT_S = 2.0, 15.0
STATUS = {job: {"interval_s": None, "running": False, "last_tick": None, "next_due": None, "last_error": None}
          for job in ("watch", "scout", "parivesh_snapshot", "bhoomi_rashi_pull", "research")}


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def enabled() -> bool:
    return os.environ.get("LIVE_JOBS", "1") != "0"


def bhoomi_enabled() -> bool:
    """BHOOMI_PULL=1: the Bhoomi Rashi pull may run (scheduled and from the API); off by default."""
    return os.environ.get("BHOOMI_PULL", "0") == "1"


async def _every(job: str, fn, interval_s: float, first_delay_s: float) -> None:
    st = STATUS[job]
    st.update(interval_s=interval_s, next_due=_iso(datetime.now(timezone.utc) + timedelta(seconds=first_delay_s)))
    await asyncio.sleep(first_delay_s)
    while True:
        st["running"] = True
        try:
            await asyncio.to_thread(fn)
            st["last_error"] = None
        except Exception as e:  # a failing run is reported in the status and must not end the loop
            st["last_error"] = f"{type(e).__name__}: {e}"[:500]
        finally:
            now = datetime.now(timezone.utc)
            st.update(running=False, last_tick=_iso(now), next_due=_iso(now + timedelta(seconds=interval_s)))
        await asyncio.sleep(interval_s)


def start() -> list[asyncio.Task]:
    """Start the job loops on the running event loop (FastAPI lifespan); none when LIVE_JOBS=0."""
    if not enabled():
        return []
    env = os.environ.get
    loops = [("watch", watcher.watch_once, float(env("WATCH_INTERVAL_S", 60)), 0),
             ("scout", scout.batch, float(env("SCOUT_INTERVAL_H", 24)) * 3600, SCOUT_FIRST_DELAY_S)]
    if env("PARIVESH_SNAPSHOT", "1") != "0":
        loops.append(("parivesh_snapshot", portals.snapshot_once,
                      float(env("PARIVESH_SNAPSHOT_INTERVAL_H", 6)) * 3600, PORTALS_FIRST_DELAY_S))
    if bhoomi_enabled():
        every_d = int(env("BHOOMI_PULL_EVERY_D", portals.PULL_EVERY_D))
        loops.append(("bhoomi_rashi_pull", lambda: portals.pull_if_due(every_d), 86400.0, PORTALS_FIRST_DELAY_S))
    if research.enabled():
        loops.append(("research", research.batch, float(env("RESEARCH_INTERVAL_H", 24)) * 3600,
                      RESEARCH_FIRST_DELAY_S))
    return [asyncio.create_task(_every(job, fn, s, first), name=job) for job, fn, s, first in loops]


async def stop(tasks: list[asyncio.Task]) -> None:
    """Cancel the loops. A run already in its thread finishes first (a pipeline step is not interrupted)."""
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def status() -> dict:
    jobs = {j["job"]: j for j in db.latest_jobs()}
    return {"enabled": enabled(), "inbox_pending": len(watcher.pending()),
            "watch": {**STATUS["watch"], "last_run": jobs.get("ingest")},
            "scout": {**STATUS["scout"], "last_run": jobs.get("scout")},
            **{job: {**STATUS[job], "last_run": jobs.get(job)}
               for job in ("parivesh_snapshot", "bhoomi_rashi_pull", "research")},
            "bhoomi_pull_enabled": bhoomi_enabled()}


async def alert_stream(after: int | None, keys=None):
    """SSE lines: every alert with id > after (default: the newest at connect) as `event: alert`; with keys (a
    viewer's project keys, backend/access.py) only the alerts on those projects."""
    last = after if after is not None else await asyncio.to_thread(db.max_alert_id)
    yield ": connected\n\n"
    beat = time.monotonic()
    while True:
        for a in await asyncio.to_thread(db.alerts_after, last):
            last = a["id"]
            if keys is not None and a["project_key"] not in keys:
                continue
            yield f"id: {a['id']}\nevent: alert\ndata: {Alert(**a).model_dump_json(by_alias=True)}\n\n"
        if time.monotonic() - beat >= HEARTBEAT_S:
            beat = time.monotonic()
            yield ": heartbeat\n\n"
        await asyncio.sleep(POLL_S)
