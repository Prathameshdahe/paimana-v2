"""Read side of the API: DuckDB over the gold and silver Parquet files.

Each data version is loaded once into an in-memory DuckDB: `cur` holds one
row per scored project (scores + latest observation + features + open flags),
the other tables are the per-project Parquet files as written by the pipeline,
plus the cross-project ones: agency matrix and map, bottlenecks and members.
The version is the mtime of external_summary.json: the profile step writes it
last, so score and analogues rewriting their files first (predictions_latest.json
before scenarios_/analogues_/risk_profile_<month>) never serves a half-written
set; and of research_summary.json, which the research step writes after its two
tables (research alone does not rewrite external_summary.json). When it changes
the tables are reloaded and every cached result goes with the old version; a
reload that fails keeps serving the loaded version and is retried after RETRY_S
seconds. The in-app research agent's facts live in SQLite (backend/db.py) and
are read per request, next to the cached gold part.
"""
from __future__ import annotations

import functools
import json
import logging
import math
import re
import threading
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import duckdb

from pipeline import external
from pipeline.hidden_delay import LIVE_Q, applicable
from pipeline.research import EXT_COLS, TAXONOMY_OF, is_live
from pipeline.identity.config import IdentityConfig
from pipeline.identity.identity_map import IdentityMap

ROOT = Path(__file__).resolve().parents[1]
GOLD, SILVER, MODEL = ROOT / "dataset" / "gold", ROOT / "dataset" / "silver", ROOT / "model"
POINTER, SILVER_MANIFEST = GOLD / "predictions_latest.json", SILVER / "silver_manifest.json"
EXTERNAL_SUMMARY, BOTTLENECKS_SUMMARY = GOLD / "external_summary.json", GOLD / "bottlenecks_summary.json"
RESEARCH_FACTS, RESEARCH_PROJECTS = GOLD / "research_facts.parquet", GOLD / "research_projects.parquet"
RESEARCH_SUMMARY = GOLD / "research_summary.json"
RETRY_S = 30
TOP_MEMBERS = 5
N_EVIDENCE = 3  # evidence lines per bottleneck, as pipeline/bottlenecks.py
TOP_FACTOR, TOP_NOTICE = 10, 20  # top lists of external_summary.json, as ml/risk_profile.py

TIERS = ["Critical", "High", "Medium", "Low"]
WATCH = "Watch"  # no anticipated completion date: no date-based score (ml/score.py)
# list flag -> risk-profile dimension that raises it
FLAG_DIMS = {"land": "land_acquisition", "forest": "forest_clearance", "litigation": "litigation",
             "contractor": "contractor_stress"}
SORTS = {"risk": "p_any_2q", "cost": "anticipated_cost_cr", "slip": "slip_to_date_months", "name": "project_name",
         "progress": "physical_progress_pct"}
ROW_SQL = """project_key AS "key", project_name AS name, sector, state, agency, ministry, tier, tier_rank_pct,
    stagnation_override AS override, p_any_2q, p_date_push_2q, p_cost_rev_2q, months_p50, months_p95,
    anticipated_cost_cr, expenditure_cr, physical_progress_pct, anticipated_completion, slip_to_date_months,
    no_completion_date, flags"""
SCORE_COLS = ["p_date_push_2q", "p_cost_rev_2q", "p_any_2q", "p_any_4q", "months_p05", "months_p50", "months_p95",
              "cost_pct_p05", "cost_pct_p50", "cost_pct_p95", "tier_rank_pct", "tier_by_rank", "tier",
              "stagnation_override", "no_completion_date", "stagnation_quarters", "elapsed_ratio"]
CAVEATS = [
    "Report remarks are free text only through 2023; later reports print templates, so the land, forest, "
    "litigation and contractor flags from remarks describe the situation up to 2023.",
    "Land-acquisition records (Bhoomi Rashi, 29 states) rate a road project only when a km range in its name places "
    "it on the notified stretches; a link on its NH or district alone is shown as possible, never flagged, and "
    "everything else is unknown, not clear.",
    "Probabilities rank projects against each other (tiers go by rank); they are not calibrated frequencies.",
    "Projects without an anticipated completion date have no date-based scores; they are in the Watch tier, "
    "listed by flagged checklist rows and then the chance of a cost revision. No backtest has checked that order.",
    "The stagnation badge (no progress for 2+ quarters) does not change the tier: in the backtest flagged projects "
    "slipped no more often than the rest.",
]
BAND_METHOD = (
    "Progress band: each quarter the lower and upper edge are the lowest and highest of the three scenario curves "
    "(own recent velocity, sector-median velocity, agency pattern) and the middle line is the own-velocity curve; "
    "it is a scenario range, not a statistical interval. Completion band: anticipated completion plus the 5th, "
    "50th and 95th percentile of predicted slip over the next 2 quarters (LightGBM quantile models), to the month.")
AGENCY_METHOD = (
    "Schedule bias = (latest anticipated completion, or for a finished project its actual completion, read to the "
    "quarter of its completion report) - sanction over (first printed scheduled completion - sanction), minus 1; "
    "cost bias = latest anticipated cost / first original cost - 1; only projects "
    "with a known planned duration. Median, IQR and a bootstrap 90% CI of the median per canonical agency (printed "
    "names merged, gold/agency_map.csv). With n < 10 the shown median is shrunk toward the sector median with weight "
    "n / (n + 10) (raw kept); agencies with n < 5 are hidden. Trend = median schedule bias of projects sanctioned in "
    "the last 3 years of data minus that of earlier ones: recent projects have had less time to slip, so a negative "
    "trend is partly that. Capital and n_open are the current portfolio.")
# flagged checklist rows in plain words, most concrete first (the public project page's top risks)
PLAIN_RISK = {
    "land_acquisition": "Land for the project is not fully acquired yet.",
    "forest_clearance": "A forest or environment clearance is still pending.",
    "litigation": "A court case is holding up the project.",
    "contractor_stress": "There are problems with the contractor.",
    "execution_stagnation": "Work on site has slowed down or stopped.",
    "schedule_slip": "The completion date is likely to be pushed back.",
    "cost_escalation": "The cost is likely to be revised upward.",
    "expenditure_lag": "Spending and work done on site are out of step.",
    "repeated_revisions": "The cost or completion date has been revised several times already.",
    "external_composite": "Land and forest issues together raise the risk.",
    "data_staleness": "The latest progress report is old.",
    "agency_optimism": "Projects of this agency usually finish later than planned.",
    "sector_headwind": "The sector as a whole is behind its targets.",
}
LIVE_NOTE = ("Live accuracy compares logged predictions with outcomes once the report 2 quarters after their asof "
             "is in silver; PR-AUC needs at least 30 realised rows.")

_lock = threading.Lock()
_state: dict = {}
_pinned = threading.Event()
_failed_at = 0.0  # time.monotonic() of the last failed reload
log = logging.getLogger(__name__)


def _version() -> tuple:
    return EXTERNAL_SUMMARY.stat().st_mtime_ns, RESEARCH_SUMMARY.exists() and RESEARCH_SUMMARY.stat().st_mtime_ns


def _posix(p: Path) -> str:
    return p.as_posix().replace("'", "''")


