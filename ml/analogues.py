"""
Analogue projects and scenario curves for the project page (docs/IMPLEMENTATION_GUIDE_v2.md B 5.1).

Runs inside the score step:  python -m pipeline.run score

Inputs   gold/features.parquet, gold/labels_h4.parquet, silver/observations.parquet, silver/project_master.parquet,
         gold/predictions_latest.json (examples only)
Outputs  gold/analogues_<asof YYYY-MM>.parquet, gold/scenarios_<asof YYYY-MM>.parquet

Analogues: historical rows whose 4-quarter outcome is known by asof (t + 4q <= asof), compared on standardised
stage features; one row per other project (its closest), same sector when it has MIN_SECTOR candidate projects,
else all sectors. Scenarios: progress for the next STEPS quarters at the project's own velocity, at the sector
median velocity, and at the median velocity of the agency's projects at the same elapsed-ratio bin, all from
rows at or before asof and capped at 100.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest, score  # noqa: E402
from pipeline import gold  # noqa: E402
from pipeline.silver import months  # noqa: E402

GOLD, SILVER, PK = backtest.GOLD, backtest.SILVER, backtest.PK
STAGE = ["elapsed_ratio", "physical_progress_pct", "progress_velocity_4q", "cost_variation_pct", "log_cost"]
OUTCOMES = ["y_months", "y_cost_pct", "y_any", "y_date_push", "y_cost_rev"]
K, MIN_SECTOR, BIG_SLIP = 10, 30, 12
STEPS, MIN_ROWS, RECENT_Q = 8, 10, 4


def pool(feats, lab4, asof):
    """Candidate rows: h=4 outcome known and realised by asof, all stage features present. Returns the rows and
    their standardised stage matrix; features are clipped to the pool's 1-99th percentiles first (cost variation
    runs to 1,900%), and the clip bounds and scale go with them for the queries."""
    d = lab4.loc[(lab4.target_period <= asof) & lab4.y_any.notna(), PK + ["target_period"] + OUTCOMES]
    d = d.merge(feats[PK + ["sector"] + STAGE], on=PK).dropna(subset=STAGE).reset_index(drop=True)
    d["_code"] = pd.factorize(d.project_key)[0]
    lo, hi = d[STAGE].quantile(0.01), d[STAGE].quantile(0.99)
    x = d[STAGE].clip(lo, hi, axis=1)
    scale = {"lo": lo, "hi": hi, "mu": x.mean(), "sd": x.std()}
    return d, ((x - scale["mu"]) / scale["sd"]).to_numpy(), scale


def standardise(rows, scale):
    return ((rows[STAGE].clip(scale["lo"], scale["hi"], axis=1) - scale["mu"]) / scale["sd"]).to_numpy(float)


def nearest(qz, key, sector, cands, Z, k=K):
    """The k closest other projects to one standardised query: RMS distance over the stage features the query has,
    each project represented by its closest row. Returns (row positions in cands, distances, basis)."""
    code = cands["_code"].to_numpy()
    ok = cands.project_key.to_numpy() != key
    same = ok & (cands.sector.to_numpy() == sector)
    basis = "sector" if len(np.unique(code[same])) >= MIN_SECTOR else "all"
    have = ~np.isnan(qz)
    if not have.any():
        return np.array([], int), np.array([]), basis
    idx = np.flatnonzero(same if basis == "sector" else ok)
    dist = np.sqrt(((Z[idx][:, have] - qz[have]) ** 2).mean(axis=1))
    order = np.argsort(dist, kind="stable")
    _, first = np.unique(code[idx[order]], return_index=True)
    pick = order[np.sort(first)][:k]
    return idx[pick], dist[pick], basis


def as_rows(cands, pos, dist, basis):
    """nearest() output as analogue rows with rank 1..k."""
    return cands.iloc[pos].drop(columns="_code").assign(distance=dist, rank=np.arange(1, len(pos) + 1), basis=basis)


def summary(rows):
    return f"{int((rows.y_months >= BIG_SLIP).sum())} of {len(rows)} experienced a schedule revision of " \
           f"{BIG_SLIP}+ months"


def context(asof=None):
    """Everything analogues() and scenarios() read, loaded once."""
    feats = pd.read_parquet(GOLD / "features.parquet")
    asof = pd.Timestamp(asof) if asof else feats.period.max()
    obs = pd.read_parquet(SILVER / "observations.parquet")
    cands, Z, scale = pool(feats, pd.read_parquet(GOLD / "labels_h4.parquet"), asof)
    return {"asof": asof, "feats": feats[feats.period <= asof], "obs": obs, "cands": cands, "Z": Z, "scale": scale,
            "span": spans(obs, asof)}


def spans(obs, asof):
    """Planned duration in months (scheduled completion - sanction, last printed values) per key at asof."""
    b = gold.base(obs, asof)
    b = b[b.period == asof]
    return pd.Series((months(b.scheduled_completion) - months(b.sanction_date)).to_numpy(), index=b.project_key)


def latest_row(ctx, project_key):
    f = ctx["feats"]
    return f[f.project_key == project_key].tail(1)


def analogues(project_key, k=K, ctx=None):
    """The k nearest historical analogues of a project at asof with their outcome by t + 4q, and the summary."""
    ctx = ctx or context()
    q = latest_row(ctx, project_key)
    rows = as_rows(ctx["cands"], *nearest(standardise(q, ctx["scale"])[0], project_key, q.sector.iloc[0],
                                          ctx["cands"], ctx["Z"], k))
    return rows, summary(rows)


def velocity(d):
    return d.progress_velocity_4q.fillna(d.progress_velocity_2q)


def scenario_table(cur, ctx):
    """Long table (project_key, step, quarter, continue, recover, agency, agency_basis) for the rows of cur."""
    asof, hist = ctx["asof"], ctx["feats"]
    hist = hist[~hist.is_completed.astype(bool)].assign(v=velocity, bin=lambda x: stage_bin(x.elapsed_ratio))
    hist = hist[hist.v.notna()]
    recent = hist[gold.qindex(hist.period) > gold.qindex(pd.Series([asof]))[0] - RECENT_Q]
    sector_v = recent.groupby("sector").v.median()
    span = ctx["span"].reindex(cur.project_key).to_numpy()
    span = np.where(span > 0, span, np.nan)[:, None]

    steps = np.arange(1, STEPS + 1)
    p0 = cur.physical_progress_pct.to_numpy()[:, None]
    v_now = velocity(cur).clip(lower=0).to_numpy()[:, None]
    v_sec = cur.sector.map(sector_v).fillna(recent.v.median()).clip(lower=0).to_numpy()[:, None]
    elapsed = (cur.elapsed_ratio.to_numpy()[:, None] + 3 * steps / span).clip(0, 3)     # 3 months per step
    long = pd.DataFrame({"project_key": np.repeat(cur.project_key.to_numpy(), STEPS), "step": np.tile(steps, len(cur)),
                         "agency": np.repeat(cur.agency.to_numpy(), STEPS),
                         "sector": np.repeat(cur.sector.to_numpy(), STEPS), "bin": stage_bin(elapsed.ravel())})
    v_ag, basis = pd.Series(np.nan, index=long.index), pd.Series(None, index=long.index, dtype="str")
    for level in ["agency", "sector"]:          # agency at that stage, else sector at that stage, else all
        t = hist.groupby([level, "bin"]).v.agg(["median", "size"])
        t = t[t["size"] >= MIN_ROWS]["median"].rename("m").reset_index()
        m = long[[level, "bin"]].merge(t, on=[level, "bin"], how="left")["m"]
        fill = v_ag.isna() & m.notna()
        v_ag[fill], basis[fill] = m[fill], level
    m = long[["bin"]].merge(hist.groupby("bin").v.median().rename("m").reset_index(), on="bin", how="left")["m"]
    fill = v_ag.isna()
    v_ag[fill], basis[fill] = m[fill], "all"
    v_ag = v_ag.clip(lower=0).to_numpy().reshape(len(cur), STEPS)

    quarter = pd.DatetimeIndex([asof + pd.DateOffset(months=3 * s) for s in steps]).as_unit("us")
    out = long[["project_key", "step"]].assign(
        quarter=np.tile(quarter.to_numpy(), len(cur)),
        **{"continue": np.minimum(p0 + v_now * steps, 100).ravel(),
           "recover": np.minimum(p0 + v_sec * steps, 100).ravel(),
           "agency": np.minimum(p0 + v_ag.cumsum(axis=1), 100).ravel()}, agency_basis=basis)
    return out[np.repeat(~np.isnan(p0[:, 0]), STEPS)].reset_index(drop=True)


def stage_bin(elapsed):
    """Elapsed-ratio bin (the gold S-curve bins); -1 when the ratio is unknown."""
    return pd.cut(pd.Series(np.asarray(elapsed, float)), gold.SCURVE_BINS, right=False, labels=False) \
        .fillna(-1).astype("int64").to_numpy()


def scenarios(project_key, ctx=None):
    """Three progress curves for the next STEPS quarters as [{quarter, continue, recover, agency}]."""
    ctx = ctx or context()
    t = scenario_table(latest_row(ctx, project_key), ctx)
    t["quarter"] = t.quarter.dt.date.astype(str)
    return t[["quarter", "continue", "recover", "agency"]].round(2).to_dict("records")


def main(asof=None):
    t0 = time.time()
    ctx = context(asof)
    asof = ctx["asof"]
    master = pd.read_parquet(SILVER / "project_master.parquet")
    keys = score.current(ctx["feats"], ctx["obs"], master, asof).project_key
    f = ctx["feats"]
    cur = f[(f.period == asof) & f.project_key.isin(keys)].sort_values("project_key", ignore_index=True)
    Q = standardise(cur, ctx["scale"])
    hits = [nearest(q, key, sec, ctx["cands"], ctx["Z"]) for q, key, sec in zip(Q, cur.project_key, cur.sector)]
    n = [len(h[0]) for h in hits]
    a = ctx["cands"].iloc[np.concatenate([h[0] for h in hits])].drop(columns="_code").reset_index(drop=True)
    a = a.rename(columns={"project_key": "analogue_key", "period": "analogue_period"}).assign(
        project_key=np.repeat(cur.project_key.to_numpy(), n), distance=np.concatenate([h[1] for h in hits]),
        rank=np.concatenate([np.arange(1, m + 1) for m in n]), basis=np.repeat([h[2] for h in hits], n))
    names = master.set_index("project_key").project_name
    a = a.assign(analogue_name=a.analogue_key.map(names), asof=asof)[
        ["project_key", "asof", "rank", "analogue_key", "analogue_name", "analogue_period", "target_period", "sector",
         "basis", "distance"] + OUTCOMES]
    a.to_parquet(GOLD / f"analogues_{asof:%Y-%m}.parquet", index=False)
    s = scenario_table(cur, ctx).assign(asof=asof)
    s.to_parquet(GOLD / f"scenarios_{asof:%Y-%m}.parquet", index=False)

    print(f"analogues: {a.project_key.nunique()} projects x up to {K} ({len(a)} rows, "
          f"{(a.drop_duplicates('project_key').basis == 'sector').mean():.0%} same-sector); "
          f"scenarios: {s.project_key.nunique()} projects x {STEPS} quarters "
          f"(agency curve basis: {s.agency_basis.value_counts(normalize=True).round(2).to_dict()})")
    pointer = json.loads((GOLD / "predictions_latest.json").read_text(encoding="utf-8"))
    top = pd.read_parquet(backtest.ROOT / pointer["path"]).nlargest(3, "p_any_2q")
    for key, name in zip(top.project_key, top.project_name):
        r = a[a.project_key == key]
        print(f"  {key} {name[:60]}: {summary(r)}; median cost change {r.y_cost_pct.median():.1f}%, "
              f"{int(r.y_any.sum())} of {len(r)} slipped on schedule or cost")
        sc = s[s.project_key == key]
        print(f"    progress in {STEPS}q: continue {sc['continue'].iloc[-1]:.0f}, recover {sc.recover.iloc[-1]:.0f}, "
              f"agency {sc.agency.iloc[-1]:.0f} ({sc.agency_basis.iloc[0]})")
    print(f"analogues + scenarios: {time.time() - t0:.1f}s")
    return a, s


if __name__ == "__main__":
    main()
