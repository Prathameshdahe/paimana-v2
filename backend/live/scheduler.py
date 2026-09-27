"""Background jobs inside the backend process (docs/IMPLEMENTATION_GUIDE_v2.md A.2: in-process scheduler, no broker)
and the alert stream.

start() runs the inbox watcher every WATCH_INTERVAL_S seconds (default 60, first tick at start) and the scout batch
every SCOUT_INTERVAL_H hours (default 24, first run SCOUT_FIRST_DELAY_S after start); LIVE_JOBS=0 starts neither
(the tests). The blocking work runs in a thread (asyncio.to_thread), and the watcher and the scout each hold their
own lock, so a scheduled run never overlaps one started from the API. A run that ingests or scouts writes its
job_runs row; an idle watch tick only updates STATUS.

alert_stream() is the Server-Sent Events body of GET /api/stream: it polls SQLite every POLL_S seconds for alerts
with an id above the last one sent and writes a comment line every HEARTBEAT_S seconds so proxies keep it open.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from backend import db
from backend.schemas import Alert

from . import scout, watcher

SCOUT_FIRST_DELAY_S = 600
POLL_S, HEARTBEAT_S = 2.0, 15.0
STATUS = {job: {"interval_s": None, "running": False, "last_tick": None, "next_due": None, "last_error": None}
          for job in ("watch", "scout")}


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def enabled() -> bool:
    return os.environ.get("LIVE_JOBS", "1") != "0"


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
    """Start the two job loops on the running event loop (FastAPI lifespan); none when LIVE_JOBS=0."""
    if not enabled():
        return []
    watch_s = float(os.environ.get("WATCH_INTERVAL_S", 60))
    scout_s = float(os.environ.get("SCOUT_INTERVAL_H", 24)) * 3600
    return [asyncio.create_task(_every("watch", watcher.watch_once, watch_s, 0)),
            asyncio.create_task(_every("scout", scout.batch, scout_s, SCOUT_FIRST_DELAY_S))]


async def stop(tasks: list[asyncio.Task]) -> None:
    """Cancel the loops. A run already in its thread finishes first (a pipeline step is not interrupted)."""
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def status() -> dict:
    jobs = {j["job"]: j for j in db.latest_jobs()}
    return {"enabled": enabled(), "inbox_pending": len(watcher.pending()),
            "watch": {**STATUS["watch"], "last_run": jobs.get("ingest")},
            "scout": {**STATUS["scout"], "last_run": jobs.get("scout")}}


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
