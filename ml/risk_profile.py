"""
Risk-profile checklist and the external early-notice summary (docs/IMPLEMENTATION_GUIDE_v2.md A.4, B 5.2).

Run from repo root after score:  python -m pipeline.run profile

Inputs   gold/predictions_latest.json (and the predictions file it names), gold/features.parquet,
         gold/labels_h4.parquet, gold/project_events.parquet, gold/project_mentions.parquet,
         gold/external_fc.parquet, gold/external_land.parquet (and the composite built from the two, as in
         gold/external_composite.parquet), gold/agency_stats.parquet,
         silver/observations.parquet, silver/sector_context.parquet
Outputs  gold/risk_profile_<asof YYYY-MM>.parquet (long: project_key, dimension, state, evidence, source,
         as_of_date), gold/external_summary.json

Every current project gets twelve checks and a thirteenth informational row, the external composite, each
flagged, clear or unknown. Unknown is a real state: a search that
finds nothing (no land table for the state, no court case in the remarks) is unknown, never clear; clear needs
positive evidence (a model score below the cut, a linked land table with low complexity, a clearance reported
done). Event rows read the point-in-time ext_open_* features at asof, so a remark after asof never counts.
The Parivesh rule (linear, worst complexity >= 6) flags only when forest hectares or a violation are known: with
no hectares every area band counts and every linear project's worst case is 7, which says nothing about it.

The composite row (pipeline/external.py external_composite: 0.5 forest/7 + 0.5 land/5) is rated only where land
is linked (coverage fc+la): flagged at score >= COMPOSITE_HIGH. It is clear only when both halves are known and
neither the land nor the forest row is flagged: without forest hectares (or a clearance reported done) the forest
half is the rulebook's expected value, an estimate, so the row is unknown. Without land (fc_only) it is unknown and
says why the land half is missing. It is not a model feature and not an early-notice factor, since its inputs are
already both.

The early notice is the pitch: projects with a flagged external factor whose CUF numbers do not show a slip yet
(slip to date <= 0 months, or tier Low/Medium). notice_backtest checks the claim on history: of the rows with no
slip to date, how many slipped by t + 4 quarters with and without an open land or forest event at t.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest, score  # noqa: E402
from pipeline import external, gold  # noqa: E402

GOLD, SILVER, ROOT = backtest.GOLD, backtest.SILVER, backtest.ROOT
DIMENSIONS = ["schedule_slip", "cost_escalation", "execution_stagnation", "expenditure_lag", "repeated_revisions",
              "sector_headwind", "agency_optimism", "land_acquisition", "forest_clearance", "litigation",
              "contractor_stress", "data_staleness", "external_composite"]
HIGH_SHARE = score.TIER_TOP[1]      # a model dimension is flagged in the top 20% (Critical + High) of its score
SPI_MIN, SPI_ELAPSED = 0.1, 0.3
BURN_LOW, BURN_HIGH = -15, 25
REVISIONS_MIN = 2
SECTOR_RATIO_MIN, SECTOR_MAX_AGE_Q = 0.95, 4
AGENCY_BIAS, AGENCY_MIN_N = 0.25, 5
STALE_MONTHS, DQ_MIN = 3, 0.7
FC_HIGH = 6
COMPOSITE_HIGH = 0.6
# summary factor -> checklist dimension, or the event category whose open event flags it
FACTORS = {"land": "land_acquisition", "forest_clearance": "forest_clearance", "litigation": "litigation",
           "contractor": "contractor_stress", "utility_shifting": "utility_shifting", "inter_agency": "inter_agency"}
EVENT_DIMENSION = {"land": "land_acquisition", "forest_env": "forest_clearance", "litigation": "litigation",
                   "contractor": "contractor_stress"}
LA_REASON = {"no_land_data_for_state": "no land data for this state (no Bhoomi Rashi export for it yet)",
             "not_road": "no land data for non-road projects",
             "no_nh_in_name": "no NH number in the name to link land data",
             "nh_only_as_end_point": "its name gives NH numbers only as end points (junctions), not its own road",
             "no_stretch_at_its_km": "no notified stretch of its NH at the km range in its name",
             "nh_not_in_table": "its NH is not in the land table of its state"}
TOP_FACTOR, TOP_NOTICE = 10, 20
COLS = ["project_key", "dimension", "state", "evidence", "source", "as_of_date"]


def states(flag, clear):
    """flagged where flag, else clear where clear, else unknown (nulls count as False)."""
    f, c = (s.fillna(False).astype(bool).to_numpy() for s in (flag, clear))
    return np.select([f, c], ["flagged", "clear"], "unknown")


def num(s, spec, suffix=""):
    """Series of numbers -> formatted strings, 'n/a' for nulls."""
    return s.map(lambda v: format(v, spec) + suffix, na_action="ignore").fillna("n/a")


def month(s):
    return s.dt.strftime("%b %Y").fillna("n/a")


def load_current(asof=None):
    """Scored current projects at asof joined to their feature row: the checklist's one row per project."""
    ptr = json.loads((GOLD / "predictions_latest.json").read_text(encoding="utf-8"))
    path = ROOT / ptr["path"]
    if asof is not None and pd.Timestamp(asof) != pd.Timestamp(ptr["asof"]):
        path = sorted(GOLD.glob(f"predictions_*_{pd.Timestamp(asof):%Y-%m}.parquet"))[-1]
    pred = pd.read_parquet(path)
    asof = pred["asof"].iloc[0]
    feats = pd.read_parquet(GOLD / "features.parquet")
    f = feats[feats["period"] == asof].drop(columns=[c for c in pred if c != "project_key" and c in feats])
    cur = pred.merge(f, on="project_key", how="left", validate="1:1")
    cur["first_period"] = cur["project_key"].map(feats.groupby("project_key")["period"].min())
    return cur, feats, asof


