"""Role-scoped API (backend/access.py): each role sees its own projects, the public a redacted page, POLICY 403s."""
import asyncio
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving, store  # noqa: E402
from backend.live import scheduler, scout  # noqa: E402
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
    for f in ("physicalProgressPct", "anticipatedCostCr", "expenditureCr", "anticipatedCompletion"):
        assert pub["latest"][f] == full["latest"][f]  # progress, cost, completion stay
    assert full["latest"]["sourceDocId"] and pub["latest"]["sourceDocId"] is None and pub["latest"]["sourcePage"] is None
    assert [r["state"] for r in pub["riskProfile"]] == [r["state"] for r in full["riskProfile"]]
    assert all(r["evidence"] is None for r in pub["riskProfile"])  # no "P = 0.55 (High-tier cut ...)"
    assert all(e["sourceDocId"] is None for e in pub["external"]["events"])
    pub_rows = client.get("/api/projects", params={"size": 20}).json()["items"]
    full_rows = client.get("/api/projects", headers=IPMD, params={"size": 20}).json()["items"]
    assert any(r["monthsP95"] is not None and r["tierRankPct"] is not None for r in full_rows)
    assert all(r["monthsP95"] is None and r["tierRankPct"] is None for r in pub_rows)
    assert [r["tier"] for r in pub_rows] == [r["tier"] for r in full_rows]
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
    for path in ("/api/jobs/watch", "/api/jobs/scout", "/api/jobs/research", "/api/jobs/second-opinion",
                 "/api/worker-runs/trigger"):
        assert client.post(path, headers=h).status_code == 403, path
    # the assistant is open to every role (its tools cut what each one reads): a bad body is 422, never 403
    assert client.post("/api/chat", headers=h, json={"messages": []}).status_code == 422
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
    # the PARIVESH open list, remark staleness and land states are recounted in scope too
    assert sum(p["portal"]["n_open"] for p in parts) == full["portal"]["n_open"] == len(full["portal"]["open_list"])
    assert all(r["project_key"] in keys for r in parts[0]["portal"]["open_list"])
    assert sum(p["remarkFlags"]["n_projects_stale"] for p in parts) == full["remarkFlags"]["n_projects_stale"]
    rated = [sum(s["n_rated"] for s in x["landCoverage"]["by_state"]) for x in [full, *parts]]
    assert rated[0] == sum(rated[1:]) == full["coverage"]["land_linked"]


def test_parivesh_details_and_hidden_delay_are_redacted_for_the_public(client):
    full = client.get("/api/external/summary", headers=IPMD).json()["portal"]
    pub = client.get("/api/external/summary").json()["portal"]
    assert full["open_list"] and full["cases"] and pub["n_open"] == full["n_open"]
    assert pub["open_list"] == [] and pub["cases"] == [] and all(r["evidence"] == [] for r in pub["top_overdue"])
    pub_notice = client.get("/api/external/summary").json()["earlyNotice"]["top"]
    assert pub_notice and all(r["evidence"] == [] and r["factors"] for r in pub_notice)
    key = next(c["project_key"] for c in full["cases"] if c["current"])  # a remark-named PARIVESH proposal
    ext = client.get(f"/api/projects/{key}", headers=IPMD).json()["external"]
    assert ext["portal"]["stageAtAsof"] and ext["proposals"][0]["proposalNo"] and ext["remarkStatus"]
    assert ext["hiddenDelay"] and all(h["basis"] for h in ext["hiddenDelay"])
    pub_ext = client.get(f"/api/projects/{key}").json()["external"]
    assert pub_ext["portal"] is None and pub_ext["remarkStatus"] is None
    assert pub_ext["proposals"] == [] and pub_ext["hiddenDelay"] == []


def test_hidden_delay_matches_the_risk_profile_groups():
    asof = date(2026, 7, 1)
    rs = {"fc_stage": "stage2_pending", "fc_stage_as_of": date(2023, 4, 1), "la_pct": 50.0,
          "la_pct_as_of": date(2026, 4, 1)}
    got = serving.hidden_delay({"la_state": "flagged"}, rs, None, asof)
    # a remark status older than four quarters is the last report's, not a current one
    assert [(h["factor"], h["group"], h["current"]) for h in got] == [
        ("forest_clearance", "fc_stage1", False), ("land_progress", "la_lt50", True),
        ("land_complexity", "cx_4_5", True)]
    # PARIVESH shows a final approval and nothing open: the remark forest stage no longer applies
    assert [h["factor"] for h in serving.hidden_delay(None, rs, {"n_final": 1, "n_open": 0}, asof)] == ["land_progress"]
    assert len(serving.hidden_delay(None, rs, {"n_final": 1, "n_open": 1}, asof)) == 2
    assert serving.hidden_delay({"la_state": "possible"}, {"fc_stage": "not_applicable", "la_pct": None}, None,
                                asof) == []


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


