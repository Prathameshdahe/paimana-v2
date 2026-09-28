"""
Measured hidden-delay priors: what a forest-clearance stage in the report remarks, a land-acquisition share in them,
or land-acquisition complexity on the km-matched NH stretch has meant for the next four quarters on REAL projects,
against matched projects without it. They replace the guessed bands of the external-factors mock files (docs/
EXTERNAL_DATA_CROSSCHECK.md, "Garvit's prior vs measured"); the mock rows are never used here. Evidence for the risk
profile and the External Factors page only: the 2026-09 backtests found no model lift from these inputs.

Run from repo root after gold (the profile step runs it before the risk profile):  python -m pipeline.hidden_delay
Inputs   gold/labels_h4.parquet, gold/features.parquet, gold/project_mentions.parquet, gold/external_land_links.parquet,
         silver/project_master.parquet and the land tables (for the NH/district link, pipeline/external.py)
Output   gold/hidden_delay_priors.parquet (one row per factor x group)

Rows: key-quarters from 2014 on, not completed, with a 4-quarter date label (y_months: months the anticipated
completion moved by t + 4 quarters; y_date_push: moved 3 months or more).
- forest_clearance: the most advanced forest stage the remarks give that quarter (FOREST_GROUPS). Baseline: quarters
  whose remarks have free text but no forest mention. Strata: sector x year.
- land_progress: the land-acquisition share the remarks give that quarter (LA_BANDS). Baseline: remark quarters
  with no land mention. Strata: sector x year.
- land_complexity: road rows, the highest complexity of km-matched stretches fully notified by t (the point-in-time
  rule of pipeline/gold.py). Baseline: road rows with no km-matched stretch notified by t. Strata: months to the
  anticipated completion (DEADLINE_BANDS, as the 2026-09 critic analysis), since slip depends mostly on it. The km
  link is the only one the checklist rates; land_complexity_nh repeats it with the looser NH/district link of that
  analysis (district links were 64% and NH-only links 32% right on the hand check) against road rows with no link.
The estimate is the group-minus-baseline difference within strata, weighted by the group's rows (strata without
baseline rows drop out; matched_share says how much of the group is kept). 95% CI: project-cluster bootstrap
(projects resampled with replacement, group and baseline apart). Groups with fewer than MIN_PROJECTS projects are
'too few to measure' and show no estimate. p is the two-sided bootstrap p (B replicates); Holm adjusts it over
every measured group and both outcomes. The groups were chosen after looking at the data, so all of this is
exploratory. applicable() says which priors describe a project today: a remark status only while it is current.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import external  # noqa: E402
from pipeline.silver import ROOT, SILVER  # noqa: E402

GOLD = ROOT / "dataset" / "gold"
PK = ["project_key", "period"]
START = pd.Timestamp("2014-01-01")
MIN_PROJECTS = 15
# 10,000 replicates: Holm multiplies the smallest p by up to 24, so at 1,000 (p resolution 0.001) one replicate moved
# an adjusted p across 0.05 and the seed decided which group 'survived'
B = 10_000
CHUNK = 1_000
SEED = 0
LIVE_Q = 4  # pipeline/gold.OPEN_MAX_AGE_Q: a remark status describes the project today within this many quarters
# remark forest stage -> (group, label, Garvit's mock status and its hidden-delay band in months: min-max, median)
FOREST_GROUPS = {
    "applied": ("fc_applied", "applied or preparing the proposal", "Pending Clearances", "15-32 (median 25.5)"),
    "state_level": ("fc_state", "pending at state level (DFO, CF, nodal, state government)", "Pending Clearances",
                    "15-32 (median 25.5)"),
    "stage1_pending": ("fc_state", "pending at state level (DFO, CF, nodal, state government)", "Pending Clearances",
                       "15-32 (median 25.5)"),
    "regional_iro": ("fc_regional", "pending at the regional office", "Pending at IRO", "11-31 (median 19.5)"),
    "central_fac_moef": ("fc_central", "pending at FAC / MoEFCC", "Pending at FAC", "28-63 (median 46)"),
    "stage1_granted": ("fc_stage1", "Stage-I granted, awaiting Stage-II or working permission", "Stage-I Approved",
                       "4-20 (median 11)"),
    "stage2_pending": ("fc_stage1", "Stage-I granted, awaiting Stage-II or working permission", "Stage-I Approved",
                       "4-20 (median 11)"),
    "wp_pending": ("fc_stage1", "Stage-I granted, awaiting Stage-II or working permission", "Stage-I Approved",
                   "4-20 (median 11)"),
    "working_permission": ("fc_stage1", "Stage-I granted, awaiting Stage-II or working permission", "Stage-I Approved",
                           "4-20 (median 11)"),
    "stage2_granted": ("fc_stage2", "Stage-II or final approval", "Stage-II Approved", "0-16 (median 8)"),
    "approved_generic": ("fc_stage2", "Stage-II or final approval", "Stage-II Approved / Approved",
                         "0-16 (median 8) / 0-14 (median 0)"),
    "fc_awaited": ("fc_awaited", "forest clearance awaited, no stage named", "Pending Clearances",
                   "15-32 (median 25.5)"),
    "rejected": ("fc_rejected", "rejected, returned or in appeal", "Rejected / In-Appeal", "78-85 (median 79)"),
}
# land share acquired (remarks) -> group; Garvit's hidden land delay is about 0.59 months per point still to acquire
LA_BANDS = [(-0.01, 50, "la_lt50", "under 50% acquired", "about 29-59 months (0.59 x points left; mock median 31)"),
            (50, 80, "la_50_80", "50-80% acquired", "about 12-29 months (mock median 21)"),
            (80, 95, "la_80_95", "80-95% acquired", "about 3-12 months (mock median 6)"),
            (95, 100, "la_95_100", "95-100% acquired", "0-3 months (0 at 100%; mock median 1)")]
CX_GROUPS = {"cx_4_5": ("complexity 4-5 of 5 on the km-matched stretch", "fragmentation factor only (no band)"),
             "cx_0_3": ("complexity 0-3 of 5 on the km-matched stretch", "fragmentation factor only (no band)")}
# the 2026-09 critic analysis linked on the NH and district alone (the model's link over all states); kept to show
# how the choice of link moves the estimate
CX_NH_GROUPS = {"cx_nh_4_5": ("complexity 4-5 of 5 on an NH/district-linked stretch (the 2026-09 analysis)",
                              "fragmentation factor only (no band)"),
                "cx_nh_0_3": ("complexity 0-3 of 5 on an NH/district-linked stretch (the 2026-09 analysis)",
                              "fragmentation factor only (no band)")}
DEADLINE_BANDS = [-1e9, 0, 6, 12, 24, 48, 1e9]
DEADLINE_LABELS = ["overdue", "0-6", "6-12", "12-24", "24-48", "48+"]
COLS = ["factor", "group", "label", "strata", "n_rows", "n_projects", "measurable", "matched_share",
        "months_group", "months_base", "extra_months", "extra_months_lo", "extra_months_hi", "p_months", "holm_months",
        "push_group", "push_base", "extra_push", "extra_push_lo", "extra_push_hi", "p_push", "holm_push",
        "garvit_status", "garvit_band", "as_of_note"]


def frame(gold=GOLD):
    """Labelled key-quarters with their remark forest group, remark land band, point-in-time land complexity group
    and the baseline flags."""
    lab = pd.read_parquet(gold / "labels_h4.parquet", columns=PK + ["y_months", "y_date_push"])
    f = pd.read_parquet(gold / "features.parquet",
                        columns=PK + ["sector", "is_completed", "months_to_anticipated_completion"])
    d = lab[lab["y_date_push"].notna()].merge(f, on=PK)
    d = d[~d["is_completed"].astype(bool) & (d["period"] >= START)].reset_index(drop=True)
    d = d.assign(y_months=d["y_months"].astype("float64"), y_date_push=d["y_date_push"].astype("float64"))
    m = pd.read_parquet(gold / "project_mentions.parquet")
    q = m.groupby(PK).agg(fc_stage=("fc_stage", "first"), la_pct=("la_pct", "first"), la_step=("la_step", "first"),
                          forest=("category", lambda s: s.eq("forest_env").any()),
                          land=("category", lambda s: s.eq("land").any())).reset_index()
    d = d.merge(q, on=PK, how="left")
    observed = d["forest"].notna()                     # the quarter's remarks have free text
    d["fc_group"] = d["fc_stage"].map({k: v[0] for k, v in FOREST_GROUPS.items()})
    d["fc_base"] = observed & ~d["forest"].fillna(False).astype(bool) & d["fc_stage"].isna()
    d["la_group"] = pd.cut(d["la_pct"], [b[0] for b in LA_BANDS] + [100], labels=[b[2] for b in LA_BANDS])
    d["la_group"] = d["la_group"].astype("str").where(d["la_pct"].notna())
    d["la_base"] = observed & ~d["land"].fillna(False).astype(bool) & d["la_pct"].isna() & d["la_step"].isna()
    d["stratum_sy"] = d["sector"].fillna("?") + "|" + d["period"].dt.year.astype("str")
    # land complexity at t: km-matched stretches first notified by t count; complexity only once fully notified
    links = pd.read_parquet(gold / "external_land_links.parquet")
    master = pd.read_parquet(SILVER / "project_master.parquet")
    st = external.stretches(external.load_land())
    nh_links = external.land_pairs(external.link_land(master, st, strict=False)[1], st)
    road = d["sector"].eq("Roads & Highways")
    for tag, p in [("", links[links["la_match_method"].eq("nh_chainage")]), ("nh_", nh_links)]:
        r = d.loc[road, ["project_key", "period"]].reset_index().merge(p, on="project_key")
        r = r[r["first_notif_date"] <= r["period"]]
        cx = r["acquisition_complexity_score"].where(r["last_notif_date"] <= r["period"])
        c = cx.groupby(r["index"]).max().reindex(d.index)
        linked = d.index.isin(r["index"])
        d[f"cx_{tag}group"] = np.select([road & linked & (c >= 4), road & linked & (c < 4)],
                                        [f"cx_{tag}4_5", f"cx_{tag}0_3"], None)
        d[f"cx_{tag}base"] = road & ~linked
    d["stratum_dl"] = pd.cut(d["months_to_anticipated_completion"], DEADLINE_BANDS, labels=DEADLINE_LABELS).astype("str")
    return d


def _mats(rows, col, strata, index):
    """Per project x stratum sums and counts of col (projects in rows order of first appearance)."""
    s = rows.groupby(["project_key", strata], observed=True)[col].agg(["sum", "count"]).reset_index()
    pk = pd.Index(s["project_key"].unique())
    shape = (len(pk), len(index))
    S, C = np.zeros(shape), np.zeros(shape)
    i, j = pk.get_indexer(s["project_key"]), index.get_indexer(s[strata])
    np.add.at(S, (i, j), s["sum"].to_numpy())
    np.add.at(C, (i, j), s["count"].to_numpy())
    return S, C


def _est(gs, gc, bs, bc):
    """Stratified difference (rows: replicates) of group mean minus baseline mean, weighted by group counts."""
    ok = (gc > 0) & (bc > 0)
    diff = np.where(ok, gs / np.where(gc > 0, gc, 1) - bs / np.where(bc > 0, bc, 1), 0.0)
    w = np.where(ok, gc, 0.0)
    return (diff * w).sum(axis=-1) / np.where(w.sum(axis=-1) > 0, w.sum(axis=-1), np.nan)


def stratified_diff(g, b, col, strata, rng, n_boot=B):
    """(estimate, lo, hi, p, group mean, matched baseline mean, matched share) of the within-stratum difference of
    col, group g minus baseline b, with a project-cluster bootstrap."""
    g, b = g[g[col].notna()], b[b[col].notna()]
    index = pd.Index(sorted(set(g[strata]) | set(b[strata])))
    GS, GC = _mats(g, col, strata, index)
    BS, BC = _mats(b, col, strata, index)
    gs, gc, bs, bc = GS.sum(0), GC.sum(0), BS.sum(0), BC.sum(0)
    est = float(_est(gs, gc, bs, bc))
    ok = (gc > 0) & (bc > 0)
    matched = float(gc[ok].sum() / gc.sum()) if gc.sum() else np.nan
    base_mean = float((bs[ok] / bc[ok] * gc[ok]).sum() / gc[ok].sum()) if ok.any() else np.nan
    res = []
    for k in range(0, n_boot, CHUNK):  # chunks keep the replicate weight matrices small
        m = min(CHUNK, n_boot - k)
        wg = rng.multinomial(len(GS), np.full(len(GS), 1 / len(GS)), size=m)
        wb = rng.multinomial(len(BS), np.full(len(BS), 1 / len(BS)), size=m)
        res.append(_est(wg @ GS, wg @ GC, wb @ BS, wb @ BC))
    res = np.concatenate(res)
    res = res[~np.isnan(res)]
    lo, hi = np.percentile(res, [2.5, 97.5])
    p = min(1.0, 2 * min((res <= 0).mean(), (res >= 0).mean()))
    return est, float(lo), float(hi), max(p, 1 / n_boot), float(g[col].mean()), base_mean, matched


def holm(p):
    """Holm step-down adjusted p-values (NaN stays NaN)."""
    p = pd.Series(p, dtype="float64")
    v = p.dropna().sort_values()
    m = len(v)
    adj = (v * (m - np.arange(m))).cummax().clip(upper=1.0)
    return adj.reindex(p.index)


def priors(d, n_boot=B, seed=SEED):
    """COLS rows: every forest group, land band and complexity group, measured against its baseline."""
    rng = np.random.default_rng(seed)
    specs = []
    for grp in dict.fromkeys(v[0] for v in FOREST_GROUPS.values()):
        k = next(key for key, v in FOREST_GROUPS.items() if v[0] == grp)
        specs.append(("forest_clearance", grp, FOREST_GROUPS[k][1], "fc_group", "fc_base", "stratum_sy",
                      "sector x year", FOREST_GROUPS[k][2], FOREST_GROUPS[k][3]))
    specs += [("land_progress", grp, label, "la_group", "la_base", "stratum_sy", "sector x year",
               "Land Acquisition Progress (%)", band) for _, _, grp, label, band in LA_BANDS]
    specs += [("land_complexity", grp, label, "cx_group", "cx_base", "stratum_dl", "months-to-deadline band",
               "la_state_fragmentation_factor", band) for grp, (label, band) in CX_GROUPS.items()]
    specs += [("land_complexity_nh", grp, label, "cx_nh_group", "cx_nh_base", "stratum_dl",
               "months-to-deadline band", "la_state_fragmentation_factor", band)
              for grp, (label, band) in CX_NH_GROUPS.items()]
    out = []
    for factor, grp, label, gcol, bcol, strata, strata_name, g_status, g_band in specs:
        g, b = d[d[gcol].eq(grp)], d[d[bcol]]
        r = {"factor": factor, "group": grp, "label": label, "strata": strata_name, "n_rows": len(g),
             "n_projects": g["project_key"].nunique(), "garvit_status": g_status, "garvit_band": g_band,
             "as_of_note": "Bhoomi Rashi register, stretches fully notified by t" if factor.startswith("land_complexity")
             else "remarks 2014 to 2023-Q2"}
        r["measurable"] = r["n_projects"] >= MIN_PROJECTS
        if r["measurable"]:
            for col, tag, scale in [("y_months", "months", 1.0), ("y_date_push", "push", 1.0)]:
                est, lo, hi, p, gm, bm, mt = stratified_diff(g, b, col, strata, rng, n_boot)
                extra = "extra_months" if tag == "months" else "extra_push"
                r.update({f"{tag}_group": gm, f"{tag}_base": bm, extra: est, f"{extra}_lo": lo, f"{extra}_hi": hi,
                          f"p_{tag}": p, "matched_share": mt})
        out.append(r)
    t = pd.DataFrame(out).reindex(columns=COLS)
    both = pd.concat([t["p_months"], t["p_push"]], ignore_index=True)
    adj = holm(both)
    t["holm_months"], t["holm_push"] = adj.iloc[:len(t)].to_numpy(), adj.iloc[len(t):].to_numpy()
    return t


def applicable(remarks, la_state, portal, asof):
    """The priors that apply to one project at asof, as (factor, group, basis, as_of, current): the forest stage and
    the land share the remarks last gave, and the land complexity of a km-matched (rated) link. A remark status is
    current only within LIVE_Q calendar quarters of asof (remark free text ends in 2023-Q2, so none is in 2026); an
    older one is what the project looked like at its last report, never an expected delay now. The remark forest
    stage drops out once PARIVESH shows every linked proposal closed with a final approval (portal: n_final, n_open).
    remarks and portal are dicts (a remark_status and an external_fc_portal row) or None."""
    rs, po = remarks or {}, portal or {}
    since = pd.Timestamp(asof) - pd.DateOffset(months=3 * LIVE_Q)
    current = lambda t: bool(pd.notna(t) and pd.Timestamp(t) > since)  # noqa: E731
    cleared = (po.get("n_final") or 0) > 0 and (po.get("n_open") or 0) == 0
    out = []
    st, v = rs.get("fc_stage"), rs.get("la_pct")
    if st in FOREST_GROUPS and not cleared:
        out.append(("forest_clearance", FOREST_GROUPS[st][0], "forest stage in the report remarks",
                    rs.get("fc_stage_as_of"), current(rs.get("fc_stage_as_of"))))
    if v is not None and pd.notna(v):  # pd.cut bins of frame(): (lo, hi]
        band = next((b[2] for b in LA_BANDS if b[0] < v <= b[1]), None)
        out.append(("land_progress", band, "land share acquired in the report remarks", rs.get("la_pct_as_of"),
                    current(rs.get("la_pct_as_of"))))
    cx = {"flagged": "cx_4_5", "clear": "cx_0_3"}.get(la_state)
    if cx:
        out.append(("land_complexity", cx, "land complexity on the km-matched NH stretch", None, True))
    return out


def text(r, as_of=None):
    """One prior as a checklist phrase: '+7 months over the next year, measured on 16 projects (CI 2-12)', 'no
    measurable extra delay (+1 month, CI -2 to +4; 43 projects)' or 'too few projects to measure (6)'."""
    if r is None or not bool(r["measurable"]):
        n = 0 if r is None else int(r["n_projects"])
        return f"too few projects to measure ({n}, need {MIN_PROJECTS})"
    m, lo, hi = r["extra_months"], r["extra_months_lo"], r["extra_months_hi"]
    p, plo, phi = 100 * r["extra_push"], 100 * r["extra_push_lo"], 100 * r["extra_push_hi"]
    sig_m, sig_p = lo > 0 or hi < 0, plo > 0 or phi < 0
    n = int(r["n_projects"])
    mo = f"{fmt(m)} month{'' if abs(round_half(m)) == 1 else 's'} over the next year"
    if not (sig_m or sig_p):
        return (f"no measurable extra delay ({mo}, CI {fmt(lo)} to {fmt(hi)}; {fmt(p)} pts date-push risk, CI "
                f"{fmt(plo)} to {fmt(phi)}; {n} projects)")
    parts = []
    if sig_m:
        parts.append(f"{mo} (CI {fmt(lo)} to {fmt(hi)})")
    if sig_p:
        parts.append(f"{fmt(p)} pts date-push risk (CI {fmt(plo)} to {fmt(phi)})")
    return " and ".join(parts) + f", measured on {n} projects"


def round_half(x):
    """Round half away from zero (2.5 -> 3, -0.5 -> -1), as the page does."""
    return int(np.sign(x) * np.floor(abs(x) + 0.5))


def fmt(x):
    """'+3', '-2', '0'."""
    n = round_half(x)
    return "0" if n == 0 else f"{n:+d}"


def main(gold=GOLD):
    t0 = time.time()
    d = frame(gold)
    t = priors(d)
    t.to_parquet(gold / "hidden_delay_priors.parquet", index=False)
    with pd.option_context("display.width", 250, "display.max_colwidth", 60):
        print(t[["factor", "group", "n_rows", "n_projects", "extra_months", "extra_months_lo", "extra_months_hi",
                 "extra_push", "extra_push_lo", "extra_push_hi", "holm_months", "holm_push", "matched_share"]].round(3)
              .to_string(index=False))
    print(f"hidden_delay_priors: {len(t)} groups ({int(t['measurable'].sum())} measurable), {time.time() - t0:.1f}s")
    return t


if __name__ == "__main__":
    main()