def agency_bias(obs, asof):
    """Per normalised agency at asof: median schedule bias (anticipated or actual duration / scheduled duration - 1)
    over its projects' latest rows, n projects, and the 2-quarter slip rate from agency_stats."""
    d = gold.base(obs, asof)
    span = gold.months(d["scheduled_completion"]) - gold.months(d["sanction_date"])
    d["bias"] = (gold.months(d["anticipated_completion"]) - gold.months(d["sanction_date"])) / span.where(span > 0) - 1
    last = d[d["bias"].notna() & d["agency"].notna()].drop_duplicates("project_key", keep="last")
    out = last.groupby("agency")["bias"].agg(bias="median", n="size")
    st = pd.read_parquet(GOLD / "agency_stats.parquet")
    st = st[st["period"] <= asof].drop_duplicates("agency", keep="last").set_index("agency")
    return out.join(st[["slip_rate_raw", "n_slip"]])


def sector_now(sectors, cur, asof):
    """Latest sector_context row at or before asof, at most SECTOR_MAX_AGE_Q quarters old, for each project."""
    s = sectors[(sectors["period"] <= asof)
                & (sectors["period"] > asof - pd.DateOffset(months=3 * SECTOR_MAX_AGE_Q))]
    s = s.sort_values("period").drop_duplicates("sector", keep="last").set_index("sector")
    return s.reindex(cur["sector"]).set_axis(cur.index)


def last_events(events, asof):
    """Per (project_key, category): the latest event first seen by asof."""
    e = events[events["first_seen"] <= asof].sort_values(["project_key", "category", "event_no"])
    return e.drop_duplicates(["project_key", "category"], keep="last").set_index(["project_key", "category"])


def event_info(cur, ev, cat, remarks_last):
    """Open flag (point-in-time feature), whether the latest event was reported done, and an evidence line."""
    e = ev.reindex(pd.MultiIndex.from_arrays([cur["project_key"], [cat] * len(cur)])).set_axis(cur.index)
    opened = cur[f"ext_open_{cat}"].eq(1)
    quote = "'" + e["evidence"].str.slice(0, 120) + "'"
    seen = "mentioned " + month(e["first_seen"]) + " to " + month(e["last_seen"])
    done = e["resolved"].fillna(False).astype(bool) & ~opened & e["first_seen"].notna()
    last = remarks_last.reindex(cur["project_key"]).set_axis(cur.index)
    none = np.where(last.notna(), "not mentioned in report remarks up to " + month(last),
                    "no free-text remarks in any report")
    ev_line = np.select([opened, done, e["first_seen"].notna()],
                        ["open in reports, " + seen + ": " + quote,
                         "reported done " + month(e["last_seen"]) + ": " + quote,
                         "last " + seen + ", not mentioned since: " + quote], none)
    return opened, done, pd.Series(ev_line, index=cur.index)


