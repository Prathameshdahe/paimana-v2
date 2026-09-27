"""
Silver build: typed rows, quarantine, then the quarterly panel (docs/IMPLEMENTATION_GUIDE_v2.md B 1.2).

Run from repo root after the identity build:  python -m pipeline.run silver

Inputs   clean/projects/projects_monthly.csv, projects_quarterly.csv, portal/portal_projects.csv
         (+ project_master.csv, reference/sector_map.csv for the portal adapter), silver/identity/resolved_rows.parquet
Outputs  silver/typed_rows.parquet, silver/quarantine/<rule_id>.parquet, silver/quarantine/summary.csv
         silver/observations.parquet (accepted links), observations_review.parquet (review links),
         silver/project_master.parquet, silver/sector_context.parquet, silver/coverage.parquet (+ .csv),
         silver/silver_manifest.json

Row ids come from build_identity.row_ids over the same adapted frame, so every clean row joins its key on
(source_report_type, source_period, source_row_id).
The panel has one row per (project_key, quarter). Each value is the last non-null observation in the
quarter (groupby last skips nulls); provenance and status come from the quarter's last report. The portal
snapshot sits in the 2026-07 quarter and is used only for keys with no PAIMANA flash row in that quarter.
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.build_identity import (KEY_COLS, PORTAL_FILE, PORTAL_PERIOD, adapt_clean,  # noqa: E402
                                     adapt_portal, row_ids)
from pipeline.identity import IdentityConfig, IdentityMap, run_all  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "dataset" / "clean"
SILVER = ROOT / "dataset" / "silver"
IDENTITY = SILVER / "identity"

PROJECT_FILES = ("projects_monthly.csv", "projects_quarterly.csv")
TEXT = ["source_file", "list_type", "project_code", "project_name", "sector", "sector_hml", "state", "agency",
        "ministry", "remarks", "dq_note", "dq_flags"]
DATES = ["doa_original", "doa_revised", "doc_original", "doc_revised", "doc_anticipated", "date_completed_actual",
         "expenditure_upto"]
COMPLETION = ["doc_original", "doc_revised", "doc_anticipated", "date_completed_actual"]
COSTS = ["cost_original_cr", "cost_revised_cr", "cost_anticipated_cr", "expenditure_cum_cr"]
MONEY = COSTS + ["outlay_current_fy_cr"]
NUMBERS = MONEY + ["physical_progress_pct", "delay_months"]
PLACEHOLDER_DATE = pd.Timestamp("1999-01-01")
IDENTITY_COLS = ["project_key", "match_score", "match_method", "review_status"]
Q_ID = KEY_COLS + ["project_key", "review_status", "source_file", "page"]
REASONS = {
    "progress_out_of_range": "physical progress outside 0-100",
    "negative_money": "negative cost or expenditure",
    "expenditure_gt_3x_cost": "expenditure above 3x latest cost (anticipated, else revised, else original)",
    "completion_before_sanction": "a completion date before the approval date",
    "placeholder_date": "01/1999 placeholder date",
    "duplicate_key_period": "same key twice in one list of one report; the more complete row was kept",
}
# list_type preference when one report prints a project in several lists; anything else ranks last
LIST_RANK = {"ongoing": 0, "completed": 1, "newly_added": 2}
REPORT = ["project_key", "review_status", "source_report_type", "source_period"]
FILLED = DATES + NUMBERS + ["sector", "state", "agency", "ministry", "project_name", "remarks"]
PERIOD_TYPE = {"monthly_flash": "monthly", "quarterly_qpisr": "quarterly", "paimana_flash": "flash",
               "portal": "portal"}
PANEL_RENAME = {"source_file": "source_doc_id", "page": "source_page", "report_period": "report_period_last",
                "list_type": "status", "cost_original_cr": "original_cost_cr", "cost_revised_cr": "revised_cost_cr",
                "expenditure_cum_cr": "expenditure_cr", "doa_original": "sanction_date",
                "doc_original": "scheduled_completion", "doc_revised": "revised_completion"}
LAST_ROW = ["period_type", "source_doc_id", "source_page", "report_period_last", "status"]
LAST_VALID = ["original_cost_cr", "revised_cost_cr", "anticipated_cost_cr", "cost_basis", "expenditure_cr",
              "physical_progress_pct", "sanction_date", "scheduled_completion", "revised_completion",
              "anticipated_completion", "completion_basis", "agency", "ministry", "sector", "sector_hml", "state",
              "project_name", "project_code", "remarks", "delay_months", "date_completed_actual"]
PANEL_COLS = (["project_key", "period"] + LAST_ROW[:4] + LAST_VALID[:11] + ["status", "is_completed"]
              + LAST_VALID[11:20] + ["obs_count_in_quarter", "months_since_last_obs", "dq_score"])
MAX_FLAGS = 5  # ponytail: fixed scale, 5+ distinct dq tokens in a quarter score 0
PK = ["project_key", "period"]
COVERAGE = ["sector", "state", "agency", "original_cost_cr", "anticipated_cost_cr", "expenditure_cr",
            "physical_progress_pct", "scheduled_completion", "anticipated_completion"]
# performance sector -> project sector vocabulary (reference/sector_map.csv); Cement has no project sector
PERF_SECTOR = {"Power": "Power", "Coal": "Coal", "Steel": "Steel", "Fertilizers": "Fertilizers & Chemicals",
               "Petroleum & Natural Gas": "Petroleum & Natural Gas", "Roads": "Roads & Highways",
               "Railways": "Railways", "Shipping & Ports": "Shipping & Ports", "Civil Aviation": "Civil Aviation",
               "Telecommunications": "Telecommunications"}


def add_token(note, mask, token):
    """Append a ;-token to dq_note where mask is true."""
    return note.mask(mask, (note.fillna("") + ";" + token).str.lstrip(";"))


def typed(raw):
    """Explicit dtypes: dates (YYYY-MM or YYYY-MM-DD) -> month start, money and progress -> float64.
    A value that does not parse becomes null plus 'parse_fail:<col>' in dq_note, never 0. Values the
    extractor marked as placeholders (dq_note placeholder_zero / placeholder_doc_1999) become null."""
    d = raw.copy()
    note = d["dq_note"].astype("str")
    for c in DATES:
        s = d[c].astype("str").str.strip()
        ok = s.str.fullmatch(r"\d{4}-\d{2}(-\d{2})?").fillna(False).astype(bool)
        d[c] = pd.to_datetime(s.where(ok).str[:7], format="%Y-%m", errors="coerce").astype("datetime64[us]")
        note = add_token(note, s.notna() & s.ne("") & d[c].isna(), f"parse_fail:{c}")
    for c in NUMBERS:
        v = pd.to_numeric(d[c], errors="coerce").astype("float64")
        note = add_token(note, d[c].notna() & v.isna(), f"parse_fail:{c}")
        d[c] = v
    flags = note.fillna("")
    pz = flags.str.contains("placeholder_zero", regex=False)
    for c in ("physical_progress_pct", "expenditure_cum_cr"):
        d[c] = d[c].mask(pz & d[c].eq(0))
    p99 = flags.str.contains("placeholder_doc_1999", regex=False)
    for c in COMPLETION:
        d[c] = d[c].mask(p99 & d[c].eq(PLACEHOLDER_DATE))
    d["dq_note"] = note
    d["page"] = pd.to_numeric(d["page"], errors="coerce").astype("Int64")
    d["report_period"] = pd.to_datetime(d["source_period"], format="%Y-%m-%d").astype("datetime64[us]")
    for c in TEXT:
        d[c] = d[c].astype("str")
    return d


def load_typed(clean=CLEAN, identity=IDENTITY):
    """All clean project rows plus the portal snapshot, typed and joined to their PRJ key."""
    proj = pd.concat([pd.read_csv(clean / "projects" / f, low_memory=False) for f in PROJECT_FILES],
                     ignore_index=True)
    portal = pd.read_csv(clean / "portal" / "portal_projects.csv")
    master = pd.read_csv(clean / "projects" / "project_master.csv", low_memory=False)
    sector_map = pd.read_csv(clean / "reference" / "sector_map.csv")
    a_proj, a_portal = adapt_clean(proj), adapt_portal(portal, master, sector_map)
    ids = row_ids(pd.concat([a_proj, a_portal], ignore_index=True)).to_numpy()
    rows = proj[TEXT + DATES + NUMBERS + ["page"]].assign(
        source_report_type=a_proj["source_report_type"], source_period=a_proj["source_period"],
        source_row_id=ids[:len(proj)])
    # the portal lists projects under monitoring, so its rows count as the ongoing list
    port = pd.DataFrame({
        "source_report_type": "portal", "source_period": PORTAL_PERIOD, "source_row_id": ids[len(proj):],
        "source_file": PORTAL_FILE, "page": None, "list_type": "ongoing",
        "project_code": portal["project_code"].astype(str), "project_name": portal["project_name"],
        "sector": a_portal["sector"], "sector_hml": portal["sector"], "agency": portal["agency"],
        "ministry": portal["ministry"], "dq_flags": portal["dq_flags"], "doa_original": portal["sanction_date"],
        "doc_original": portal["doc_original"], "doc_revised": portal["doc_revised"],
        "cost_original_cr": portal["cost_original_cr"], "cost_revised_cr": portal["cost_revised_cr"],
        "expenditure_cum_cr": portal["expenditure_cum_cr"], "physical_progress_pct": portal["physical_progress_pct"],
        "delay_months": portal["delay_months"]})
    raw = pd.concat([rows, port.reindex(columns=rows.columns)], ignore_index=True)
    res = pd.read_parquet(identity / "resolved_rows.parquet", columns=KEY_COLS + IDENTITY_COLS)
    out = typed(raw).merge(res, on=KEY_COLS, how="left", validate="1:1")
    assert out["project_key"].notna().all(), "clean rows without a resolved key; rerun the identity build"
    return out


def quarantine_rules(d):
    """rule_id -> (row mask, offending columns)."""
    # latest cost as the clean layer's cost_latest_cr: old flash reports print escalation only as anticipated
    cost_ref = d["cost_anticipated_cr"].fillna(d["cost_revised_cr"]).fillna(d["cost_original_cr"])
    prog = d["physical_progress_pct"]
    return {
        "progress_out_of_range": (prog.gt(100) | prog.lt(0), ["physical_progress_pct"]),
        "negative_money": (d[COSTS].lt(0).any(axis=1), COSTS),
        "expenditure_gt_3x_cost": (d["expenditure_cum_cr"].gt(3 * cost_ref),
                                   ["expenditure_cum_cr", "cost_anticipated_cr", "cost_revised_cr",
                                    "cost_original_cr"]),
        "completion_before_sanction": (d[COMPLETION].lt(d["doa_original"], axis=0).any(axis=1),
                                       ["doa_original"] + COMPLETION),
        "placeholder_date": (d[DATES].eq(PLACEHOLDER_DATE).any(axis=1), DATES),
    }


def quarantine(d):
    """Split rows into (kept, {rule_id: quarantined frame}). A row failing several rules is listed under each."""
    out, bad = {}, pd.Series(False, index=d.index)
    for rule, (mask, cols) in quarantine_rules(d).items():
        out[rule] = d.loc[mask, Q_ID + cols].assign(rule_id=rule, reason=REASONS[rule])
        bad |= mask
    return d[~bad], out


def dedupe_reports(d):
    """One row per (project_key, review_status, report). A project printed in several lists of one report
    keeps the preferred list (ongoing, completed, newly_added, others) and takes missing fields from the
    other lists (groupby first = combine_first in preference order). Two rows of the preferred list are a
    duplicate: the more complete one is kept, the rest are returned for quarantine."""
    s = d.assign(_rank=d["list_type"].map(LIST_RANK).fillna(len(LIST_RANK)),
                 _filled=d[FILLED].notna().sum(axis=1))
    s = s.sort_values(REPORT + ["_rank", "_filled", "source_row_id"], ascending=[True] * 5 + [False, True],
                      kind="mergesort")
    g = s.groupby(REPORT, sort=False)
    dup = s.duplicated(REPORT) & s["_rank"].eq(g["_rank"].transform("first"))
    dups = s.loc[dup, Q_ID + ["list_type"]].assign(
        kept_row_id=g["source_row_id"].transform("first")[dup], n_filled=s.loc[dup, "_filled"],
        rule_id="duplicate_key_period", reason=REASONS["duplicate_key_period"])
    kept = s[~dup].drop(columns=["_rank", "_filled"])
    return kept.groupby(REPORT, sort=False).first().reset_index()[d.columns], dups


def quarter(ts):
    return ts.dt.to_period("Q").dt.start_time.astype("datetime64[us]")


def months(ts):
    return ts.dt.year * 12 + ts.dt.month


def coalesce(d, cols, labels):
    """First non-null of cols (in order) and which one it was."""
    value = d[cols[0]]
    basis = pd.Series(np.where(value.notna(), labels[0], None), index=d.index, dtype=object)
    for c, lab in zip(cols[1:], labels[1:]):
        basis = basis.where(value.notna(), np.where(d[c].notna(), lab, None))
        value = value.combine_first(d[c])
    return value, basis.astype("str")


def panel(reports):
    """Report rows (one per key x report) -> one row per (project_key, quarter)."""
    d = reports.assign(period=quarter(reports["report_period"]))
    flash = pd.MultiIndex.from_frame(d.loc[d["source_report_type"].eq("paimana_flash"), PK])
    d = d[~(d["source_report_type"].eq("portal") & pd.MultiIndex.from_frame(d[PK]).isin(flash))].copy()
    d["anticipated_cost_cr"], d["cost_basis"] = coalesce(
        d, ["cost_anticipated_cr", "cost_revised_cr", "cost_original_cr"], ["anticipated", "revised", "original"])
    d["anticipated_completion"], d["completion_basis"] = coalesce(
        d, ["doc_anticipated", "doc_revised"], ["anticipated", "revised"])
    d["period_type"] = d["source_report_type"].map(PERIOD_TYPE)
    d["_type"] = d["source_report_type"].map({t: i for i, t in enumerate(PERIOD_TYPE)})
    d = d.rename(columns=PANEL_RENAME).sort_values(PK + ["report_period_last", "_type"], kind="mergesort",
                                                   ignore_index=True)
    g = d.groupby(PK, sort=False)
    out = g[LAST_VALID].last().join(d.drop_duplicates(PK, keep="last").set_index(PK)[LAST_ROW])
    out["obs_count_in_quarter"] = g.size()
    out = out.reset_index()
    out["is_completed"] = out["status"].eq("completed") | out["date_completed_actual"].notna()
    last = months(out["report_period_last"])
    out["months_since_last_obs"] = (last - last.groupby(out["project_key"]).shift()).astype("Int64")
    tok = pd.concat([d["dq_note"], d["dq_flags"]]).dropna().str.split(";").explode()
    tok = tok.str.split(":").str[0].str.strip()
    tok = tok[tok.ne("")]
    n = (d.loc[tok.index, PK].assign(t=tok.to_numpy()).drop_duplicates().groupby(PK).size()
         .reindex(pd.MultiIndex.from_frame(out[PK]), fill_value=0))
    out["dq_score"] = (1 - n.to_numpy() / MAX_FLAGS).clip(0, 1)
    return out[PANEL_COLS]


def _increases(obs, col, step):
    """Per key, count consecutive non-null quarter pairs where col reached step(previous value)."""
    c = obs[["project_key", col]].dropna()
    prev = c.groupby("project_key")[col].shift()
    return (c[col] >= step(prev)).groupby(c["project_key"]).sum()


def project_master(obs, review, rows):
    """One row per panel key; keys seen only through review links come from the review panel."""
    base = pd.concat([obs, review[~review["project_key"].isin(obs["project_key"])]])
    base = base.sort_values(PK, kind="mergesort", ignore_index=True)
    g = base.groupby("project_key")
    codes = rows[["project_key", "project_code"]].dropna().drop_duplicates().sort_values(["project_key", "project_code"])
    flash = rows[rows["source_report_type"].eq("paimana_flash")]
    m = pd.DataFrame({
        "first_seen": g["period"].min(), "last_seen": g["period"].max(), "n_obs": g.size(),
        "n_reports": g["obs_count_in_quarter"].sum(), "sanction_date": g["sanction_date"].last(),
        "last_status": g["status"].last(),
        "completed_period": base[base["is_completed"]].groupby("project_key")["period"].min(),
        "agency": g["agency"].last(), "ministry": g["ministry"].last(), "sector": g["sector"].last(),
        "state": g["state"].last(), "project_name": g["project_name"].last(),
        "codes_seen": codes.groupby("project_key")["project_code"].agg(";".join),
        "n_cost_revisions": _increases(base, "anticipated_cost_cr", lambda p: p * 1.05),
        "n_schedule_slips": _increases(base.assign(ac=months(base["anticipated_completion"])), "ac",
                                       lambda p: p + 3),
    }).reindex(g.size().index).reset_index()
    for c in ("n_obs", "n_reports", "n_cost_revisions", "n_schedule_slips"):
        m[c] = m[c].fillna(0).astype("int64")
    latest = flash.loc[flash["source_period"].eq(flash["source_period"].max()), "project_key"]
    m["in_latest_report"] = m["project_key"].isin(latest)
    m["in_portal_snapshot"] = m["project_key"].isin(rows.loc[rows["source_report_type"].eq("portal"), "project_key"])
    m["has_review_rows"] = m["project_key"].isin(review["project_key"])
    return m


def sector_context(perf):
    """Headline indicator per (project sector, quarter): actual/target, mean YoY growth, 4-quarter trend.
    Quarters come from data_month; a month reprinted by a later report keeps the later print."""
    h = perf[perf["is_sector_headline"].astype(str).str.lower().eq("true")]
    h = h.sort_values(["sector", "data_month", "report_month"]).drop_duplicates(["sector", "data_month"], keep="last")
    both = h["month_actual"].notna() & h["month_target"].notna()
    h = h.assign(period=quarter(pd.to_datetime(h["data_month"], format="%Y-%m")),
                 a=h["month_actual"].where(both), t=h["month_target"].where(both))
    g = h.groupby(["sector", "period"])
    out = pd.DataFrame({"indicator_key": g["indicator_key"].last(),
                        "actual_target_ratio": g["a"].sum(min_count=1) / g["t"].sum(min_count=1),
                        "yoy_growth_pct": g["month_growth_pct"].mean(), "n_months": g.size()}).reset_index()
    # this quarter and the 3 before it: quarter starts within 300 days (the 4th one back is ~365 days away)
    out["trend_4q"] = out.groupby("sector").rolling("300D", on="period")["yoy_growth_pct"].mean().to_numpy()
    out = out.rename(columns={"sector": "perf_sector"})
    out.insert(0, "sector", out["perf_sector"].map(PERF_SECTOR))
    return out.dropna(subset=["sector"]).sort_values(["sector", "period"], ignore_index=True)


def coverage(obs, quarantined):
    """Per quarter: share non-null of the key fields, row and key counts, quarantined rows, source mix."""
    g = obs.groupby("period")
    nq = quarantined.groupby(quarter(pd.to_datetime(quarantined["source_period"], format="%Y-%m-%d"))).size()
    mix = (pd.crosstab(obs["period"], obs["period_type"])
           .reindex(columns=list(PERIOD_TYPE.values()), fill_value=0).add_prefix("n_"))
    out = pd.concat([g.size().rename("n_rows"), g["project_key"].nunique().rename("n_keys"),
                     nq.rename("n_quarantined"), mix, obs[COVERAGE].notna().groupby(obs["period"]).mean()], axis=1)
    out.index.name = "period"
    counts = ["n_rows", "n_keys", "n_quarantined"] + list(mix.columns)
    out[counts] = out[counts].fillna(0).astype("int64")
    return out.reset_index()


def write_quarantine(q, out):
    qdir = out / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    for rule, f in q.items():
        f.reset_index(drop=True).to_parquet(qdir / f"{rule}.parquet", index=False)
    summary = pd.DataFrame([{"rule": r, "rows": len(f), "keys": f["project_key"].nunique()} for r, f in q.items()])
    summary.to_csv(qdir / "summary.csv", index=False, lineterminator="\n")
    return summary


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(out, clean, idmap, frames, q, rows, obs, checks):
    """silver_version hashes the output Parquet bytes, so identical inputs give an identical version."""
    files = sorted(p for p in out.rglob("*.parquet") if "identity" not in p.relative_to(out).parts)
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(out).as_posix().encode() + b"\0" + p.read_bytes())
    inputs = [clean / "projects" / f for f in PROJECT_FILES + ("project_master.csv",)] + [
        clean / "portal" / "portal_projects.csv", clean / "reference" / "sector_map.csv",
        clean / "performance" / "performance_sector_monthly.csv", out / "identity" / "resolved_rows.parquet"]
    ident = json.loads((out / "identity" / "identity_manifest.json").read_text(encoding="utf-8"))
    flash = rows[rows["source_report_type"].eq("paimana_flash")]
    latest_flash = flash["source_period"].max()
    return {
        "silver_version": h.hexdigest()[:12],
        "run_id": idmap.run_id,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p): sha256(p) for p in inputs},
        "rows": {name: len(f) for name, f in frames.items()},
        "quarantine": {rule: len(f) for rule, f in q.items()},
        "identity": {k: ident.get(k) for k in ("keys", "entities", "entity_status", "status", "review_share")}
                    | {"keys_in_panel": int(obs["project_key"].nunique())},
        "latest_period": str(obs["period"].max().date()),
        "latest_paimana_flash_report": latest_flash[:7],
        "n_current_projects": int(flash.loc[flash["source_period"].eq(latest_flash), "project_key"].nunique()),
        "portal_rows_in_panel": int(obs["period_type"].eq("portal").sum()),
        "checks": checks,
    }


def main(clean=CLEAN, out=SILVER):
    """Build every silver table, run the identity invariants (raise before anything is written), write."""
    t0 = time.time()
    rows = load_typed(clean, out / "identity")
    kept, q = quarantine(rows)
    reports, q["duplicate_key_period"] = dedupe_reports(kept)
    obs = panel(reports[reports["review_status"].eq("accepted")])
    review = panel(reports[reports["review_status"].ne("accepted")])
    master = project_master(obs, review, rows)
    sectors = sector_context(pd.read_csv(clean / "performance" / "performance_sector_monthly.csv"))
    quarantined = pd.concat([f[KEY_COLS] for f in q.values()]).drop_duplicates()
    cov = coverage(obs, quarantined)
    idmap = IdentityMap(IdentityConfig(root=out / "identity"))
    checks = run_all(idmap, obs, rows[rows["source_report_type"].eq("portal")], review, master)

    frames = {"typed_rows": rows, "observations": obs, "observations_review": review, "project_master": master,
              "sector_context": sectors, "coverage": cov}
    for name, f in frames.items():
        f.to_parquet(out / f"{name}.parquet", index=False, row_group_size=50000)
    cov.to_csv(out / "coverage.csv", index=False, lineterminator="\n", date_format="%Y-%m-%d")
    summary = write_quarantine(q, out)
    man = manifest(out, clean, idmap, frames, q, rows, obs, checks)
    (out / "silver_manifest.json").write_text(json.dumps(man, indent=2, default=str) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"silver {man['silver_version']}: {len(rows)} typed rows, {len(reports)} report rows, {len(obs)} panel rows "
          f"({obs['project_key'].nunique()} keys), {len(review)} review rows, {len(master)} master rows, "
          f"{len(sectors)} sector rows, {man['n_current_projects']} current projects, "
          f"{man['portal_rows_in_panel']} portal rows in the panel, {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
