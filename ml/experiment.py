"""
Paired champion-vs-challenger experiments (docs/MODEL_UPGRADES_2026-09.md).

Run from repo root after the gold build:  python -m ml.experiment <candidate> [--seeds 0,1,2] [--targets y_any_h2]
                                          python -m ml.experiment --list | --table

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, silver/coverage.parquet,
         silver/observations.parquet (candidates that build features), model/registry.json (the champions)
Outputs  model/experiments/<candidate>.csv (one row per target and block), temp/experiment_cache/ (champion
         predictions per gold version, target, cutoffs, columns, params and seed; safe to delete)

The champion of each target is its registry entry (feature list, categoricals and LightGBM params). A challenger
changes one thing against it: extra columns joined on (project_key, period), which must be point-in-time (checked
below), a different fit function (which may weight the training rows) or other columns. Both are backtested with
backtest.backtest on the same rows and cutoffs, the validation and flash blocks of backtest.windows, once per seed
in SEEDS (LightGBM random_state), so every comparison is paired. A block's PR-AUC delta is the mean over seeds of the
pooled PR-AUC differences. Its CI is a paired project bootstrap: BOOT resamples of the block's projects with
replacement (a project is drawn with all its fold rows), both models' seed-mean PR-AUC recomputed on each resample.
The decision is registry.rule, the promotion rule: gain >= 0 on both blocks, >= NOISE_SDS x SEED_SD on at least one,
validation ECE at most the champion's + ECE_SLACK. The scores are raw: the cost revision's served Platt calibrator is
left out here, the train run's registry gate compares the calibrated ones.

Point-in-time check: a candidate's extra columns at a cutoff c must be the same when built from the observations
cut at c (CHECK_AT), else the run stops before any fit.
"""
import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest as bt, registry  # noqa: E402
from pipeline import gold  # noqa: E402

PK = bt.PK
OUT = bt.ROOT / "model" / "experiments"
CACHE = bt.ROOT / "temp" / "experiment_cache"
SEEDS = (0, 1, 2)
BOOT = 2000
CHUNK = 100                     # bootstrap resamples per vectorised batch
BLOCKS = {"val": "validation", "flash": "flash"}     # registry block name -> backtest.windows key
CHECK_AT = ("2023-07-01", "2025-10-01")


# ---------------------------------------------------------------------------------------------------- statistics

def ap_weighted(y, p, W):
    """Average precision of scores p for 0/1 labels y under each row of weights W (resamples x rows): sklearn's
    average_precision_score with sample_weight, tied scores grouped as one threshold."""
    y, p, W = np.asarray(y, float), np.asarray(p, float), np.atleast_2d(np.asarray(W, float))
    o = np.argsort(-p, kind="mergesort")
    y, p, W = y[o], p[o], W[:, o]
    last = np.r_[np.flatnonzero(np.diff(p)), len(p) - 1]       # last row of each tied score group
    tp = np.cumsum(W * y, axis=1)[:, last]
    fp = np.cumsum(W * (1 - y), axis=1)[:, last]
    with np.errstate(invalid="ignore", divide="ignore"):
        prec = np.where(tp + fp > 0, tp / (tp + fp), 0.0)
        rec = tp / tp[:, -1:]
    return (np.diff(rec, axis=1, prepend=0) * prec).sum(axis=1)


def paired_bootstrap(y, groups, champ, chall, n_boot=BOOT, seed=0):
    """Resampled seed-mean PR-AUC deltas (challenger minus champion). y and groups (the project of each row) are
    shared; champ and chall are lists of score arrays, one per seed, on the same rows. Projects are drawn with
    replacement, each with all its rows."""
    codes, uniq = pd.factorize(pd.Series(groups))
    rng = np.random.default_rng(seed)
    out = []
    for start in range(0, n_boot, CHUNK):
        b = min(CHUNK, n_boot - start)
        counts = rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)), size=b)
        W = counts[:, codes]
        mean = lambda ps: np.mean([ap_weighted(y, p, W) for p in ps], axis=0)
        out.append(mean(chall) - mean(champ))
    return np.concatenate(out)