def build_rows(cur, asof, events, mentions, fc, land, agencies, sector):
    """The thirteen checklist rows (twelve checks and the external composite) for every project in cur, long
    format."""
    k, out = cur["project_key"], []

    def add(dim, flag, clear, evidence, source):
        src = source if isinstance(source, pd.Series) else pd.Series(source, index=cur.index)
        out.append(pd.DataFrame({"project_key": k, "dimension": dim, "state": states(flag, clear),
                                 "evidence": evidence, "source": src}))

    # model dimensions: flagged in the top HIGH_SHARE of the score; unscored (no completion date) is unknown
    sector_v = cur["progress_velocity_2q"] - cur["velocity_vs_sector_median"]
    vel = "; velocity " + num(cur["progress_velocity_2q"], ".1f", "%/q") + " vs sector " + num(sector_v, ".1f", "%/q")
    untiered = np.where(cur["no_completion_date"].fillna(False), "Watch tier: no anticipated completion date in "
                        "the reports, so the date models cannot score it", "not scored")
    for dim, col, extra in [("schedule_slip", "p_date_push_2q", vel),
                            ("cost_escalation", "p_cost_rev_2q",
                             "; cost variation so far " + num(cur["cost_variation_pct"], "+.0f", "%"))]:
        p = cur[col]
        cut = p.quantile(1 - HIGH_SHARE)
        scored = p.notna() & cur["tier"].notna() if dim == "schedule_slip" else p.notna()
        ev = "P = " + num(p, ".2f") + f" (High-tier cut {cut:.2f})" + extra
        add(dim, scored & (p >= cut), scored, ev.where(scored, pd.Series(untiered, index=cur.index) + extra), "model")

    prog, el = cur["physical_progress_pct"], cur["elapsed_ratio"]
    # the stagnation badge's rule (ml/score.py) flags it too, so the checklist never says clear next to the badge
    stuck = pd.Series(score.stagnant(cur), index=cur.index)
    known = cur["spi"].notna() & el.notna()
    stuck_line = ("; no progress for " + num(cur["stagnation_quarters"], ".0f", " quarters")).where(stuck, "")
    add("execution_stagnation", stuck | (known & (cur["spi"] < SPI_MIN) & (el >= SPI_ELAPSED)), known,
        (num(prog, ".0f", "% progress at ") + num(el * 100, ".0f", "% elapsed") + " (SPI " + num(cur["spi"], ".2f")
         + ")").where(known, "no progress or no sanction/scheduled dates to measure against") + stuck_line,
        "silver")

    gap = cur["burn_gap"]
    add("expenditure_lag", (gap < BURN_LOW) | (gap > BURN_HIGH), gap.notna(),
        ("spent " + num(cur["expenditure_ratio"] * 100, ".0f", "%") + ", built " + num(prog, ".0f", "%")
         + " (gap " + num(gap, "+.0f", " pp") + ")").where(gap.notna(), "expenditure or progress not printed"),
        "silver")

    rev = cur["revisions_so_far"]
    add("repeated_revisions", rev >= REVISIONS_MIN, rev.notna(),
        "revisions so far: " + num(rev, ".0f") + " (cost +5% or completion +3 months) in reports since "
        + month(cur["first_period"]), "silver")

    ratio, trend = sector["actual_target_ratio"], sector["trend_4q"]
    have = ratio.notna() | trend.notna()
    add("sector_headwind", (trend < 0) | (ratio < SECTOR_RATIO_MIN), have,
        (cur["sector"].fillna("sector") + " output " + num(ratio * 100, ".0f", "% of target") + ", 4q growth "
         + num(trend, "+.1f", "%") + " (" + month(sector["period"]) + ")").where(
            have, "no sector output data within 4 quarters of " + f"{asof:%b %Y}"), "sector_context")

    a = agencies.reindex(gold.norm_agency(cur["agency"])).set_axis(cur.index)
    enough = a["n"] >= AGENCY_MIN_N
    add("agency_optimism", enough & (a["bias"] > AGENCY_BIAS), enough,
        pd.Series(np.select([cur["agency"].isna(), ~enough],
                            ["agency not printed",
                             "only " + a["n"].fillna(0).astype(int).astype(str) + " dated projects of this agency "
                             f"(need {AGENCY_MIN_N})"],
                            "agency timelines run " + num(a["bias"] * 100, "+.0f", "%") + " vs schedule (median of "
                            + a["n"].fillna(0).astype(int).astype(str) + " projects)"
                            + ("; 2q slip rate " + num(a["slip_rate_raw"] * 100, ".0f", "%")).where(
                                a["slip_rate_raw"].notna(), "")), index=cur.index), "agency_stats")

    remarks_last = mentions[mentions["period"] <= asof].groupby("project_key")["period"].max()
    ev = last_events(events, asof)
    info = {c: event_info(cur, ev, c, remarks_last) for c in EVENT_DIMENSION}

    la = land.set_index("project_key").reindex(k).set_axis(cur.index)
    opened, _, line = info["land"]
    la_flag, la_clear = la["la_state"].eq("flagged"), la["la_state"].eq("clear")
    la_line = la["la_evidence"].fillna(la["la_match_method"].map(LA_REASON)).fillna("not in the land linkage")
    land_flag = opened | la_flag
    add("land_acquisition", land_flag, la_clear,
        pd.Series(np.where(opened, line + np.where(la["la_evidence"].notna(), "; " + la_line, ""),
                           la_line + "; " + line), index=cur.index),
        pd.Series(np.where(opened, "report", "bhoomi_rashi"), index=cur.index))

    f = fc.set_index("project_key").reindex(k).set_axis(cur.index)
    opened, done, line = info["forest_env"]
    # ponytail: with no hectares every area band counts, so every linear project's worst case is 7; the rule flags
    # only when the area (or a violation) is known, else it would flag 1,300 projects for missing data
    informed = f["fc_area_known"].fillna(False) | f["fc_violation"].fillna(False)
    high = f["fc_shape"].eq("Linear") & (f["fc_worst_complexity"] >= FC_HIGH) & informed
    rules = (f["fc_evidence"].fillna("no Parivesh profile") + " (expected "
             + num(f["fc_expected_complexity"], ".1f") + ")")
    fc_flag = opened | high
    # the forest half is measured only with hectares (or a clearance reported done); else it is the rulebook's
    # expected value over every area band, an estimate
    fc_known = (f["fc_area_known"].fillna(False).astype(bool) | done) & ~fc_flag
    add("forest_clearance", fc_flag, done,
        pd.Series(np.select([opened, high], [line + "; " + rules, "high clearance complexity expected: " + rules + "; "
                                             + line], line + "; " + rules), index=cur.index),
        pd.Series(np.where(opened | done, "report", "parivesh_rules"), index=cur.index))

    comp = external.external_composite(fc, land).set_index("project_key").reindex(k).set_axis(cur.index)
    both, ext_score = comp["coverage"].eq("fc+la"), comp["external_factor_score"]
    missing = la["la_match_method"].map(LA_REASON).fillna("not in the land linkage")
    # clear needs both halves positively known and neither checklist row flagged; flagged needs only the score
    comp_flag = both & (ext_score >= COMPOSITE_HIGH)
    comp_clear = both & fc_known & la_clear & ~land_flag
    why = np.select([comp_flag | comp_clear, ~both, land_flag, fc_flag],
                    ["", " (" + missing + "), so the score is the forest half alone and is not rated",
                     "; not rated clear: the land row is flagged", "; not rated clear: the forest row is flagged"],
                    "; not rated clear: forest area unknown, so the forest half is the rulebook's estimate")
    add("external_composite", comp_flag, comp_clear,
        "score " + num(ext_score, ".2f") + " (" + comp["coverage"].fillna("n/a") + "): "
        + comp["ext_score_evidence"].fillna("no Parivesh profile") + pd.Series(why, index=cur.index),
        "external_composite")

    for dim, cat in [("litigation", "litigation"), ("contractor_stress", "contractor")]:
        opened, _, line = info[cat]
        add(dim, opened, pd.Series(False, index=cur.index), line, "report")

    gap_m, dq = cur["months_since_last_obs"], cur["dq_score"]
    add("data_staleness", (gap_m > STALE_MONTHS) | (dq < DQ_MIN), gap_m.notna() | dq.notna(),
        f"last report {asof:%b %Y}, " + ("gap to the previous one " + num(gap_m, ".0f", " mo.")).where(
            gap_m.notna(), "its first report") + "; data quality " + num(dq, ".2f"), "silver")
    rows = pd.concat(out, ignore_index=True).assign(as_of_date=asof)
    rows["dimension"] = pd.Categorical(rows["dimension"], DIMENSIONS)
    return rows.sort_values(["project_key", "dimension"], ignore_index=True).astype({"dimension": "str"})[COLS]


