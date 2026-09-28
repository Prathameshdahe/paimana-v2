"""Background jobs inside the backend process (docs/IMPLEMENTATION_GUIDE_v2.md A.2: in-process scheduler, no broker)
and the alert stream.

start() runs the inbox watcher every WATCH_INTERVAL_S seconds (default 60, first tick at start), the scout batch
every SCOUT_INTERVAL_H hours (default 24, first run SCOUT_FIRST_DELAY_S after start) and the public-portal jobs of
backend/live/portals.py: the PARIVESH dashboard snapshot every PARIVESH_SNAPSHOT_INTERVAL_H hours (default 6; a
date already archived is not fetched again, so this is one fetch a day with same-day retries; PARIVESH_SNAPSHOT=0
turns it off) and, only with BHOOMI_PULL=1, a daily check that pulls the Bhoomi Rashi register when the newest pull
is BHOOMI_PULL_EVERY_D days old (default 91, quarterly), and the research agent (backend/live/research.py) every
RESEARCH_INTERVAL_H hours (default 24, first run RESEARCH_FIRST_DELAY_S after start; RESEARCH_AGENT=0 turns it off),
up to RESEARCH_PER_RUN projects a run, and the LLM second opinion (backend/live/opinions.py) every
SECOND_OPINION_INTERVAL_H hours (default 24, first run SECOND_OPINION_FIRST_DELAY_S after start, 45 minutes: after
the research agent's first batch has started; SECOND_OPINION_JOB=0 turns it off), up to SECOND_OPINION_PER_RUN
projects a run. The two LLM jobs share the one local model through its gate (llm/client.py) and let chat requests go
first. LIVE_JOBS=0 starts none of them (the tests). The blocking
work runs in a thread (asyncio.to_thread), and every job holds its own lock, so a scheduled run never overlaps one
started from the API. A run that ingests, scouts or fetches writes its job_runs row; an idle tick (nothing in the
inbox, today already archived, pull not due) only updates STATUS.

Each run has a time limit (MAX_RUNTIME_S per job): past it the loop logs the overrun, records it in STATUS as the
job's last_error, tells the job to stop (the LLM jobs' stop flags; a pipeline step or a fetch cannot be interrupted
and finishes on its own) and moves on to the next tick; the thread is never killed and the process is never taken
down with it. stop() (the lifespan's shutdown) sets the LLM jobs' stop flags before cancelling the loops, so a
research or second-opinion batch in flight (scheduled, or started from the API) ends at its next check instead of
holding the restart for an hour, waits a little for the threads to end and then clears the flags.

alert_stream() is the Server-Sent Events body of GET /api/stream: it polls the database every POLL_S seconds for
alerts with an id above the last one sent and writes a comment line every HEARTBEAT_S seconds so proxies keep it
open.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from backend import db
from backend.schemas import Alert

from . import opinions, portals, research, scout, watcher

SCOUT_FIRST_DELAY_S = 600
PORTALS_FIRST_DELAY_S = 120
RESEARCH_FIRST_DELAY_S = 1800
SECOND_OPINION_FIRST_DELAY_S = 2700
POLL_S, HEARTBEAT_S = 2.0, 15.0
STOP_WAIT_S = 30.0   # stop() waits this long for the LLM jobs' threads to end before clearing their flags
# a run's time limit in seconds (module docstring); an ingest is about 2 minutes, a research batch about an hour
MAX_RUNTIME_S = {"watch": 4 * 3600.0, "scout": 2 * 3600.0, "parivesh_snapshot": 3600.0,
                 "bhoomi_rashi_pull": 4 * 3600.0, "research": 3 * 3600.0, "second_opinion": 2 * 3600.0}
STOPPERS = {"research": (research.stop, research.resume), "second_opinion": (opinions.stop, opinions.resume)}
STATUS = {job: {"interval_s": None, "running": False, "last_tick": None, "next_due": None, "last_error": None}
          for job in MAX_RUNTIME_S}
_inflight: set[asyncio.Future] = set()   # the runs in their threads (an overrunning one too, until it ends)
log = logging.getLogger(__name__)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def enabled() -> bool:
    return os.environ.get("LIVE_JOBS", "1") != "0"


def bhoomi_enabled() -> bool:
    """BHOOMI_PULL=1: the Bhoomi Rashi pull may run (scheduled and from the API); off by default."""
    return os.environ.get("BHOOMI_PULL", "0") == "1"


def _overrun(job: str, fut: asyncio.Future, max_s: float) -> None:
    """A run past its time limit: log it, tell the job to stop (the LLM jobs), and when its thread does end, log
    that and clear the flag; the thread itself is left alone (module docstring)."""
    log.error("%s: the run exceeded %.0f s; it was told to stop and is left to finish on its own", job, max_s)
    stopper, resumer = STOPPERS.get(job, (None, None))
    if stopper is not None:
        stopper()

    def finished(f: asyncio.Future) -> None:
        e = None if f.cancelled() else f.exception()
        log.warning("%s: the overrunning run ended%s", job, f" with {type(e).__name__}: {e}" if e else "")
        if resumer is not None:
            resumer()
    fut.add_done_callback(finished)


async def _every(job: str, fn, interval_s: float, first_delay_s: float) -> None:
    st = STATUS[job]
    st.update(interval_s=interval_s, next_due=_iso(datetime.now(timezone.utc) + timedelta(seconds=first_delay_s)))
    await asyncio.sleep(first_delay_s)
    while True:
        st["running"] = True
        max_s = MAX_RUNTIME_S.get(job)
        fut = asyncio.ensure_future(asyncio.to_thread(fn))
        _inflight.add(fut)
        fut.add_done_callback(_inflight.discard)
        try:
            await asyncio.wait_for(asyncio.shield(fut), max_s)   # shielded: a timeout or a cancel leaves it running
            st["last_error"] = None
        except TimeoutError as e:
            if fut.done():   # the job's own TimeoutError, not the limit
                st["last_error"] = f"{type(e).__name__}: {e}"[:500]
            else:
                st["last_error"] = f"TimeoutError: the run exceeded {max_s:.0f} s and was told to stop"
                _overrun(job, fut, max_s)
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
    if opinions.enabled():
        loops.append(("second_opinion", opinions.batch, float(env("SECOND_OPINION_INTERVAL_H", 24)) * 3600,
                      SECOND_OPINION_FIRST_DELAY_S))
    return [asyncio.create_task(_every(job, fn, s, first), name=job) for job, fn, s, first in loops]


def _llm_jobs_busy() -> bool:
    """A research or second-opinion run is in flight, scheduled or started from the API (POST /api/jobs/...)."""
    return research.busy() or opinions.busy()


async def stop(tasks: list[asyncio.Task]) -> None:
    """Set the LLM jobs' stop flags, cancel the loops, wait up to STOP_WAIT_S for the runs in flight to end (the
    scheduled ones and an LLM run started from the API: an LLM batch stops at its next check; a pipeline step or a
    fetch finishes first, it is not interrupted) and clear the flags again when they have, so a later start() runs
    the jobs."""
    for stopper, _ in STOPPERS.values():
        stopper()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    deadline = time.monotonic() + STOP_WAIT_S
    pending = [f for f in _inflight if not f.done()]
    if pending:
        await asyncio.wait(pending, timeout=STOP_WAIT_S)
    while _llm_jobs_busy() and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    if not _inflight and not _llm_jobs_busy():
        for _, resumer in STOPPERS.values():
            resumer()
    else:
        log.warning("a job run is still in its thread; the process waits for it at exit")


def status() -> dict:
    jobs = {j["job"]: j for j in db.latest_jobs()}
    return {"enabled": enabled(), "inbox_pending": len(watcher.pending()),
            "watch": {**STATUS["watch"], "last_run": jobs.get("ingest")},
            "scout": {**STATUS["scout"], "last_run": jobs.get("scout")},
            **{job: {**STATUS[job], "last_run": jobs.get(job)}
               for job in ("parivesh_snapshot", "bhoomi_rashi_pull", "research", "second_opinion")},
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