def ci(deltas, level=0.95):
    a = (1 - level) / 2
    return float(np.quantile(deltas, a)), float(np.quantile(deltas, 1 - a))


# ---------------------------------------------------------------------------------------------------- candidates

class Ctx:
    """What a candidate may read: gold features and labels, the silver observations and gold.base() of them. With
    a cutoff everything is cut at it (the point-in-time check)."""
    _obs = None

    def __init__(self, feats, labels, manifest, cutoff=None):
        self.cutoff = None if cutoff is None else pd.Timestamp(cutoff)
        self.feats = feats if cutoff is None else feats[feats.period <= self.cutoff]
        self.labels, self.manifest = labels, manifest

    @cached_property
    def obs(self):
        if Ctx._obs is None:
            Ctx._obs = pd.read_parquet(bt.SILVER / "observations.parquet")
        o = Ctx._obs
        return o if self.cutoff is None else o[o.period <= self.cutoff]

    @cached_property
    def base(self):
        return gold.base(self.obs)


@dataclass
class Candidate:
    """A challenger. extra(ctx) -> frame of PK + new columns; cols(champion cols, key) -> the challenger's columns
    (default: the champion's plus every extra column); fit(seed, ctx, y, h, params) -> a backtest fit function
    (default LightGBM with the champion's params at that seed); targets: the target keys it runs on (default all)."""
    about: str
    extra: Callable | None = None
    cols: Callable | None = None
    fit: Callable | None = None
    cats: list = field(default_factory=list)
    targets: tuple | None = None


def lgbm(params, weight=None):
    """backtest.fit_lgbm with the given params; weight(tr) -> optional sample weights of the training rows."""
    def fit(tr, cols, cats, y):
        m = lgb.LGBMClassifier(**params).fit(bt.lgb_X(tr, cols, cats), tr[y],
                                             sample_weight=None if weight is None else weight(tr))
        return m, lambda d: m.predict_proba(bt.lgb_X(d, cols, cats))[:, 1]
    return fit


CANDIDATES = {
    "null": Candidate("the champion against itself (harness sanity: every delta is 0)"),
}


# ---------------------------------------------------------------------------------------------------- the run

def champion(reg, key, man):
    """(feature list, categoricals, params) of the target's registry champion, else the manifest's full feature set
    with LGB_PARAMS."""
    e = next((r for r in reg["runs"] if r["entry_id"] == reg["champions"].get(key, {}).get("entry_id")), None)
    if e is None or e["model"] != "lightgbm":
        cols = [f for _, gs in bt.ABLATION[-1:] for g in gs for f in man["features"][g]]
        return cols, man["categorical"], dict(bt.LGB_PARAMS)
    return e["feature_list"], e["categorical"], {**bt.LGB_PARAMS, **e["params"]}


def cached(tag, make):
    """Predictions frame from the cache file of tag, else make() written there."""
    path = CACHE / f"{hashlib.sha256(tag.encode()).hexdigest()[:20]}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    p = make()
    CACHE.mkdir(parents=True, exist_ok=True)
    p.to_parquet(path, index=False)
    return p


def frames_equal(a, b):
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=False, check_categorical=False)
        return True
    except AssertionError:
        return False


def check_point_in_time(cand, feats, labels, man, at=CHECK_AT):
    """Extra columns at each cutoff built from the full data vs from data cut at it; raises on a difference."""
    if cand.extra is None:
        return {}
    full = cand.extra(Ctx(feats, labels, man)).set_index(PK).sort_index()
    out = {}
    for c in pd.to_datetime(list(at)):
        a = full[full.index.get_level_values("period") == c]
        b = cand.extra(Ctx(feats, labels, man, cutoff=c)).set_index(PK).sort_index()
        b = b[b.index.get_level_values("period") == c]
        out[str(c.date())] = {"rows": len(a), "identical": frames_equal(a, b)}
    bad = [c for c, v in out.items() if not v["identical"]]
    assert not bad, f"candidate columns change when the data are cut at {bad}"
    return out


