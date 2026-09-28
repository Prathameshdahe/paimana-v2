"""pipeline/serve.py and backend/db/serve.py: the serving tables from a small synthetic bundle (uniqueness rules,
idempotency, the served model row, prediction history across model versions) and from a slice of the real data;
the pipeline.run step; the model seals of ml/registry.py and serving's refusal of a tampered champion file."""
import copy
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.db import serve as dbs  # noqa: E402
from ml import registry  # noqa: E402
from pipeline import run as pipeline_run  # noqa: E402
from pipeline import serve  # noqa: E402

ASOF = pd.Timestamp("2026-07-01")
TARGETS = ("y_any_h2", "y_date_push_h2", "y_cost_rev_h2", "y_any_h4")


def bundle(tmp_path: Path, model_version="lgbm-any2q-TEST") -> serve.Data:
    """Three projects: A current and Critical, B current and Low, C completed (not scored); one report file."""
    doc = tmp_path / "Flash_2026-07.pdf"
    doc.write_bytes(b"%PDF-1.4 test")
    master = pd.DataFrame([
        {"project_key": "PRJ-A", "project_name": "Alpha road", "ministry": "MoRTH", "sector": "Road", "agency": "NHAI",
         "state": "Odisha", "last_status": "ongoing", "in_latest_report": True},
        {"project_key": "PRJ-B", "project_name": "Beta line", "ministry": "MoR", "sector": "Railways", "agency": "NHAI",
         "state": "Bihar", "last_status": "ongoing", "in_latest_report": True},
        {"project_key": "PRJ-C", "project_name": None, "ministry": None, "sector": "Power", "agency": "OTHER",
         "state": None, "last_status": "completed", "in_latest_report": False}])
    aliases = pd.DataFrame([{"source_report_type": "clean_key", "source_row_id": row_id, "source_name": name,
                             "project_key": key, "match_score": score, "match_method": method, "review_status": status}
                            for row_id, name, key, score, method, status in [
                                ("NAME:a1", "Alpha road", "PRJ-A", 1.0, "new", "accepted"),
                                ("NAME:a2", "Alpha rd", "PRJ-A", 0.87, "name_attrs", "review"),
                                ("NAME:b1", "Beta line", "PRJ-B", 1.0, "new", "accepted"),
                                ("NAME:c1", "Gamma", "PRJ-C", 1.0, "new", "accepted"),
                                ("NAME:zz", "Unknown", "PRJ-Z", 1.0, "new", "accepted")]])
    obs = pd.DataFrame([
        {"project_key": "PRJ-A", "period": pd.Timestamp("2026-04-01"), "period_type": "flash",
         "source_doc_id": "docs/Flash_2026-04.pdf", "source_page": 3, "report_period_last": pd.Timestamp("2026-04-01"),
         "original_cost_cr": 100.0, "revised_cost_cr": None, "anticipated_cost_cr": 125.0, "expenditure_cr": 40.0,
         "physical_progress_pct": 35.0, "scheduled_completion": pd.Timestamp("2027-03-01"), "revised_completion": None,
         "anticipated_completion": pd.Timestamp("2027-06-01"), "status": "ongoing", "project_code": "700001",
         "delay_months": 3.0, "project_name": "Alpha road", "sector": "Road", "state": "Odisha", "agency": "NHAI"},
        {"project_key": "PRJ-A", "period": ASOF, "period_type": "flash", "source_doc_id": "docs/Flash_2026-07.pdf",
         "source_page": 4, "report_period_last": ASOF, "original_cost_cr": 100.0, "revised_cost_cr": 120.0,
         "anticipated_cost_cr": 130.0, "expenditure_cr": 60.0, "physical_progress_pct": 60.0,
         "scheduled_completion": pd.Timestamp("2027-03-01"), "revised_completion": pd.Timestamp("2027-09-01"),
         "anticipated_completion": pd.Timestamp("2027-12-01"), "status": "ongoing", "project_code": "700001",
         "delay_months": 9.0, "project_name": "Alpha road", "sector": "Road", "state": "Odisha", "agency": "NHAI"},
        {"project_key": "PRJ-B", "period": ASOF, "period_type": "flash", "source_doc_id": "docs/Flash_2026-07.pdf",
         "source_page": 9, "report_period_last": ASOF, "original_cost_cr": 0.0, "revised_cost_cr": None,
         "anticipated_cost_cr": 50.0, "expenditure_cr": 5.0, "physical_progress_pct": 10.0,
         "scheduled_completion": None, "revised_completion": None, "anticipated_completion": None, "status": "ongoing",
         "project_code": None, "delay_months": None, "project_name": "Beta line", "sector": "Railways",
         "state": "Bihar", "agency": "NHAI"},
        {"project_key": "PRJ-C", "period": pd.Timestamp("2020-01-01"), "period_type": "quarterly",
         "source_doc_id": "docs/Q.pdf", "source_page": 1, "report_period_last": pd.Timestamp("2020-01-01"),
         "original_cost_cr": 10.0, "revised_cost_cr": None, "anticipated_cost_cr": 10.0, "expenditure_cr": 10.0,
         "physical_progress_pct": 100.0, "scheduled_completion": pd.Timestamp("2019-12-01"), "revised_completion": None,
         "anticipated_completion": pd.Timestamp("2019-12-01"), "status": "completed", "project_code": None,
         "delay_months": 0.0, "project_name": "Gamma", "sector": "Power", "state": None, "agency": "OTHER"}])
    version = {"asof": ASOF, "model_version": model_version, "gold_version": "g1", "silver_version": "s1"}
    pred = pd.DataFrame([
        {"project_key": "PRJ-A", **version,
         "p_date_push_2q": 0.8, "p_cost_rev_2q": 0.3, "p_any_2q": 0.9, "p_any_4q": 0.95, "months_p05": 1.0,
         "months_p50": 6.0, "months_p95": 18.0, "cost_pct_p05": 0.0, "cost_pct_p50": 5.0, "cost_pct_p95": 40.0,
         "no_completion_date": False, "tier_rank_pct": 0.99, "tier_by_rank": "Critical", "tier": "Critical",
         "stagnation_override": False,
         "shap_top5_json": json.dumps([{"feature": "x", "value": 1, "contribution": 0.5}]),
         "stagnation_quarters": 0.0, "elapsed_ratio": 0.8, "project_name": "Alpha road", "sector": "Road",
         "state": "Odisha", "agency": "NHAI", "ministry": "MoRTH", "anticipated_cost_cr": 130.0, "expenditure_cr": 60.0,
         "physical_progress_pct": 60.0, "anticipated_completion": pd.Timestamp("2027-12-01")},
        {"project_key": "PRJ-B", **version,
         "p_date_push_2q": None, "p_cost_rev_2q": 0.05, "p_any_2q": None, "p_any_4q": None, "months_p05": None,
         "months_p50": None, "months_p95": None, "cost_pct_p05": None, "cost_pct_p50": None, "cost_pct_p95": None,
         "no_completion_date": True, "tier_rank_pct": None, "tier_by_rank": None, "tier": "Watch",
         "stagnation_override": True, "shap_top5_json": None, "stagnation_quarters": 3.0, "elapsed_ratio": None,
         "project_name": "Beta line", "sector": "Railways", "state": "Bihar", "agency": "NHAI", "ministry": "MoR",
         "anticipated_cost_cr": 50.0, "expenditure_cr": 5.0, "physical_progress_pct": 10.0,
         "anticipated_completion": pd.NaT}])
    pred_path = tmp_path / f"predictions_{model_version}.parquet"
    pred.to_parquet(pred_path, index=False)
    runs, champions = [], {}
    for i, key in enumerate(TARGETS):
        f = tmp_path / f"lightgbm_{key}.txt"
        f.write_text(f"tree {key}")
        entry_id = f"ML-TEST/lightgbm/{key}"
        runs.append({"entry_id": entry_id, "run_id": "ML-TEST", "target": key[:-3], "horizon": int(key[-1]),
                     "gold_version": "g1", "silver_version": "s1", "model": "lightgbm", "feature_list": ["f1", "f2"],
                     "categorical": [], "params": {"n": i},
                     "metrics": {"pooled": {"pr_auc": 0.7 + i / 100, "ece": 0.05}},
                     "windows": {"validation": ["2023-07-01", "2024-10-01"], "test": ["2026-01-01"], "flash": []},
                     "artifacts": {"model": str(f)}, **({"artifact_sha256": serve.sha256_of(f)} if i else {}),
                     "created_at": "2026-09-28T00:00:00+00:00"})
        champions[key] = {"entry_id": entry_id, "run_id": "ML-TEST", "model": "lightgbm", "since": "2026-09-28"}
    pointer = {"path": str(pred_path), "asof": "2026-07-01", "model_version": model_version, "gold_version": "g1",
               "models": {"p_any_2q": champions["y_any_h2"]["entry_id"]}}
    rp = pd.DataFrame([{"project_key": k, "dimension": d, "state": s, "evidence": f"{d} evidence", "source": "model",
                        "as_of_date": ASOF} for k, d, s in [("PRJ-A", "schedule_slip", "flagged"),
                                                            ("PRJ-A", "land_acquisition", "flagged"),
                                                            ("PRJ-A", "litigation", "clear"),
                                                            ("PRJ-B", "data_staleness", "flagged")]])
    scen = pd.DataFrame([{"project_key": "PRJ-A", "step": s, "quarter": ASOF + pd.DateOffset(months=3 * s),
                          "continue": 60 + s, "recover": 62 + s, "agency": 61 + s, "agency_basis": "sector",
                          "asof": ASOF} for s in (1, 2)])
    ana = pd.DataFrame([{"project_key": "PRJ-A", "asof": ASOF, "rank": 1, "analogue_key": "PRJ-C",
                         "analogue_name": "Gamma",
                         "analogue_period": pd.Timestamp("2019-01-01"), "target_period": pd.Timestamp("2020-01-01"),
                         "sector": "Power", "basis": "sector", "distance": 0.4, "y_months": 3.0, "y_cost_pct": 0.0,
                         "y_any": 1, "y_date_push": 1, "y_cost_rev": 0}])
    stats = pd.DataFrame([{"agency": "NHAI", "period": ASOF, "agency_n": 2.0, "n_slip": 1.0, "slip_rate_raw": 0.5,
                           "n_cost": 0.0, "cost_pct_raw": None, "last_outcome_period": pd.Timestamp("2026-04-01")},
                          {"agency": "NHAI", "period": pd.Timestamp("2025-07-01"), "agency_n": 1.0, "n_slip": 0.0,
                           "slip_rate_raw": 0.0, "n_cost": 0.0, "cost_pct_raw": None, "last_outcome_period": pd.NaT},
                          {"agency": "OTHER", "period": ASOF, "agency_n": 0.0, "n_slip": 0.0, "slip_rate_raw": None,
                           "n_cost": 0.0, "cost_pct_raw": None, "last_outcome_period": pd.NaT}])
    return serve.Data(master=master, aliases=aliases, observations=obs, predictions=pred, pointer=pointer,
                      registry={"runs": runs, "champions": champions, "decisions": []}, risk_profile=rp,
                      scenarios=scen, analogues=ana, agency_stats=stats, silver_version="s1",
                      merged_into={"PRJ-C": "PRJ-A"}, documents={"docs/Flash_2026-07.pdf": doc})


