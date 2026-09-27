"""Read side of the API: DuckDB over the gold and silver Parquet files.

Each data version is loaded once into an in-memory DuckDB: `cur` holds one
row per scored project (scores + latest observation + features + open flags),
the other tables are the per-project Parquet files as written by the pipeline.
The version is the mtime of predictions_latest.json, silver_manifest.json and
external_summary.json (the profile step writes it last); when one changes the
tables are reloaded and every cached result goes with the old version.
"""
from __future__ import annotations

import functools
import json
import math
import threading
from datetime import date, datetime
from pathlib import Path

import duckdb

from pipeline.identity.config import IdentityConfig
from pipeline.identity.identity_map import IdentityMap

ROOT = Path(__file__).resolve().parents[1]
GOLD, SILVER, MODEL = ROOT / "dataset" / "gold", ROOT / "dataset" / "silver", ROOT / "model"
POINTER, SILVER_MANIFEST = GOLD / "predictions_latest.json", SILVER / "silver_manifest.json"
EXTERNAL_SUMMARY = GOLD / "external_summary.json"
VERSION_FILES = (POINTER, SILVER_MANIFEST, EXTERNAL_SUMMARY)

TIERS = ["Critical", "High", "Medium", "Low"]
# list flag -> risk-profile dimension that raises it
FLAG_DIMS = {"land": "land_acquisition", "forest": "forest_clearance", "litigation": "litigation",
             "contractor": "contractor_stress"}
SORTS = {"risk": "p_any_2q", "cost": "anticipated_cost_cr", "slip": "slip_to_date_months", "name": "project_name"}
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
    "Land-acquisition records (Bhoomi Rashi) are linked only for Maharashtra national-highway projects; "
    "elsewhere land is unknown, not clear.",
    "Probabilities rank projects against each other (tiers go by rank); they are not calibrated frequencies.",
    "Projects without an anticipated completion date have no date-based scores and no tier (untiered).",
]
BAND_METHOD = (
    "Progress band: each quarter the lower and upper edge are the lowest and highest of the three scenario curves "
    "(own recent velocity, sector-median velocity, agency pattern) and the middle line is the own-velocity curve; "
    "it is a scenario range, not a statistical interval. Completion band: anticipated completion plus the 5th, "
    "50th and 95th percentile of predicted slip over the next 2 quarters (LightGBM quantile models), to the month.")

_lock = threading.Lock()
_state: dict = {}
_pinned = threading.Event()


def _version() -> tuple:
    return tuple(p.stat().st_mtime_ns for p in VERSION_FILES)


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
        "land_pairs": GOLD / "external_land_pairs.parquet", "composite": GOLD / "external_composite.parquet",
        "scen": GOLD / f"scenarios_{ym}.parquet", "ana": GOLD / f"analogues_{ym}.parquet",
        "scurve": GOLD / "sector_scurve.parquet",
    }
    for name, path in files.items():
        # sorted by key so a one-project filter skips most row groups
        order = "ORDER BY project_key" if name not in ("scurve",) else ""
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{_posix(path)}') {order}")
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
        r AS (SELECT project_key, {flag_cols} FROM rp GROUP BY 1),
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
                   AS flags
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
    }


def pin(on: bool) -> None:
    """While pinned, state() keeps the loaded version even if the version files change: the report watcher pins
    it while a pipeline run rewrites them, and leaves it pinned when a failed run left them half rewritten."""
    _pinned.set() if on else _pinned.clear()


def state() -> dict:
    """The loaded data version, reloaded when a version file changes (unless pinned)."""
    global _state
    if _state and _pinned.is_set():
        return _state
    v = _version()
    if _state.get("version") != v:
        with _lock:
            if _state.get("version") != v:
                _state = {**_load(), "version": v}
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


def _where(ministry=None, sector=None, state_=None, tier=None, q=None, flag=None) -> tuple[str, list]:
    conds, params = [], []
    for col, v in (("ministry", ministry), ("sector", sector), ("state", state_)):
        if v:
            conds.append(f"{col} = ?")
            params.append(v)
    if tier == "untiered":
        conds.append("tier IS NULL")
    elif tier:
        conds.append("tier = ?")
        params.append(tier)
    if q:
        conds.append("(project_name ILIKE ? OR project_key ILIKE ?)")
        params += [f"%{q}%"] * 2
    if flag:
        conds.append("list_contains(flags, ?)")
        params.append(flag)
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def canonical(key: str) -> str | None:
    """Canonical PRJ key for any key the identity map knows, else None."""
    idmap = state()["idmap"]
    k = idmap.canonical(key)
    return k if k in idmap._projects else None  # noqa: SLF001 - read-only, as in pipeline/identity/bundle.py


# ------------------------------------------------------------------ portfolio

@cached
def meta(s):
    counts = _one(s, "SELECT count(*) AS n, count(*) FILTER (WHERE tier IS NULL) AS untiered FROM cur")
    return {
        "asof": s["asof"], "model_version": s["model_version"], "gold_version": s["gold_version"],
        "silver_version": s["silver_version"], "n_current": counts["n"], "n_untiered": counts["untiered"],
        "latest_report_period": s["latest_report_period"], "latest_report_doc": s["latest_report_doc"],
        "models": s["pointer"].get("models", {}), "caveats": CAVEATS,
    }