def _load() -> dict:
    """Read one data version into a fresh in-memory DuckDB."""
    ptr = json.loads(POINTER.read_text(encoding="utf-8"))
    silver = json.loads(SILVER_MANIFEST.read_text(encoding="utf-8"))
    asof = date.fromisoformat(ptr["asof"])
    ym = f"{asof:%Y-%m}"
    con = duckdb.connect()
    files = {
        "obs": SILVER / "observations.parquet", "master": SILVER / "project_master.parquet",
        "rp": GOLD / f"risk_profile_{ym}.parquet", "events": GOLD / "project_events.parquet",
        "fc": GOLD / "external_fc.parquet", "land": GOLD / "external_land.parquet",
        "land_pairs": GOLD / "external_land_links.parquet", "composite": GOLD / "external_composite.parquet",
        "scen": GOLD / f"scenarios_{ym}.parquet", "ana": GOLD / f"analogues_{ym}.parquet",
        "scurve": GOLD / "sector_scurve.parquet",
        # PARIVESH links (per project), the remark-named proposals, the remark status with its as-of quarters and
        # the measured hidden-delay priors (pipeline/parivesh.py, pipeline/external.py, pipeline/hidden_delay.py)
        "portal": GOLD / "external_fc_portal.parquet", "fcprop": GOLD / "fc_proposal_status.parquet",
        "rstat": GOLD / "remark_status.parquet",
    }
    for name, path in files.items():
        # sorted by key so a one-project filter skips most row groups
        order = "ORDER BY project_key" if name not in ("scurve",) else ""
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{_posix(path)}') {order}")
    for name, path in (("agencies", GOLD / "agency_matrix.parquet"), ("bottlenecks", GOLD / "bottlenecks.parquet"),
                       ("bmembers", GOLD / "bottleneck_members.parquet"),
                       ("priors", GOLD / "hidden_delay_priors.parquet")):
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{_posix(path)}')")
    # the Bhoomi Rashi register per state (every stretch table load_land reads, newest pull first)
    la = external.load_land()
    register = la.assign(k=external.state_key(la["state"])).groupby("k", as_index=False).agg(  # noqa: F841 (SQL)
        stretches=("highway_name", "size"), parcels=("num_parcels", "sum"), area_ha=("total_area_ha", "sum"),
        last_notif=("last_notif_date", "max"))
    con.execute("CREATE TABLE register AS SELECT k, stretches, parcels, area_ha, last_notif::DATE AS last_notif "
                "FROM register")
    _load_research(con)
    con.execute(f"CREATE TABLE amap AS SELECT * FROM read_csv_auto('{_posix(GOLD / 'agency_map.csv')}')")
    con.execute(f"""CREATE TABLE review AS SELECT project_key, count(*) AS n_rows, min(period) AS first_period,
        max(period) AS last_period FROM read_parquet('{_posix(SILVER / "observations_review.parquet")}') GROUP BY 1""")
    flag_cols = ",\n".join(f"coalesce(bool_or(dimension = '{d}' AND state = 'flagged'), false) AS f_{f}"
                           for f, d in FLAG_DIMS.items())
    any_flag = " OR ".join(f"f_{f}" for f in FLAG_DIMS)
    flag_list = ", ".join(f"CASE WHEN f_{f} THEN '{f}' END" for f in FLAG_DIMS)
    # early notice as in ml/risk_profile.py: a flagged external factor while the CUF numbers show no slip yet
    con.execute(f"""
        CREATE TABLE cur AS
        WITH o AS (
            SELECT project_key, period AS obs_period, period_type, source_doc_id, source_page, original_cost_cr,
                   scheduled_completion
            FROM obs WHERE period <= DATE '{asof}'
            QUALIFY row_number() OVER (PARTITION BY project_key ORDER BY period DESC) = 1),
        f AS (
            SELECT project_key, slip_to_date_months, months_since_last_obs, dq_score, cost_variation_pct,
                   ext_open_utility_shifting, ext_open_inter_agency
            FROM read_parquet('{_posix(GOLD / "features.parquet")}') WHERE period = DATE '{asof}'),
        r AS (SELECT project_key, {flag_cols}, count(*) FILTER (WHERE state = 'flagged') AS n_flagged
              FROM rp GROUP BY 1),
        j AS (
            SELECT p.*, o.* EXCLUDE (project_key), f.* EXCLUDE (project_key), r.* EXCLUDE (project_key)
            FROM read_parquet('{_posix(ROOT / ptr["path"])}') p
            LEFT JOIN o USING (project_key) LEFT JOIN f USING (project_key) LEFT JOIN r USING (project_key)),
        e AS (
            SELECT *, (coalesce({any_flag}, false) OR coalesce(ext_open_utility_shifting = 1, false)
                       OR coalesce(ext_open_inter_agency = 1, false))
                      AND (coalesce(slip_to_date_months <= 0, false) OR coalesce(tier IN ('Low', 'Medium'), false))
                      AS early_notice
            FROM j)
        SELECT * EXCLUDE ({", ".join(f"f_{f}" for f in FLAG_DIMS)}),
               list_filter([{flag_list}, CASE WHEN early_notice THEN 'early_notice' END], x -> x IS NOT NULL)
                   AS flags,
               -- the Watch tier's order: flagged checklist rows, then P(cost revision); not validated
               CASE WHEN tier = '{WATCH}' THEN coalesce(n_flagged, 0) + coalesce(p_cost_rev_2q, 0) END AS watch_score
        FROM e ORDER BY project_key""")
    report = con.execute("""SELECT period, source_doc_id FROM obs WHERE period = (SELECT max(period) FROM obs)
        GROUP BY ALL ORDER BY count(*) DESC LIMIT 1""").fetchone()
    idmap = IdentityMap(IdentityConfig(root=SILVER / "identity"))
    return {
        "con": con, "idmap": idmap, "cache": {}, "asof": asof, "pointer": ptr,
        "model_version": ptr["model_version"], "gold_version": ptr["gold_version"],
        "silver_version": silver["silver_version"],
        "latest_report_period": report[0].date() if report else None,
        "latest_report_doc": report[1] if report else None,
        "external_summary": json.loads(EXTERNAL_SUMMARY.read_text(encoding="utf-8")),
        "bottlenecks_summary": json.loads(BOTTLENECKS_SUMMARY.read_text(encoding="utf-8")),
    }


# gold research tables (pipeline/research.py FACT_COLS, PROJECT_COLS); empty with these columns before the first run
RESEARCH_DDL = {
    "rfacts": (RESEARCH_FACTS, """fact_id VARCHAR, project_key VARCHAR, category VARCHAR, taxonomy VARCHAR,
        direction VARCHAR, severity TINYINT, event_date TIMESTAMP, date_precision VARCHAR, published_date TIMESTAMP,
        status VARCHAR, summary VARCHAR, headline VARCHAR, source VARCHAR, url VARCHAR, domain VARCHAR, match VARCHAR,
        match_reason VARCHAR, verified VARCHAR, origin VARCHAR, researched_on TIMESTAMP, live BOOLEAN"""),
    "rprojects": (RESEARCH_PROJECTS, """project_key VARCHAR, researched_on TIMESTAMP, searched BOOLEAN,
        n_queries BIGINT, n_facts BIGINT, n_negative_live BIGINT, latest_status VARCHAR, land_acquired_pct DOUBLE,
        land_as_of VARCHAR, fc_stage VARCHAR, fc_as_of VARCHAR, court VARCHAR, court_status VARCHAR,
        court_as_of VARCHAR, contractor VARCHAR, contractor_status VARCHAR, contractor_as_of VARCHAR,
        new_target VARCHAR, new_target_as_of VARCHAR, cost_revision_cr DOUBLE, cost_revision_as_of VARCHAR"""),
}


def _load_research(con) -> None:
    """The web research tables rfacts and rprojects: the gold files, or empty tables when research never ran."""
    for name, (path, ddl) in RESEARCH_DDL.items():
        if path.exists():
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{_posix(path)}') ORDER BY project_key")
        else:
            con.execute(f"CREATE TABLE {name} ({ddl})")


def pin(on: bool) -> None:
    """While pinned, state() keeps the loaded version even if the version file changes: the report watcher pins
    it while a pipeline run rewrites the data, and leaves it pinned when a failed run left it half rewritten."""
    _pinned.set() if on else _pinned.clear()


def _due(v: tuple) -> bool:
    return _state.get("version") != v and (not _state or time.monotonic() - _failed_at >= RETRY_S)


def state() -> dict:
    """The loaded data version, reloaded when the version file changes (unless pinned). A failed reload keeps
    serving the loaded version and is retried after RETRY_S; with nothing loaded yet it raises."""
    global _state, _failed_at
    if _state and _pinned.is_set():
        return _state
    v = _version()
    if _due(v):
        with _lock:
            if _due(v):
                try:
                    _state = {**_load(), "version": v}
                except Exception:
                    if not _state:
                        raise
                    _failed_at = time.monotonic()
                    log.exception("data reload failed; still serving asof %s (%s)", _state["asof"],
                                  _state["model_version"])
    return _state


def cached(fn):
    """Cache fn(state, *args, **kw) per (fn, args, kw) for the current data version."""
    @functools.wraps(fn)
    def wrap(*args, **kw):
        s = state()
        key = (fn.__name__, args, tuple(sorted(kw.items())))
        if key not in s["cache"]:
            if len(s["cache"]) > 5000:  # ponytail: drop-all bound, an LRU if search traffic ever grows
                s["cache"].clear()
            s["cache"][key] = fn(s, *args, **kw)
        return s["cache"][key]
    return wrap


def _clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, datetime):
        return v.date() if v.time() == datetime.min.time() else v
    return v


def _rows(s: dict, sql: str, params: list | tuple = ()) -> list[dict]:
    res = s["con"].cursor().execute(sql, list(params))
    cols = [d[0] for d in res.description]
    return [{c: _clean(v) for c, v in zip(cols, r)} for r in res.fetchall()]


def _one(s: dict, sql: str, params: list | tuple = ()) -> dict | None:
    rows = _rows(s, sql, params)
    return rows[0] if rows else None


def _scope_sql(scope) -> tuple[str, list]:
    """Condition over cur (or master: same columns) and its params for a viewer's scope (backend/access.py):
    ('ministry', name), ('agency', canonical name), None for every project."""
    if not scope:
        return "true", []
    kind, name = scope
    if kind == "ministry":
        return "ministry = ?", [name]
    return "agency IN (SELECT raw FROM amap WHERE canonical = ?)", [name]


