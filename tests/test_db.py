"""backend/db: the app-state helpers on PostgreSQL (shapes as the callers expect), the ingest lineage, the health
probe and the one-time copy of an old SQLite database."""
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend import settings as cfg  # noqa: E402
from backend.db import migrate_sqlite  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import as_role, email_for  # noqa: E402 - tests/viewers.py

KEY, OTHER = "PRJ-000698", "PRJ-000733"
ADDRESS = "203.0.113.9"   # the test client's address: the audit rows record it


@pytest.fixture()
def client(fresh_db):
    with TestClient(app, client=(ADDRESS, 50000)) as c:
        yield c


def ipmd(client):
    return as_role(client, "ipmd")


def ministry_of(client, key):
    """Sign the client in as a ministry official of key's ministry; their headers."""
    ministry = client.get("/api/projects", params={"q": key}, headers=ipmd(client)).json()["items"][0]["ministry"]
    return as_role(client, "ministry", ministry=ministry)


def audit_rows():
    """The audit log oldest first, without the sign-ins the test accounts made."""
    return [(r["role"], r["action"], r["target"], r["detail"]) for r in reversed(db.audit_rows(size=100)["items"])
            if not r["action"].startswith("auth.")]


def signal(url, title="t", **kw):
    return {"url": url, "url_hash": url[-8:], "title": title, "source": "PTI",
            "published_at": "2026-08-02T06:00:00+00:00", "fetched_at": "2026-08-02T07:00:00+00:00", "summary": "",
            "category": "land", "severity": 2, "text_hash": title[:8], **kw}


# ------------------------------------------------------------------ through the API, as before

def test_seed_is_idempotent(client):
    ipmd(client)
    n_early = len(serving.early_notice())
    n_critical = len(serving.in_tier("Critical"))
    page = client.get("/api/alerts", params={"size": 100}).json()
    assert page["total"] == n_early + n_critical and len(page["items"]) == 100
    asof = client.get("/api/meta").json()["asof"]
    assert {a["source"] for a in page["items"]} == {f"seed:{asof}"}
    assert client.get("/api/alerts", params={"kind": "early_notice"}).json()["total"] == n_early
    crit = client.get("/api/alerts", params={"kind": "tier_up", "size": 5}).json()["items"]
    assert all(a["severity"] == 3 and a["detail"].startswith(f"entered Critical at asof {asof}") for a in crit)
    # a second start and a direct call seed nothing
    assert db.init() == 0 and db.seed() == 0
    with TestClient(app) as again:
        assert again.get("/api/alerts", headers=ipmd(again)).json()["total"] == n_early + n_critical
    jobs = client.get("/api/jobs").json()
    assert [j["job"] for j in jobs] == ["seed_alerts"] and jobs[0]["summary"]["alerts"] == n_early + n_critical


def test_alert_filters_and_bounds(client):
    ipmd(client)
    assert client.get("/api/alerts", params={"size": 101}).status_code == 422
    assert client.get("/api/alerts", params={"kind": "nope"}).status_code == 422
    assert client.get("/api/alerts", params={"since": "2999-01-01"}).json()["total"] == 0
    assert client.get("/api/alerts", params={"since": "2000-01-01"}).json()["total"] > 0


def test_ack_flow_writes_audit(client):
    h = ipmd(client)
    first = client.get("/api/alerts", params={"acked": False, "size": 1}).json()["items"][0]
    r = client.post(f"/api/alerts/{first['id']}/ack", json={"role": "ipmd_analyst"}, headers=h)
    assert r.status_code == 200 and r.json()["ackedBy"] == "ipmd_analyst" and r.json()["ackedAt"]
    assert client.get("/api/alerts", params={"acked": True}).json()["total"] == 1
    # a later ack does not overwrite the first, but is still logged
    again = client.post(f"/api/alerts/{first['id']}/ack", json={"role": "ministry_official"},
                        headers=ministry_of(client, first["projectKey"])).json()
    assert again["ackedBy"] == "ipmd_analyst"
    assert audit_rows() == [("ipmd_analyst", "alert.ack", str(first["id"]), None),
                            ("ministry_official", "alert.ack", str(first["id"]), "already acked by ipmd_analyst")]
    # every write's row says who (account and email) and from where
    row = next(r for r in db.audit_rows(action="alert.ack")["items"] if r["role"] == "ipmd_analyst")
    assert row["email"] == email_for("ipmd_analyst") and row["user_id"] and row["ip"] == ADDRESS
    h = ipmd(client)
    assert client.post("/api/alerts/999999/ack", json={"role": "ipmd_analyst"}, headers=h).status_code == 404
    assert client.post(f"/api/alerts/{first['id']}/ack", json={"role": "hacker"}, headers=h).status_code == 422


