"""Role-scoped API (backend/access.py): each role sees its own projects, the public a redacted page, POLICY 403s."""
import asyncio
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving, store  # noqa: E402
from backend.live import scheduler  # noqa: E402
from backend.main import app  # noqa: E402

IPMD = {"X-Paimana-Role": "ipmd_analyst"}


def ministry(name):
    return {"X-Paimana-Role": "ministry_official", "X-Paimana-Ministry": quote(name)}


def agency(name):
    return {"X-Paimana-Role": "agency_official", "X-Paimana-Agency": quote(name)}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """No default headers: a request without any is the public."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))
        with TestClient(app) as c:
            yield c


@pytest.fixture(scope="module")
def scopes(client):
    s = client.get("/api/scopes").json()
    assert s["ministries"] and s["agencies"]
    return s


def total(client, path, headers, **params):
    r = client.get(path, headers=headers, params=params)
    assert r.status_code == 200, (path, r.text)
    return r.json()["total"]


def test_each_role_sees_its_own_projects(client, scopes):
    n = client.get("/api/portfolio").json()["kpis"]["nProjects"]
    assert client.get("/api/portfolio", headers=IPMD).json()["kpis"]["nProjects"] == n
    assert sum(m["n"] for m in scopes["ministries"]) == n
    m, a = scopes["ministries"][2], next(x for x in scopes["agencies"] if x["n"] >= 5)
    for h, want, col, val in ((ministry(m["name"]), m["n"], "ministry", m["name"]),
                              (agency(a["name"]), a["n"], "agency", None)):
        assert client.get("/api/portfolio", headers=h).json()["kpis"]["nProjects"] == want
        assert total(client, "/api/projects", h) == want
        rows = client.get("/api/projects", headers=h, params={"size": 100}).json()["items"]
        assert val is None or all(r[col] == val for r in rows)
        # a filter outside the scope finds nothing, it does not widen it
        other = next(x["name"] for x in scopes["ministries"] if x["name"] != rows[0]["ministry"])
        assert total(client, "/api/projects", h, ministry=other) == 0
    # alerts: only on the viewer's projects, never the project-less ones
    keys = serving.scope_keys(("ministry", m["name"]))
    alerts = client.get("/api/alerts", headers=ministry(m["name"]), params={"size": 100}).json()
    assert alerts["total"] < total(client, "/api/alerts", IPMD)
    assert all(x["projectKey"] in keys for x in alerts["items"])


def test_out_of_scope_project_is_404(client, scopes):
    coal, rail = scopes["ministries"][2]["name"], scopes["ministries"][1]["name"]
    key = client.get("/api/projects", headers=IPMD, params={"ministry": rail, "size": 1}).json()["items"][0]["key"]
    for path in (f"/api/projects/{key}", f"/api/projects/{key}/timeline", f"/api/projects/{key}/forecast",
                 f"/api/projects/{key}/signals"):
        assert client.get(path, headers=ministry(coal)).status_code == 404
        assert client.get(path, headers=ministry(rail)).status_code == 200


def test_public_project_page_is_redacted(client):
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    full = client.get(f"/api/projects/{key}", headers=IPMD).json()
    pub = client.get(f"/api/projects/{key}").json()
    assert full["scores"]["shapTop5"] and full["scores"]["monthsP95"] is not None
    assert full["provenance"]["modelVersion"] and full["provenance"]["sourceDocId"]
    assert pub["scores"]["shapTop5"] == [] and pub["scores"]["monthsP05"] is None
    assert pub["scores"]["monthsP95"] is None and pub["scores"]["costPctP95"] is None
    assert pub["scores"]["tier"] == full["scores"]["tier"] and pub["scores"]["monthsP50"] == full["scores"]["monthsP50"]
    prov = pub["provenance"]
    assert prov["modelVersion"] is None and prov["goldVersion"] is None and prov["sourceDocId"] is None
    assert prov["asof"] == full["provenance"]["asof"] and pub["review"] is None
    assert pub["latest"] == full["latest"]  # progress, cost, completion stay
    flagged = [r for r in full["riskProfile"] if r["state"] == "flagged"]
    assert pub["topRisksPlain"] == full["topRisksPlain"] and len(pub["topRisksPlain"]) == min(3, len(flagged))
    assert all(s.endswith(".") and len(s) < 90 for s in pub["topRisksPlain"])
    assert all(p["sourceDocId"] is None for p in client.get(f"/api/projects/{key}/timeline").json()["points"])
    for path in (f"/api/projects/{key}/forecast", f"/api/projects/{key}/brief", f"/api/projects/{key}/signals"):
        assert client.get(path).status_code == 403


@pytest.mark.parametrize("role, allowed", [
    ("public", {"/api/external/summary", "/api/scopes"}),
    ("agency_official", {"/api/external/summary", "/api/scopes", "/api/alerts", "/api/bottlenecks",
                         "/api/agencies/matrix", "/api/signals/feed", "/api/radar/summary", "/api/dispatch",
                         "/api/live/status", "/api/jobs"}),
    ("ministry_official", {"/api/external/summary", "/api/scopes", "/api/alerts", "/api/bottlenecks",
                           "/api/agencies/matrix", "/api/signals/feed", "/api/radar/summary", "/api/dispatch",
                           "/api/live/status", "/api/jobs", "/api/models"}),
])
def test_policy_403s(client, scopes, role, allowed):
    h = {"public": {}, "agency_official": agency(scopes["agencies"][0]["name"]),
         "ministry_official": ministry(scopes["ministries"][0]["name"])}[role]
    for path in ("/api/external/summary", "/api/scopes", "/api/alerts", "/api/bottlenecks", "/api/agencies/matrix",
                 "/api/signals/feed", "/api/radar/summary", "/api/dispatch", "/api/live/status", "/api/jobs",
                 "/api/models", "/api/worker-runs"):
        assert client.get(path, headers=h).status_code == (200 if path in allowed else 403), path
    for path in ("/api/jobs/watch", "/api/jobs/scout", "/api/worker-runs/trigger"):
        assert client.post(path, headers=h).status_code == 403, path
    if role != "ministry_official":
        assert client.post("/api/alerts/1/ack", headers=h).status_code == 403
    # the stream takes the viewer as query parameters: the public may not open it, a role without its scope is 400
    assert client.get("/api/stream", params={"role": role}).status_code == (403 if role == "public" else 400)


def test_bad_viewer_headers_are_400(client):
    assert client.get("/api/portfolio", headers={"X-Paimana-Role": "admin"}).status_code == 400
    assert client.get("/api/portfolio", headers={"X-Paimana-Role": "ministry_official"}).status_code == 400
    assert client.get("/api/portfolio", headers=ministry("Ministry of Nothing")).status_code == 400
    assert client.get("/api/portfolio", headers=agency("NOPE")).status_code == 400


def test_scoped_external_summary_adds_up(client, scopes):
    full = client.get("/api/external/summary", headers=IPMD).json()
    parts = [client.get("/api/external/summary", headers=ministry(m["name"])).json() for m in scopes["ministries"]]
    assert sum(p["nProjects"] for p in parts) == full["nProjects"]
    for f, block in full["factors"].items():
        assert sum(p["factors"][f]["n_flagged"] for p in parts) == block["n_flagged"], f
    assert sum(p["earlyNotice"]["n_projects"] for p in parts) == full["earlyNotice"]["n_projects"]
    keys = serving.scope_keys(("ministry", scopes["ministries"][0]["name"]))
    top = parts[0]["earlyNotice"]["top"]
    assert top and all(r["project_key"] in keys and r["evidence"] for r in top)


def test_bottlenecks_matrix_and_memos_in_scope(client, scopes):
    full = client.get("/api/bottlenecks", headers=IPMD, params={"size": 100}).json()
    m = scopes["ministries"][2]["name"]
    keys = serving.scope_keys(("ministry", m))
    cut = client.get("/api/bottlenecks", headers=ministry(m), params={"size": 100}).json()
    assert 0 < cut["total"] <= full["total"]
    for b in cut["items"]:
        assert b["nProjects"] >= 1 and all(t["key"] in keys for t in b["topMembers"])
        assert all(any(f"({k})" in e for k in keys) for e in b["evidence"])
        d = client.get(f"/api/bottlenecks/{b['bottleneckId']}", headers=ministry(m)).json()
        assert d["total"] == b["nProjects"] and all(x["key"] in keys for x in d["members"])
    hidden = {b["bottleneckId"] for b in full["items"]} - {b["bottleneckId"] for b in cut["items"]}
    for bid in hidden:
        assert client.get(f"/api/bottlenecks/{bid}", headers=ministry(m)).status_code == 404

    a = next(x for x in scopes["agencies"] if x["n"] >= 5)["name"]
    pts = client.get("/api/agencies/matrix", headers=agency(a)).json()["points"]
    assert [p["agency"] for p in pts if p["isSelf"]] == [a] and len(pts) > 1  # peers shown, own flagged
    mpts = client.get("/api/agencies/matrix", headers=ministry(m)).json()["points"]
    assert 0 < len(mpts) < len(client.get("/api/agencies/matrix", headers=IPMD).json()["points"])

    drafts = store.load_dispatch_drafts()
    assert len(client.get("/api/dispatch", headers=IPMD).json()) == len(drafts)
    for h, role in ((agency(a), "agency_official"), (ministry(m), "ministry_official")):
        seen = client.get("/api/dispatch", headers=h).json()
        assert all(d["recommendedRecipientRole"] == role for d in seen)
    other = next((d for d in drafts if d["recommended_recipient_role"] != "ipmd_analyst"), None)
    if other:  # IPMD sees it but decides only its own memos (checked before anything is written)
        r = client.post("/api/approvals", headers=IPMD, json={"draftId": other["id"], "decision": "approved"})
        assert r.status_code == 403


def test_stream_skips_alerts_outside_the_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
    monkeypatch.setattr(scheduler, "POLL_S", 0.05)
    db.init()
    start = db.max_alert_id()
    db.add_alerts([{"project_key": "PRJ-OUT", "kind": "signal", "severity": 2, "title": "out"},
                   {"project_key": "PRJ-IN", "kind": "signal", "severity": 2, "title": "in"}])

    async def first_event():
        async for line in scheduler.alert_stream(start, frozenset({"PRJ-IN"})):
            if line.startswith("id:"):
                return line
    line = asyncio.run(asyncio.wait_for(first_event(), 10))
    assert '"projectKey":"PRJ-IN"' in line and "PRJ-OUT" not in line