def factor_flags(rows, cur):
    """Summary factor -> booleans over cur: its checklist dimension is flagged, or (utility shifting, inter-agency,
    not on the checklist) its event category is open at asof."""
    wide = rows.pivot(index="project_key", columns="dimension", values="state").reindex(cur["project_key"])
    out = {}
    for name, dim in FACTORS.items():
        if dim in wide:
            out[name] = wide[dim].eq("flagged").to_numpy()
        else:
            out[name] = cur[f"ext_open_{dim}"].eq(1).to_numpy()
    return pd.DataFrame(out, index=cur.index)


def project_card(d, lines):
    keep = ["project_key", "project_name", "sector", "state", "anticipated_cost_cr", "tier", "p_any_2q",
            "slip_to_date_months"]
    recs = d[keep].assign(evidence=lines.reindex(d.index)).round({"anticipated_cost_cr": 1, "p_any_2q": 3,
                                                                  "slip_to_date_months": 0})
    return json.loads(recs.to_json(orient="records"))


def mh_ratio(y, flag, strata):
    """Mantel-Haenszel risk ratio of 0/1 outcomes y, flag vs not, within strata (a stratum without one of the two
    groups adds nothing)."""
    t = pd.DataFrame({"y": np.asarray(y, float), "f": np.asarray(flag, bool), "s": np.asarray(strata)})
    g = t.groupby(["s", "f"])["y"].agg(["sum", "size"]).unstack("f", fill_value=0)
    g = g.reindex(columns=pd.MultiIndex.from_product([["sum", "size"], [False, True]]), fill_value=0)
    n = g["size"].sum(axis=1)
    num, den = (g["sum"][True] * g["size"][False] / n).sum(), (g["sum"][False] * g["size"][True] / n).sum()
    return float(num / den) if den > 0 else None