NEAR_COMPLETE = (80, 99)  # progress band (%) of the public Home's "closest to completion" (99.9% is all but done)


def _where(ministry=None, sector=None, state_=None, tier=None, q=None, flag=None, agency=None,
           scope=None, near_complete=False) -> tuple[str, list]:
    conds, params = [], []
    if scope:
        sql, params = _scope_sql(scope)
        conds.append(sql)
    if agency:  # canonical agency (gold/agency_map.csv): every printed name that maps to it
        conds.append("agency IN (SELECT raw FROM amap WHERE canonical = ?)")
        params.append(agency)
    for col, v in (("ministry", ministry), ("sector", sector), ("state", state_)):
        if v:
            conds.append(f"{col} = ?")
            params.append(v)
    if tier:
        conds.append("tier = ?")
        params.append(tier)
    if q:
        conds.append("(project_name ILIKE ? OR project_key ILIKE ?)")
        params += [f"%{q}%"] * 2
    if flag:
        conds.append("list_contains(flags, ?)")
        params.append(flag)
    if near_complete:  # not done yet and not past its anticipated completion
        conds.append('physical_progress_pct BETWEEN ? AND ? AND anticipated_completion >= "asof"')
        params += list(NEAR_COMPLETE)
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def canonical(key: str) -> str | None:
    """Canonical PRJ key for any key the identity map knows, else None."""
    idmap = state()["idmap"]
    k = idmap.canonical(key)
    return k if k in idmap._projects else None  # noqa: SLF001 - read-only, as in pipeline/identity/bundle.py


@cached
def scope_keys(s, scope) -> frozenset:
    """Keys of the current and past projects in a scope (alerts, signals and memos are cut to these)."""
    sql, params = _scope_sql(scope)
    return frozenset(r["k"] for r in _rows(s, f"""SELECT project_key AS k FROM cur WHERE {sql}
        UNION SELECT project_key FROM master WHERE {sql}""", params * 2))


@cached
def scopes(s):
    """Ministries and canonical agencies of the current portfolio with their project counts (the sign-in picker)."""
    return {
        "ministries": _rows(s, """SELECT ministry AS name, count(*) AS n FROM cur WHERE ministry IS NOT NULL
            GROUP BY 1 ORDER BY n DESC, name"""),
        "agencies": _rows(s, """SELECT a.canonical AS name, count(*) AS n, any_value(g.names) AS names,
                any_value(c.ministry) AS ministry
            FROM cur c JOIN amap a ON a.raw = c.agency LEFT JOIN agencies g ON g.agency = a.canonical
            WHERE a.canonical IS NOT NULL GROUP BY 1 ORDER BY n DESC, name"""),
    }


# ------------------------------------------------------------------ portfolio

@cached
def meta(s):
    counts = _one(s, f"SELECT count(*) AS n, count(*) FILTER (WHERE tier = '{WATCH}') AS watch FROM cur")
    return {
        "asof": s["asof"], "model_version": s["model_version"], "gold_version": s["gold_version"],
        "silver_version": s["silver_version"], "n_current": counts["n"], "n_watch": counts["watch"],
        "latest_report_period": s["latest_report_period"], "latest_report_doc": s["latest_report_doc"],
        "models": s["pointer"].get("models", {}), "caveats": CAVEATS,
    }


@cached
def portfolio(s, ministry=None, sector=None, state_=None, tier=None, scope=None):
    where, params = _where(ministry, sector, state_, tier, scope=scope)
    k = _one(s, f"""SELECT count(*) AS n_projects,
            sum(original_cost_cr) AS original_cost_cr, sum(anticipated_cost_cr) AS anticipated_cost_cr,
            sum(expenditure_cr) AS expenditure_cr,
            sum(anticipated_cost_cr - original_cost_cr) AS overrun_cr,
            100 * sum(anticipated_cost_cr - original_cost_cr)
                / nullif(sum(original_cost_cr) FILTER (WHERE anticipated_cost_cr IS NOT NULL), 0) AS overrun_pct,
            avg(physical_progress_pct) AS avg_progress_pct
        FROM cur{where}""", params)
    tiers = {r["tier"]: r for r in _rows(s, f"""SELECT tier, count(*) AS n,
        coalesce(sum(anticipated_cost_cr), 0) AS capital_cr FROM cur{where} GROUP BY 1""", params)}

    def by(col):
        return _rows(s, f"""SELECT {col} AS name, count(*) AS n, sum(anticipated_cost_cr) AS capital_cr,
            count(*) FILTER (WHERE tier = 'Critical') AS n_critical, count(*) FILTER (WHERE tier = 'High') AS n_high
            FROM cur{where} GROUP BY 1 ORDER BY capital_cr DESC NULLS LAST, n DESC""", params)

    top = _rows(s, f"""SELECT project_key AS "key", project_name AS name, sector, state, tier, p_any_2q,
        anticipated_cost_cr, stagnation_override AS override FROM cur{where}
        ORDER BY p_any_2q DESC NULLS LAST, project_key LIMIT 20""", params)
    return {
        "asof": s["asof"], "filters": {"ministry": ministry, "sector": sector, "state": state_, "tier": tier},
        "kpis": k,
        "tiers": [tiers.get(t, {"tier": t, "n": 0, "capital_cr": 0.0}) for t in TIERS + [WATCH]],
        "by_state": by("state"), "by_sector": by("sector"), "by_ministry": by("ministry"), "top": top,
    }


@cached
def projects(s, q=None, ministry=None, sector=None, state_=None, tier=None, flag=None, sort="risk", order=None,
             page=1, size=50, agency=None, scope=None, near_complete=False):
    size = max(1, min(int(size), 100))
    page = max(1, int(page))
    where, params = _where(ministry, sector, state_, tier, q, flag, agency, scope, near_complete)
    direction = (order or ("asc" if sort == "name" else "desc")).upper()
    total = _one(s, f"SELECT count(*) AS n FROM cur{where}", params)["n"]
    items = _rows(s, f"""SELECT {ROW_SQL} FROM cur{where}
        ORDER BY {SORTS[sort]} {direction} NULLS LAST, watch_score DESC NULLS LAST, project_key LIMIT ? OFFSET ?""",
                  params + [size, (page - 1) * size])
    return {"total": total, "page": page, "size": size, "items": items}


@cached
def rows_for_keys(s, keys: tuple):
    """List rows for up to 100 given keys (watchlist), in the given order."""
    keys = list(keys)[:100]
    if not keys:
        return []
    got = {r["key"]: r for r in _rows(
        s, f"SELECT {ROW_SQL} FROM cur WHERE project_key IN ({','.join('?' * len(keys))})", keys)}
    return [got[k] for k in keys if k in got]


@cached
def top_projects(s, n=10):
    """Full current rows of the n highest p_any_2q projects (worker cell input)."""
    return _rows(s, "SELECT * FROM cur ORDER BY p_any_2q DESC NULLS LAST, project_key LIMIT ?", [n])


# -------------------------------------------------------------------- project

def project(key):
    """Everything the project page shows for one canonical key (see canonical()), with its web research summary
    (research_brief: read per call, since the research agent adds facts between data versions)."""
    return {**_project(key), "research": research_brief(key)}


@cached
def _project(s, key):
    """project() without the research summary, cached per data version."""
    master = _one(s, "SELECT * FROM master WHERE project_key = ?", [key])
    latest = _one(s, f"""SELECT * FROM obs WHERE project_key = ? AND period <= DATE '{s["asof"]}'
        ORDER BY period DESC LIMIT 1""", [key])
    cur = _one(s, "SELECT * FROM cur WHERE project_key = ?", [key])
    scores = None
    if cur:
        scores = {c: cur[c] for c in SCORE_COLS}
        scores["shap_top5"] = json.loads(cur["shap_top5_json"] or "[]")
    review = _one(s, "SELECT n_rows, first_period, last_period FROM review WHERE project_key = ?", [key])
    if review:
        review["note"] = (f"{review['n_rows']} report rows are linked to this project with an identity match still "
                          "under review; they are not in the numbers shown.")
    risk = _rows(s, "SELECT dimension, state, evidence, source, as_of_date FROM rp WHERE project_key = ?", [key])
    flagged = {r["dimension"] for r in risk if r["state"] == "flagged"}
    land = _one(s, "SELECT * EXCLUDE (project_key) FROM land WHERE project_key = ?", [key])
    remarks = _one(s, "SELECT * EXCLUDE (project_key) FROM rstat WHERE project_key = ?", [key])
    portal = _one(s, "SELECT * EXCLUDE (project_key, evidence) FROM portal WHERE project_key = ?", [key])
    return {
        "key": key, "master": master, "latest": latest, "scores": scores,
        "flags": cur["flags"] if cur else [],
        "risk_profile": risk,
        "top_risks_plain": [text for dim, text in PLAIN_RISK.items() if dim in flagged][:3],
        "external": {
            "fc": _one(s, "SELECT * EXCLUDE (project_key) FROM fc WHERE project_key = ?", [key]),
            "land": land,
            "land_pairs": _rows(s, """SELECT * EXCLUDE (project_key) FROM land_pairs WHERE project_key = ?
                ORDER BY nh, stretch_id""", [key]),
            "composite": _one(s, "SELECT * EXCLUDE (project_key) FROM composite WHERE project_key = ?", [key]),
            "events": _rows(s, """SELECT * EXCLUDE (project_key, state, sector) FROM events WHERE project_key = ?
                ORDER BY status DESC, last_seen DESC, category""", [key]),
            "portal": portal,
            "proposals": _rows(s, """SELECT * EXCLUDE (project_key, name, evidence) FROM fcprop WHERE project_key = ?
                ORDER BY received""", [key]),
            "remark_status": remarks,
            "hidden_delay": hidden_delay(land, remarks, portal, s["asof"]),
        },
        "provenance": {
            "asof": s["asof"], "model_version": s["model_version"] if cur else None,
            "gold_version": s["gold_version"], "silver_version": s["silver_version"],
            "source_doc_id": latest and latest["source_doc_id"], "source_page": latest and latest["source_page"],
            "period": latest and latest["period"], "period_type": latest and latest["period_type"],
        },
        "review": review,
    }


