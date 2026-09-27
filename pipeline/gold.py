"""
Gold build: point-in-time features and horizon labels (docs/IMPLEMENTATION_GUIDE_v2.md B 2).

Run from repo root after the silver build:  python -m pipeline.run gold

Inputs   silver/observations.parquet, silver/sector_context.parquet, silver/silver_manifest.json,
         gold/project_mentions.parquet, gold/external_fc.parquet, gold/external_land_pairs.parquet (the external
         step, pipeline/external.py)
Outputs  gold/features.parquet, gold/labels_h2.parquet, gold/labels_h4.parquet, gold/sector_scurve.parquet,
         gold/agency_stats.parquet, gold/manifest.json

Point-in-time rule: the feature row at (key, t) reads only rows with period <= t. Per-key history comes from
groupby cumulative ops and backward as-of joins; cross-project statistics use rows at or before t only: the
sector velocity median uses the same quarter, the S-curve for calendar year Y is fitted on rows before Y-01-01
of projects completed before Y-01-01, and agency rates use label rows whose outcome period t0 + h is <= t.
The external group reads remark quarters <= t and land stretches first notified by t (parcels and complexity only
of stretches last notified by t); the forest-clearance prior (sector and name) does not change with t.
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
from pipeline.external import OPEN_LAST_Q, TAXONOMY  # noqa: E402
from pipeline.silver import ROOT, SILVER, months  # noqa: E402

GOLD = ROOT / "dataset" / "gold"

HORIZONS = (2, 4)
AGENCY_H = 2              # agency rates come from the 2-quarter labels (more realised outcomes, sooner)
SHRINK_K = 10             # pseudo-counts pulling agency rates toward the sector rate
COST_STEP = 1.05          # anticipated cost up >= 5% is a cost revision
DATE_STEP = 3             # anticipated completion pushed >= 3 months is a schedule slip
STAGNANT_PP = 0.5         # |progress velocity| below this (pp per quarter) counts as stagnant
SCURVE_BINS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0, 1.25, 1.5, 2.0, 3.0001]
SCURVE_MIN_ROWS = 20      # sector bins with fewer rows use the all-sector curve
ALL = "*"
COST_BANDS = [0, 500, 1000, 5000, np.inf]   # crore; band 0-3
PK = ["project_key", "period"]
EXT_CATS = list(TAXONOMY)
EXT_FIRST = ["land", "forest_env"]            # months since the first mention
FC_FEATURES = ["fc_expected_complexity", "fc_worst_complexity", "fc_max_authority_level"]
EXTERNAL_FILES = {"mentions": "project_mentions.parquet", "fc": "external_fc.parquet",
                  "land_pairs": "external_land_pairs.parquet"}
BINARY = ["y_date_push", "y_cost_rev", "y_any"]
TARGETS = BINARY + ["y_months", "y_cost_pct"]

FEATURE_GROUPS = {
    "state": ["physical_progress_pct", "elapsed_ratio", "cost_variation_pct", "expenditure_ratio", "burn_gap",
              "spi", "months_to_scheduled_completion", "months_to_anticipated_completion", "slip_to_date_months",
              "revisions_so_far", "months_since_last_revision", "log_cost", "cost_band"],
    "dynamics": ["progress_velocity_2q", "progress_velocity_4q", "spend_velocity_2q", "acceleration",
                 "stagnation_quarters", "velocity_vs_sector_median"],
    "context": ["expected_progress_scurve", "scurve_deviation", "sector_actual_target_ratio", "sector_yoy_growth",
                "sector_trend_4q", "agency_slip_rate", "agency_cost_optimism", "agency_n", "ministry", "sector",
                "state"],
    "freshness": ["obs_count_in_quarter", "months_since_last_obs", "dq_score", "period_type"],
    "external": [f"ext_open_{c}" for c in EXT_CATS] + ["ext_open_total"] + [f"ext_ever_{c}" for c in EXT_CATS]
                + [f"ext_months_since_first_{c}" for c in EXT_FIRST] + ["ext_remark_quarters"] + FC_FEATURES
                + ["la_linked", "la_complexity_max_by_t", "la_parcels_by_t", "la_notif_span_by_t"],
}
CATEGORICAL = ["ministry", "sector", "state", "period_type"]
BASELINE = ["slipped_last_period", "rule_score"]
META = ["project_key", "period", "agency", "is_completed"]
FEATURES = [f for fs in FEATURE_GROUPS.values() for f in fs]
SECTOR_CONTEXT = {"actual_target_ratio": "sector_actual_target_ratio", "yoy_growth_pct": "sector_yoy_growth",
                  "trend_4q": "sector_trend_4q"}


def qindex(period):
    """Quarter-start timestamps -> consecutive integers (year * 4 + quarter)."""
    return (period.dt.year * 4 + (period.dt.month - 1) // 3).astype("int64")


def norm_agency(s):
    """Upper case, punctuation to spaces; a bracketed acronym ('... [NHAI]') replaces the name.
    ponytail: no alias table, so 'NHAI' and 'NATIONAL HIGHWAYS AUTHORITY OF INDIA' stay two agencies."""
    s = s.str.extract(r"\[([^\]]+)\]", expand=False).fillna(s)
    s = s.str.upper().str.replace(r"[^A-Z0-9]+", " ", regex=True).str.strip()
    return s.mask(s.eq(""))


def lagged(d, col, back, window):
    """Per key, the latest non-null col at quarter q' in [q - back - window, q - back], and q - q'."""
    left = d[["project_key", "q"]].assign(_look=d["q"] - back).reset_index()
    right = d.loc[d[col].notna(), ["project_key", "q", col]].rename(columns={"q": "_rq", col: "_ref"})
    m = pd.merge_asof(left.sort_values("_look", kind="mergesort"), right.sort_values("_rq", kind="mergesort"),
                      left_on="_look", right_on="_rq", by="project_key", direction="backward", tolerance=window)
    m = m.set_index("index").reindex(d.index)
    return m["_ref"], d["q"] - m["_rq"]


def velocity(d, col, back, window):
    """Change of col per quarter against the reference found by lagged()."""
    ref, dq = lagged(d, col, back, window)
    return (d[col] - ref) / dq, dq


def base(obs, cutoff=None):
    """Rows at or before cutoff, sorted by key and period, with the state features."""
    d = obs if cutoff is None else obs[obs["period"] <= pd.Timestamp(cutoff)]
    d = d.sort_values(PK, kind="mergesort", ignore_index=True)
    g = d.groupby("project_key", sort=False)
    # baseline dates are rarely re-printed; carrying the last printed value forward reads only the past
    d["sanction_date"] = g["sanction_date"].ffill()
    d["scheduled_completion"] = g["scheduled_completion"].ffill()
    d["agency"] = norm_agency(d["agency"])
    d["q"] = qindex(d["period"])
    now, cost, prog = months(d["period"]), d["anticipated_cost_cr"], d["physical_progress_pct"]
    sanction = months(d["sanction_date"])
    span = months(d["scheduled_completion"]) - sanction
    d["elapsed_ratio"] = ((now - sanction) / span.where(span > 0)).clip(0, 3)
    d["cost_variation_pct"] = (cost / d["original_cost_cr"].where(d["original_cost_cr"] > 0) - 1) * 100
    d["expenditure_ratio"] = d["expenditure_cr"] / cost.where(cost > 0)
    d["burn_gap"] = d["expenditure_ratio"] * 100 - prog
    # ponytail: capped at 5, a project days after sanction would otherwise divide by ~0
    d["spi"] = (prog / 100 / d["elapsed_ratio"].where(d["elapsed_ratio"] > 0)).clip(upper=5)
    ac = months(d["anticipated_completion"])
    d["months_to_scheduled_completion"] = months(d["scheduled_completion"]) - now
    d["months_to_anticipated_completion"] = ac - now
    d["slip_to_date_months"] = ac - months(d["scheduled_completion"])
    # a revision at t: cost or anticipated completion stepped up against the key's previous printed value
    prev_cost = g["anticipated_cost_cr"].ffill().groupby(d["project_key"]).shift()
    prev_ac = ac.groupby(d["project_key"]).ffill().groupby(d["project_key"]).shift()
    event = (cost >= COST_STEP * prev_cost) | (ac >= prev_ac + DATE_STEP)
    d["slipped_last_period"] = event.astype("int64")
    d["revisions_so_far"] = event.groupby(d["project_key"]).cumsum()
    since = now.where(event).groupby(d["project_key"]).ffill()
    # no revision yet: months since the key entered the panel
    d["months_since_last_revision"] = now - since.fillna(now.groupby(d["project_key"]).transform("first"))
    d["log_cost"] = np.log1p(cost)
    d["cost_band"] = pd.cut(cost, COST_BANDS, right=False, labels=False)
    return d


def fit_scurves(d):
    """Sector S-curve per fit year Y: median progress per elapsed-ratio bin over rows before Y-01-01 of keys
    completed before Y-01-01, made monotone with a running max. Sector '*' is the all-sector curve."""
    done = d.loc[d["is_completed"]].groupby("project_key")["period"].min()
    p = d.loc[d["elapsed_ratio"].notna() & d["physical_progress_pct"].notna(),
              ["project_key", "period", "sector", "elapsed_ratio", "physical_progress_pct"]]
    p = p.assign(bin=pd.cut(p["elapsed_ratio"], SCURVE_BINS, right=False, labels=False).astype("float64"),
                 done=done.reindex(p["project_key"]).to_numpy())
    p = p[p["done"].notna()]
    fits = []
    for y in range(int(d["period"].dt.year.min()), int(d["period"].dt.year.max()) + 1):
        start = pd.Timestamp(y, 1, 1)
        f = p[(p["done"] < start) & (p["period"] < start)]
        if f.empty:
            continue
        f = pd.concat([f, f.assign(sector=ALL)])
        c = f.groupby(["sector", "bin"]).agg(expected_progress=("physical_progress_pct", "median"),
                                             n_rows=("project_key", "size"),
                                             n_projects=("project_key", "nunique")).reset_index()
        c["expected_progress"] = c.groupby("sector")["expected_progress"].cummax()
        fits.append(c.assign(fit_year=y))
    cols = ["fit_year", "sector", "bin", "bin_lo", "bin_hi", "expected_progress", "n_rows", "n_projects"]
    if not fits:
        return pd.DataFrame(columns=cols)
    out = pd.concat(fits, ignore_index=True)
    edges = np.array(SCURVE_BINS)
    out["bin_lo"], out["bin_hi"] = edges[out["bin"].astype(int)], edges[out["bin"].astype(int) + 1]
    return out[cols]


def expected_progress(d, curves):
    """S-curve value for each row: fit year = calendar year of the period, sector curve else '*'."""
    key = pd.DataFrame({"fit_year": d["period"].dt.year.astype("int64"), "sector": d["sector"],
                        "bin": pd.cut(d["elapsed_ratio"], SCURVE_BINS, right=False, labels=False).astype("float64")})
    c = curves.assign(fit_year=curves["fit_year"].astype("int64"), bin=curves["bin"].astype("float64"))
    on = ["fit_year", "sector", "bin"]
    own = key.merge(c[c["n_rows"] >= SCURVE_MIN_ROWS][on + ["expected_progress"]], on=on, how="left")
    pooled = key.assign(sector=ALL).merge(c[on + ["expected_progress"]], on=on, how="left")
    return own["expected_progress"].fillna(pooled["expected_progress"]).set_axis(d.index)


def build_labels(obs, h):
    """Outcome h quarters after each row, from the same key's observation at exactly t + h quarters.
    Rows completed at t and rows without an observation at t + h are dropped; a target whose inputs are
    null stays null. y_any is labelled only when both flags are known: were it true whenever one known flag
    is true, rows missing one input would be labelled only when positive and the model would learn the gap.
    A value taken from a different field at t + h than at t (cost_basis / completion_basis: anticipated, revised,
    original) is not compared either: from 2025-07 the flash reports print no anticipated cost or date, and QPISR
    anticipated vs flash revised is a change of report format, not a revision."""
    cols = ["project_key", "anticipated_cost_cr", "anticipated_completion", "cost_basis", "completion_basis"]
    q = qindex(obs["period"])
    now = obs.loc[~obs["is_completed"], cols + ["period"]].assign(_q=q + h)
    later = obs[cols + ["period"]].assign(_q=q).rename(columns={"period": "target_period"})
    m = now.merge(later, on=["project_key", "_q"], suffixes=("", "_h"), validate="1:1")
    slip = (months(m["anticipated_completion_h"]) - months(m["anticipated_completion"])).where(
        m["completion_basis"].eq(m["completion_basis_h"]))
    cost_pct = ((m["anticipated_cost_cr_h"] / m["anticipated_cost_cr"].where(m["anticipated_cost_cr"] > 0) - 1)
                * 100).where(m["cost_basis"].eq(m["cost_basis_h"]))
    date_push = pd.Series(slip >= DATE_STEP, dtype="boolean").mask(slip.isna())
    cost_rev = pd.Series(m["anticipated_cost_cr_h"] >= COST_STEP * m["anticipated_cost_cr"],
                         dtype="boolean").mask(cost_pct.isna())
    any_slip = (date_push | cost_rev).mask(date_push.isna() | cost_rev.isna())
    out = pd.DataFrame({"project_key": m["project_key"], "period": m["period"],
                        "target_period": m["target_period"], "y_date_push": date_push.astype("Int8"),
                        "y_cost_rev": cost_rev.astype("Int8"), "y_any": any_slip.astype("Int8"),
                        "y_months": slip.astype("float64"), "y_cost_pct": cost_pct})
    return out.sort_values(PK, kind="mergesort", ignore_index=True)


def realised(lab, d, by):
    """Cumulative outcome sums per `by` value as of each row of d: label rows with target_period <= period."""
    g = lab.groupby([by, "target_period"])
    s = pd.DataFrame({"n": g.size(), "s_n": g["slip"].count(), "s_sum": g["slip"].sum(),
                      "c_n": g["cost"].count(), "c_sum": g["cost"].sum()})
    s = s.groupby(level=0).cumsum().reset_index()
    left = d[[by, "period"]].reset_index()
    m = pd.merge_asof(left.sort_values("period", kind="mergesort"), s.sort_values("target_period", kind="mergesort"),
                      left_on="period", right_on="target_period", by=by, direction="backward")
    m = m.set_index("index").reindex(d.index)
    return m[["n", "s_n", "s_sum", "c_n", "c_sum", "target_period"]]


def agency_context(d):
    """Point-in-time agency rates from the AGENCY_H labels realised at or before each row's period:
    schedule-slip rate and mean cost change % (clipped to -50..100), shrunk toward the sector rate
    (else the all-project rate) with SHRINK_K pseudo-counts. Returns a frame aligned with d."""
    lab = build_labels(d, AGENCY_H)
    lab = lab.merge(d[PK + ["agency", "sector"]], on=PK, how="left", validate="1:1").assign(
        slip=lambda x: x["y_date_push"].astype("float64"),
        cost=lambda x: x["y_cost_pct"].clip(-50, 100), _all=0)
    rows = d[["period", "agency", "sector"]].assign(_all=0)
    a = realised(lab[lab["agency"].notna()], rows.fillna({"agency": ""}), "agency")
    s = realised(lab, rows, "sector")
    t = realised(lab, rows, "_all")
    prior_slip = (s["s_sum"] / s["s_n"]).fillna(t["s_sum"] / t["s_n"])
    prior_cost = (s["c_sum"] / s["c_n"]).fillna(t["c_sum"] / t["c_n"])
    a0 = a[["n", "s_n", "s_sum", "c_n", "c_sum"]].fillna(0)
    return pd.DataFrame({
        "agency_n": a0["n"], "n_slip": a0["s_n"], "slip_rate_raw": a["s_sum"] / a["s_n"],
        "n_cost": a0["c_n"], "cost_pct_raw": a["c_sum"] / a["c_n"], "last_outcome_period": a["target_period"],
        "agency_slip_rate": (a0["s_sum"] + SHRINK_K * prior_slip) / (a0["s_n"] + SHRINK_K),
        "agency_cost_optimism": (a0["c_sum"] + SHRINK_K * prior_cost) / (a0["c_n"] + SHRINK_K),
    }, index=d.index)


def agency_table(d):
    """Agency x period point-in-time stats (raw, before shrinkage) for every agency and period in d."""
    a = pd.concat([d[["agency", "period"]], agency_context(d)], axis=1)
    a = a[a["agency"].notna()].drop_duplicates(["agency", "period"])
    cols = ["agency", "period", "agency_n", "n_slip", "slip_rate_raw", "n_cost", "cost_pct_raw", "last_outcome_period"]
    return a[cols].sort_values(["agency", "period"], kind="mergesort", ignore_index=True)


def rule_score(d):
    """The old dashboard composite (pipeline/build_real_projects.py, same weights and P95 anchors 81.4 / 75).
    Missing values count as 0 as there; the printed delay falls back to slip_to_date_months."""
    cost = d["anticipated_cost_cr"]
    overrun = d["cost_variation_pct"].clip(lower=0).fillna(0)
    delay = d["delay_months"].fillna(d["slip_to_date_months"]).clip(lower=0).fillna(0)
    spend = (d["expenditure_cr"] / cost.where(cost > 0)).fillna(0)
    return (0.30 * (overrun / 81.4 * 100).clip(0, 100) + 0.30 * (delay / 75.0 * 100).clip(0, 100)
            + 0.25 * (100 - d["physical_progress_pct"].fillna(0)).clip(0, 100)
            + 0.15 * (spend / 1.5 * 100).clip(0, 100))


def load_external(gold=GOLD):
    return {k: pd.read_parquet(gold / f) for k, f in EXTERNAL_FILES.items()}


def external_until(ext, t):
    """The external inputs as they stood at t: later remark quarters and later-notified stretches removed, and a
    stretch still being notified at t has no parcels, complexity or last notification yet."""
    m, p = ext["mentions"], ext["land_pairs"]
    p = p[p["first_notif_date"] <= t]
    live = p["last_notif_date"] > t
    p = p.assign(**{c: p[c].mask(live) for c in ["num_parcels", "acquisition_complexity_score", "last_notif_date"]})
    return {**ext, "mentions": m[m["period"] <= t], "land_pairs": p}


def asof_join(d, right, cols):
    """cols of the latest right row of the same key with period <= each row's period (null when none)."""
    left = d[PK].reset_index()
    m = pd.merge_asof(left.sort_values("period", kind="mergesort"),
                      right[PK + cols].sort_values("period", kind="mergesort"),
                      on="period", by="project_key", direction="backward")
    return m.set_index("index").reindex(d.index)[cols]


