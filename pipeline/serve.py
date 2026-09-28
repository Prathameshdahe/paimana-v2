"""
The serving tables (docs/DATABASE.md): PostgreSQL's copy of the projects, timeline, scores, flags and forecasts in
Manamrit's core and ml schemas, loaded from silver and gold.

Run from repo root after profile (the report watcher runs it too):  python -m pipeline.run serve

Inputs   silver/project_master.parquet, silver/identity/{aliases,projects}.parquet, silver/observations.parquet,
         silver/silver_manifest.json, gold/predictions_latest.json and the predictions file it names,
         gold/risk_profile_<asof>.parquet, gold/scenarios_<asof>.parquet, gold/analogues_<asof>.parquet,
         gold/agency_stats.parquet, model/registry.json (and the champion model files, for their sha256)
Outputs  core.projects (every canonical key; is_current from the latest report), core.project_keys (each identity
         alias: source key -> canonical, match method and score, review status, merged_into), core.project_timeline
         (one row per project and period with its source document, page and silver version), ingest.source_documents
         (a historical report registered with its sha256 when its file is under the Dataset drive folder),
         ml.model_registry (every champion entry with metrics, params, feature list, artifact path and sha256, and
         one row for the served combination of champions: model_version of the pointer, target 'served'),
         ml.predictions (the served scores per project at asof: risk_tier is our tier, the probabilities and
         quantiles are columns, SHAP and the rest the payload), ml.risk_flags (the flagged risk-profile rows),
         ml.forecasts (scenarios, analogues and the completion band per project), ml.agency_stats, and an
         ingest.load_runs row (SERVING) with the counts. Every write is an upsert: a second run changes nothing.

read() collects the inputs into a Data bundle (keys: only these projects, for a sample), load() writes it; the
API keeps reading DuckDB (backend/serving.py) - these tables are for the dashboard queries of the coming segments
and for anyone joining on canonical_project_key.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.silver import ROOT  # noqa: E402

SILVER, GOLD, MODEL = ROOT / "dataset" / "silver", ROOT / "dataset" / "gold", ROOT / "model"
DATASET = ROOT / "Dataset drive folder" / "Dataset"     # where source_doc_id paths resolve (pipeline/extract/common.py)
SERVED = "served"                                        # target_name of the served combination of champions
PCT_CAP = 999999.0                                       # cost_overrun_pct is numeric(10, 4)
TIER_COUNTS = {"Low": "green_count", "Medium": "amber_count", "High": "red_count", "Critical": "red_count"}
PROB_COLS = ["p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "p_any_4q", "months_p05", "months_p50", "months_p95",
             "cost_pct_p05", "cost_pct_p50", "cost_pct_p95", "tier_rank_pct"]
PAYLOAD_COLS = ["tier_by_rank", "no_completion_date", "stagnation_quarters", "elapsed_ratio", "gold_version",
                "silver_version", "project_name", "sector", "state", "agency", "ministry", "anticipated_cost_cr",
                "expenditure_cr", "physical_progress_pct", "anticipated_completion"]
STATS_COLS = ["agency_n", "n_slip", "slip_rate_raw", "n_cost", "cost_pct_raw", "last_outcome_period"]


@dataclass
class Data:
    """The inputs of one load, as frames and dicts (read() fills it; the tests build small ones)."""
    master: pd.DataFrame
    aliases: pd.DataFrame
    observations: pd.DataFrame
    predictions: pd.DataFrame
    pointer: dict
    registry: dict
    risk_profile: pd.DataFrame
    scenarios: pd.DataFrame
    analogues: pd.DataFrame
    agency_stats: pd.DataFrame
    silver_version: str
    merged_into: dict[str, str] = field(default_factory=dict)
    documents: dict[str, Path] = field(default_factory=dict)   # source_doc_id -> the raw file, when present


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def clean(v):
    """A frame value as a plain Python value: NaN / NaT -> None, numpy scalars -> Python, Timestamp -> datetime."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        return v.item()
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def _day(v):
    v = clean(v)
    return v.date() if isinstance(v, datetime) else v