def by(table, col):
    return {r[col]: r for r in dbs.rows(table)}


def test_load_is_idempotent_and_keeps_the_uniqueness_rules(fresh_db, tmp_path):
    d = bundle(tmp_path)
    first = serve.load(d)
    again = serve.load(d)
    sent = {k: v for k, v in first.items() if k not in ("seconds", "load_run_id")}
    assert sent == {k: v for k, v in again.items() if k not in ("seconds", "load_run_id")}
    assert sent == {"core.projects": 3, "core.project_keys": 4, "ingest.source_documents": 1,
                    "core.project_timeline": 4, "ml.model_registry": 5, "ml.predictions": 2, "ml.risk_flags": 3,
                    "ml.forecasts": 2, "ml.agency_stats": 3}
    assert dbs.counts() == {**sent, "ingest.load_runs": 2}
    runs = db.load_runs("SERVING")
    assert [r["status"] for r in runs] == ["SUCCESS", "SUCCESS"] and runs[0]["rows_read"] == 4
    assert runs[0]["model_version"] == "lgbm-any2q-TEST" and runs[0]["report_period"] == "2026-07-01"

    projects = by("core.projects", "canonical_project_key")
    assert projects["PRJ-A"]["is_current"] and not projects["PRJ-C"]["is_current"]
    assert projects["PRJ-C"]["project_name"] == "PRJ-C" and projects["PRJ-A"]["line_ministry"] == "MoRTH"
    keys = by("core.project_keys", "source_project_key")
    assert set(keys) == {"NAME:a1", "NAME:a2", "NAME:b1", "NAME:c1"}          # the alias of an unknown key is skipped
    assert keys["NAME:a2"]["review_status"] == "review" and keys["NAME:a2"]["match_score"] == 0.87
    assert keys["NAME:c1"]["merged_into"] == "PRJ-A" and keys["NAME:a1"]["merged_into"] is None
    assert keys["NAME:a1"]["project_id"] == projects["PRJ-A"]["project_id"]

    docs = db.source_documents()
    assert len(docs) == 1 and docs[0]["source_path"] == "docs/Flash_2026-07.pdf" and docs[0]["file_type"] == "pdf"
    assert docs[0]["sha256"] == serve.sha256_of(d.documents["docs/Flash_2026-07.pdf"])
    assert docs[0]["report_period"] == "2026-07-01" and docs[0]["report_type"] == "flash"
    tl = {(r["project_id"], r["report_period"]): r for r in dbs.rows("core.project_timeline")}
    a_now = tl[projects["PRJ-A"]["project_id"], "2026-07-01"]
    assert a_now["source_document_id"] == docs[0]["source_document_id"] and a_now["source_page"] == 4
    assert tl[projects["PRJ-A"]["project_id"], "2026-04-01"]["source_document_id"] is None       # no file on disk
    assert (a_now["cost_overrun_cr"], a_now["cost_overrun_pct"], a_now["doc_anticipated"]) == (30.0, 30.0, "2027-12-01")
    b_now = tl[projects["PRJ-B"]["project_id"], "2026-07-01"]
    assert b_now["cost_overrun_pct"] is None and b_now["source_project_key"] is None     # original cost 0: no pct

    models = by("ml.model_registry", "model_version")
    assert len(models) == 5 and all(m["is_champion"] for m in models.values())
    served = models["lgbm-any2q-TEST"]
    assert served["target_name"] == serve.SERVED
    assert served["artifact_sha256"] == serve.sha256_of(Path(d.pointer["path"]))
    assert served["feature_list_json"] == ["f1", "f2"] and served["metrics_json"]["models"] == d.pointer["models"]
    for key in TARGETS:
        m = models[f"ML-TEST/lightgbm/{key}"]
        assert m["target_name"] == key and m["entry_id"] == f"ML-TEST/lightgbm/{key}" and m["run_id"] == "ML-TEST"
        assert m["artifact_sha256"] == serve.sha256_of(tmp_path / f"lightgbm_{key}.txt")   # sealed or hashed now
        assert m["validation_start_period"] == "2023-07-01" and m["test_end_period"] == "2026-01-01"

    preds = by("ml.predictions", "project_id")
    a, b = preds[projects["PRJ-A"]["project_id"]], preds[projects["PRJ-B"]["project_id"]]
    assert (a["risk_tier"], a["risk_rank"], a["p_risk"], a["risk_score"], a["p_any_4q"]) == (
        "Critical", 1, 0.9, 90.0, 0.95)
    assert (a["slip_interval_high"], a["months_p95"], a["cost_pct_p50"]) == (18.0, 18.0, 5.0)
    assert a["shap_top5_json"][0]["feature"] == "x" and a["prediction_payload"]["models"] == d.pointer["models"]
    assert a["prediction_payload"]["anticipated_completion"] == "2027-12-01T00:00:00"
    assert a["stagnation_override"] is False
    assert (b["risk_tier"], b["risk_rank"], b["p_risk"], b["stagnation_override"]) == ("Watch", None, None, True)
    assert b["model_id"] == served["model_id"]

    flags = {(r["project_id"], r["dimension"]): r for r in dbs.rows("ml.risk_flags")}
    assert set(flags) == {(projects["PRJ-A"]["project_id"], "schedule_slip"),
                          (projects["PRJ-A"]["project_id"], "land_acquisition"),
                          (projects["PRJ-B"]["project_id"], "data_staleness")}
    assert flags[projects["PRJ-A"]["project_id"], "schedule_slip"]["evidence_json"] == {
        "evidence": "schedule_slip evidence", "source": "model", "as_of_date": "2026-07-01"}
    fc = by("ml.forecasts", "project_id")
    pa = fc[projects["PRJ-A"]["project_id"]]["forecast_payload"]
    assert [s["step"] for s in pa["scenarios"]] == [1, 2] and pa["analogues"][0]["analogue_key"] == "PRJ-C"
    assert pa["completion"] == {"anticipated": "2027-12-01", "months_p05": 1.0, "months_p50": 6.0, "months_p95": 18.0}
    assert fc[projects["PRJ-B"]["project_id"]]["forecast_payload"]["scenarios"] == []
    stats = {(r["agency_name"], r["report_period"]): r for r in dbs.rows("ml.agency_stats")}
    now = stats["NHAI", "2026-07-01"]
    # A is red; B is Watch, which has no colour
    assert (now["project_count"], now["red_count"], now["amber_count"], now["green_count"]) == (2, 1, 0, 0)
    assert now["avg_risk_score"] == 90.0 and now["stats_payload"]["last_outcome_period"] == "2026-04-01"
    assert stats["NHAI", "2025-07-01"]["avg_risk_score"] is None and stats["OTHER", "2026-07-01"]["red_count"] == 0