def rates(y, flag):
    w, wo = y[flag], y[~flag]
    return {"n_with": int(len(w)), "slip_rate_with": round(float(w.mean()), 4) if len(w) else None,
            "n_without": int(len(wo)), "slip_rate_without": round(float(wo.mean()), 4) if len(wo) else None,
            "lift": round(float(w.mean() / wo.mean()), 3) if len(w) and len(wo) and wo.mean() > 0 else None}


def notice_backtest(feats, lab4, min_rows=30):
    """The early-notice claim on history. Rows: not completed, no slip to date at t, 4-quarter date label known,
    and at least one free-text remark quarter by t (the remark era, so both groups could have had an event).
    Outcome: completion pushed >= 3 months by t + 4q. Per event group (open at t): slip rate with and without,
    the raw lift, the lift within sector x year (Mantel-Haenszel), and per sector with >= min_rows flagged rows."""
    d = lab4[["project_key", "period", "y_date_push"]].merge(feats, on=["project_key", "period"])
    d = d[~d["is_completed"].astype(bool) & d["y_date_push"].notna() & (d["slip_to_date_months"] <= 0)
          & (d["ext_remark_quarters"] > 0)]
    y = d["y_date_push"].astype("float64")
    strata = d["sector"].fillna("?") + "|" + d["period"].dt.year.astype("str")
    out = {}
    for name, flag in [("land_or_forest", d["ext_open_land"].eq(1) | d["ext_open_forest_env"].eq(1)),
                       ("land", d["ext_open_land"].eq(1)), ("forest_env", d["ext_open_forest_env"].eq(1))]:
        r = rates(y, flag) | {"projects_with": int(d.loc[flag, "project_key"].nunique())}
        mh = mh_ratio(y, flag, strata)
        r["lift_within_sector_year"] = None if mh is None else round(mh, 3)
        big = flag.groupby(d["sector"]).sum()
        r["by_sector"] = {sec: rates(y[d["sector"].eq(sec)], flag[d["sector"].eq(sec)])
                          for sec in big[big >= min_rows].index}
        out[name] = r
    return out