def test_watchlist_add_remove(client):
    key = client.get("/api/projects", params={"size": 1}, headers=ipmd(client)).json()["items"][0]["key"]
    h = ministry_of(client, key)
    assert client.get("/api/watchlist", params={"role": "ministry_official"}, headers=h).json()["total"] == 0
    body = {"role": "ministry_official", "projectKey": key}
    w = client.post("/api/watchlist", json=body, headers=h).json()
    assert w["total"] == 1 and w["items"][0]["projectKey"] == key and w["items"][0]["project"]["key"] == key
    assert client.post("/api/watchlist", json=body, headers=h).json()["total"] == 1
    assert client.get("/api/watchlist", params={"role": "ipmd_analyst"}, headers=ipmd(client)).json()["total"] == 0
    assert db.watched_keys() == [key]   # per role: the IPMD list is empty
    h = ministry_of(client, key)
    gone = client.delete("/api/watchlist", params={"role": "ministry_official", "project_key": key}, headers=h).json()
    assert gone["total"] == 0
    assert [a[1] for a in audit_rows()] == ["watchlist.add", "watchlist.add", "watchlist.remove"]
    assert client.post("/api/watchlist", json={**body, "projectKey": "PRJ-999999"}, headers=h).status_code == 404
    # the role sent must be the signed-in one
    assert client.post("/api/watchlist", json=body, headers=ipmd(client)).status_code == 403


def test_project_signals_empty_is_not_clear(client):
    key = client.get("/api/projects", params={"size": 1}, headers=ipmd(client)).json()["items"][0]["key"]
    s = client.get(f"/api/projects/{key}/signals").json()
    assert s == {"key": key, "lastScoutAt": None, "items": []}
    assert client.get("/api/projects/PRJ-999999/signals").status_code == 404


# ------------------------------------------------------------------ the helpers

def test_alert_shapes_keys_and_stream(fresh_db):
    n = db.add_alerts([{"project_key": KEY, "kind": "signal", "severity": 2, "title": "a", "asof": "2026-07-01",
                        "source": "https://n/1"},
                       {"project_key": OTHER, "kind": "tier_up", "severity": 3, "title": "b"},
                       {"project_key": None, "kind": "pipeline_error", "severity": 3, "title": "c"}])
    assert n == 3 and db.max_alert_id() == 3
    a = db.alerts(keys={KEY})["items"]
    assert [x["project_key"] for x in a] == [KEY] and a[0]["asof"] == "2026-07-01" and a[0]["acked_at"] is None
    assert a[0]["created_at"].endswith("+00:00") and len(a[0]["created_at"]) == 25
    assert db.alerts(keys=set())["total"] == 0 and db.alerts()["total"] == 3          # a project-less alert: no scope
    assert db.alerts(kind="pipeline_error")["items"][0]["project_key"] is None
    assert [x["id"] for x in db.alerts_after(1)] == [2, 3] and db.alerts_after(3) == []
    assert db.ack(1, "ipmd_analyst", keys={OTHER}) is None and db.ack(999, "ipmd_analyst") is None
    acked = db.ack(1, "ipmd_analyst", keys={KEY})
    assert acked["acked_by"] == "ipmd_analyst" and acked["acked_at"] and db.alerts(acked=True)["total"] == 1
    once = [{"project_key": KEY, "kind": "signal", "severity": 2, "title": "a", "source": "https://n/1"},
            {"project_key": KEY, "kind": "signal", "severity": 2, "title": "d", "source": "https://n/2"}]
    assert db.add_alerts_once(once) == 1
    assert db.add_alerts([]) == 0
    with pytest.raises(Exception, match="ck_alerts_kind"):
        db.add_alerts([{"project_key": KEY, "kind": "nope", "severity": 2}])


