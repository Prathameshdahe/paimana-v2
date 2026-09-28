"""The serving tables' writers (Manamrit's ingest / core / ml schemas), used by pipeline/serve.py: every load is an
upsert on the table's natural key, so a run repeated on the same data changes nothing. Rows arrive as dicts with
plain Python values (pipeline/serve.py cleans the frames); a batch goes through COPY into a temporary table and one
INSERT ... ON CONFLICT DO UPDATE, which keeps the 73k-row timeline load to seconds. Nothing here reads the tables
back for the API: backend/serving.py stays on DuckDB.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import sqlalchemy as sa

from .app import _in, _json, _out, _rows
from .engine import connect, now

PROJECT_COLS = ("canonical_project_key", "project_name", "line_ministry", "sector_name", "implementing_agency", "state",
                "status", "is_current", "updated_at")
KEY_COLS = ("project_id", "source_system", "source_project_key", "source_project_name", "match_method", "match_score",
            "review_status", "merged_into")
TIMELINE_COLS = ("project_id", "source_project_key", "report_period", "report_type", "project_name", "sector_name",
                 "state", "implementing_agency", "project_type", "cost_original_cr", "cost_revised_cr",
                 "cost_anticipated_cr", "cost_overrun_cr", "cost_overrun_pct", "cumulative_expenditure_cr",
                 "doc_original", "doc_revised", "doc_anticipated", "delay_months", "physical_progress_pct",
                 "source_document_id", "source_page", "source_file", "silver_version", "loaded_at")
DOCUMENT_COLS = ("filename", "file_type", "sha256", "report_period", "report_type", "source_path")
MODEL_COLS = ("model_name", "model_version", "model_type", "target_name", "feature_version", "gold_version",
              "training_end_period", "validation_start_period", "validation_end_period", "test_start_period",
              "test_end_period", "metrics_json", "hyperparameters_json", "artifact_path", "artifact_sha256", "status",
              "is_champion", "run_id", "entry_id", "feature_list_json")
PREDICTION_COLS = ("project_id", "report_period", "model_id", "p_risk", "risk_score", "risk_tier",
                   "p_schedule_deterioration", "p_cost_deterioration", "expected_slip_months", "expected_cost_pct",
                   "slip_interval_low", "slip_interval_high", "cost_interval_low", "cost_interval_high", "risk_rank",
                   "shap_top5_json", "prediction_payload", "p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "p_any_4q",
                   "months_p05", "months_p50", "months_p95", "cost_pct_p05", "cost_pct_p50", "cost_pct_p95",
                   "tier_rank_pct", "stagnation_override")
FLAG_COLS = ("project_id", "report_period", "model_id", "dimension", "flag_type", "severity", "evidence_json")
FORECAST_COLS = ("project_id", "report_period", "model_id", "forecast_payload")
AGENCY_COLS = ("agency_name", "report_period", "model_id", "project_count", "green_count", "amber_count", "red_count",
               "avg_risk_score", "stats_payload")
JSON_COLS = {"metrics_json", "hyperparameters_json", "feature_list_json", "shap_top5_json", "prediction_payload",
             "evidence_json", "forecast_payload", "stats_payload"}
TABLES = ("ingest.source_documents", "ingest.load_runs", "core.projects", "core.project_keys", "core.project_timeline",
          "ml.model_registry", "ml.predictions", "ml.risk_flags", "ml.forecasts", "ml.agency_stats")
COPY_CHUNK = 20000


def _value(col: str, v: Any):
    if col in JSON_COLS:
        return _json(v)
    return v


def _copy_upsert(con: sa.Connection, table: str, cols: tuple[str, ...], rows: Iterable[dict], key: tuple[str, ...],
                 skip: tuple[str, ...] = ()) -> int:
    """COPY rows (dicts of cols) into a temp table and upsert them into table on key; the columns in skip are
    inserted but never updated (created_at-like). Returns the number of rows sent."""
    tmp = "tmp_" + table.replace(".", "_")
    con.execute(sa.text(f"DROP TABLE IF EXISTS {tmp}"))
    con.execute(sa.text(f"CREATE TEMP TABLE {tmp} AS SELECT {', '.join(cols)} FROM {table} WITH NO DATA"))
    raw = con.connection.dbapi_connection
    n = 0
    with raw.cursor() as cur, cur.copy(f"COPY {tmp} ({', '.join(cols)}) FROM STDIN") as copy:
        for r in rows:
            copy.write_row([_value(c, _in({c: r.get(c)})[c]) for c in cols])
            n += 1
    update = [c for c in cols if c not in key and c not in skip]
    con.execute(sa.text(f"""INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {tmp}
        ON CONFLICT ({', '.join(key)}) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in update)}"""))
    con.execute(sa.text(f"DROP TABLE {tmp}"))
    return n


# ---------------------------------------------------------------- core

def upsert_projects(rows: list[dict]) -> dict[str, int]:
    """core.projects from project-master rows (PROJECT_COLS); returns canonical key -> project_id."""
    with connect() as con:
        _copy_upsert(con, "core.projects", PROJECT_COLS, [{**r, "updated_at": now()} for r in rows],
                     ("canonical_project_key",))
        return project_ids(con)


def project_ids(con=None) -> dict[str, int]:
    sql = "SELECT canonical_project_key, project_id FROM core.projects"
    if con is not None:
        return dict(con.execute(sa.text(sql)).all())
    with connect() as c:
        return dict(c.execute(sa.text(sql)).all())


def upsert_project_keys(rows: list[dict]) -> int:
    """core.project_keys (KEY_COLS) on (source_system, source_project_key)."""
    with connect() as con:
        return _copy_upsert(con, "core.project_keys", KEY_COLS, rows, ("source_system", "source_project_key"))


def register_documents(docs: list[dict]) -> dict[str, int]:
    """ingest.source_documents (DOCUMENT_COLS) on sha256; returns source_path -> source_document_id for every
    registered document, the ones given and the ones already there."""
    with connect() as con:
        if docs:
            _copy_upsert(con, "ingest.source_documents", DOCUMENT_COLS, docs, ("sha256",))
        return dict(con.execute(sa.text("SELECT source_path, source_document_id FROM ingest.source_documents "
                                        "WHERE source_path IS NOT NULL")).all())


def upsert_timeline(rows: Iterable[dict]) -> int:
    """core.project_timeline (TIMELINE_COLS) on (project_id, report_period)."""
    with connect() as con:
        return _copy_upsert(con, "core.project_timeline", TIMELINE_COLS,
                            ({**r, "loaded_at": now()} for r in rows), ("project_id", "report_period"))


# ---------------------------------------------------------------- ml

def upsert_models(rows: list[dict]) -> dict[str, int]:
    """ml.model_registry (MODEL_COLS) on model_version; a row with is_champion takes the flag from the other
    versions of its target first (one champion per target). Returns model_version -> model_id."""
    with connect() as con:
        for r in rows:
            if r.get("is_champion"):
                con.execute(sa.text("UPDATE ml.model_registry SET is_champion = FALSE WHERE target_name = :t "
                                    "AND model_version <> :v AND is_champion"),
                            {"t": r["target_name"], "v": r["model_version"]})
        _copy_upsert(con, "ml.model_registry", MODEL_COLS, rows, ("model_version",))
        return dict(con.execute(sa.text("SELECT model_version, model_id FROM ml.model_registry")).all())


def upsert_predictions(rows: Iterable[dict]) -> int:
    with connect() as con:
        return _copy_upsert(con, "ml.predictions", PREDICTION_COLS, rows, ("project_id", "report_period", "model_id"))


def upsert_risk_flags(rows: Iterable[dict]) -> int:
    with connect() as con:
        return _copy_upsert(con, "ml.risk_flags", FLAG_COLS, rows,
                            ("project_id", "report_period", "model_id", "dimension"))


def upsert_forecasts(rows: Iterable[dict]) -> int:
    with connect() as con:
        return _copy_upsert(con, "ml.forecasts", FORECAST_COLS, rows, ("project_id", "report_period", "model_id"))


def upsert_agency_stats(rows: Iterable[dict]) -> int:
    with connect() as con:
        return _copy_upsert(con, "ml.agency_stats", AGENCY_COLS, rows, ("agency_name", "report_period", "model_id"))


# ---------------------------------------------------------------- runs, counts

def record_serving_run(started, status: str, report_period=None, silver_version=None, gold_version=None,
                       model_version=None, rows_read=None, rows_loaded=None, rows_failed=None) -> int:
    """One ingest.load_runs row of run_type SERVING; returns its id."""
    with connect() as con:
        return con.execute(sa.text("""INSERT INTO ingest.load_runs (run_type, report_period, pipeline_version,
                silver_version, gold_version, model_version, started_at, finished_at, status, rows_read, rows_loaded,
                rows_failed)
            VALUES ('SERVING', :period, 'pipeline.serve', :silver, :gold, :model, :started, :finished, :status, :read,
                :loaded, :failed) RETURNING load_run_id"""),
                           _in({"period": report_period, "silver": silver_version, "gold": gold_version,
                                "model": model_version, "started_at": started, "finished": now(), "status": status,
                                "read": rows_read, "loaded": rows_loaded, "failed": rows_failed}
                               | {"started": _in({"started_at": started})["started_at"]})).scalar()


def counts() -> dict[str, int]:
    """Rows per serving table."""
    with connect() as con:
        return {t: con.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar() for t in TABLES}


def rows(table: str, order: str = "1", limit: int = 100) -> list[dict]:
    """Rows of one serving table (a name of TABLES), for the tests and checks."""
    if table not in TABLES:
        raise ValueError(f"not a serving table: {table}")
    with connect() as con:
        out = _rows(con, f"SELECT * FROM {table} ORDER BY {order} LIMIT :limit", {"limit": limit})
    return [{k: (json.loads(v) if k in JSON_COLS and isinstance(v, str) else v) for k, v in _out(r).items()}
            for r in out]