# ------------------------------------------------------------------ read

def read(keys: set[str] | None = None) -> Data:
    """The inputs from silver, gold and the registry; keys: only these projects (a sample)."""
    ptr = json.loads((GOLD / "predictions_latest.json").read_text(encoding="utf-8"))
    ym = ptr["asof"][:7]
    silver = json.loads((SILVER / "silver_manifest.json").read_text(encoding="utf-8"))
    master = pd.read_parquet(SILVER / "project_master.parquet")
    idp = pd.read_parquet(SILVER / "identity" / "projects.parquet", columns=["project_key", "merged_into"])
    aliases = pd.read_parquet(SILVER / "identity" / "aliases.parquet")
    obs = pd.read_parquet(SILVER / "observations.parquet")
    pred = pd.read_parquet(ROOT / ptr["path"])
    d = Data(master=master, aliases=aliases, observations=obs, predictions=pred, pointer=ptr,
             registry=json.loads((MODEL / "registry.json").read_text(encoding="utf-8")),
             risk_profile=pd.read_parquet(GOLD / f"risk_profile_{ym}.parquet"),
             scenarios=pd.read_parquet(GOLD / f"scenarios_{ym}.parquet"),
             analogues=pd.read_parquet(GOLD / f"analogues_{ym}.parquet"),
             agency_stats=pd.read_parquet(GOLD / "agency_stats.parquet"), silver_version=silver["silver_version"],
             merged_into={k: m for k, m in zip(idp["project_key"], idp["merged_into"]) if isinstance(m, str)})
    if keys is not None:
        for name in ("master", "aliases", "observations", "predictions", "risk_profile", "scenarios", "analogues"):
            frame = getattr(d, name)
            setattr(d, name, frame[frame["project_key"].isin(keys)].reset_index(drop=True))
        agencies = set(d.master["agency"].dropna())
        d.agency_stats = d.agency_stats[d.agency_stats["agency"].isin(agencies)].reset_index(drop=True)
    for doc in d.observations["source_doc_id"].dropna().unique():
        p = DATASET / doc
        if p.is_file():
            d.documents[doc] = p
    return d


# ------------------------------------------------------------------ rows

def project_rows(master: pd.DataFrame) -> list[dict]:
    return [{"canonical_project_key": r["project_key"], "project_name": r["project_name"] or r["project_key"],
             "line_ministry": r["ministry"], "sector_name": r["sector"], "implementing_agency": r["agency"],
             "state": r["state"], "status": r["last_status"], "is_current": bool(r["in_latest_report"])}
            for r in records(master)]


def key_rows(aliases: pd.DataFrame, ids: dict[str, int], merged_into: dict[str, str]) -> list[dict]:
    """One row per identity alias (the last of a repeated source key wins); an alias whose project is not in
    core.projects is skipped."""
    out = {}
    for r in records(aliases):
        pid = ids.get(r["project_key"])
        if pid is None:
            continue
        out[r["source_report_type"], r["source_row_id"]] = {
            "project_id": pid, "source_system": r["source_report_type"], "source_project_key": r["source_row_id"],
            "source_project_name": r.get("source_name"), "match_method": r["match_method"] or "unknown",
            "match_score": r.get("match_score"), "review_status": r["review_status"] or "review",
            "merged_into": merged_into.get(r["project_key"])}
    return list(out.values())


def document_rows(obs: pd.DataFrame, documents: dict[str, Path]) -> list[dict]:
    """ingest.source_documents rows for the historical reports whose file is present (sha256 of the file; the
    period is the report period most of its rows carry)."""
    out = []
    for doc, path in sorted(documents.items()):
        mine = obs[obs["source_doc_id"] == doc]
        period = (mine["report_period_last"].mode() if "report_period_last" in mine
                  else pd.Series(dtype="datetime64[us]"))
        out.append({"filename": path.name, "file_type": path.suffix.lstrip(".").lower() or "file",
                    "sha256": sha256_of(path), "report_period": _day(period.iloc[0]) if len(period) else None,
                    "report_type": mine["period_type"].mode().iloc[0] if len(mine) else None, "source_path": doc})
    return out


