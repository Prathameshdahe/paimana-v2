import inspect
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import app  # noqa: E402
from llm import worker  # noqa: E402

MAX_ROWS = 100


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))  # startup seeds the app DB
        with TestClient(app) as c:
            yield c


def project_rows(body):
    """Every list of project-like dicts (anything with a key or projectKey) anywhere in a response."""
    found = []
    if isinstance(body, dict):
        for v in body.values():
            found += project_rows(v)
    elif isinstance(body, list):
        if body and all(isinstance(x, dict) and ("key" in x or "projectKey" in x) for x in body):
            found.append(body)
        for v in body:
            found += project_rows(v)
    return found


def test_meta_has_versions_and_caveats(client):
    m = client.get("/api/meta").json()
    assert m["nCurrent"] > 0 and m["nUntiered"] >= 0
    for k in ("asof", "modelVersion", "goldVersion", "silverVersion", "latestReportPeriod"):
        assert m[k]
    assert any("2023" in c for c in m["caveats"]) and any("Maharashtra" in c for c in m["caveats"])


def test_portfolio_kpis_and_tiers(client):
    p = client.get("/api/portfolio").json()
    n = p["kpis"]["nProjects"]
    assert sum(t["n"] for t in p["tiers"]) == n
    assert [t["tier"] for t in p["tiers"]] == ["Critical", "High", "Medium", "Low", "untiered"]
    assert sum(s["n"] for s in p["byState"]) == n
    assert len(p["top"]) == 20
    probs = [t["pAny2q"] for t in p["top"]]
    assert probs == sorted(probs, reverse=True)
    sector = p["bySector"][0]["name"]
    f = client.get("/api/portfolio", params={"sector": sector}).json()
    assert f["kpis"]["nProjects"] == p["bySector"][0]["n"]
    assert all(t["sector"] == sector for t in f["top"])