def test_a_new_served_version_keeps_the_history(fresh_db, tmp_path):
    serve.load(bundle(tmp_path))
    serve.load(bundle(tmp_path, model_version="lgbm-any2q-TEST+NEW"))
    models = by("ml.model_registry", "model_version")
    assert models["lgbm-any2q-TEST"]["is_champion"] is False and models["lgbm-any2q-TEST+NEW"]["is_champion"] is True
    assert sum(m["is_champion"] for m in models.values()) == 5
    assert dbs.counts()["ml.predictions"] == 4          # prediction history is never overwritten
    with db.read() as con:
        import sqlalchemy as sa
        cur = con.execute(sa.text("SELECT canonical_project_key, model_version FROM ml.current_predictions")).all()
    assert sorted(cur) == [("PRJ-A", "lgbm-any2q-TEST+NEW"), ("PRJ-B", "lgbm-any2q-TEST+NEW")]


def test_a_failed_load_records_a_failed_run(fresh_db, tmp_path, monkeypatch):
    d = bundle(tmp_path)
    monkeypatch.setattr(dbs, "upsert_predictions", lambda rows: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        serve.load(d)
    (run,) = db.load_runs("SERVING")
    assert run["status"] == "FAILED" and run["rows_loaded"] == 3 + 4 + 1 + 4 + 5


def test_real_data_slice(fresh_db):
    ptr = json.loads((serve.GOLD / "predictions_latest.json").read_text(encoding="utf-8"))
    keys = set(pd.read_parquet(serve.ROOT / ptr["path"], columns=["project_key"])["project_key"].head(40))
    d = serve.read(keys)
    n = serve.load(d)
    assert n["core.projects"] == 40 and n["ml.predictions"] == 40 and n["core.project_keys"] >= 40
    assert n["core.project_timeline"] == len(d.observations) > 40 and n["ml.model_registry"] == 5
    assert n["ml.risk_flags"] == int((d.risk_profile["state"] == "flagged").sum()) > 0 and n["ml.forecasts"] == 40
    models = by("ml.model_registry", "model_version")
    assert models[d.pointer["model_version"]]["target_name"] == serve.SERVED
    assert all(models[c["entry_id"]]["artifact_sha256"] for c in d.registry["champions"].values())
    tiers = {r["risk_tier"] for r in dbs.rows("ml.predictions")}
    assert tiers <= {"Critical", "High", "Medium", "Low", "Watch"}
    assert serve.load(d)["core.project_timeline"] == n["core.project_timeline"]      # idempotent on real rows too


def test_pipeline_run_has_the_serve_step(monkeypatch):
    ran = []
    monkeypatch.setattr(serve, "main", lambda: ran.append("serve"))
    pipeline_run.main(["serve"])
    assert ran == ["serve"] and pipeline_run.ALL[-1] == "serve"


# ------------------------------------------------------------------ model integrity

def test_registry_is_sealed_and_verifies():
    reg = registry.load()
    checks = registry.verify(reg)
    assert set(checks) == set(reg["champions"]) and all(v["status"] == "ok" for v in checks.values()), checks
    assert all(e.get("artifact_sha256") for e in reg["runs"]
               if (registry.backtest.ROOT / e["artifacts"]["model"]).is_file())
    tampered = copy.deepcopy(reg)
    e = next(r for r in tampered["runs"] if r["entry_id"] == tampered["champions"]["y_any_h2"]["entry_id"])
    e["artifact_sha256"] = "0" * 64
    assert registry.verify(tampered)["y_any_h2"]["status"] == "mismatch"
    e["artifact_sha256"] = None
    assert registry.verify(tampered)["y_any_h2"]["status"] == "unsealed"
    e["artifacts"]["model"] = "model/runs/nowhere.txt"
    assert registry.verify(tampered)["y_any_h2"]["status"] == "missing"
    assert registry.seal(tampered) == []                     # nothing to seal: the file is missing
    e["artifacts"]["model"] = reg["runs"][0]["artifacts"]["model"]
    assert registry.seal(tampered) == [e["entry_id"]] and e["artifact_sha256"] == reg["runs"][0]["artifact_sha256"]


def test_serving_refuses_a_tampered_model_and_keeps_the_version(fresh_db, monkeypatch):
    before = serving.state()
    assert serving.verify_models()["y_any_h2"]["status"] == "ok"
    m = serving.models()
    assert m["champions"]["y_any_h2"]["artifact_sha256"] and all(
        r["artifact_sha256"] for r in m["registry"] if r["champion"])
    bad = {"y_any_h2": {"entry_id": "X/lightgbm/y_any_h2", "path": "model/runs/X/lightgbm_y_any_h2.txt",
                        "status": "mismatch", "sha256": "0" * 64}}
    monkeypatch.setattr(registry, "verify", lambda reg, root=None: bad)
    with pytest.raises(serving.ModelIntegrityError, match="mismatch"):
        serving.verify_models()
    alerts = db.alerts(kind="pipeline_error")["items"]
    assert len(alerts) == 1 and alerts[0]["source"] == "model:X/lightgbm/y_any_h2" and alerts[0]["project_key"] is None
    monkeypatch.setattr(serving, "_version", lambda: ("tampered", 1))
    monkeypatch.setattr(serving, "_failed_at", 0.0)
    assert serving.state() is before                          # the old version stays served
    assert db.alerts(kind="pipeline_error")["total"] == 1     # add_alerts_once: one alert for one bad model