@cached
def portfolio(s, ministry=None, sector=None, state_=None, tier=None):
    where, params = _where(ministry, sector, state_, tier)
    k = _one(s, f"""SELECT count(*) AS n_projects,
            sum(original_cost_cr) AS original_cost_cr, sum(anticipated_cost_cr) AS anticipated_cost_cr,
            sum(expenditure_cr) AS expenditure_cr,
            sum(anticipated_cost_cr - original_cost_cr) AS overrun_cr,
            100 * sum(anticipated_cost_cr - original_cost_cr)
                / nullif(sum(original_cost_cr) FILTER (WHERE anticipated_cost_cr IS NOT NULL), 0) AS overrun_pct,
            avg(physical_progress_pct) AS avg_progress_pct
        FROM cur{where}""", params)
    tiers = {r["tier"]: r for r in _rows(s, f"""SELECT coalesce(tier, 'untiered') AS tier, count(*) AS n,
        coalesce(sum(anticipated_cost_cr), 0) AS capital_cr FROM cur{where} GROUP BY 1""", params)}

    def by(col):
        return _rows(s, f"""SELECT {col} AS name, count(*) AS n, sum(anticipated_cost_cr) AS capital_cr,
            count(*) FILTER (WHERE tier = 'Critical') AS n_critical, count(*) FILTER (WHERE tier = 'High') AS n_high
            FROM cur{where} GROUP BY 1 ORDER BY capital_cr DESC NULLS LAST, n DESC""", params)

    top = _rows(s, f"""SELECT project_key AS "key", project_name AS name, sector, state, tier, p_any_2q,
        anticipated_cost_cr FROM cur{where} ORDER BY p_any_2q DESC NULLS LAST, project_key LIMIT 20""", params)
    return {
        "asof": s["asof"], "filters": {"ministry": ministry, "sector": sector, "state": state_, "tier": tier},
        "kpis": k,
        "tiers": [tiers.get(t, {"tier": t, "n": 0, "capital_cr": 0.0}) for t in TIERS + ["untiered"]],
        "by_state": by("state"), "by_sector": by("sector"), "by_ministry": by("ministry"), "top": top,
    }


@cached
def projects(s, q=None, ministry=None, sector=None, state_=None, tier=None, flag=None, sort="risk", order=None,
             page=1, size=50):
    size = max(1, min(int(size), 100))
    page = max(1, int(page))
    where, params = _where(ministry, sector, state_, tier, q, flag)
    direction = (order or ("asc" if sort == "name" else "desc")).upper()
    total = _one(s, f"SELECT count(*) AS n FROM cur{where}", params)["n"]
    items = _rows(s, f"""SELECT {ROW_SQL} FROM cur{where}
        ORDER BY {SORTS[sort]} {direction} NULLS LAST, project_key LIMIT ? OFFSET ?""",
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

@cached
def project(s, key):
    """Everything the project page shows for one canonical key (see canonical())."""
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
    return {
        "key": key, "master": master, "latest": latest, "scores": scores,
        "flags": cur["flags"] if cur else [],
        "risk_profile": _rows(s, """SELECT dimension, state, evidence, source, as_of_date FROM rp
            WHERE project_key = ?""", [key]),
        "external": {
            "fc": _one(s, "SELECT * EXCLUDE (project_key) FROM fc WHERE project_key = ?", [key]),
            "land": _one(s, "SELECT * EXCLUDE (project_key) FROM land WHERE project_key = ?", [key]),
            "land_pairs": _rows(s, """SELECT * EXCLUDE (project_key) FROM land_pairs WHERE project_key = ?
                ORDER BY nh, stretch_id""", [key]),
            "composite": _one(s, "SELECT * EXCLUDE (project_key) FROM composite WHERE project_key = ?", [key]),
            "events": _rows(s, """SELECT * EXCLUDE (project_key, state, sector) FROM events WHERE project_key = ?
                ORDER BY status DESC, last_seen DESC, category""", [key]),
        },
        "provenance": {
            "asof": s["asof"], "model_version": s["model_version"] if cur else None,
            "gold_version": s["gold_version"], "silver_version": s["silver_version"],
            "source_doc_id": latest and latest["source_doc_id"], "source_page": latest and latest["source_page"],
            "period": latest and latest["period"], "period_type": latest and latest["period_type"],
        },
        "review": review,
    }


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


@cached
def last_remarks(s, key):
    """Most recent free-text remark (reports before 2024) for one project, or None."""
    return _one(s, """SELECT period, remarks, source_doc_id, source_page FROM obs
        WHERE project_key = ? AND period < DATE '2024-01-01' AND length(trim(remarks)) > 0
        ORDER BY period DESC LIMIT 1""", [key])


# ------------------------------------------------------------ external, models

@cached
def external_summary(s):
    summary = json.loads(EXTERNAL_SUMMARY.read_text(encoding="utf-8"))
    cov = _one(s, """SELECT count(*) AS n_current,
            count(*) FILTER (WHERE l.la_linked) AS land_linked,
            count(*) FILTER (WHERE f.fc_area_known) AS forest_area_known,
            count(*) FILTER (WHERE c.coverage = 'fc+la') AS composite_fc_la,
            count(*) FILTER (WHERE c.coverage = 'fc_only') AS composite_fc_only
        FROM cur LEFT JOIN land l USING (project_key) LEFT JOIN fc f USING (project_key)
        LEFT JOIN composite c USING (project_key)""")
    return {**summary, "coverage": cov, "caveats": CAVEATS[:2] + [
        f"Land is linked for {cov['land_linked']} of {cov['n_current']} current projects and forest area is known "
        f"for {cov['forest_area_known']}; everything else is unknown, not clear."]}


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

    def csv(name):
        path = run / name
        return _rows(s, f"SELECT * FROM read_csv_auto('{_posix(path)}')") if path.exists() else []

    return {"champions": champ, "run_id": run_id, "backtest": csv("backtest_summary.csv"),
            "ablation": csv("ablation.csv")}