def test_pagination_bounds(client):
    first = client.get("/api/projects").json()
    assert first["size"] == 50 and len(first["items"]) == 50 and first["total"] > 100
    big = client.get("/api/projects", params={"size": 100, "page": 2}).json()
    assert len(big["items"]) == 100
    last_page = -(-first["total"] // 100)
    tail = client.get("/api/projects", params={"size": 100, "page": last_page}).json()
    assert len(tail["items"]) == first["total"] - 100 * (last_page - 1)
    assert client.get("/api/projects", params={"page": last_page + 1, "size": 100}).json()["items"] == []
    for bad in ({"size": 101}, {"size": 0}, {"page": 0}, {"sort": "nope"}, {"tier": "Severe"}, {"flag": "x"}):
        assert client.get("/api/projects", params=bad).status_code == 422
    # pages do not overlap and follow the risk order
    a = client.get("/api/projects", params={"size": 20}).json()["items"]
    b = client.get("/api/projects", params={"size": 20, "page": 2}).json()["items"]
    assert not {r["key"] for r in a} & {r["key"] for r in b}
    assert a[-1]["pAny2q"] >= b[0]["pAny2q"]


def test_filters(client):
    crit = client.get("/api/projects", params={"tier": "Critical", "size": 100}).json()
    assert crit["total"] > 0 and all(r["tier"] == "Critical" for r in crit["items"])
    untiered = client.get("/api/projects", params={"tier": "untiered"}).json()
    assert untiered["total"] > 0 and all(r["tier"] is None and r["noCompletionDate"] for r in untiered["items"])
    for flag in ("land", "forest", "early_notice"):
        page = client.get("/api/projects", params={"flag": flag, "size": 100}).json()
        assert page["total"] > 0 and all(flag in r["flags"] for r in page["items"])
    road = client.get("/api/projects", params={"q": "nh", "sector": "Roads & Highways"}).json()
    assert road["total"] > 0 and all(r["sector"] == "Roads & Highways" for r in road["items"])
    by_name = client.get("/api/projects", params={"sort": "name", "size": 10}).json()["items"]
    names = [r["name"] for r in by_name]
    assert names == sorted(names)
    costly = client.get("/api/projects", params={"sort": "cost", "order": "asc", "size": 10}).json()["items"]
    costs = [r["anticipatedCostCr"] for r in costly]
    assert costs == sorted(costs)


def test_unknown_project_is_404(client):
    for path in ("/api/projects/PRJ-999999", "/api/projects/PRJ-999999/timeline",
                 "/api/projects/PRJ-999999/forecast", "/api/projects/nonsense"):
        assert client.get(path).status_code == 404


def test_detail_bundle_has_provenance(client):
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    d = client.get(f"/api/projects/{key}").json()
    assert d["key"] == key
    prov = d["provenance"]
    for k in ("asof", "modelVersion", "goldVersion", "silverVersion", "sourceDocId", "sourcePage", "period"):
        assert prov[k] is not None, k
    assert d["scores"]["pAny2q"] is not None and len(d["scores"]["shapTop5"]) == 5
    states = {r["state"] for r in d["riskProfile"]}
    assert states <= {"flagged", "clear", "unknown"} and len(d["riskProfile"]) >= 12
    assert "projectName" in d["master"] and "sourceDocId" in d["latest"]
    t = client.get(f"/api/projects/{key}/timeline").json()["points"]
    assert t and all(p["sourceDocId"] for p in t)
    assert [p["period"] for p in t] == sorted(p["period"] for p in t)
    f = client.get(f"/api/projects/{key}/forecast").json()
    assert len(f["scenarios"]) == 8 and "continue" in f["scenarios"][0]
    assert len(f["analogues"]) == 10 and f["analogueSummary"]
    assert all(b["lo"] <= b["mid"] <= b["hi"] for b in f["band"]) and f["bandMethod"]


def test_no_endpoint_returns_more_than_100_project_rows(client):
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    paths = ["/api/meta", "/api/portfolio", "/api/projects", "/api/projects?size=100", "/api/external/summary",
             "/api/models", f"/api/projects/{key}", f"/api/projects/{key}/timeline", f"/api/projects/{key}/forecast"]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, path
        for rows in project_rows(r.json()):
            assert len(rows) <= MAX_ROWS, path


def test_external_and_models(client):
    e = client.get("/api/external/summary").json()
    assert e["earlyNotice"]["n_projects"] == client.get("/api/projects", params={"flag": "early_notice"}).json()[
        "total"]
    assert e["coverage"]["land_linked"] > 0 and e["caveats"]
    m = client.get("/api/models").json()
    assert m["champions"]["y_any_h2"]["run_id"] == m["runId"] and m["backtest"] and m["ablation"]
    assert "prAuc" in m["backtest"][0]


def test_forecaster_is_pure_lookup_on_top_projects():
    assert "call_llm(" not in inspect.getsource(worker.forecaster)
    from backend import serving
    top = serving.top_projects(worker.TOP_N)
    assert len(top) == worker.TOP_N
    out = worker.forecaster(top[0]["project_key"])
    assert out["p_any_2q"] == top[0]["p_any_2q"] and out["model_version"]


def test_auditor_flags_zero_progress_with_overrun(monkeypatch):
    monkeypatch.setattr(worker, "call_llm", lambda *a, **k: None)  # no LM Studio in tests
    row = {"project_name": "test", "physical_progress_pct": 0, "cost_variation_pct": 12.5,
           "months_since_last_obs": 6, "dq_score": 1.0}
    issues, confidence, _ = worker.auditor(row)
    assert any("cost has already overrun" in i for i in issues)
    assert any("6 months" in i for i in issues)
    assert confidence < 1.0


def test_cache_is_dropped_when_the_data_version_changes(monkeypatch):
    from backend import serving
    before = serving.state()
    serving.meta()
    assert before["cache"]
    monkeypatch.setattr(serving, "_version", lambda: ("changed",))
    after = serving.state()
    assert after is not before and not after["cache"]
    assert serving.meta()["n_current"] == before["cache"][("meta", (), ())]["n_current"]


def test_a_failed_reload_keeps_serving_the_loaded_version(monkeypatch):
    # score writes predictions_latest.json before profile writes risk_profile_<month>: that window must not 500
    from backend import serving
    before = serving.state()
    calls = []

    def broken():
        calls.append(1)
        raise FileNotFoundError("risk_profile_2026-08.parquet")
    monkeypatch.setattr(serving, "_load", broken)
    monkeypatch.setattr(serving, "_version", lambda: ("half written",))
    assert serving.state() is before and serving.state() is before
    assert len(calls) == 1                                       # retried only after RETRY_S
    monkeypatch.setattr(serving, "RETRY_S", 0)
    assert serving.state() is before and len(calls) == 2