def block_metrics(p, h):
    """Pooled metrics of one model's predictions on a block (folds recomputed from the rows)."""
    folds = pd.DataFrame([{"cutoff": c, "model": "m", **bt.score(g.y, g.p)} for c, g in p.groupby("cutoff")])
    return bt.pooled(p.assign(model="m"), folds, h).iloc[0]


def run(name, cand=None, seeds=SEEDS, targets=None, n_boot=BOOT, out=OUT, use_cache=True):
    """Backtest the champion and the challenger on both blocks of every target; returns the result table."""
    cand = cand or CANDIDATES[name]
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    reg = registry.load()
    pit = check_point_in_time(cand, feats, labels, man)
    # the challenger's frame: extra columns added, or replacing the champion's column of the same name
    extra = cand.extra(Ctx(feats, labels, man)) if cand.extra else None
    new_cols = [c for c in extra.columns if c not in PK] if extra is not None else []
    cfeats = feats if extra is None else feats.drop(columns=[c for c in new_cols if c in feats]).merge(
        extra, on=PK, how="left", validate="1:1")
    ctx = Ctx(cfeats, labels, man)
    keys = targets or cand.targets or [f"{y}_h{h}" for y, h in bt.TARGETS]
    rows = []
    for y, h in bt.TARGETS:
        key = f"{y}_h{h}"
        if key not in keys:
            continue
        t1 = time.time()
        cols, cats, params = champion(reg, key, man)
        ccols = cand.cols(cols, key) if cand.cols else cols + [c for c in new_cols if c not in cols]
        ccats = cats + [c for c in cand.cats if c not in cats]
        d, dc = bt.frame(feats, labels[h], y, h), bt.frame(cfeats, labels[h], y, h)
        assert d[PK].equals(dc[PK])
        w = bt.windows(cov, d, y, h)
        blocks = {b: pd.to_datetime(w[k]) for b, k in BLOCKS.items() if w[k]}
        cutoffs = pd.DatetimeIndex(sorted(set().union(*[set(c) for c in blocks.values()])))
        champ, chall = [], []
        for s in seeds:
            ps = {**params, "random_state": s}
            tag = json.dumps([man["gold_version"], key, [str(c.date()) for c in cutoffs], cols, cats, ps],
                             sort_keys=True)
            make = lambda: bt.backtest(d, y, cutoffs, {"m": (lgbm(ps), cols, cats)})[0]
            champ.append(cached(tag, make) if use_cache else make())
            fit = cand.fit(s, ctx, y, h, ps) if cand.fit else lgbm(ps)
            chall.append(bt.backtest(dc, y, cutoffs, {"m": (fit, ccols, ccats)})[0])
            assert (champ[-1][["cutoff", "project_key"]].values == chall[-1][["cutoff", "project_key"]].values).all()
        res = {}
        for b, cs in blocks.items():
            sel = [p[p.cutoff.isin(cs)].reset_index(drop=True) for p in champ + chall]
            a, c = sel[:len(seeds)], sel[len(seeds):]
            ma, mc = [block_metrics(p, h) for p in a], [block_metrics(p, h) for p in c]
            mean = lambda ms, k: float(np.mean([m[k] for m in ms]))
            deltas = [x.pr_auc - z.pr_auc for x, z in zip(mc, ma)]
            boot = paired_bootstrap(a[0].y.to_numpy(), a[0].project_key.to_numpy(), [p.p.to_numpy() for p in a],
                                    [p.p.to_numpy() for p in c], n_boot=n_boot)
            lo, hi = ci(boot)
            res[b] = {"candidate": name, "target": key, "block": b, "n_rows": len(a[0]),
                      "n_projects": a[0].project_key.nunique(), "n_folds": len(cs), "seeds": len(seeds),
                      "champion_pr_auc": mean(ma, "pr_auc"), "challenger_pr_auc": mean(mc, "pr_auc"),
                      "delta_pr_auc": float(np.mean(deltas)), "ci_lo": lo, "ci_hi": hi,
                      "boot_share_le_0": float((boot <= 0).mean()),
                      "seed_deltas": "/".join(f"{x:+.4f}" for x in deltas),
                      "champion_seed_sd": float(np.std([m.pr_auc for m in ma], ddof=1)) if len(seeds) > 1 else np.nan,
                      "challenger_seed_sd": float(np.std([m.pr_auc for m in mc], ddof=1)) if len(seeds) > 1 else np.nan,
                      **{f"{who}_{k}": mean(ms, k) for k in ["ece", "precision_50", "nyd_pr_auc", "brier", "roc_auc"]
                         for who, ms in (("champion", ma), ("challenger", mc))}}
        margin = registry.NOISE_SDS * registry.SEED_SD.get(key, 0.0)
        gains = {b: r["delta_pr_auc"] for b, r in res.items()}
        ok, why = registry.rule(gains, margin, res["val"]["challenger_ece"], res["val"]["champion_ece"])
        for r in res.values():
            rows.append({**r, "margin": margin, "decision": "pass" if ok else "fail", "reason": why,
                         "n_features": len(ccols), "runtime_s": round(time.time() - t1, 1)})
        print(f"  {key}: {'PASS' if ok else 'fail'}  " + "  ".join(
            f"{b} {r['champion_pr_auc']:.4f} -> {r['challenger_pr_auc']:.4f} ({r['delta_pr_auc']:+.4f} "
            f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}])" for b, r in res.items())
              + f"  val ECE {res['val']['champion_ece']:.4f} -> {res['val']['challenger_ece']:.4f}"
              + f"  {time.time() - t1:.0f}s", flush=True)
    table = pd.DataFrame(rows)
    table["point_in_time"] = json.dumps(pit)
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / f"{name}.csv", index=False)
    print(f"experiment {name}: {out / f'{name}.csv'}, {time.time() - t0:.0f}s")
    return table