PRIOR_COLS = ("factor", "group", "label", "n_rows", "n_projects", "measurable", "extra_months", "extra_months_lo",
              "extra_months_hi", "extra_push", "extra_push_lo", "extra_push_hi", "holm_months", "holm_push")


@cached
def _priors(s):
    return {(r["factor"], r["group"]): {c: r[c] for c in PRIOR_COLS}
            for r in _rows(s, "SELECT * FROM priors")}


def hidden_delay(land: dict | None, remarks: dict | None, portal: dict | None, asof) -> list[dict]:
    """The measured hidden-delay priors that apply to one project (pipeline/hidden_delay.applicable, as the
    checklist picks them): basis says what it was matched on, as_of the remark quarter, current whether that status
    still describes the project at asof (else it is the status at the last report, not an expected delay)."""
    pri = _priors()
    return [{**pri[(f, g)], "basis": basis, "as_of": as_of, "current": cur}
            for f, g, basis, as_of, cur in applicable(remarks, (land or {}).get("la_state"), portal, asof)
            if (f, g) in pri]


def public_project(d: dict) -> dict:
    """The project page for the public: no SHAP drivers, quantile intervals, identity review, risk evidence lines
    (model probabilities, tier cuts), PARIVESH proposal details, remark status or measured hidden delay, or
    provenance internals (model, data versions, source documents), and no match reasons on the research facts nor
    the research agent's headlines (public_facts); tier, progress, cost, completion, risk states, top risks and the
    cited research facts stay."""
    no_src = {"source_doc_id": None, "source_page": None}
    scores = d["scores"] and {**d["scores"], "shap_top5": [], "tier_rank_pct": None, "tier_by_rank": None,
                              **{c: None for c in SCORE_COLS if c.endswith(("_p05", "_p95"))}}
    prov = {**d["provenance"], "model_version": None, "gold_version": None, "silver_version": None, **no_src}
    research = d.get("research")
    return {**d, "scores": scores, "provenance": prov, "review": None,
            "research": research and {**research, "top": public_facts(research["top"])},
            "latest": d["latest"] and {**d["latest"], **no_src},
            "risk_profile": [{**r, "evidence": None} for r in d["risk_profile"]],
            "external": {**d["external"], "events": [{**e, **no_src} for e in d["external"]["events"]],
                         "portal": None, "proposals": [], "remark_status": None, "hidden_delay": []}}


def public_external(d: dict) -> dict:
    """The External Factors summary for the public, redacted as the public project page: the counts, factors and
    measured priors stay; the evidence lines of every project card (risk-profile text with PARIVESH proposals and
    hidden delay) and the per-project PARIVESH lists (open list, the remark-named proposals) go."""
    def bare(cards):
        return [{**r, "evidence": []} for r in cards]

    po = d.get("portal")
    return {**d, "factors": {n: {**f, "top": bare(f["top"])} for n, f in d["factors"].items()},
            "early_notice": {**d["early_notice"], "top": bare(d["early_notice"]["top"])},
            "portal": po and {**po, "open_list": [], "cases": [], "top_overdue": bare(po["top_overdue"])}}


def public_page(page: dict) -> dict:
    """A project list page for the public: no upper slip quantile or rank percentile (as public_project)."""
    return {**page, "items": [{**r, "months_p95": None, "tier_rank_pct": None} for r in page["items"]]}


# ---------------------------------------------------------------- research

N_RESEARCH_TOP, N_BLOCKERS = 3, 20
RESEARCH_NOTE = (
    "Web research is evidence, not a model input. Sweep facts were found by a research agent and checked by a second "
    "one that re-opened the source; agent facts are news items the in-app research agent judged with the local LLM "
    "from the headline and feed summary alone. A fact is live when it is negative, not resolved and dated within "
    f"{LIVE_Q} quarters of the as-of quarter. No news is not no problem: coverage favours large, much-reported "
    "projects.")


def _day(v) -> date | None:
    """An ISO date or timestamp string (SQLite) -> date."""
    return date.fromisoformat(v[:10]) if isinstance(v, str) and v else v


def _agent_fact(r: dict, asof) -> dict:
    """A research agent row (db.research_facts) in the gold fact shape, live at the served asof."""
    ev, pub = _day(r["event_date"]), _day(r["published_date"])
    return {**{k: v for k, v in r.items() if k not in ("model", "prompt_version")}, "event_date": ev,
            "published_date": pub, "researched_on": _day(r["researched_on"]), "verified": None,
            "live": is_live(r["direction"], r["status"], ev, pub, asof)}


def _cites(f: dict) -> set[tuple[str, str]]:
    """What a fact cites, for deduplication: its URL and its story, the headline without a trailing ' - Source' or
    ' | Source' tail, casefolded, punctuation out. The research agent's URLs are Google News redirect links, never the
    publisher URL the sweep cites, so the same story found by both matches on the headline only."""
    h = f.get("headline") or ""
    if f.get("source"):
        h = re.sub(rf"\s*[-|:\u2013\u2014]\s*{re.escape(f['source'])}\s*$", "", h, flags=re.I)
    story = " ".join(re.sub(r"[\W_]+", " ", h.casefold()).split())
    return {("url", f["url"])} | ({("story", story)} if story else set())


def _newest(f: dict) -> date:
    return f["event_date"] or f["published_date"] or date.min


def public_facts(facts: list[dict]) -> list[dict]:
    """Research facts for the public: no match reason, and no headline on the research agent's facts. An agent
    headline is the raw news feed title (it can name a victim, a farmer or a protester; the privacy floor catches an
    honorific + name only), and the public cannot read the scout's feed either (signals need insights); its own
    summary, source, URL and dates stay."""
    return [{**f, "match_reason": None, **({"headline": None} if f["origin"] == "agent" else {})} for f in facts]


def _nest(p: dict | None) -> dict:
    """research_projects' flattened external columns -> {entry: {field: value} | None} (the sweep's shape)."""
    out: dict = {}
    for (entry, field), col in EXT_COLS.items():
        out.setdefault(entry, {})[field] = (p or {}).get(col)
    return {e: v if any(x is not None for x in v.values()) else None for e, v in out.items()}


@cached
def _research_sweep(s, key):
    return (_one(s, "SELECT * FROM rprojects WHERE project_key = ?", [key]),
            _rows(s, "SELECT * FROM rfacts WHERE project_key = ?", [key]))


def research(key: str) -> dict:
    """One project's web research: the sweep's line (researched_on, latest status, the external block) and its facts
    merged with the research agent's (origin 'agent', SQLite), newest first; an agent fact whose URL or story
    (_cites: the normalised headline) the sweep or an earlier agent fact already cites is dropped (two sweep facts
    from one page stay: they differ in category).
    searched: the sweep searched it or the agent researched it; with no facts that reads 'searched, nothing found'."""
    from . import db  # db imports this module
    asof = state()["asof"]
    proj, sweep = _research_sweep(key)
    seen = set().union(*map(_cites, sweep))
    agent = []
    for r in db.research_facts(key):
        cites = _cites(r)
        if not cites & seen:
            seen |= cites
            agent.append(_agent_fact(r, asof))
    facts = sorted([{**f, "signal_id": None, "judged_at": None} for f in sweep] + agent, key=_newest, reverse=True)
    agent_at = db.researched(key).get(key)
    return {"key": key, "researched_on": proj and proj["researched_on"],
            "searched": bool(proj and proj["searched"]) or agent_at is not None, "agent_researched_at": agent_at,
            "latest_status": proj and proj["latest_status"], "external": _nest(proj), "n_facts": len(facts),
            "n_negative_live": sum(f["live"] for f in facts), "facts": facts}


