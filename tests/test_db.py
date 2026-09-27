import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
    with TestClient(app) as c:
        yield c


def audit_rows():
    with closing(sqlite3.connect(db.path())) as con:
        return con.execute("SELECT role, action, target, detail FROM audit_log ORDER BY rowid").fetchall()


def test_seed_is_idempotent(client):
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
        assert again.get("/api/alerts").json()["total"] == n_early + n_critical
    jobs = client.get("/api/jobs").json()
    assert [j["job"] for j in jobs] == ["seed_alerts"] and jobs[0]["summary"]["alerts"] == n_early + n_critical


def test_alert_filters_and_bounds(client):
    assert client.get("/api/alerts", params={"size": 101}).status_code == 422
    assert client.get("/api/alerts", params={"kind": "nope"}).status_code == 422
    assert client.get("/api/alerts", params={"since": "2999-01-01"}).json()["total"] == 0
    assert client.get("/api/alerts", params={"since": "2000-01-01"}).json()["total"] > 0


def test_ack_flow_writes_audit(client):
    first = client.get("/api/alerts", params={"acked": False, "size": 1}).json()["items"][0]
    r = client.post(f"/api/alerts/{first['id']}/ack", json={"role": "ipmd_analyst"})
    assert r.status_code == 200 and r.json()["ackedBy"] == "ipmd_analyst" and r.json()["ackedAt"]
    assert client.get("/api/alerts", params={"acked": True}).json()["total"] == 1
    # a later ack does not overwrite the first, but is still logged
    again = client.post(f"/api/alerts/{first['id']}/ack", json={"role": "ministry_official"}).json()
    assert again["ackedBy"] == "ipmd_analyst"
    assert audit_rows() == [("ipmd_analyst", "alert.ack", str(first["id"]), None),
                            ("ministry_official", "alert.ack", str(first["id"]), "already acked by ipmd_analyst")]
    assert client.post("/api/alerts/999999/ack", json={"role": "ipmd_analyst"}).status_code == 404
    assert client.post(f"/api/alerts/{first['id']}/ack", json={"role": "hacker"}).status_code == 422


def test_watchlist_add_remove(client):
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    assert client.get("/api/watchlist", params={"role": "agency_official"}).json()["total"] == 0
    body = {"role": "agency_official", "projectKey": key}
    w = client.post("/api/watchlist", json=body).json()
    assert w["total"] == 1 and w["items"][0]["projectKey"] == key and w["items"][0]["project"]["key"] == key
    assert client.post("/api/watchlist", json=body).json()["total"] == 1
    assert client.get("/api/watchlist", params={"role": "ipmd_analyst"}).json()["total"] == 0  # per role
    gone = client.delete("/api/watchlist", params={"role": "agency_official", "project_key": key}).json()
    assert gone["total"] == 0
    assert [a[1] for a in audit_rows()] == ["watchlist.add", "watchlist.add", "watchlist.remove"]
    assert client.post("/api/watchlist", json={**body, "projectKey": "PRJ-999999"}).status_code == 404


def test_project_signals_empty_is_not_clear(client):
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    s = client.get(f"/api/projects/{key}/signals").json()
    assert s == {"key": key, "lastScoutAt": None, "items": []}
    assert client.get("/api/projects/PRJ-999999/signals").status_code == 404