def test_jobs_sources_and_ingest_lineage(fresh_db):
    db.record_job("scout", "2026-09-28T10:00:00+00:00", "ok", {"items": 3, "when": Path("x")})
    db.record_job("scout", "2026-09-28T11:00:00+00:00", "error", {"error": "x\u0000y"})
    (j,) = db.latest_jobs()
    assert j["status"] == "error" and j["summary"] == {"error": "xy"} and j["started_at"] == "2026-09-28T11:00:00+00:00"
    assert not db.source_seen("abc", "v1")
    db.record_source({"sha256": "abc", "pipeline_version": "v1", "filename": "notes.csv", "kind": None,
                      "status": "error", "error": "not a report"})
    assert db.source_seen("abc", "v1") and not db.source_seen("abc", "v2")
    assert db.source_documents() == [] and db.load_runs() == []             # an unrecognised file leaves no lineage
    db.record_source({"sha256": "def", "pipeline_version": "v1", "filename": "Flash_2026-08.pdf", "kind": "flash_pdf",
                      "period": "2026-08", "rows": 1800, "status": "ok", "archived_as": "raw/pdf/2026-27/Flash.pdf",
                      "started_at": "2026-09-28T10:00:00+00:00", "rows_read": 1800, "rows_loaded": 1800,
                      "rows_failed": 0, "silver_version": "s1", "gold_version": "g1", "model_version": "m1"})
    (doc,) = db.source_documents("def")
    assert (doc["file_type"], doc["report_period"], doc["report_type"], doc["source_path"]) == (
        "pdf", "2026-08-01", "flash_pdf", "raw/pdf/2026-27/Flash.pdf")
    (run,) = db.load_runs("INGEST")
    assert (run["source_document_id"], run["status"], run["rows_loaded"], run["gold_version"]) == (
        doc["source_document_id"], "SUCCESS", 1800, "g1")
    db.record_source({"sha256": "def", "pipeline_version": "v2", "filename": "Flash_2026-08.pdf", "kind": "flash_pdf",
                      "period": "2026-08", "status": "error", "error": "gold broke"})
    assert len(db.source_documents()) == 1 and [r["status"] for r in db.load_runs()] == ["FAILED", "SUCCESS"]


def test_signals_links_feed_and_radar(fresh_db):
    ids = db.save_signals([signal("https://n/1", "Farmers stall land handover", links=[(KEY, 0.75, "places+context")]),
                           signal("https://n/2", "Mention only", severity=1, published_at="2026-08-01",
                                  links=[(KEY, 0.5, "places"), (OTHER, 0.5, "places")]),
                           signal("https://n/3", "Pool item", published_at=None)])
    assert ids == [1, 2, 3]
    known = db.known_signal_hashes(["ps://n/1", "zzz"], ["Pool ite"])     # the hashes of every signal hit
    assert known == ({"ps://n/1", "ps://n/3"}, {"Farmers ", "Pool ite"})
    assert db.known_signal_hashes([], []) == (set(), set())
    s = db.project_signals(KEY)
    assert s["last_scout_at"] is None and [x["id"] for x in s["items"]] == [1, 2]
    assert s["items"][1]["published_at"] == "2026-08-01T00:00:00+00:00" and s["items"][0]["method"] == "places+context"
    db.mark_scouted([(KEY, 2)])
    assert db.project_signals(KEY)["last_scout_at"] and set(db.scouted_at()) == {KEY}
    assert [ln["project_key"] for ln in db.signal_links(2)] == [KEY, OTHER] and len(db.signal_links()) == 3
    assert db.signals("https://n/3")[0]["published_at"] is None and len(db.signals()) == 3
    total, rows, links = db.signal_feed()
    assert total == 3 and [r["id"] for r in rows] == [1, 2, 3] and set(links) == {1, 2}   # undated last
    assert db.signal_feed(keys={OTHER})[0] == 1 and db.signal_feed(linked=False)[1][0]["id"] == 3
    assert db.signal_feed(severity=2, since="2026-08-02")[0] == 1 and db.signal_feed(state_keys=[])[0] == 0
    assert db.severe_links("2026-08-01") == [(1, KEY)]
    c = db.radar_counts("2026-08-01")
    assert (c["total"], c["n_window"], c["n_linked"], c["scouted"]) == (3, 2, 2, 1)
    assert c["by_severity"] == [{"name": 1, "n": 1}, {"name": 2, "n": 1}] and len(c["pairs"]) == 3
    assert db.radar_counts("2026-08-01", keys={OTHER})["total"] == 1
    news = db.news_for_index(1)
    assert [(n["id"], n["project_key"]) for n in news] == [(1, KEY), (2, OTHER)]
    assert [r["project_key"] for r in db.linked_signals(2)] == [KEY]
    assert db.index_marks() == {"signals": 3, "links": 3, "research": [0, None]}