def _overrun(original, anticipated):
    if original is None or anticipated is None:
        return None, None
    cr = anticipated - original
    pct = 100.0 * cr / original if original else None
    return cr, None if pct is None else max(-PCT_CAP, min(PCT_CAP, pct))


def timeline_rows(obs: pd.DataFrame, ids: dict[str, int], doc_ids: dict[str, int], silver_version: str):
    for r in records(obs):
        pid = ids.get(r["project_key"])
        if pid is None:
            continue
        cr, pct = _overrun(r.get("original_cost_cr"), r.get("anticipated_cost_cr"))
        yield {"project_id": pid, "source_project_key": r.get("project_code"), "report_period": _day(r["period"]),
               "report_type": r.get("period_type"), "project_name": r.get("project_name"),
               "sector_name": r.get("sector"), "state": r.get("state"), "implementing_agency": r.get("agency"),
               "project_type": None, "cost_original_cr": r.get("original_cost_cr"),
               "cost_revised_cr": r.get("revised_cost_cr"), "cost_anticipated_cr": r.get("anticipated_cost_cr"),
               "cost_overrun_cr": cr, "cost_overrun_pct": pct, "cumulative_expenditure_cr": r.get("expenditure_cr"),
               "doc_original": _day(r.get("scheduled_completion")), "doc_revised": _day(r.get("revised_completion")),
               "doc_anticipated": _day(r.get("anticipated_completion")), "delay_months": r.get("delay_months"),
               "physical_progress_pct": r.get("physical_progress_pct"),
               "source_document_id": doc_ids.get(r.get("source_doc_id")), "source_page": r.get("source_page"),
               "source_file": r.get("source_doc_id"), "silver_version": silver_version}


def _entry(registry: dict, entry_id: str) -> dict:
    return next(e for e in registry["runs"] if e["entry_id"] == entry_id)


def model_rows(registry: dict, pointer: dict, predictions_path: Path | None) -> list[dict]:
    """The champion entries of the registry and the served combination (target SERVED), champions all."""
    out = []
    for key, champ in registry.get("champions", {}).items():
        e = _entry(registry, champ["entry_id"])
        w = e.get("windows") or {}
        val, test = w.get("validation") or [], w.get("test") or []
        model_file = MODEL.parent / e["artifacts"]["model"]
        feature_version = hashlib.sha256(json.dumps(e["feature_list"]).encode()).hexdigest()[:12]
        out.append({"model_name": e["model"], "model_version": e["entry_id"], "model_type": e["model"].split("_")[0],
                    "target_name": key, "feature_version": feature_version, "gold_version": e["gold_version"],
                    "training_end_period": val[0] if val else None, "validation_start_period": val[0] if val else None,
                    "validation_end_period": val[-1] if val else None, "test_start_period": test[0] if test else None,
                    "test_end_period": test[-1] if test else None, "metrics_json": e["metrics"],
                    "hyperparameters_json": e.get("params"), "artifact_path": e["artifacts"]["model"],
                    "artifact_sha256": e.get("artifact_sha256") or (sha256_of(model_file) if model_file.is_file()
                                                                    else None),
                    "status": "registered", "is_champion": True, "run_id": e["run_id"], "entry_id": e["entry_id"],
                    "feature_list_json": e["feature_list"]})
    lead = registry["champions"].get("y_any_h2") or next(iter(registry["champions"].values()), {})
    features = sorted({f for c in registry["champions"].values()
                       for f in _entry(registry, c["entry_id"])["feature_list"]})
    out.append({"model_name": SERVED, "model_version": pointer["model_version"], "model_type": "composite",
                "target_name": SERVED, "feature_version": "-", "gold_version": pointer["gold_version"],
                "training_end_period": None, "validation_start_period": None, "validation_end_period": None,
                "test_start_period": None, "test_end_period": None,
                "metrics_json": {"models": pointer.get("models", {}), "asof": pointer["asof"]},
                "hyperparameters_json": {}, "artifact_path": pointer["path"],
                "artifact_sha256": sha256_of(predictions_path) if predictions_path and predictions_path.is_file()
                else None, "status": "registered", "is_champion": True, "run_id": lead.get("run_id"),
                "entry_id": None, "feature_list_json": features})
    return out