def research_brief(key: str) -> dict:
    """research() for the project page: the counts and the top N_RESEARCH_TOP facts (live blockers first, most
    severe, then newest)."""
    d = research(key)
    top = sorted(d["facts"], key=lambda f: (not f["live"], -f["severity"], -_newest(f).toordinal()))
    return {**{k: d[k] for k in ("researched_on", "searched", "agent_researched_at", "latest_status", "n_facts",
                                 "n_negative_live")}, "top": top[:N_RESEARCH_TOP]}


def public_research(d: dict) -> dict:
    """research() for the public: the same facts, redacted by public_facts."""
    return {**d, "facts": public_facts(d["facts"])}


@cached
def _research_scope(s, scope):
    """The current projects in scope (key -> name, state, tier), their sweep lines and their sweep facts."""
    sql, params = _scope_sql(scope)
    cur = {r["project_key"]: r for r in _rows(s, f"""SELECT project_key, project_name, state, tier FROM cur
        WHERE {sql}""", params)}
    inscope = f"project_key IN (SELECT project_key FROM cur WHERE {sql})"
    projects = _rows(s, f"SELECT project_key, searched, researched_on FROM rprojects WHERE {inscope}", params)
    return cur, projects, _rows(s, f"SELECT * FROM rfacts WHERE {inscope}", params)


def research_summary(scope=None) -> dict:
    """Web research over the current projects in scope, sweep and agent facts together (deduplicated per project by
    URL and story as research()): coverage, facts by category x direction with the live ones, by state, and the newest live
    blockers (severity >= 2) with their project."""
    from . import db
    s = state()
    cur, projects, sweep = _research_scope(scope)
    seen = {(f["project_key"], c) for f in sweep for c in _cites(f)}
    agent = []
    for r in db.research_facts(keys=frozenset(cur)):
        cites = {(r["project_key"], c) for c in _cites(r)}
        if not cites & seen:
            seen |= cites
            agent.append(_agent_fact(r, s["asof"]))
    facts = sweep + agent
    agent_at = {k: t for k, t in db.researched().items() if k in cur}
    searched = {p["project_key"] for p in projects if p["searched"]} | set(agent_at)
    live = [f for f in facts if f["live"]]

    def n_keys(rows):
        return len({f["project_key"] for f in rows})

    by_cat = []
    for cat, tax in TAXONOMY_OF.items():
        fs = [f for f in facts if f["category"] == cat]
        if fs:
            lv = [f for f in fs if f["live"]]
            by_cat.append({"category": cat, "taxonomy": tax, **{d: sum(f["direction"] == d for f in fs) for d in (
                "negative", "positive", "neutral")}, "n_live": len(lv), "n_projects_live": n_keys(lv)})
    by_state = []
    for st in sorted({r["state"] for r in cur.values()}, key=str):
        keys = {k for k, r in cur.items() if r["state"] == st}
        lv = [f for f in live if f["project_key"] in keys]
        by_state.append({"state": st, "n_current": len(keys), "n_searched": len(keys & searched),
                         "n_with_facts": len(keys & {f["project_key"] for f in facts}), "n_negative_live": len(lv),
                         "n_projects_negative_live": n_keys(lv)})
    by_state.sort(key=lambda r: (-r["n_negative_live"], -r["n_searched"], str(r["state"])))
    # one row per project and page (a page can give a land and a forest fact), the newest and most severe
    first: dict = {}
    for f in sorted((f for f in live if f["severity"] >= 2), key=lambda f: (_newest(f), f["severity"]), reverse=True):
        first.setdefault((f["project_key"], f["url"]), f)
    blockers = list(first.values())[:N_BLOCKERS]
    dates = [p["researched_on"] for p in projects if p["researched_on"]]
    return {
        "asof": s["asof"], "live_window_quarters": LIVE_Q,
        "researched_on": {"first": min(dates, default=None), "last": max(dates, default=None)},
        "coverage": {"n_current": len(cur), "n_searched": len(searched),
                     "n_with_facts": n_keys(facts), "n_facts": len(facts), "n_negative_live": len(live),
                     "n_projects_negative_live": n_keys(live), "n_agent_facts": len(agent),
                     "n_agent_projects": len(agent_at)},
        "by_category": by_cat, "by_state": by_state,
        "top_recent_blockers": [{**{k: f.get(k) for k in ("fact_id", "project_key", "category", "severity",
                                                           "event_date", "date_precision", "published_date",
                                                           "summary", "headline", "source", "url", "origin")},
                                 **{k: cur[f["project_key"]][k] for k in ("project_name", "state", "tier")}}
                                for f in blockers],
        "agent_last_run": max(agent_at.values(), default=None), "note": RESEARCH_NOTE}


def public_research_summary(d: dict) -> dict:
    """research_summary() for the public: the counts, and of the sweep's blockers only headline, URL and dates (the
    event date, and the publish date for a fact whose source gives no event date; a headline is all a public blocker
    says, and the research agent's are raw feed titles: see public_facts)."""
    keep = ("headline", "url", "event_date", "date_precision", "published_date")
    return {**d, "top_recent_blockers": [{k: f[k] for k in keep} for f in d["top_recent_blockers"]
                                         if f["origin"] == "sweep"]}


@cached
def timeline(s, key):
    return _rows(s, f"""SELECT period, physical_progress_pct, expenditure_cr, anticipated_cost_cr,
        anticipated_completion, source_doc_id, source_page, period_type FROM obs
        WHERE project_key = ? AND period <= DATE '{s["asof"]}' ORDER BY period""", [key])


def _add_months(d: date | None, m: float | None) -> date | None:
    if d is None or m is None:
        return None
    y, mo = divmod(d.month - 1 + round(m), 12)
    return date(d.year + y, mo + 1, 1)