def composite_summary(cur, comp):
    """The external composite over cur: score distribution per coverage and the top TOP_NOTICE fc+la projects."""
    d = cur.drop(columns=[c for c in comp if c != "project_key" and c in cur]).merge(comp, on="project_key",
                                                                                    how="left")
    by = {}
    for cov, g in d.groupby("coverage"):
        s = g["external_factor_score"]
        by[cov] = {"n_projects": int(len(g)), "n_score_ge_high": int((s >= COMPOSITE_HIGH).sum()),
                   **{k: round(float(v), 4) for k, v in s.describe()[["mean", "min", "25%", "50%", "75%",
                                                                       "max"]].items()}}
    top = d[d["coverage"].eq("fc+la")].sort_values(["external_factor_score", "anticipated_cost_cr"],
                                                   ascending=False).head(TOP_NOTICE)
    keep = ["project_key", "project_name", "sector", "state", "anticipated_cost_cr", "tier", "external_factor_score",
            "fc_component", "la_component", "ext_score_evidence"]
    top = top[keep].round({"anticipated_cost_cr": 1, "external_factor_score": 4, "fc_component": 4,
                           "la_component": 4})
    return {"rule": "score = 0.5 x forest complexity/7 + 0.5 x land complexity/5 where land is linked (coverage "
                    "fc+la), forest/7 alone otherwise (fc_only, not rated); flagged at score >= "
                    f"{COMPOSITE_HIGH} with fc+la; clear below it only with forest hectares known (or a clearance "
                    "reported done) and neither the land nor the forest row flagged, else unknown. Informational, "
                    "not a model feature.",
            "by_coverage": by, "top_fc_la": json.loads(top.to_json(orient="records"))}


def evidence_of(ev_lines, dim, keys):
    """The flagged evidence line of dimension dim for each of keys, null where it is not flagged (also when no
    project has dim flagged: the four-quarter expiry of remark flags can leave a factor with none)."""
    return ev_lines[ev_lines.index.get_level_values("dimension") == dim].droplevel("dimension").reindex(keys)