def prediction_rows(pred: pd.DataFrame, ids: dict[str, int], model_id: int, pointer: dict):
    rank = pred["p_any_2q"].rank(method="first", ascending=False)
    for r, rk in zip(records(pred), rank):
        pid = ids.get(r["project_key"])
        if pid is None:
            continue
        p = r.get("p_any_2q")
        shap = r.get("shap_top5_json")
        yield {"project_id": pid, "report_period": _day(r["asof"]), "model_id": model_id, "p_risk": p,
               "risk_score": None if p is None else round(100 * p, 2), "risk_tier": r.get("tier"),
               "p_schedule_deterioration": r.get("p_date_push_2q"), "p_cost_deterioration": r.get("p_cost_rev_2q"),
               "expected_slip_months": r.get("months_p50"), "expected_cost_pct": r.get("cost_pct_p50"),
               "slip_interval_low": r.get("months_p05"), "slip_interval_high": r.get("months_p95"),
               "cost_interval_low": r.get("cost_pct_p05"), "cost_interval_high": r.get("cost_pct_p95"),
               "risk_rank": None if p is None or pd.isna(rk) else int(rk),
               "shap_top5_json": json.loads(shap) if isinstance(shap, str) else shap,
               "prediction_payload": {**{c: r.get(c) for c in PAYLOAD_COLS if c in r}, "models": pointer.get("models")},
               **{c: r.get(c) for c in PROB_COLS}, "stagnation_override": r.get("stagnation_override")}


def flag_rows(rp: pd.DataFrame, ids: dict[str, int], model_id: int, asof):
    for r in records(rp[rp["state"] == "flagged"]):
        pid = ids.get(r["project_key"])
        if pid is None:
            continue
        yield {"project_id": pid, "report_period": asof, "model_id": model_id, "dimension": r["dimension"],
               "flag_type": "flagged", "severity": None,
               "evidence_json": {"evidence": r.get("evidence"), "source": r.get("source"),
                                 "as_of_date": _day(r.get("as_of_date"))}}


def forecast_rows(pred: pd.DataFrame, scen: pd.DataFrame, ana: pd.DataFrame, ids: dict[str, int], model_id: int, asof):
    scen_by = {k: records(g.drop(columns=["project_key", "asof"], errors="ignore"))
               for k, g in scen.groupby("project_key", sort=False)}
    ana_by = {k: records(g.drop(columns=["project_key", "asof"], errors="ignore"))
              for k, g in ana.groupby("project_key", sort=False)}
    for r in records(pred):
        pid = ids.get(r["project_key"])
        if pid is None:
            continue
        yield {"project_id": pid, "report_period": asof, "model_id": model_id, "forecast_payload": {
            "completion": {"anticipated": _day(r.get("anticipated_completion")),
                           **{c: r.get(c) for c in ("months_p05", "months_p50", "months_p95")}},
            "cost": {c: r.get(c) for c in ("cost_pct_p05", "cost_pct_p50", "cost_pct_p95")},
            "scenarios": scen_by.get(r["project_key"], []), "analogues": ana_by.get(r["project_key"], [])}}