def test_research_judgements_facts_and_verdicts(fresh_db):
    sid, pool = db.save_signals([signal("https://n/1", links=[(KEY, 0.75, "places+context")]), signal("https://n/2")])
    assert db.research_candidates(KEY, 10) == ([{**db.signals("https://n/1")[0], "method": "places+context"}],
                                               db.signals("https://n/2"))
    fact = {"fact_id": "f1", "project_key": KEY, "category": "land", "taxonomy": "land", "direction": "negative",
            "severity": 2, "event_date": "2026-08-01", "date_precision": "month", "published_date": "2026-08-02",
            "status": "unknown", "summary": "s", "headline": "h", "source": "PTI", "url": "https://n/1",
            "domain": "n", "match": "high", "match_reason": "r", "origin": "agent", "researched_on": "2026-08-03",
            "live": 1, "signal_id": sid, "model": "m", "prompt_version": "p", "judged_at": "2026-08-03T10:00:00+00:00"}
    judged = [{"signal_id": sid, "project_key": KEY, "relevant": 1, "verdict_json": json.dumps({"i": 1}), "model": "m",
               "prompt_version": "p", "judged_at": "2026-08-03T10:00:00+00:00"},
              {"signal_id": pool, "project_key": KEY, "relevant": None,
               "verdict_json": json.dumps({"rejected": ["x"]})}]
    assert db.save_research(KEY, judged, [fact], [pool]) == ["f1"]
    assert db.save_research(KEY, judged, [fact], [pool]) == []                       # kept as it is
    assert db.research_candidates(KEY, 10) == ([], [])
    assert db.signal_verdicts(KEY) == {sid: 1, pool: None}
    j = db.signal_judgements(signal_id=pool)
    assert json.loads(j[0]["verdict_json"]) == {"rejected": ["x"]} and j[0]["relevant"] is None
    (f,) = db.research_facts(KEY)
    assert (f["live"], f["event_date"], f["researched_on"], f["judged_at"]) == (
        1, "2026-08-01", "2026-08-03", "2026-08-03T10:00:00+00:00")
    assert db.research_facts(keys={OTHER}) == [] and db.research_facts(keys={KEY, OTHER}) == [f]
    assert [ln["method"] for ln in db.signal_links(pool)] == ["llm"]
    db.mark_researched(KEY, 2, 1)
    assert set(db.researched()) == {KEY} and db.researched(OTHER) == {}
    db.mark_researched(KEY, 3, 1, researched_at="2026-09-30T10:00:00+00:00")
    assert db.researched(KEY) == {KEY: "2026-09-30T10:00:00+00:00"}
    assert db.researched_rows(KEY)[0]["n_candidates"] == 3
    assert db.index_marks()["research"] == [1, "2026-08-03T10:00:00+00:00"]


def test_second_opinions_and_briefs(fresh_db):
    row = {"project_key": KEY, "evidence_hash": "h1", "model": "m", "prompt_version": "v1", "asof": "2026-07-01",
           "generated_at": "2026-09-01T00:00:00+00:00", "status": "ok", "narrative": "n [E1]",
           "evidence": [{"id": "E1"}]}
    db.save_second_opinion(row)
    got = db.second_opinion(KEY, "h1", "m")
    assert got == row and db.second_opinion(KEY, "h1", "other") is None
    db.save_second_opinion({**row, "last_rejected": {"prompt_version": "v2", "at": "2099-01-01T00:00:00+00:00"}})
    assert db.second_opinion_times() == {KEY: "2099-01-01T00:00:00+00:00"}
    db.save_second_opinion({**row, "evidence_hash": "h2", "generated_at": "2026-09-02T00:00:00+00:00",
                            "status": "rejected"})
    assert [o["evidence_hash"] for o in db.second_opinions(KEY)] == ["h2", "h1"] and len(db.second_opinions()) == 2
    assert db.cached_brief(KEY, "2026-07-01", "mv") is None
    b = {"key": KEY, "asof": "2026-07-01", "model_version": "mv", "text": "t", "n_numbers_checked": 3, "attempts": 1,
         "generated_at": "2026-09-01T00:00:00+00:00"}
    db.save_brief(b)
    db.save_brief({**b, "text": "t2"})
    assert db.cached_brief(KEY, "2026-07-01", "mv") == {**b, "text": "t2"}


def test_audit_rows_and_health(fresh_db):
    db.audit("ipmd_analyst", "jobs.scout", "batch", "3 projects")
    db.audit("ministry_official", "jobs.watch", "inbox")
    page = db.audit_rows(action="jobs.scout")
    assert page["total"] == 1 and page["items"][0]["detail"] == "3 projects" and page["items"][0]["at"]
    assert db.audit_rows(user="ministry_official")["total"] == 1 and db.audit_rows(since="2999-01-01")["total"] == 0
    assert db.healthy() is True
    assert db.app._rows_or_none("SELECT * FROM app.no_such_table") == []


def test_health_probe_never_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody@127.0.0.1:9/nothing")
    cfg.reload()
    try:
        assert db.healthy() is False
    finally:
        monkeypatch.undo()
        cfg.reload()


