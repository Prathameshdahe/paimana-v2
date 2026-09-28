import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db  # noqa: E402
from backend.live import opinions, research, scheduler, scout, watcher  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import as_role  # noqa: E402 - tests/viewers.py


def test_scheduler_is_off_in_tests():
    assert scheduler.start() == []  # LIVE_JOBS=0 from conftest.py
    with TestClient(app) as c:
        as_role(c, "ipmd")
        s = c.get("/api/live/status").json()
    assert s["enabled"] is False and s["watch"]["lastRun"] is None and s["scout"]["nextDue"] is None
    assert isinstance(s["inboxPending"], int)


def test_scheduler_runs_both_loops_when_on(monkeypatch):
    calls = []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setenv("WATCH_INTERVAL_S", "0.05")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")  # the portal loops: tests/test_portals.py
    monkeypatch.setenv("RESEARCH_AGENT", "0")     # the research loop: tests/test_research_agent.py
    monkeypatch.setenv("SECOND_OPINION_JOB", "0")  # the second-opinion loop: tests/test_second_opinion_job.py
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    monkeypatch.setattr(scheduler, "SCOUT_FIRST_DELAY_S", 0.1)
    monkeypatch.setattr(watcher, "watch_once", lambda: calls.append("watch"))
    monkeypatch.setattr(scout, "batch", lambda: calls.append("scout") or 1 / 0)  # a failing run keeps the loop

    async def main():
        tasks = scheduler.start()
        await asyncio.sleep(0.4)
        await scheduler.stop(tasks)
        return tasks
    tasks = asyncio.run(main())
    assert len(tasks) == 2 and all(t.cancelled() for t in tasks)
    assert calls.count("watch") >= 3 and calls.count("scout") == 1
    assert scheduler.STATUS["scout"]["last_error"].startswith("ZeroDivisionError")
    assert scheduler.STATUS["watch"]["last_error"] is None and scheduler.STATUS["watch"]["next_due"]


def test_a_run_past_its_time_limit_is_an_error_and_the_loop_and_process_go_on(monkeypatch):
    """The scheduler's per-job deadline: an overrun is logged and recorded as the job's last_error, the job is told
    to stop (the LLM jobs' flags), its thread is left to finish on its own, the loop ticks on and nothing is killed."""
    calls, stopped_seen = [], []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setenv("WATCH_INTERVAL_S", "0.05")
    monkeypatch.setenv("SCOUT_INTERVAL_H", "0.0003")      # about 1 s: the next run starts after the test's look
    monkeypatch.setenv("RESEARCH_INTERVAL_H", "0.0003")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")
    monkeypatch.setenv("SECOND_OPINION_JOB", "0")
    monkeypatch.setenv("RESEARCH_AGENT", "1")
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    monkeypatch.setattr(scheduler, "STATUS", {j: dict(v) for j, v in scheduler.STATUS.items()})
    monkeypatch.setattr(scheduler, "MAX_RUNTIME_S", {**scheduler.MAX_RUNTIME_S, "scout": 0.05, "research": 0.05})
    monkeypatch.setattr(scheduler, "SCOUT_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(scheduler, "RESEARCH_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(watcher, "watch_once", lambda: calls.append("watch"))

    def slow_scout():
        time.sleep(0.3)               # a fetch that cannot be interrupted: past the limit, left to finish
        calls.append("scout done")

    def slow_research():
        deadline = time.monotonic() + 5
        while not research.stopping() and time.monotonic() < deadline:   # an LLM batch: stops at its next check
            time.sleep(0.01)
        stopped_seen.append(research.stopping())
        calls.append("research done")
    monkeypatch.setattr(scout, "batch", slow_scout)
    monkeypatch.setattr(research, "batch", slow_research)

    async def main():
        tasks = scheduler.start()
        await asyncio.sleep(0.2)
        errors = {j: scheduler.STATUS[j]["last_error"] for j in ("scout", "research")}
        running = {j: scheduler.STATUS[j]["running"] for j in ("scout", "research")}
        await asyncio.sleep(0.4)
        await scheduler.stop(tasks)
        return errors, running
    errors, running = asyncio.run(main())
    assert all(e and e.startswith("TimeoutError: the run exceeded 0 s") for e in errors.values()), errors
    assert not any(running.values())                          # the loop moved on while the thread ran
    assert "scout done" in calls and "research done" in calls and stopped_seen == [True]
    assert calls.count("watch") >= 3                          # the other loop kept ticking
    assert not research.stopping()                            # cleared once its thread ended
    assert scheduler.STATUS["watch"]["last_error"] is None


def test_stop_sets_the_llm_jobs_stop_flags_and_clears_them_when_their_threads_end(monkeypatch):
    seen = []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setenv("WATCH_INTERVAL_S", "60")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")
    monkeypatch.setenv("RESEARCH_AGENT", "1")
    monkeypatch.setenv("SECOND_OPINION_JOB", "1")
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    monkeypatch.setattr(scheduler, "STATUS", {j: dict(v) for j, v in scheduler.STATUS.items()})
    monkeypatch.setattr(scheduler, "SCOUT_FIRST_DELAY_S", 60)
    monkeypatch.setattr(scheduler, "RESEARCH_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(scheduler, "SECOND_OPINION_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(watcher, "watch_once", lambda: None)

    def batch(module):
        def run():
            deadline = time.monotonic() + 5
            while not module.stopping() and time.monotonic() < deadline:
                time.sleep(0.01)
            seen.append(module.__name__.rsplit(".", 1)[-1])
        return run
    monkeypatch.setattr(research, "batch", batch(research))
    monkeypatch.setattr(opinions, "batch", batch(opinions))

    async def main():
        tasks = scheduler.start()
        await asyncio.sleep(0.2)
        t0 = time.monotonic()
        await scheduler.stop(tasks)
        return time.monotonic() - t0
    took = asyncio.run(main())
    assert sorted(seen) == ["opinions", "research"] and took < 3      # both stopped at their next check
    assert not research.stopping() and not opinions.stopping()        # and the flags are clear again


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_stream_pushes_a_new_alert(monkeypatch):
    """A real server (TestClient buffers whole responses, an endless stream never returns)."""
    monkeypatch.setattr(scheduler, "POLL_S", 0.1)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none",
                                           timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        live = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
        as_role(live, "ipmd")                     # the stream reads the session cookie, nothing else
        with live.stream("GET", "/api/stream") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = r.iter_lines()
            assert next(lines) == ": connected"  # the stream has taken its starting id
            db.add_alerts([{"project_key": "PRJ-000001", "kind": "signal", "severity": 2, "title": "t"}])
            event = []
            for line in lines:
                if line.startswith(("id:", "event:", "data:")):
                    event.append(line)
                if line.startswith("data:"):
                    break
        assert event[0] == f"id: {db.max_alert_id()}" and event[1] == "event: alert"
        body = json.loads(event[2].removeprefix("data: "))
        assert body["kind"] == "signal" and body["projectKey"] == "PRJ-000001" and body["id"] == db.max_alert_id()
        live.close()
    finally:
        server.should_exit = True
        thread.join(10)
