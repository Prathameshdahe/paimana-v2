"""backend/live/opinions.py, the nightly job `second_opinion`, with a fake LLM (client.chat): order, skips, limit,
pauses, the job route and the scheduler loop."""
import asyncio
import json
import sys
from contextlib import closing
from itertools import islice
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.live import opinions, research, scheduler  # noqa: E402
from backend.main import app  # noqa: E402
from llm import client  # noqa: E402
from llm import second_opinion as so  # noqa: E402

KEY = "PRJ-000698"      # Medium: never in the batch, but it can be asked for by key


def fake_chat(calls):
    """client.chat answering as the evidence in the prompt allows: 'concern' on a current hold-up, else 'watch' on a
    minor or old issue, else 'none'; it cites the first item of that group."""
    def chat(messages, max_tokens=400, temperature=0.2, model=None):
        calls.append(messages)
        user = messages[1]["content"]
        groups, head = {}, None
        for line in user.split("<<<EVIDENCE")[1].splitlines():
            if line.startswith("E") and " | " in line:
                groups.setdefault(head, []).append(line.split(" | ")[0])
            elif line.endswith(":"):
                head = line.split(" (")[0]
        ok = user.split("This evidence allows concern ")[1].split(".")[0]
        concern, cite = next(((c, groups[g][0]) for c, g in (("concern", "Current hold-ups"),
                                                               ("watch", "Minor current issues"),
                                                               ("watch", "Old items")) if g in groups and c in ok),
                             ("none", next(iter(groups.values()))[0]))
        return json.dumps({"concern": concern, "headline": "The evidence is read",
                           "narrative": f"The evidence on the project is read here [{cite}], and the latest report "
                                        "is read as well.", "key_evidence": [cite],
                           "gaps": ["Nothing after the latest report"]})
    return chat


@pytest.fixture()
def job_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
    db.init()
    calls = []
    monkeypatch.setattr(client, "chat", fake_chat(calls))
    yield calls
    client._down_at = -1e9


def with_evidence(keys, n):
    """The first n of keys whose pack has evidence about the project."""
    return list(islice((k for k in keys if so.has_evidence(so.pack(k))), n))


def job():
    return {j["job"]: j for j in db.latest_jobs()}["second_opinion"]


def test_batch_keys_take_the_risky_tiers_least_recently_asked_first(job_db):
    keys = opinions.batch_keys()
    tiers = {t: {r["project_key"] for r in serving.in_tier(t)} for t in opinions.RISKY_TIERS}
    assert len(keys) == sum(map(len, tiers.values())) and KEY not in keys
    assert keys[0] in tiers["Critical"] and keys[-1] in tiers["Watch"]
    assert opinions.run([keys[0]], limit=1)["asked"] == 1
    assert opinions.batch_keys()[-1] == keys[0]           # asked: to the back of the rotation


def test_run_asks_what_is_due_up_to_the_limit_and_skips_the_rest(job_db, monkeypatch):
    keys = opinions.batch_keys()
    evidence = with_evidence(keys, 3)
    out = opinions.run(evidence, limit=2)
    assert out["asked"] == 2 and out["keys"] == evidence[:2] and out["ok"] == 2 and len(job_db) == 2
    assert out["concern_concern"] + out["concern_watch"] == 2 and job()["status"] == "ok"
    again = opinions.run(evidence[:2] + ["PRJ-999999"])
    assert again["asked"] == 0 and again["up_to_date"] == 2 and again["not_scored"] == 1 and len(job_db) == 2
    monkeypatch.setattr(so, "has_evidence", lambda p: False)
    assert opinions.run(evidence[2:])["no_evidence"] == 1 and len(job_db) == 2


def test_rejections_wait_for_new_evidence_and_old_prompts_are_redone(job_db, monkeypatch):
    key = next(k for k in opinions.batch_keys() if so.has_evidence(so.pack(k)))
    monkeypatch.setattr(client, "chat", lambda messages, **kw: job_db.append(messages) or "not JSON")
    out = opinions.run([key])
    assert out["rejected"] == 1 and len(job_db) == 2 and so.cached(key) is None
    assert opinions.run([key])["up_to_date"] == 1 and len(job_db) == 2       # not asked again every night
    monkeypatch.setattr(client, "chat", fake_chat(job_db))
    monkeypatch.setattr(so, "PROMPT_VERSION", "second-opinion-test")          # a new prompt: asked again
    assert opinions.run([key])["ok"] == 1 and so.cached(key)["prompt_version"] == "second-opinion-test"
    monkeypatch.setattr(so, "PROMPT_VERSION", "second-opinion-test-2")
    calls = len(job_db)
    assert so.generate(key)["cached"] and len(job_db) == calls                # a person asking gets it at once
    assert opinions.run([key])["ok"] == 1 and len(job_db) == calls + 1        # the job redoes it