def agency_rows(stats: pd.DataFrame, pred: pd.DataFrame, model_id: int):
    """One row per agency and period; the tier counts and the mean score are the current portfolio's at the served
    asof, on the rows of that period (0 / null on the others)."""
    cur = pred.dropna(subset=["agency"])
    asof = _day(pred["asof"].iloc[0]) if len(pred) else None
    tiers = {a: g["tier"].value_counts().to_dict() for a, g in cur.groupby("agency")}
    score = {a: clean(g["p_any_2q"].mean()) for a, g in cur.groupby("agency")}
    for r in records(stats):
        period = _day(r["period"])
        counts = tiers.get(r["agency"], {}) if period == asof else {}
        row = {"agency_name": r["agency"], "report_period": period, "model_id": model_id,
               "project_count": int(r.get("agency_n") or 0), "green_count": 0, "amber_count": 0, "red_count": 0,
               "avg_risk_score": None if period != asof or score.get(r["agency"]) is None
               else round(100 * score[r["agency"]], 2),
               "stats_payload": {c: (_day(r.get(c)) if c == "last_outcome_period" else r.get(c)) for c in STATS_COLS}}
        for tier, n in counts.items():
            if tier in TIER_COUNTS:
                row[TIER_COUNTS[tier]] += int(n)
        yield row


# ------------------------------------------------------------------ load

def load(d: Data) -> dict[str, int]:
    """Write one Data bundle; returns the rows sent per table (and the load run id)."""
    from backend.db import serve as db  # noqa: PLC0415 - the pipeline's only use of the app database
    started, t0 = _now(), time.time()
    asof = _day(pd.Timestamp(d.pointer["asof"]))
    n = {}
    try:
        ids = db.upsert_projects(project_rows(d.master))
        n["core.projects"] = len(ids)
        n["core.project_keys"] = db.upsert_project_keys(key_rows(d.aliases, ids, d.merged_into))
        doc_ids = db.register_documents(document_rows(d.observations, d.documents))
        n["ingest.source_documents"] = len(doc_ids)
        n["core.project_timeline"] = db.upsert_timeline(timeline_rows(d.observations, ids, doc_ids, d.silver_version))
        models = db.upsert_models(model_rows(d.registry, d.pointer, ROOT / d.pointer["path"]))
        n["ml.model_registry"] = len(models)
        served = models[d.pointer["model_version"]]
        n["ml.predictions"] = db.upsert_predictions(prediction_rows(d.predictions, ids, served, d.pointer))
        n["ml.risk_flags"] = db.upsert_risk_flags(flag_rows(d.risk_profile, ids, served, asof))
        n["ml.forecasts"] = db.upsert_forecasts(forecast_rows(d.predictions, d.scenarios, d.analogues, ids, served,
                                                              asof))
        n["ml.agency_stats"] = db.upsert_agency_stats(agency_rows(d.agency_stats, d.predictions, served))
    except Exception:
        db.record_serving_run(started, "FAILED", asof, d.silver_version, d.pointer["gold_version"],
                              d.pointer["model_version"], rows_read=len(d.observations), rows_loaded=sum(n.values()))
        raise
    n["load_run_id"] = db.record_serving_run(started, "SUCCESS", asof, d.silver_version, d.pointer["gold_version"],
                                             d.pointer["model_version"], rows_read=len(d.observations),
                                             rows_loaded=sum(n.values()), rows_failed=0)
    n["seconds"] = round(time.time() - t0, 1)
    return n


def main(keys: set[str] | None = None) -> dict[str, int]:
    t0 = time.time()
    d = read(keys)
    n = load(d)
    print(f"serve: asof {d.pointer['asof']} model {d.pointer['model_version']} -> "
          + ", ".join(f"{t} {c}" for t, c in n.items() if t not in ("seconds", "load_run_id"))
          + f" (load run {n['load_run_id']}, {len(d.documents)} of {d.observations['source_doc_id'].nunique()} source "
          f"documents on disk), {time.time() - t0:.1f}s")
    return n


if __name__ == "__main__":
    main()