def build_risk_profile(asof=None):
    """Write gold/risk_profile_<asof>.parquet and gold/external_summary.json; returns (rows, summary)."""
    t0 = time.time()
    cur, feats, asof = load_current(asof)
    obs = pd.read_parquet(SILVER / "observations.parquet")
    events = pd.read_parquet(GOLD / "project_events.parquet")
    mentions = pd.read_parquet(GOLD / "project_mentions.parquet")
    fc = pd.read_parquet(GOLD / "external_fc.parquet")
    land = pd.read_parquet(GOLD / "external_land.parquet")
    sectors = pd.read_parquet(SILVER / "sector_context.parquet")
    rows = build_rows(cur, asof, events, mentions, fc, land, agency_bias(obs, asof), sector_now(sectors, cur, asof))
    path = GOLD / f"risk_profile_{asof:%Y-%m}.parquet"
    rows.to_parquet(path, index=False)

    flags = factor_flags(rows, cur)
    ev_lines = rows[rows["state"].eq("flagged")].set_index(["project_key", "dimension"])["evidence"]
    cap = cur["anticipated_cost_cr"]
    remarks_last = mentions[mentions["period"] <= asof].groupby("project_key")["period"].max()
    ev = last_events(events, asof)

    def lines(names):
        """'factor: evidence' lines of the given flagged factors per project."""
        parts = []
        for name in names:
            dim = FACTORS[name]
            if dim in DIMENSIONS:
                e = evidence_of(ev_lines, dim, cur["project_key"]).set_axis(cur.index)
            else:
                e = event_info(cur, ev, dim, remarks_last)[2]
            parts.append((name + ": " + e).where(flags[name]))
        return pd.concat(parts, axis=1).apply(lambda r: [v for v in r if isinstance(v, str)], axis=1)

    factors = {}
    for name in FACTORS:
        d = cur[flags[name]].sort_values("anticipated_cost_cr", ascending=False)
        factors[name] = {"n_flagged": int(len(d)),
                         "capital_exposed_cr": round(float(d["anticipated_cost_cr"].sum()), 1),
                         "top": project_card(d.head(TOP_FACTOR), lines([name]))}
    any_flag = flags.any(axis=1)
    no_slip = (cur["slip_to_date_months"] <= 0) | cur["tier"].isin(["Low", "Medium"])
    notice = cur[any_flag & no_slip].sort_values("anticipated_cost_cr", ascending=False)
    strict = notice[notice["slip_to_date_months"] <= 0]
    summary = {
        "as_of_date": str(asof.date()), "n_projects": int(len(cur)), "model_version": cur["model_version"].iloc[0],
        "rule": "early notice = a flagged external factor (land, forest clearance, litigation, contractor, utility "
                "shifting, inter-agency) while the CUF numbers show no slip yet: slip to date <= 0 months or tier "
                "Low/Medium",
        "factors": factors,
        "early_notice": {"n_projects": int(len(notice)), "capital_exposed_cr": round(float(notice[
            "anticipated_cost_cr"].sum()), 1), "by_factor": {n: int(flags.loc[notice.index, n].sum()) for n in FACTORS},
            "n_flagged_any": int(any_flag.sum()), "capital_flagged_any_cr": round(float(cap[any_flag].sum()), 1),
            "no_slip_to_date": {"n_projects": int(len(strict)),
                                "capital_exposed_cr": round(float(strict["anticipated_cost_cr"].sum()), 1)},
            "top": project_card(notice.head(TOP_NOTICE), lines(list(FACTORS)))},
        "notice_backtest": notice_backtest(feats, pd.read_parquet(GOLD / "labels_h4.parquet")),
        "external_composite": composite_summary(cur, external.external_composite(fc, land)),
    }
    (GOLD / "external_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"risk profile {path.name}: {len(rows)} rows for {len(cur)} projects at {asof.date()}")
    print(pd.crosstab(pd.Series(pd.Categorical(rows["dimension"], DIMENSIONS), name="dimension"),
                      rows["state"]).to_string())
    print("external factors: " + ", ".join(f"{n} {v['n_flagged']} (Rs {v['capital_exposed_cr']:,.0f} cr)"
                                           for n, v in factors.items()))
    en = summary["early_notice"]
    print(f"early notice: {en['n_projects']} projects, Rs {en['capital_exposed_cr']:,.0f} cr "
          f"({en['no_slip_to_date']['n_projects']} with no slip to date); by factor {en['by_factor']}")
    for r in en["top"][:5]:
        print(f"  {r['project_key']} Rs {r['anticipated_cost_cr']:,.0f} cr {r['tier']} "
              f"slip {r['slip_to_date_months']}: "
              f"{str(r['project_name'])[:60]} | {' | '.join(r['evidence'])[:200]}")
    ec = summary["external_composite"]["by_coverage"]
    print("external composite: " + ", ".join(f"{c} {v['n_projects']} (median {v['50%']:.2f}, >= {COMPOSITE_HIGH}: "
                                            f"{v['n_score_ge_high']})" for c, v in ec.items()))
    for name, r in summary["notice_backtest"].items():
        print(f"notice backtest {name}: slip by t+4q {r['slip_rate_with']} with (n {r['n_with']}, "
              f"{r['projects_with']} projects) vs {r['slip_rate_without']} without (n {r['n_without']}); lift "
              f"{r['lift']}, within sector x year {r['lift_within_sector_year']}; by sector {r['by_sector']}")
    print(f"profile: {time.time() - t0:.1f}s")
    return rows, summary


def main(asof=None):
    return build_risk_profile(asof)


if __name__ == "__main__":
    main()