def external_features(d, ext):
    """External group at each (project_key, period) row of d. A category is open at t when it is mentioned in one
    of the key's last OPEN_LAST_Q remark-observed quarters up to t and that latest mention does not report it done
    (the pipeline/external.py rule applied at t, not the final status). Land: a key is linked at t when a stretch
    of its NH (pipeline/external.py link_land) was first notified by t; the notification span is cut at t, parcels
    and complexity count only stretches fully notified by t, and the land values of a key not linked at t are null
    (unknown), not 0."""
    out = pd.DataFrame(index=d.index)
    mq = ext["mentions"]
    seen = mq[PK].drop_duplicates().sort_values(PK, kind="mergesort")
    seen = seen.assign(qn=seen.groupby("project_key").cumcount().astype("float64"))
    qn_t = asof_join(d, seen, ["qn"])["qn"]
    ment = mq[mq["category"].notna()].merge(seen, on=PK)
    for c in EXT_CATS:
        mc = ment[ment["category"].eq(c)]
        last = asof_join(d, mc, ["qn", "resolved"])
        ever = last["qn"].notna()
        done = last["resolved"].fillna(False).astype(bool)
        out[f"ext_open_{c}"] = (ever & (last["qn"] >= qn_t - (OPEN_LAST_Q - 1)) & ~done).astype("float64")
        out[f"ext_ever_{c}"] = ever.astype("float64")
        if c in EXT_FIRST:
            first = d["project_key"].map(months(mc["period"]).astype("float64").groupby(mc["project_key"]).min())
            out[f"ext_months_since_first_{c}"] = (months(d["period"]) - first).where(ever)
    out["ext_open_total"] = out[[f"ext_open_{c}" for c in EXT_CATS]].sum(axis=1)
    out["ext_remark_quarters"] = (qn_t + 1).fillna(0)
    fc = ext["fc"].set_index("project_key")
    for c in FC_FEATURES:
        out[c] = d["project_key"].map(fc[c.replace("fc_", "fc_prior_")]).astype("float64")
    r = d[PK].reset_index().merge(ext["land_pairs"], on="project_key")
    r = r[r["first_notif_date"] <= r["period"]]
    # parcels and complexity are snapshot totals that count later notifications: only a stretch whose last
    # notification is by t gives them; one still being notified gives its span so far
    done = r["last_notif_date"] <= r["period"]
    span = r["last_notif_date"].where(done, r["period"]) - r["first_notif_date"]
    g = r.assign(span=span.dt.days, parcels=r["num_parcels"].where(done),
                 complexity=r["acquisition_complexity_score"].where(done)).groupby("index")
    la = pd.DataFrame({"la_complexity_max_by_t": g["complexity"].max(),
                       "la_parcels_by_t": g["parcels"].sum(min_count=1), "la_notif_span_by_t": g["span"].max()})
    la = la.reindex(d.index).astype("float64")
    out["la_linked"] = la["la_notif_span_by_t"].notna().astype("float64")
    out[list(la.columns)] = la
    return out