# ------------------------------------------------------------------ the one-time SQLite copy

def old_sqlite(path: Path) -> None:
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript("""
            CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, project_key TEXT,
                kind TEXT NOT NULL, severity INTEGER NOT NULL, title TEXT, detail TEXT, asof TEXT, model_version TEXT,
                source TEXT, acked_by TEXT, acked_at TEXT);
            CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, url_hash TEXT, title TEXT,
                source TEXT, published_at TEXT, fetched_at TEXT, summary TEXT, category TEXT, severity INTEGER,
                text_hash TEXT);
            CREATE TABLE signal_projects (signal_id INTEGER NOT NULL, project_key TEXT NOT NULL, link_score REAL,
                method TEXT, PRIMARY KEY (signal_id, project_key));
            CREATE TABLE audit_log (at TEXT NOT NULL, role TEXT, action TEXT NOT NULL, target TEXT, detail TEXT);
            CREATE TABLE job_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, started_at TEXT,
                finished_at TEXT, status TEXT, summary_json TEXT);
            CREATE TABLE second_opinions (project_key TEXT NOT NULL, evidence_hash TEXT NOT NULL, model TEXT NOT NULL,
                prompt_version TEXT, asof TEXT, generated_at TEXT, json TEXT,
                PRIMARY KEY (project_key, evidence_hash, model));
            INSERT INTO alerts (id, created_at, project_key, kind, severity, title, asof) VALUES
                (5, '2026-09-27T15:17:36+00:00', 'PRJ-000001', 'tier_up', 3, 'old', '2026-07-01'),
                (9, '2026-09-27T15:17:37+00:00', NULL, 'pipeline_error', 3, 'err', NULL);
            INSERT INTO signals (id, url, url_hash, title, published_at, severity) VALUES
                (3, 'https://n/a', 'ha', 'A', '2026-02-11T08:00:00+00:00', 1), (7, 'https://n/b', 'hb', 'B', NULL, 2);
            INSERT INTO signal_projects VALUES (3, 'PRJ-000001', 0.75, 'places'), (7, 'PRJ-000002', NULL, 'llm');
            INSERT INTO audit_log VALUES ('2026-09-27T17:37:27+00:00', NULL, 'worker.trigger', 'worker_cycle', NULL),
                ('2026-09-27T17:37:44+00:00', 'ipmd_analyst', 'jobs.watch', 'inbox', '0 pending');
            INSERT INTO job_runs (id, job, started_at, finished_at, status, summary_json) VALUES
                (8, 'scout', '2026-09-28T09:41:35+00:00', '2026-09-28T09:44:48+00:00', 'ok', '{"queries": 186}');
            INSERT INTO second_opinions VALUES ('PRJ-004326', 'e1', 'qwen', 'v7', '2026-07-01',
                '2026-09-28T09:04:17+00:00', '{"status": "ok", "tier": "Critical", "narrative": "n [E1]"}');
        """)


def test_migrate_sqlite_copies_once_and_keeps_ids(fresh_db, tmp_path, capsys):
    path = tmp_path / "paimana.db"
    old_sqlite(path)
    assert migrate_sqlite.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "alerts                   2 in the file,       2 copied" in out
    assert "watchlist          not in the file" in out
    assert [a["id"] for a in db.alerts()["items"]] == [9, 5] and db.alerts()["items"][1]["asof"] == "2026-07-01"
    assert [s["id"] for s in db.signals()] == [3, 7] and db.signals()[1]["published_at"] is None
    assert db.signal_links(7) == [{"signal_id": 7, "project_key": "PRJ-000002", "link_score": None, "method": "llm"}]
    assert [(r["id"], r["role"], r["action"]) for r in db.audit_rows()["items"]] == [   # newest first
        (2, "ipmd_analyst", "jobs.watch"), (1, None, "worker.trigger")]
    assert db.latest_jobs()[0]["summary"] == {"queries": 186} and db.latest_jobs()[0]["id"] == 8
    assert db.second_opinion("PRJ-004326", "e1", "qwen")["narrative"] == "n [E1]"
    # the sequences moved past the copied ids
    assert db.add_alerts([{"project_key": "PRJ-000001", "kind": "signal", "severity": 1}]) == 1
    assert db.max_alert_id() == 10
    assert db.save_signals([signal("https://n/c")]) == [8]
    # a second run copies nothing
    assert migrate_sqlite.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "alerts                   2 in the file,       0 copied,       3 now in PostgreSQL" in out
    assert migrate_sqlite.main([str(tmp_path / "missing.db")]) == 2