@cached
def forecast(s, key):
    cur = _one(s, "SELECT * FROM cur WHERE project_key = ?", [key])
    if cur is None:
        return None
    scen = _rows(s, """SELECT step, quarter, "continue" AS continue_, recover, agency, agency_basis FROM scen
        WHERE project_key = ? ORDER BY step""", [key])
    ana = _rows(s, """SELECT * EXCLUDE (project_key, "asof") FROM ana WHERE project_key = ? ORDER BY rank""", [key])
    n_any = sum(1 for a in ana if a["y_any"] == 1)
    months = sorted(a["y_months"] for a in ana if a["y_months"] is not None)
    median = months[len(months) // 2] if months else None
    summary = (f"{n_any} of {len(ana)} nearest analogues ({ana[0]['basis']} pool) slipped or revised cost within "
               f"4 quarters; median slip {median:.0f} months." if ana and median is not None
               else "no analogues at this stage")
    fit = _one(s, "SELECT max(fit_year) AS y FROM scurve WHERE sector = ? AND fit_year <= ?",
               [cur["sector"], s["asof"].year])
    curve = _rows(s, """SELECT bin_lo AS elapsed_lo, bin_hi AS elapsed_hi, expected_progress, n_projects FROM scurve
        WHERE sector = ? AND fit_year = ? ORDER BY bin""", [cur["sector"], fit and fit["y"]])
    # elapsed ratio -> calendar date on the project's own sanction-to-scheduled span (as in pipeline/gold.py)
    master = _one(s, "SELECT sanction_date FROM master WHERE project_key = ?", [key]) or {}
    start, end = master.get("sanction_date"), cur["scheduled_completion"]
    for p in curve:
        mid = (p["elapsed_lo"] + p["elapsed_hi"]) / 2
        p["date"] = (_add_months(start, mid * ((end.year - start.year) * 12 + end.month - start.month))
                     if start and end and end > start else None)
    ac = cur["anticipated_completion"]
    return {
        "key": key, "asof": s["asof"], "sector": cur["sector"], "elapsed_ratio": cur["elapsed_ratio"],
        "physical_progress_pct": cur["physical_progress_pct"], "scenarios": scen, "analogues": ana,
        "analogue_summary": summary, "scurve_fit_year": fit and fit["y"], "scurve": curve,
        "band": [{"quarter": p["quarter"], "lo": min(p["continue_"], p["recover"], p["agency"]),
                  "mid": p["continue_"], "hi": max(p["continue_"], p["recover"], p["agency"])} for p in scen
                 if None not in (p["continue_"], p["recover"], p["agency"])],
        "completion": {"anticipated": ac, "months_p05": cur["months_p05"], "months_p50": cur["months_p50"],
                       "months_p95": cur["months_p95"], "p05": _add_months(ac, cur["months_p05"]),
                       "p50": _add_months(ac, cur["months_p50"]), "p95": _add_months(ac, cur["months_p95"])},
        "band_method": BAND_METHOD,
    }


# ------------------------------------------------------------ external, models

# external_summary.json factor -> (condition over cur, risk-profile dimension with its evidence line)
EXT_FACTORS = {"land": ("list_contains(c.flags, 'land')", "land_acquisition"),
               "forest_clearance": ("list_contains(c.flags, 'forest')", "forest_clearance"),
               "litigation": ("list_contains(c.flags, 'litigation')", "litigation"),
               "contractor": ("list_contains(c.flags, 'contractor')", "contractor_stress"),
               "utility_shifting": ("coalesce(c.ext_open_utility_shifting = 1, false)", None),
               "inter_agency": ("coalesce(c.ext_open_inter_agency = 1, false)", None)}
CARD = ("project_key", "project_name", "sector", "state", "anticipated_cost_cr", "tier", "p_any_2q",
        "slip_to_date_months")


def _scoped_external(s, summary, scope):
    """external_summary.json recounted over the projects in scope (factor and early-notice counts, capital, top
    lists, as ml/risk_profile.py builds them); the notice backtest, the composite's coverage stats, the PARIVESH and
    land counts, the remark staleness and the hidden-delay priors stay portfolio-wide (the overdue PARIVESH list is
    filtered to the scope)."""
    sql, params = _scope_sql(scope)
    # ponytail: utility shifting / inter-agency evidence comes from the file's top lists, complete while those
    # factors flag <= TOP_FACTOR projects (1 and 3 today); read project_events if they grow past that
    file_lines = {}
    for name, (_, dim) in EXT_FACTORS.items():
        for r in summary["factors"][name]["top"] if dim is None else []:
            file_lines.setdefault(r["project_key"], []).extend(r["evidence"] or [])
    dims = "', '".join(d for _, d in EXT_FACTORS.values() if d)
    rows = _rows(s, f"""SELECT c.project_key, c.project_name, c.sector, c.state, c.anticipated_cost_cr, c.tier,
            c.p_any_2q, c.slip_to_date_months, c.early_notice,
            {", ".join(f"{cond} AS f_{n}" for n, (cond, _) in EXT_FACTORS.items())},
            list({{'d': r.dimension, 'e': r.evidence}}) FILTER (WHERE r.project_key IS NOT NULL) AS ev
        FROM cur c LEFT JOIN rp r ON r.project_key = c.project_key AND r.state = 'flagged' AND r.dimension IN ('{dims}')
        WHERE c.project_key IN (SELECT project_key FROM cur WHERE {sql})
        GROUP BY ALL ORDER BY c.anticipated_cost_cr DESC NULLS LAST, c.project_key""", params)

    def card(r, names):
        ev = {x["d"]: x["e"] for x in r["ev"] or []}
        lines = []
        for n in names:
            dim = EXT_FACTORS[n][1]
            if r[f"f_{n}"]:
                lines += ([f"{n}: {ev[dim]}"] if dim in ev else
                          [ln for ln in file_lines.get(r["project_key"], []) if ln.startswith(n + ":")])
        return {**{k: r[k] for k in CARD}, "anticipated_cost_cr": r["anticipated_cost_cr"] and round(
            r["anticipated_cost_cr"], 1), "p_any_2q": r["p_any_2q"] and round(r["p_any_2q"], 3), "evidence": lines}

    def cap(rs):
        return round(sum(r["anticipated_cost_cr"] or 0 for r in rs), 1)

    factors = {}
    for n in EXT_FACTORS:
        d = [r for r in rows if r[f"f_{n}"]]
        factors[n] = {"n_flagged": len(d), "capital_exposed_cr": cap(d), "top": [card(r, [n]) for r in d[:TOP_FACTOR]]}
    flagged = [r for r in rows if any(r[f"f_{n}"] for n in EXT_FACTORS)]
    notice = [r for r in rows if r["early_notice"]]
    strict = [r for r in notice if r["slip_to_date_months"] is not None and r["slip_to_date_months"] <= 0]
    keys = scope_keys(scope)
    return {**summary, "n_projects": len(rows), "factors": factors, "early_notice": {
        **summary["early_notice"], "n_projects": len(notice), "capital_exposed_cr": cap(notice),
        "by_factor": {n: sum(1 for r in notice if r[f"f_{n}"]) for n in EXT_FACTORS},
        "n_flagged_any": len(flagged), "capital_flagged_any_cr": cap(flagged),
        "no_slip_to_date": {"n_projects": len(strict), "capital_exposed_cr": cap(strict)},
        "top": [card(r, list(EXT_FACTORS)) for r in notice[:TOP_NOTICE]]},
        "external_composite": {**summary["external_composite"], "top_fc_la": [
            r for r in summary["external_composite"]["top_fc_la"] if r["project_key"] in keys]},
        **({"portal": {**summary["portal"], "top_overdue": [r for r in summary["portal"]["top_overdue"]
                                                            if r["project_key"] in keys]}}
           if summary.get("portal") else {})}


@cached
def external_summary(s, scope=None):
    summary = s["external_summary"] if scope is None else _scoped_external(s, s["external_summary"], scope)
    sql, params = _scope_sql(scope)
    cov = _one(s, f"""SELECT count(*) AS n_current,
            count(*) FILTER (WHERE l.la_linked) AS land_linked,
            count(*) FILTER (WHERE l.la_state = 'possible') AS land_possible,
            count(*) FILTER (WHERE f.fc_area_known) AS forest_area_known,
            count(*) FILTER (WHERE c.coverage = 'fc+la') AS composite_fc_la,
            count(*) FILTER (WHERE c.coverage = 'fc_only') AS composite_fc_only
        FROM cur LEFT JOIN land l USING (project_key) LEFT JOIN fc f USING (project_key)
        LEFT JOIN composite c USING (project_key)
        WHERE project_key IN (SELECT project_key FROM cur WHERE {sql})""", params)
    stalled = {r["k"] for r in _rows(s, "SELECT project_key AS k FROM cur WHERE stagnation_override")}

    def mark(cards):  # the stagnation badge and the flagged factors (from the evidence lines) on every card
        return [{**r, "stalled": r["project_key"] in stalled,
                 "factors": list(dict.fromkeys(ln.split(": ", 1)[0] for ln in r.get("evidence") or []))}
                for r in cards]

    inscope = f"project_key IN (SELECT project_key FROM cur WHERE {sql})"
    portal = summary.get("portal") and {**summary["portal"], **_portal_block(s, inscope, params, scope, mark),
                                        "top_overdue": mark(summary["portal"]["top_overdue"])}
    return {**summary, "coverage": cov, "caveats": CAVEATS[:2] + [
        f"Land is rated for {cov['land_linked']} of {cov['n_current']} current projects ({cov['land_possible']} more "
        f"have a possible link, not rated) and forest area is known for {cov['forest_area_known']}; everything else "
        "is unknown, not clear."],
        "factors": {n: {**f, "top": mark(f["top"])} for n, f in summary["factors"].items()},
        "early_notice": {**summary["early_notice"], "top": mark(summary["early_notice"]["top"])},
        "portal": portal,
        "remark_flags": summary.get("remark_flags") and {**summary["remark_flags"],
                                                         **_remark_block(s, inscope, params)},
        "land_coverage": summary.get("land_coverage") and {**summary["land_coverage"],
                                                           "by_state": _land_states(s, inscope, params)},
        "hidden_delay_priors": summary.get("hidden_delay_priors") and _priors_in_scope(
            s, summary["hidden_delay_priors"], inscope, params)}


def _priors_in_scope(s, block, inscope, params):
    """The measured priors with n_current: how many current projects in scope each one describes today
    (hidden_delay with current set; a remark status older than LIVE_Q quarters does not count); None for the
    NH/district grouping, which the checklist does not rate."""
    rows = _rows(s, f"""SELECT r.fc_stage, r.fc_stage_as_of, r.la_pct, r.la_pct_as_of, l.la_state, p.n_final,
            p.n_open
        FROM cur c LEFT JOIN rstat r USING (project_key) LEFT JOIN land l USING (project_key)
        LEFT JOIN portal p USING (project_key) WHERE c.{inscope}""", params)
    n = Counter((h["factor"], h["group"]) for r in rows
                for h in hidden_delay({"la_state": r["la_state"]}, r, r, s["asof"]) if h["current"])
    return {**block, "rows": [{**r, "n_current": None if r["factor"] == "land_complexity_nh"
                               else n[(r["factor"], r["group"])]} for r in block["rows"]]}


REMARK_CATS = "'land', 'forest_env', 'litigation', 'contractor'"  # ml/risk_profile.EVENT_DIMENSION
STATE_KEY = "trim(regexp_replace(replace(upper({}), '&', ' AND '), '[^A-Z]+', ' ', 'g'))"  # external.state_key


def _remark_block(s, inscope, params):
    """Open remark events of the current projects in scope, live (last mention within LIVE_Q calendar quarters of
    asof) against stale, per category with the newest last mention of the stale ones (ml/risk_profile.remark_flags
    recounted in scope)."""
    rows = _rows(s, f"""WITH e AS (
            SELECT project_key, category, last_seen,
                   last_seen > DATE '{s["asof"]}' - INTERVAL {3 * LIVE_Q} MONTH AS live
            FROM events WHERE status = 'open' AND category IN ({REMARK_CATS}) AND {inscope})
        SELECT category, count(DISTINCT project_key) AS open,
               count(DISTINCT project_key) FILTER (WHERE live) AS live,
               count(DISTINCT project_key) FILTER (WHERE NOT live) AS stale,
               max(last_seen) FILTER (WHERE NOT live) AS last_known
        FROM e GROUP BY GROUPING SETS ((category), ()) ORDER BY category NULLS FIRST""", params)
    total = next((r for r in rows if r["category"] is None), {"open": 0, "live": 0, "stale": 0})
    return {"n_projects_open_by_remark_rule": total["open"], "n_projects_live": total["live"],
            "n_projects_stale": total["stale"],
            "by_category": {r["category"]: {k: r[k] for k in ("open", "live", "last_known")}
                            for r in rows if r["category"]}}


def _portal_block(s, inscope, params, scope, mark):
    """PARIVESH-linked current projects in scope: the counts of ml/risk_profile.portal_summary, every still-open one
    (overdue first, then longest in its stage) and the proposals the remarks name (past projects too)."""
    n = _one(s, f"""SELECT count(*) AS n_linked, count(*) FILTER (WHERE p.n_open > 0) AS n_open,
            count(*) FILTER (WHERE p.n_overdue > 0) AS n_overdue,
            count(*) FILTER (WHERE p.open_not_in_report) AS n_open_not_in_report,
            round(coalesce(sum(c.anticipated_cost_cr) FILTER (WHERE p.n_open > 0), 0), 1) AS capital_open_cr
        FROM portal p JOIN cur c USING (project_key) WHERE p.{inscope}""", params)
    by_stage = {r["stage_at_asof"]: r["n"] for r in _rows(s, f"""SELECT stage_at_asof, count(*) AS n FROM portal
        WHERE {inscope} GROUP BY 1 ORDER BY n DESC, 1""", params)}
    open_list = _rows(s, f"""SELECT {", ".join("c." + k for k in CARD)}, p.stage_at_asof, p.months_in_stage,
            p.norm_months, p.n_overdue > 0 AS overdue, p.oldest_open_received, p.open_not_in_report, p.n_open,
            p.proposals
        FROM portal p JOIN cur c USING (project_key) WHERE p.n_open > 0 AND p.{inscope}
        ORDER BY overdue DESC, p.months_in_stage DESC NULLS LAST, c.anticipated_cost_cr DESC NULLS LAST""", params)
    keys, cases = scope_keys(scope) if scope else None, {}
    for r in _rows(s, """SELECT f.* EXCLUDE (name, evidence), m.project_name, c.project_key IS NOT NULL AS current
            FROM fcprop f LEFT JOIN master m USING (project_key) LEFT JOIN cur c USING (project_key)
            ORDER BY f.project_key, f.received"""):
        if keys is None or r["project_key"] in keys:
            c = cases.setdefault(r["project_key"], {k: r[k] for k in ("project_key", "project_name", "current")}
                                 | {"proposals": []})
            c["proposals"].append({k: v for k, v in r.items() if k not in c})
    return {**n, "by_stage": by_stage, "open_list": mark(open_list), "cases": list(cases.values())}


def _land_states(s, inscope, params):
    """Per state: the Bhoomi Rashi register (stretches, parcels, hectares, latest notification) and the current
    road projects in scope, rated (km match), flagged (complexity 4+) and possible (NH or district only)."""
    return _rows(s, f"""WITH p AS (
            SELECT {STATE_KEY.format("c.state")} AS k, any_value(c.state) AS name,
                   count(*) FILTER (WHERE l.la_match_method <> 'not_road') AS n_road,
                   count(*) FILTER (WHERE l.la_linked) AS n_rated,
                   count(*) FILTER (WHERE l.la_state = 'flagged') AS n_flagged,
                   count(*) FILTER (WHERE l.la_state = 'possible') AS n_possible
            FROM cur c JOIN land l USING (project_key) WHERE c.state IS NOT NULL AND c.{inscope}
            GROUP BY 1)
        SELECT coalesce(p.name, r.k) AS state, r.k IS NOT NULL AS has_data, r.stretches, r.parcels,
               round(r.area_ha, 1) AS area_ha, r.last_notif, coalesce(p.n_road, 0) AS n_road,
               coalesce(p.n_rated, 0) AS n_rated, coalesce(p.n_flagged, 0) AS n_flagged,
               coalesce(p.n_possible, 0) AS n_possible
        FROM register r FULL JOIN p USING (k) WHERE r.k IS NOT NULL OR p.n_road > 0
        ORDER BY r.area_ha DESC NULLS LAST, state""", params)


@cached
def early_notice(s):
    """Current early-notice projects with their flagged external evidence lines."""
    dims = "', '".join(FLAG_DIMS.values())
    return _rows(s, f"""SELECT c.project_key, c.project_name, c.tier, c.anticipated_cost_cr, c.flags,
            c.ext_open_utility_shifting, c.ext_open_inter_agency,
            list(r.dimension || ': ' || r.evidence ORDER BY r.dimension) FILTER (WHERE r.project_key IS NOT NULL)
                AS evidence
        FROM cur c LEFT JOIN rp r ON r.project_key = c.project_key AND r.state = 'flagged'
            AND r.dimension IN ('{dims}')
        WHERE c.early_notice GROUP BY ALL ORDER BY c.anticipated_cost_cr DESC NULLS LAST""")


@cached
def in_tier(s, tier):
    return _rows(s, """SELECT project_key, project_name, tier, p_any_2q, anticipated_cost_cr FROM cur
        WHERE tier = ? ORDER BY p_any_2q DESC""", [tier])


@cached
def models(s):
    reg = json.loads((MODEL / "registry.json").read_text(encoding="utf-8"))
    champ = reg.get("champions", {})
    run_id = (champ.get("y_any_h2") or next(iter(champ.values()), {})).get("run_id")
    run = MODEL / "runs" / str(run_id)

    def csv(name, sql="SELECT * FROM t"):
        path = run / name
        return _rows(s, sql.replace("FROM t", f"FROM read_csv_auto('{_posix(path)}')")) if path.exists() else []

    champions = {c["entry_id"] for c in champ.values()}
    runs = [{"entry_id": r["entry_id"], "run_id": r["run_id"], "model": r["model"], "target": r["target"],
             "horizon": r["horizon"], "gold_version": r["gold_version"], "created_at": r.get("created_at"),
             "pr_auc": r["metrics"]["pooled"].get("pr_auc"), "ece": r["metrics"]["pooled"].get("ece"),
             "test_pr_auc": (r["metrics"].get("test") or {}).get("pr_auc"), "champion": r["entry_id"] in champions}
            for r in reg.get("runs", [])]
    return {"champions": champ, "run_id": run_id, "backtest": csv("backtest_summary.csv"),
            "ablation": csv("ablation.csv"),
            "shap_summary": csv("shap_summary.csv", """SELECT feature, "group", mean_abs_shap FROM t
                WHERE target = 'y_any' AND horizon = 2 ORDER BY mean_abs_shap DESC LIMIT 20"""),
            "calibration": csv("calibration.csv", "SELECT * FROM t ORDER BY target, horizon, model, bin"),
            "registry": runs[-100:], "decisions": reg.get("decisions", [])[-100:], "live_accuracy": live_accuracy()}


def average_precision(y: list[int], p: list[float]) -> float | None:
    """PR-AUC as average precision: the mean of the precision at each positive, ranked by p (ties by order)."""
    order = sorted(range(len(p)), key=lambda i: -p[i])
    hits, total = 0, 0.0
    for rank, i in enumerate(order, 1):
        if y[i]:
            hits += 1
            total += hits / rank
    return total / hits if hits else None


@cached
def live_accuracy(s):
    """Realised 2-quarter outcomes of logged predictions (latest model per project and asof): filled in the log by
    the watcher, or read from the h=2 labels once silver has the report 2 quarters after the asof."""
    rows = _rows(s, f"""
        WITH p AS (SELECT * FROM read_parquet('{_posix(GOLD / "prediction_log.parquet")}')
                   QUALIFY row_number() OVER (PARTITION BY project_key, "asof" ORDER BY model_version DESC) = 1),
             l AS (SELECT project_key, period AS "asof", y_any FROM read_parquet('{_posix(GOLD / "labels_h2.parquet")}')
                   WHERE y_any IS NOT NULL)
        SELECT p."asof", p.tier, p.p_any_2q, coalesce(p.y_any_2q, l.y_any) AS y
        FROM p LEFT JOIN l USING (project_key, "asof")""")
    done = [r for r in rows if r["y"] is not None]
    watch = [r for r in done if r["tier"] in ("Critical", "High")]
    scored = [r for r in done if r["p_any_2q"] is not None]
    first = min((r["asof"] for r in rows), default=None)
    out = {"n_logged": len(rows), "n_realised": len(done), "first_asof": first,
           "n_critical_high_realised": len(watch),
           "precision_critical_high": sum(r["y"] for r in watch) / len(watch) if watch else None,
           "base_rate": sum(r["y"] for r in done) / len(done) if done else None,
           "pr_auc": average_precision([r["y"] for r in scored], [r["p_any_2q"] for r in scored])
           if len(scored) >= 30 else None, "note": LIVE_NOTE}
    if not done:
        out["note"] = (f"No logged prediction is realised yet: the earliest asof is {first}, and its 2-quarter outcome "
                       "is known once the report 2 quarters later is in silver. " + LIVE_NOTE)
    return out


# ------------------------------------------------------ agencies, bottlenecks

@cached
def agency_matrix(s, sector=None, ministry=None, include_hidden=False, scope=None):
    """scope ('ministry', m): the agencies with a current project of that ministry (or matrix ministry m);
    ('agency', a): every agency, a flagged is_self and always shown."""
    kind, name = scope or (None, None)
    self_ = name if kind == "agency" else None
    scope_sql, scope_params = "true", []
    if kind == "ministry":
        scope_sql = """(ministry = ? OR agency IN (SELECT a.canonical FROM cur c JOIN amap a ON a.raw = c.agency
            WHERE c.ministry = ?))"""
        scope_params = [name, name]
    counts = _one(s, f"""SELECT count(*) AS n, count(*) FILTER (WHERE hidden) AS n_hidden FROM agencies
        WHERE {scope_sql}""", scope_params)
    conds, params = [scope_sql], list(scope_params)
    if not include_hidden:
        conds.append("(NOT hidden OR agency = ?)")
        params.append(self_)
    for col, v in (("sector", sector), ("ministry", ministry)):
        if v:
            conds.append(f"{col} = ?")
            params.append(v)
    points = _rows(s, f"""SELECT * EXCLUDE ("asof"), coalesce(agency = ?, false) AS is_self FROM agencies
        WHERE {" AND ".join(conds)} ORDER BY hidden, capital_cr DESC, n_projects DESC, agency LIMIT 500""",
                   [self_] + params)
    return {"asof": s["asof"], "n_agencies": counts["n"], "n_hidden": counts["n_hidden"], "method": AGENCY_METHOD,
            "points": points}


@cached
def agency_known(s, agency):
    return _one(s, "SELECT 1 AS ok FROM agencies WHERE agency = ?", [agency]) is not None


def _top_members(s, rows):
    """Replace each bottleneck row's member_keys by its first TOP_MEMBERS members (key, name, tier, p, cost)."""
    keys = sorted({k for r in rows for k in r["member_keys"][:TOP_MEMBERS]})
    got = {r["key"]: r for r in _rows(s, f"""SELECT project_key AS "key", project_name AS name, tier, p_any_2q,
        anticipated_cost_cr FROM cur WHERE project_key IN ({','.join('?' * len(keys))})""", keys)} if keys else {}
    for r in rows:
        r["top_members"] = [got[k] for k in r.pop("member_keys")[:TOP_MEMBERS] if k in got]
    return rows


def _cut_bottleneck(s, b, keys):
    """Bottleneck row b cut to its members in keys (None: b as it is): counts, capital, means, dates, evidence lines
    and headline over those members, as pipeline/bottlenecks.py builds them; None when no member is in scope."""
    if keys is None:
        return b
    members = [k for k in b["member_keys"] if k in keys]
    if not members:
        return None
    m = _one(s, f"""SELECT coalesce(sum(anticipated_cost_cr), 0) AS cap, avg(p_any_2q) AS p, avg(months_p50) AS mo,
        count(*) FILTER (WHERE tier IN ('Critical', 'High')) AS ch FROM cur
        WHERE project_key IN ({','.join('?' * len(members))})""", members)
    names = {r["k"]: r["name"] for r in _rows(s, f"""SELECT project_key AS k, project_name AS name FROM cur
        WHERE project_key IN ({','.join('?' * len(members))})""", members)}
    ev = [e for e in _rows(s, """SELECT project_key, kind, first_seen, last_seen, evidence FROM bmembers
        WHERE bottleneck_id = ? ORDER BY last_seen DESC NULLS LAST, kind""", [b["bottleneck_id"]])
          if e["project_key"] in keys]
    lines = list({e["project_key"]: e for e in reversed(ev)}.values())[::-1]  # the latest line per project
    firsts, lasts = [e["first_seen"] for e in ev if e["first_seen"]], [e["last_seen"] for e in ev if e["last_seen"]]
    return {**b, "member_keys": members, "n_projects": len(members), "capital_exposed_cr": round(m["cap"], 2),
            "mean_p_any_2q": m["p"], "mean_months_p50": m["mo"], "n_critical_high": m["ch"],
            "earliest_first_seen": min(firsts, default=None), "last_seen": max(lasts, default=None),
            "n_signals": sum(e["kind"] == "signal" for e in ev),
            "evidence": [f"{str(names.get(e['project_key'], e['project_key']))[:70]} ({e['project_key']}): "
                         f"{e['evidence']}" for e in lines[:N_EVIDENCE]],
            "headline": f"Blocking {len(members)} project{'s' * (len(members) != 1)} worth Rs {m['cap']:,.0f} Cr"}


@cached
def bottlenecks(s, category=None, state_=None, min_projects=None, level=None, page=1, size=50, scope=None):
    """scope: members cut to the viewer's projects and every figure recounted over them; clusters with none hidden
    (then min_projects applies to the in-scope count)."""
    keys = scope_keys(scope) if scope else None
    every = [r for r in (_cut_bottleneck(s, b, keys) for b in _rows(s, 'SELECT * EXCLUDE ("asof") FROM bottlenecks'))
             if r is not None]
    rows = [r for r in every if r["n_projects"] >= (min_projects or 0) and all(
        r[c] == v for c, v in (("category", category), ("state", state_), ("level", level)) if v is not None)]
    rows.sort(key=lambda r: (-r["capital_exposed_cr"], r["bottleneck_id"]))
    summary = s["bottlenecks_summary"]
    if keys is not None:
        members = sorted({k for r in every for k in r["member_keys"]})
        cap = _one(s, f"""SELECT coalesce(sum(anticipated_cost_cr), 0) AS cap FROM cur
            WHERE project_key IN ({','.join('?' * len(members)) or 'NULL'})""", members)["cap"]
        summary = {**summary, "n_bottlenecks": sum(r["level"] == "authority" for r in every),
                   "n_rollups": sum(r["level"] == "state" for r in every), "n_projects": len(members),
                   "capital_exposed_cr": round(cap, 1),
                   "by_category": dict(sorted(Counter(r["category"] for r in every).items()))}
    return {"asof": s["asof"], "total": len(rows), "page": page, "size": size, "summary": summary,
            "items": _top_members(s, rows[(page - 1) * size: page * size])}


@cached
def bottleneck(s, bid, page=1, size=50, scope=None):
    """One bottleneck and one page of its member projects (riskiest first) with their evidence lines; None when it
    does not exist or has no member in scope."""
    b = _one(s, 'SELECT * EXCLUDE ("asof") FROM bottlenecks WHERE bottleneck_id = ?', [bid])
    b = b and _cut_bottleneck(s, b, scope_keys(scope) if scope else None)
    if b is None:
        return None
    keys = b["member_keys"]
    page_keys = keys[(page - 1) * size: page * size]
    got = {r["key"]: r for r in _rows(s, f"""SELECT project_key AS "key", project_name AS name, sector, state, agency,
        tier, p_any_2q, months_p50, anticipated_cost_cr FROM cur
        WHERE project_key IN ({','.join('?' * len(page_keys))})""", page_keys)} if page_keys else {}
    ev = {}
    for e in _rows(s, """SELECT * EXCLUDE (bottleneck_id) FROM bmembers WHERE bottleneck_id = ?
            ORDER BY project_key, last_seen DESC""", [bid]):
        ev.setdefault(e.pop("project_key"), []).append(e)
    members = [{**got[k], "evidence": ev.get(k, [])} for k in page_keys if k in got]
    return {"asof": s["asof"], "bottleneck": _top_members(s, [b])[0], "total": len(keys), "page": page, "size": size,
            "members": members}