def build_features(obs, cutoff=None, sectors=None, external=None):
    """One row per (project_key, period <= cutoff): META + FEATURES + BASELINE, using for each row only
    rows at or before its own period. sectors defaults to silver/sector_context.parquet, external to the external
    step's gold files (load_external)."""
    if sectors is None:
        sectors = pd.read_parquet(SILVER / "sector_context.parquet")
    if external is None:
        external = load_external()
    d = base(obs, cutoff)
    prog = d["physical_progress_pct"]
    d["progress_velocity_2q"], _ = velocity(d, "physical_progress_pct", 2, 2)
    d["progress_velocity_4q"], _ = velocity(d, "physical_progress_pct", 4, 2)
    d["spend_velocity_2q"], _ = velocity(d.assign(spend=d["expenditure_ratio"] * 100), "spend", 2, 2)
    # last 2 quarters' velocity minus the 2 before them: v(t-2..t) - v(t-4..t-2) = 2 * (v2 - v4)
    d["acceleration"] = 2 * (d["progress_velocity_2q"] - d["progress_velocity_4q"])
    v1, dq = velocity(d, "physical_progress_pct", 1, 1)
    stuck = v1.abs() < STAGNANT_PP
    run = (~stuck).groupby(d["project_key"]).cumsum()
    d["stagnation_quarters"] = dq.where(stuck, 0).groupby([d["project_key"], run]).cumsum()
    d["velocity_vs_sector_median"] = d["progress_velocity_2q"] - d.groupby(["sector", "period"])[
        "progress_velocity_2q"].transform("median")

    d["expected_progress_scurve"] = expected_progress(d, fit_scurves(d))
    d["scurve_deviation"] = prog - d["expected_progress_scurve"]
    ctx = sectors[["sector", "period", *SECTOR_CONTEXT]].rename(columns=SECTOR_CONTEXT)
    d = d.merge(ctx, on=["sector", "period"], how="left", validate="m:1")
    d = pd.concat([d, agency_context(d)[["agency_slip_rate", "agency_cost_optimism", "agency_n"]]], axis=1)
    d = pd.concat([d, external_features(d, external)], axis=1)
    d["rule_score"] = rule_score(d)

    out = d[META + FEATURES + BASELINE].copy()
    num = [c for c in FEATURES + BASELINE if c not in CATEGORICAL]
    out[num] = out[num].astype("float64")
    return out


