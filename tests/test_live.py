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
from backend.live import scheduler, scout, watcher  # noqa: E402
from backend.main import app  # noqa: E402


def test_scheduler_is_off_in_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
    assert scheduler.start() == []  # LIVE_JOBS=0 from conftest.py
    with TestClient(app, headers={"X-Paimana-Role": "ipmd_analyst"}) as c:
        s = c.get("/api/live/status").json()
    assert s["enabled"] is False and s["watch"]["lastRun"] is None and s["scout"]["nextDue"] is None
    assert isinstance(s["inboxPending"], int)


def test_scheduler_runs_both_loops_when_on(monkeypatch):
    calls = []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setenv("WATCH_INTERVAL_S", "0.05")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")  # the portal loops: tests/test_portals.py
    monkeypatch.setenv("RESEARCH_AGENT", "0")     # the research loop: tests/test_research_agent.py
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_stream_pushes_a_new_alert(tmp_path, monkeypatch):
    """A real server (TestClient buffers whole responses, an endless stream never returns)."""
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
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
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/stream?role=ipmd_analyst", timeout=10) as r:
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
    finally:
        server.should_exit = True
        thread.join(10)