def summary_table(out=OUT, names=None):
    """Markdown table of every experiment CSV (or the named ones), one row per candidate and target."""
    lines = ["| Candidate | Target | Val PR-AUC | Flash PR-AUC | Val delta [95% CI] | Flash delta [95% CI] | "
             "Flash P@50 | Val ECE | Decision |", "|---|---|---|---|---|---|---|---|---|"]
    for path in sorted(out.glob("*.csv")):
        if names and path.stem not in names:
            continue
        t = pd.read_csv(path)
        for key, g in t.groupby("target", sort=False):
            b = g.set_index("block")
            v, f = b.loc["val"], b.loc["flash"] if "flash" in b.index else None
            fmt = lambda r: f"{r.delta_pr_auc:+.4f} [{r.ci_lo:+.4f}, {r.ci_hi:+.4f}]"
            lines.append(
                f"| {path.stem} | {key} | {v.champion_pr_auc:.4f} -> {v.challenger_pr_auc:.4f} | "
                + (f"{f.champion_pr_auc:.4f} -> {f.challenger_pr_auc:.4f} | " if f is not None else "- | ")
                + f"{fmt(v)} | " + (f"{fmt(f)} | " if f is not None else "- | ")
                + (f"{f.champion_precision_50:.3f} -> {f.challenger_precision_50:.3f} | " if f is not None else "- | ")
                + f"{v.champion_ece:.4f} -> {v.challenger_ece:.4f} | {v.decision} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ml.experiment")
    ap.add_argument("candidate", nargs="?")
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--targets", default=None, help="comma-separated target keys, e.g. y_any_h2")
    ap.add_argument("--boot", type=int, default=BOOT)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        print("\n".join(f"{n:24s} {c.about}" for n, c in CANDIDATES.items()))
    elif a.table:
        print(summary_table())
    elif a.candidate:
        run(a.candidate, seeds=tuple(int(s) for s in a.seeds.split(",")),
            targets=a.targets.split(",") if a.targets else None, n_boot=a.boot, use_cache=not a.no_cache)
    else:
        ap.error("name a candidate, or --list / --table")


if __name__ == "__main__":
    main()