def label_summary(lab):
    """target -> labelled (non-null) rows, plus the positive rate for the binary targets."""
    out = {}
    for c in TARGETS:
        v = lab[c].astype("float64").dropna()
        out[c] = {"n": len(v)} | ({"pos_rate": round(float(v.mean()), 4) if len(v) else None} if c in BINARY else {})
    return out


def truncation_check(obs, sectors, ext, feats, cutoffs):
    """Features at each cutoff are identical whether built on the full panel and external inputs or on both cut
    there."""
    out = {}
    for c in cutoffs:
        a = feats[feats["period"] == c].reset_index(drop=True)
        b = build_features(obs, cutoff=c, sectors=sectors, external=external_until(ext, c))
        b = b[b["period"] == c].reset_index(drop=True)
        out[str(c.date())] = {"rows": len(a), "identical": bool(a.equals(b))}
    return out


def label_checks(lab, obs, h):
    done = lab.merge(obs[PK + ["is_completed"]], on=PK, how="left")["is_completed"]
    return {"exact_horizon": bool((qindex(lab["target_period"]) - qindex(lab["period"])).eq(h).all()),
            "no_completed_rows": not bool(done.any()), "unique": not bool(lab.duplicated(PK).any())}


def main(silver=SILVER, out=GOLD):
    """Build features, labels, S-curves and agency stats; run the leakage checks (raise before writing); write."""
    t0 = time.time()
    obs = pd.read_parquet(silver / "observations.parquet")
    sectors = pd.read_parquet(silver / "sector_context.parquet")
    ext = load_external(out)
    feats = build_features(obs, sectors=sectors, external=ext)
    d = base(obs)
    frames = {"features": feats, **{f"labels_h{h}": build_labels(obs, h) for h in HORIZONS},
              "sector_scurve": fit_scurves(d), "agency_stats": agency_table(d)}
    # cutoffs at the 25/50/75% points of the quarters present, and the second-latest quarter
    periods = np.sort(obs["period"].unique())
    cutoffs = [pd.Timestamp(periods[int(len(periods) * f)]) for f in (0.25, 0.5, 0.75)] + [pd.Timestamp(periods[-2])]
    ag = frames["agency_stats"]
    checks = {"truncation": truncation_check(obs, sectors, ext, feats, cutoffs),
              "agency_outcomes_realised": bool((ag["last_outcome_period"].isna()
                                                | (ag["last_outcome_period"] <= ag["period"])).all()),
              **{f"labels_h{h}": label_checks(frames[f"labels_h{h}"], obs, h) for h in HORIZONS}}
    bad = [c for c, v in checks["truncation"].items() if not v["identical"]]
    assert not bad, f"features change when the panel is cut at {bad}"
    assert checks["agency_outcomes_realised"], "agency stats use outcomes after their period"
    assert all(all(checks[f"labels_h{h}"].values()) for h in HORIZONS), checks

    out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for name, f in frames.items():
        path = out / f"{name}.parquet"
        f.to_parquet(path, index=False, row_group_size=50000)
        digest.update(name.encode() + bytes(1) + path.read_bytes())
    years = {f"h{h}": {str(y): label_summary(g) for y, g in lab.groupby(lab["period"].dt.year)}
             for h in HORIZONS for lab in [frames[f"labels_h{h}"]]}
    now = datetime.now(timezone.utc)
    silver_man = json.loads((silver / "silver_manifest.json").read_text(encoding="utf-8"))
    man = {
        "gold_version": digest.hexdigest()[:12],
        "silver_version": silver_man["silver_version"],
        "run_id": f"RUN-{now:%Y%m%d-%H%M%S}",
        "built_at": now.isoformat(timespec="seconds"),
        "latest_period": str(obs["period"].max().date()),
        "horizons_quarters": list(HORIZONS),
        "features": FEATURE_GROUPS,
        "categorical": CATEGORICAL,
        "baselines": BASELINE,
        "meta": META,
        "params": {"agency_label_horizon": AGENCY_H, "shrink_k": SHRINK_K, "cost_step": COST_STEP,
                   "date_step_months": DATE_STEP, "stagnant_pp_per_quarter": STAGNANT_PP,
                   "scurve_bins": SCURVE_BINS, "scurve_min_rows": SCURVE_MIN_ROWS,
                   "cost_bands_cr": COST_BANDS[:-1], "external_open_last_q": OPEN_LAST_Q},
        "rows": {name: len(f) for name, f in frames.items()},
        "labelled": {f"h{h}": label_summary(frames[f"labels_h{h}"]) for h in HORIZONS},
        "labelled_by_year": years,
        "checks": checks,
    }
    (out / "manifest.json").write_text(json.dumps(man, indent=2, default=str) + "\n", encoding="utf-8")
    for k, by_year in years.items():
        table = pd.DataFrame({y: {f"{c} {s}": v for c, st in t.items() for s, v in st.items()}
                              for y, t in by_year.items()}).T
        table = table.astype({c: "int64" for c in table.columns if c.endswith(" n")})
        print(f"labelled rows (n) and positive rate (pos_rate) per year of t, {k}:")
        print(table.to_string())
    print(f"gold {man['gold_version']} (silver {man['silver_version']}): "
          + ", ".join(f"{v} {n}" for n, v in man["rows"].items()) + f", {time.time() - t0:.1f}s")
    return man


if __name__ == "__main__":
    main()