def test_memos_reach_the_official_they_are_addressed_to(client, scopes, tmp_path, monkeypatch):
    m, other = scopes["ministries"][2]["name"], scopes["ministries"][1]["name"]
    a = next(x for x in scopes["agencies"] if x["n"] >= 5)["name"]
    mkey, okey = (client.get("/api/projects", headers=ministry(n), params={"size": 1}).json()["items"][0]["key"]
                  for n in (m, other))
    akey = client.get("/api/projects", headers=agency(a), params={"size": 1}).json()["items"][0]["key"]
    monkeypatch.setattr(store, "DISPATCH_DRAFTS_PATH", str(tmp_path / "drafts.json"))
    store.append_dispatch_drafts([
        {"id": i, "project_id": k, "project_name": k, "draft_memo": "memo", "recommended_recipient_role": role,
         "status": "pending", "created_at": "2026-09-01T00:00:00+00:00", "evidence": []}
        for i, k, role in (("m", mkey, "ministry_official"), ("a", akey, "agency_official"),
                           ("o", okey, "ministry_official"))])
    ids = lambda h: [d["id"] for d in client.get("/api/dispatch", headers=h).json()]  # noqa: E731
    assert ids(IPMD) == ["m", "a", "o"]
    assert ids(ministry(m)) == ["m"] and ids(ministry(other)) == ["o"] and ids(agency(a)) == ["a"]
    r = client.post("/api/approvals", headers=ministry(other), json={"draftId": "m", "decision": "approved"})
    assert r.status_code == 404
    r = client.post("/api/approvals", headers=ministry(m), json={"draftId": "m", "decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_watchlist_delete_is_scoped(client, scopes):
    coal, rail = scopes["ministries"][2]["name"], scopes["ministries"][1]["name"]
    key = client.get("/api/projects", headers=ministry(rail), params={"size": 1}).json()["items"][0]["key"]
    watched = lambda: [i["projectKey"] for i in client.get("/api/watchlist", headers=ministry(rail)).json()["items"]]  # noqa: E731
    assert client.post("/api/watchlist", headers=ministry(rail), json={"projectKey": key}).status_code == 200
    assert client.post("/api/watchlist", headers=ministry(coal), json={"projectKey": key}).status_code == 404
    assert client.delete("/api/watchlist", headers=ministry(coal), params={"project_key": key}).status_code == 404
    assert key in watched()
    assert client.delete("/api/watchlist", headers=ministry(rail), params={"project_key": key}).status_code == 200
    assert key not in watched()


def test_signal_state_filter_keeps_the_viewer_scope(client, scopes):
    m = scopes["ministries"][2]["name"]
    keys = serving.scope_keys(("ministry", m))
    idx = scout.index()["projects"]
    mine = next(k for k, p in idx.items() if k in keys and p["state"])
    x = idx[mine]["state"]
    theirs_y = next(k for k, p in idx.items() if k not in keys and p["state"] not in (None, x))
    theirs_x = next(k for k, p in idx.items() if k not in keys and p["state"] == x)
    y = idx[theirs_y]["state"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(db.connect()) as con, con:
        sids = [con.execute("INSERT INTO signals (url, title, source, published_at, severity) VALUES (?, ?, 'PTI', ?, 3)",
                            [f"https://n/state-{i}", f"s{i}", now]).lastrowid for i in range(2)]
        con.executemany("INSERT INTO signal_projects (signal_id, project_key) VALUES (?, ?)",
                        [(sids[0], mine), (sids[0], theirs_y), (sids[1], theirs_x)])
    feed = lambda h, **p: client.get("/api/signals/feed", headers=h, params=p).json()  # noqa: E731
    base = feed(ministry(m))
    assert {h["state"]: h["n"] for h in base["stateHeat"]} == {x: 1}
    for st in (x, y):
        got = feed(ministry(m), state=st)
        assert got["stateHeat"] == base["stateHeat"]  # the viewer's heat, not every project of that state
        assert all(p["key"] in keys for s in got["items"] for p in s["projects"])
    assert feed(ministry(m), state=y)["total"] == 0  # its only link to y is not the viewer's project
    assert [s["id"] for s in feed(ministry(m), state=x)["items"]] == [sids[0]]
    ipmd = feed(IPMD, state=x)
    assert {h["state"] for h in ipmd["stateHeat"]} >= {x, y}  # IPMD: heat and links of every state
    assert {p["key"] for s in ipmd["items"] if s["id"] == sids[0] for p in s["projects"]} == {mine, theirs_y}


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
