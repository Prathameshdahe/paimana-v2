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
        with TestClient(app, headers={"X-Paimana-Role": "ipmd_analyst"}) as c:
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
    assert m["nCurrent"] > 0 and m["nWatch"] >= 0
    for k in ("asof", "modelVersion", "goldVersion", "silverVersion", "latestReportPeriod"):
        assert m[k]
    assert any("2023" in c for c in m["caveats"]) and any("Bhoomi Rashi" in c for c in m["caveats"])


def test_portfolio_kpis_and_tiers(client):
    p = client.get("/api/portfolio").json()
    n = p["kpis"]["nProjects"]
    assert sum(t["n"] for t in p["tiers"]) == n
    assert [t["tier"] for t in p["tiers"]] == ["Critical", "High", "Medium", "Low", "Watch"]
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
    watch = client.get("/api/projects", params={"tier": "Watch", "size": 100}).json()
    assert watch["total"] > 0 and all(r["tier"] == "Watch" and r["noCompletionDate"] for r in watch["items"])
    assert client.get("/api/projects", params={"tier": "untiered"}).status_code == 422
    from backend import serving   # the Watch list follows its order: flagged checklist rows, then P(cost revision)
    ws = {r["k"]: r["w"] for r in serving._rows(serving.state(), "SELECT project_key AS k, watch_score AS w FROM cur "
                                                "WHERE watch_score IS NOT NULL")}
    assert set(ws) == {r["key"] for r in watch["items"]} or watch["total"] > 100
    assert [ws[r["key"]] for r in watch["items"]] == sorted((ws[r["key"]] for r in watch["items"]), reverse=True)
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
    done = client.get("/api/projects", params={"sort": "progress", "size": 10}).json()["items"]
    progress = [r["physicalProgressPct"] for r in done]
    assert progress == sorted(progress, reverse=True)


def test_unknown_project_is_404(client):
    for path in ("/api/projects/PRJ-999999", "/api/projects/PRJ-999999/timeline",
                 "/api/projects/PRJ-999999/forecast"):
        assert client.get(path).status_code == 404
    assert client.get("/api/projects/nonsense").status_code == 400   # not even a key (tests/test_input_validation.py)


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


def test_near_complete_excludes_done_and_overdue_projects(client):
    rows = client.get("/api/projects", params={"near_complete": True, "sort": "progress", "size": 20}).json()
    asof = client.get("/api/meta").json()["asof"]
    assert rows["total"] > 0 and rows["items"][0]["physicalProgressPct"] < 100
    assert all(80 <= r["physicalProgressPct"] <= 99 and r["anticipatedCompletion"] >= asof for r in rows["items"])


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


def test_worker_cell_takes_the_llm_gate_per_call_so_a_chat_goes_between_calls(monkeypatch):
    """Each generation holds the gate on its own (worker._generate): a chat request that arrives during a project
    gets the LLM after the current call, not after the project's 4 calls (Segment 8 review, llm lens)."""
    import threading
    import time
    import types

    from backend.schemas import AnalystOutput, AuditorQuery, DispatcherOutput, ScoutOutput
    from llm import client

    held, call_s = [], 0.15
    samples = {AuditorQuery: AuditorQuery(query_text="q"), ScoutOutput: ScoutOutput(tags=[]),
               AnalystOutput: AnalystOutput(summary="s", bottlenecks=[], recommended_action="a"),
               DispatcherOutput: DispatcherOutput(draft_memo="m", recommended_recipient_role="ipmd_analyst")}

    def fake_call_llm(system, user, model):
        with client.gate(0) as free:      # the gate is held around the generation: another take must wait
            held.append(not free)
        time.sleep(call_s)
        return samples[model]
    rows = [{"project_key": "PRJ-000001", "project_name": "p", "months_since_last_obs": 5, "dq_score": 0.5}]
    event = {"status": "open", "category": "land", "first_seen": "a", "last_seen": "b", "evidence": "e",
             "source_doc_id": "d", "source_page": 1}
    monkeypatch.setattr(worker, "call_llm", fake_call_llm)
    monkeypatch.setattr(worker, "serving", types.SimpleNamespace(
        top_projects=lambda n: rows, meta=lambda: {"model_version": "m", "asof": "a"},
        state=lambda: {"pointer": {"path": "x/y"}},
        project=lambda k: {"scores": {}, "latest": {}, "provenance": {"model_version": "m"},
                           "external": {"events": [event]}}))
    monkeypatch.setattr(worker, "db", types.SimpleNamespace(project_signals=lambda k, limit: {"items": []}))
    monkeypatch.setattr(worker, "store", types.SimpleNamespace(append_worker_runs=lambda r: None,
                                                              append_dispatch_drafts=lambda d: None))
    t = threading.Thread(target=worker.run_worker_cycle)
    t.start()
    time.sleep(call_s / 2)                # a chat arrives during the auditor's call
    t0 = time.monotonic()
    with client.gate(2 * call_s, chat=True) as ok:
        waited = time.monotonic() - t0
    t.join(10)
    assert ok and waited < 1.5 * call_s   # after the current call, not after all four
    assert held == [True] * 4
    with client.gate(0) as free:          # nothing left held
        assert free


def test_duckdb_runs_under_a_memory_and_thread_cap(monkeypatch):
    import duckdb
    from backend import serving
    con = serving.state()["con"]
    limit, threads = con.execute("SELECT current_setting('memory_limit'), current_setting('threads')").fetchone()
    assert limit.endswith("GiB") and float(limit.split()[0]) < 2 and int(threads) == 4   # the 2GB / 4 defaults
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", " 512MiB ")
    monkeypatch.setenv("DUCKDB_THREADS", "2")
    fresh = duckdb.connect()
    serving._limits(fresh)
    assert fresh.execute("SELECT current_setting('memory_limit'), current_setting('threads')").fetchone() == (
        "512.0 MiB", 2)
    for bad in ("lots", "2GB; DROP TABLE cur", "-1GB", ""):
        monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", bad)
        with pytest.raises(ValueError):
            serving._limits(duckdb.connect())
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "1GB")
    monkeypatch.setenv("DUCKDB_THREADS", "0")
    with pytest.raises(ValueError):
        serving._limits(duckdb.connect())


def test_failed_reload_keeps_the_old_version_and_raises_one_pipeline_error_alert(client, monkeypatch):
    from backend import serving
    before = serving.state()
    n0 = client.get("/api/alerts", params={"kind": "pipeline_error"}).json()["total"]
    monkeypatch.setattr(serving, "_version", lambda: ("half-written",))
    monkeypatch.setattr(serving, "_load", lambda: 1 / 0)
    monkeypatch.setattr(serving, "_failed_at", 0.0)
    assert serving.state() is before                      # the loaded version is still served
    page = client.get("/api/alerts", params={"kind": "pipeline_error"}).json()
    assert page["total"] == n0 + 1
    a = page["items"][0]
    assert a["projectKey"] is None and "still served" in a["title"] and "ZeroDivisionError" in a["detail"]
    assert a["source"].startswith("reload:") and a["asof"] == str(before["asof"])
    assert serving.state() is before                      # not retried within RETRY_S
    monkeypatch.setattr(serving, "_failed_at", 0.0)
    assert serving.state() is before                      # retried, failed again: the alert is not repeated
    assert client.get("/api/alerts", params={"kind": "pipeline_error"}).json()["total"] == n0 + 1
    assert client.get("/api/meta").status_code == 200     # and the app answers from the old version


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