def test_a_new_prompt_rejected_keeps_the_old_opinion_and_is_not_asked_every_night(job_db, monkeypatch):
    key = next(k for k in opinions.batch_keys() if so.has_evidence(so.pack(k)))
    assert opinions.run([key])["ok"] == 1
    old = so.cached(key)
    monkeypatch.setattr(so, "PROMPT_VERSION", "second-opinion-test")
    monkeypatch.setattr(so, "_now", lambda: "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(client, "chat", lambda messages, **kw: job_db.append(messages) or "not JSON")
    calls = len(job_db)
    assert opinions.run([key])["rejected"] == 1 and len(job_db) == calls + 2
    for night in range(2):                                                    # the next nights: not asked again
        assert opinions.due(key) == "up_to_date" and opinions.run([key])["up_to_date"] == 1
    assert len(job_db) == calls + 2
    kept = so.cached(key)                                                     # the accepted opinion stays
    assert kept["narrative"] == old["narrative"] and kept["prompt_version"] == old["prompt_version"]
    row = db.second_opinion(key, so.evidence_hash(so.pack(key)), client.LLM_CHAT_MODEL)
    assert row["last_rejected"]["prompt_version"] == "second-opinion-test" and row["last_rejected"]["reasons"]
    assert db.second_opinion_times()[key] == "2099-01-01T00:00:00+00:00"      # asked: to the back of the rotation
    assert opinions.batch_keys()[-1] == key
    monkeypatch.setattr(so, "PROMPT_VERSION", "second-opinion-test-2")         # a newer prompt: asked again
    monkeypatch.setattr(client, "chat", fake_chat(job_db))
    assert opinions.due(key) == "due" and opinions.run([key])["ok"] == 1
    assert "last_rejected" not in db.second_opinion(key, so.evidence_hash(so.pack(key)), client.LLM_CHAT_MODEL)


def test_run_stops_for_a_busy_chat_and_for_lm_studio_down(job_db, monkeypatch):
    keys = with_evidence(opinions.batch_keys(), 2)
    monkeypatch.setattr(client, "wait_chat_idle", lambda max_s=300, poll_s=0.5: False)
    out = opinions.run(keys)
    assert out["asked"] == 0 and "chat" in out["stopped"] and job()["status"] == "error" and not job_db
    monkeypatch.setattr(client, "wait_chat_idle", lambda max_s=300, poll_s=0.5: True)
    monkeypatch.setattr(client, "down_recently", lambda s=30: True)
    out = opinions.run(keys)
    assert out["asked"] == 0 and "unreachable" in out["stopped"] and not job_db
    with opinions._lock:
        assert opinions.run(keys) == {"busy": True}


def test_job_route_live_status_and_access(job_db):
    with TestClient(app, headers={"X-Paimana-Role": "ipmd_analyst"}) as c:
        r = c.post("/api/jobs/second-opinion", params={"project_key": KEY}).json()
        assert r["started"] is True and r["pending"] == 1
        got = c.get(f"/api/projects/{KEY}/second-opinion", params={"cached": 1}).json()   # the task has run
        assert got["status"] == "ok" and got["cached"] and len(job_db) == 1
        assert c.post("/api/jobs/second-opinion", params={"project_key": "PRJ-999999"}).status_code == 404
        live = c.get("/api/live/status").json()
        assert live["secondOpinion"]["lastRun"]["job"] == "second_opinion"
        assert live["secondOpinion"]["intervalS"] is None                     # LIVE_JOBS=0: no loop
        with opinions._lock:
            assert c.post("/api/jobs/second-opinion").json()["started"] is False
        with pytest.MonkeyPatch.context() as mp:
            ran = []
            mp.setattr(opinions, "run", lambda keys, limit=None: ran.append((len(keys), limit)))
            r = c.post("/api/jobs/second-opinion").json()
            assert r["started"] and ran == [(len(opinions.batch_keys()), opinions.per_run())]
    with TestClient(app) as pub:
        assert pub.post("/api/jobs/second-opinion", params={"project_key": KEY}).status_code == 403
    with closing(db.connect()) as con:
        assert con.execute("SELECT count(*) FROM audit_log WHERE action = 'jobs.second_opinion'").fetchone()[0] == 2


def test_scheduler_runs_the_second_opinion_loop(monkeypatch):
    ran = []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")
    monkeypatch.setenv("RESEARCH_AGENT", "0")
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    monkeypatch.setattr(scheduler, "STATUS", {j: dict(v) for j, v in scheduler.STATUS.items()})
    monkeypatch.setattr(scheduler, "SCOUT_FIRST_DELAY_S", 60)
    monkeypatch.setattr(scheduler, "SECOND_OPINION_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(scheduler.watcher, "watch_once", lambda: None)
    monkeypatch.setattr(opinions, "batch", lambda: ran.append("second_opinion"))
    monkeypatch.setattr(research, "batch", lambda: ran.append("research"))

    async def names():
        tasks = scheduler.start()
        await asyncio.sleep(0.3)
        await scheduler.stop(tasks)
        return [t.get_name() for t in tasks]
    monkeypatch.setenv("SECOND_OPINION_JOB", "1")
    assert asyncio.run(names()) == ["watch", "scout", "second_opinion"] and ran == ["second_opinion"]
    assert scheduler.STATUS["second_opinion"]["interval_s"] == 86400.0
    monkeypatch.setenv("SECOND_OPINION_JOB", "0")
    assert asyncio.run(names()) == ["watch", "scout"]
