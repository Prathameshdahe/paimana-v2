"""
Paired champion-vs-challenger experiments (docs/MODEL_UPGRADES_2026-09.md).

Run from repo root after the gold build:  python -m ml.experiment <candidate> [--seeds 0,1,2] [--targets y_any_h2]
                                                                     [--champion-run ML-20260927-222602]
                                          python -m ml.experiment --list | --table
                                          python -m ml.experiment --seed-sd [--champion-run RUN]
                                          python -m ml.experiment --tune y_any_h2 [--trials 20] [--no-es]
                                          python -m ml.experiment g_intervals | g2_intervals_asym | k1_isotonic |
                                                                  h1_hurdle          (SPECIAL: no ranking target)

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, silver/coverage.parquet,
         silver/observations.parquet (candidates that build features), model/registry.json (the champions)
Outputs  model/experiments/<candidate>.csv (one row per target and block), tune_<target>[_trees].csv, seed_sd.csv,
         temp/experiment_cache/ (champion predictions per gold version, target, cutoffs, columns, params and seed, and
         the code that makes them: ml/backtest.py and the LightGBM version; safe to delete)

The champion of each target is its registry entry (feature list, categoricals and LightGBM params), or with
--champion-run that run's LightGBM entry of the target (the champions a round started from, so a result stays
reproducible after a promotion); the CSV's champion_entry column names it. A challenger
changes one thing against it: extra columns joined on (project_key, period), which must be point-in-time (checked
below), a different fit function (which may weight the training rows) or other columns. Both are backtested with
backtest.backtest on the same rows and cutoffs, the validation and flash blocks of backtest.windows, once per seed
in SEEDS (LightGBM random_state), so every comparison is paired. The decision metric is the within-cutoff PR-AUC
(registry.GAIN): each fold's own PR-AUC, averaged over the block's folds, because a served score is only ranked
against the projects of its own as-of date. Pooled PR-AUC (all fold rows together) is reported beside it: it also
rewards a score level that follows each fold's base rate, which is calibration, not ranking, and on y_any_h4 it showed
a gain where the ranking got worse on 4 of 6 folds. A block's delta is the mean over seeds of the differences; the
fold_deltas column has each fold's. Its CI is a paired project bootstrap: BOOT resamples of the block's projects with
replacement (a project is drawn with all its fold rows), both models' seed-mean fold-mean PR-AUC recomputed on each
resample (pooled_ci_* the same for pooled PR-AUC). The decision is registry.rule, the promotion rule: gain >= 0 on
both blocks, >= NOISE_SDS x SEED_SD of that block on at least one (registry.margins; --seed-sd measures the SDs:
the champion's within-cutoff PR-AUC over SD_SEEDS seeds, per block, since a one-fold block is noisier than six),
validation ECE at most the champion's + ECE_SLACK. The scores are
raw: the cost revision's served Platt calibrator is left out here, the train run's registry gate compares the
calibrated ones (Platt is monotone within a cutoff, so the within-cutoff PR-AUC is the same up to ties).

Point-in-time check: a candidate's extra columns at a cutoff c must be the same when built from the observations
cut at c (CHECK_AT), else the run stops before any fit.

Shipping guard (robust, the CSV's ship column): on top of the rule, some block that clears the margin must also have
its bootstrap CI above 0. The catalogue (CANDIDATES, letters as in docs/MODEL_UPGRADES_2026-09.md) keeps every
candidate measured in September 2026, kept or not, so each result can be re-run.
"""
import argparse
import functools
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
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest as bt, registry, survival  # noqa: E402
from pipeline import gold  # noqa: E402
from pipeline.silver import months  # noqa: E402

PK = bt.PK
OUT = bt.ROOT / "model" / "experiments"
CACHE = bt.ROOT / "temp" / "experiment_cache"
SEEDS = (0, 1, 2)
SD_SEEDS = (0, 1, 2, 3, 4)      # seed_sd: the seeds the noise margins are measured over
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


def paired_bootstrap(y, groups, champ, chall, n_boot=BOOT, seed=0, folds=None):
    """Resampled seed-mean PR-AUC deltas (challenger minus champion). y and groups (the project of each row) are
    shared; champ and chall are lists of score arrays, one per seed, on the same rows. Projects are drawn with
    replacement, each with all its rows. With folds (the cutoff of each row) the PR-AUC is the within-cutoff one,
    each fold's own averaged over the folds (a fold left with no positive in a resample is skipped); without, it is
    pooled over all rows."""
    y = np.asarray(y, float)
    codes, uniq = pd.factorize(pd.Series(groups))
    f = pd.Series(np.zeros(len(y)) if folds is None else folds)
    parts = [np.flatnonzero(f.eq(v).to_numpy()) for v in f.unique()]
    rng = np.random.default_rng(seed)
    out = []
    for start in range(0, n_boot, CHUNK):
        b = min(CHUNK, n_boot - start)
        counts = rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)), size=b)
        W = counts[:, codes]
        ap = lambda p: np.nanmean([ap_weighted(y[i], np.asarray(p)[i], W[:, i]) for i in parts], axis=0)
        mean = lambda ps: np.mean([ap(p) for p in ps], axis=0)
        out.append(mean(chall) - mean(champ))
    return np.concatenate(out)


def robust(ok, blocks):
    """The shipping guard on top of the promotion rule (ok): some block that clears its margin also has its paired
    bootstrap CI above 0. With a dozen candidates on four targets, and blocks as small as one fold (y_any_h4 flash,
    335 rows), a pass inside the CI is too often luck. blocks: dicts with delta_fold_pr_auc (the within-cutoff gain),
    margin (the block's noise margin) and ci_lo (the gain's CI)."""
    return bool(ok and any(b["delta_fold_pr_auc"] >= b["margin"] and b["ci_lo"] > 0 for b in blocks))


def ci(deltas, level=0.95):
    a = (1 - level) / 2
    return float(np.quantile(deltas, a)), float(np.quantile(deltas, 1 - a))


# ---------------------------------------------------------------------------------------------------- candidates

class Ctx:
    """What a candidate may read: gold features and labels, the silver observations and gold.base() of them. With
    a cutoff everything is cut at it (the point-in-time check): features and observations at periods <= cutoff,
    labels whose outcome quarter target_period is <= cutoff (known by then)."""
    _obs = None

    def __init__(self, feats, labels, manifest, cutoff=None):
        self.cutoff = None if cutoff is None else pd.Timestamp(cutoff)
        self.feats = feats if cutoff is None else feats[feats.period <= self.cutoff]
        self.labels = labels if cutoff is None else {h: lab[lab.target_period <= self.cutoff]
                                                     for h, lab in labels.items()}
        self.manifest = manifest

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
    return functools.partial(bt.fit_lgbm, params=params, weight=weight)


def feasibility(ctx):
    """(a) Deadline feasibility, row-local: the progress (and spend) pace in pp per quarter needed to finish by the
    anticipated date against the recent pace, the months late the project finishes at its 4-quarter velocity, and
    whether the date falls inside 2 or 4 quarters. Velocities are floored at STAGNANT_PP and ratios capped at 100."""
    f = ctx.feats
    left = f.months_to_anticipated_completion
    q_left = (left / 3).clip(lower=1 / 3)                  # overdue: the remaining work is due within a month
    v = f.progress_velocity_4q.fillna(f.progress_velocity_2q)
    floor = gold.STAGNANT_PP
    todo = (100 - f.physical_progress_pct).clip(lower=0)
    need, need_spend = todo / q_left, ((1 - f.expenditure_ratio) * 100).clip(lower=0) / q_left
    return f[PK].assign(
        required_pace_pq=need, pace_ratio=(need / v.clip(lower=floor)).clip(upper=100), pace_gap_pq=need - v,
        required_spend_pace_pq=need_spend,
        spend_pace_ratio=(need_spend / f.spend_velocity_2q.clip(lower=floor)).clip(upper=100),
        projected_overrun_months=(todo / v.clip(lower=floor) * 3 - left).clip(-120, 240),
        deadline_in_2q=(left <= 6).astype("float64").where(left.notna()),
        deadline_in_4q=(left <= 12).astype("float64").where(left.notna()))


def revision_events(b):
    """Cost and date revision events of gold.base() rows, masked as build_labels masks a label: a step up counts only
    when the previous printed value has the same basis (cost_basis, completion_basis). Returns (cost event, date
    event, months pushed at a date event)."""
    key = b.project_key
    cost, ac = b.anticipated_cost_cr, months(b.anticipated_completion)
    prev = lambda s: s.groupby(key).ffill().groupby(key).shift()
    cb, tb = b.cost_basis.where(cost.notna()), b.completion_basis.where(ac.notna())
    cost_ev = (cost >= gold.COST_STEP * prev(cost)) & cb.eq(prev(cb))
    date_ev = (ac >= prev(ac) + gold.DATE_STEP) & tb.eq(prev(tb))
    return cost_ev, date_ev, (ac - prev(ac)).where(date_ev)


BASIS_FIXED = ("revisions_so_far", "months_since_last_revision")


def basis_fixed(b):
    """revisions_so_far and months_since_last_revision (gold.base) from the basis-masked events."""
    cost_ev, date_ev, _ = revision_events(b)
    key, now = b.project_key, months(b.period)
    event = cost_ev | date_ev
    since = now.where(event).groupby(key).ffill()
    return b[PK].assign(revisions_so_far=event.groupby(key).cumsum().astype("float64"),
                        months_since_last_revision=(now - since.fillna(now.groupby(key).transform("first")))
                        .astype("float64"))


def events_in(b, ev, back):
    """Events per key in the last `back` quarters (q - back, q]."""
    cum = ev.astype("int64").groupby(b.project_key).cumsum()
    ref, _ = gold.lagged(b.assign(_cum=cum.astype("float64")), "_cum", back, 10 ** 6)
    return (cum - ref.fillna(0)).astype("float64")


def slip_history(ctx):
    """(b) The basis fix, then the key's slip history at t: change in slip_to_date over 2 and 4 quarters (against the
    latest printed value 2-3 or 4-5 quarters back, same completion basis only), months pushed at the last date event,
    date events in the last 4 and 8 quarters, and the key's own realised 2-quarter slip and cost-revision rates
    (labels with t0 + 2 <= t, as gold.agency_context counts them)."""
    b = ctx.base
    _, date_ev, push = revision_events(b)
    code = pd.Series(pd.factorize(b.completion_basis)[0], index=b.index).astype("float64")
    b = b.assign(_basis=code.where(b.slip_to_date_months.notna() & b.completion_basis.notna()))
    out = basis_fixed(b)
    for back in (2, 4):
        ref, _ = gold.lagged(b, "slip_to_date_months", back, 2)
        rb, _ = gold.lagged(b, "_basis", back, 2)
        out[f"slip_change_{back}q"] = (b.slip_to_date_months - ref).where(rb.eq(b._basis))
    out["last_push_months"] = push.groupby(b.project_key).ffill()
    out["pushes_4q"], out["pushes_8q"] = events_in(b, date_ev, 4), events_in(b, date_ev, 8)
    lab = gold.build_labels(ctx.obs, 2)
    lab = lab.assign(slip=lab.y_date_push.astype("float64"), cost=lab.y_cost_rev.astype("float64"))
    r = gold.realised(lab, b[PK], "project_key")
    out["own_slip_n"] = r.s_n.fillna(0).to_numpy()
    out["own_slip_rate"] = (r.s_sum / r.s_n.where(r.s_n > 0)).to_numpy()
    out["own_cost_rev_rate"] = (r.c_sum / r.c_n.where(r.c_n > 0)).to_numpy()
    return out


# (c) project-type keywords in the name printed at t; a name may match several
NAME_TYPES = {
    "doubling": r"doubl|\b(?:3rd|third|4th|fourth) line",
    "new_line": r"new (?:bg |broad gauge |mg |rail(?:way)? )?line",
    "gauge_conversion": r"gauge conversion|\bgc\b",
    "electrification": r"electrif",
    "lane_2": r"\b2[- ]?l(?:ane|aning)?\b|two[- ]?lan|paved shoulder",
    "lane_4": r"\b4[- ]?l(?:ane|aning)?\b|four[- ]?lan",
    "lane_6": r"\b[68][- ]?l(?:ane|aning)?\b|(?:six|eight)[- ]?lan",
    "upgrade": r"rehabilitation|up-?gradation|widening|strengthening",
    "bypass": r"by[- ]?pass",
    "bridge": r"bridge|\brob\b|\brub\b|flyover|viaduct",
    "tunnel": r"tunnel",
    "hydro": r"hydro|\bh\.?e\.?p\b",
    "thermal": r"thermal|\bs?tpp\b|\bstps\b",
    "transmission": r"transmission|\btransm\b|\bkv\b|sub[- ]?station|pooling|\bhvdc\b",
    "pipeline": r"pipe ?line",
    "mine_ug": r"underground|\bug\b",
    "mine_oc": r"open ?cast|\boc[mp]?\b",
    "airport": r"airport|terminal building|runway",
    "medical": r"aiims|medical|hospital",
    "metro": r"metro|\bm?rts\b|rapid rail",
    "port": r"\bport\b|berth|jetty|harbou?r|dredg",
    "expansion": r"expansion|augmentation",
}


def name_flags(ctx):
    """(c) One 0/1 column per NAME_TYPES keyword group, from the project name printed at t (row-local)."""
    o = ctx.obs[PK + ["project_name"]]
    name = o.project_name.fillna("").str.lower()
    return o[PK].assign(**{f"name_{k}": name.str.contains(p, regex=True).astype("float64")
                           for k, p in NAME_TYPES.items()})


def name_type(ctx):
    """(c) The first NAME_TYPES group the name matches, as one categorical (other when none)."""
    f = name_flags(ctx)
    hit = f[[f"name_{k}" for k in NAME_TYPES]].to_numpy() > 0
    first = np.where(hit.any(axis=1), np.array(list(NAME_TYPES), dtype=object)[hit.argmax(axis=1)], "other")
    return f[PK].assign(name_type=first)


def decay(half_life_q):
    """(d) Sample weight 0.5 ** (age / half_life_q), age = quarters from the row's t to the newest training t."""
    def weight(tr):
        q = bt.qindex(tr.period).to_numpy()
        return 0.5 ** ((q.max() - q) / half_life_q)
    return weight


def flash_weight(k):
    """(d) Sample weight k for flash-report rows, 1 for the rest."""
    return lambda tr: np.where(tr.period_type.astype(str).eq("flash"), float(k), 1.0)


def weighted(weight):
    return lambda seed, ctx, y, h, params: lgbm(params, weight)


def bagged(n):
    """(e) The mean of n LightGBM fits with seeds n * seed .. n * seed + n - 1 (disjoint sets per harness seed)."""
    def make(seed, ctx, y, h, params):
        fits = [lgbm({**params, "random_state": n * seed + i}) for i in range(n)]

        def fit(tr, cols, cats, yy):
            ms = [f(tr, cols, cats, yy) for f in fits]
            return [m for m, _ in ms], lambda d: np.mean([p(d) for _, p in ms], axis=0)
        return fit
    return make


# (m) monotone constraints: the features whose effect on the risk is known to go one way. LightGBM's constraints
# hold per tree, so the model cannot learn a fold-specific reversal; the plan's "stabler, more explainable, small
# accuracy cost". implied gap is not a gold feature (its stand-in, a_feasibility's projected_overrun_months, was
# measured and left out), so the constrained set is prior revisions, stall count, slip to date and cost growth.
MONOTONE = {"revisions_so_far": 1, "stagnation_quarters": 1, "slip_to_date_months": 1, "cost_variation_pct": 1}


def monotone(constraints=MONOTONE):
    """(m) LightGBM with monotone_constraints on the constrained columns present in the feature list."""
    def make(seed, ctx, y, h, params):
        def fit(tr, cols, cats, yy):
            mc = [constraints.get(c, 0) for c in cols]
            return lgbm({**params, "monotone_constraints": mc, "monotone_constraints_method": "advanced"})(
                tr, cols, cats, yy)
        return fit
    return make


_HAZARDS = {}


def survival_fit(seed, ctx, y, h, params):
    """(s) The discrete-time survival model (ml/survival.py): one hazard LightGBM over person-periods (t, k) with
    the champion's features plus k, P(event by h) from the cumulative hazard. Its person-periods are realised at
    t + k (t + k' for a filled zero), and each fold's model trains on those realised by the fold's cutoff, the
    same information as the champion's label rows. Fitted models are shared across the y_any horizons of one
    run (the same cutoff gives every horizon)."""
    key = (y, seed, id(ctx.feats))
    if key not in _HAZARDS:
        _HAZARDS[key] = survival.Hazard(ctx.feats, survival.labels(), y)
    return _HAZARDS[key].fit(h, params)


def cross_target(mode):
    """(f) y_any from the date and cost models trained on their own (larger) label sets, both cut at the fold's
    newest training outcome quarter: 'or' = 1 - (1 - p_date)(1 - p_cost), 'avg' = the mean of that and the direct
    y_any model."""
    def make(seed, ctx, y, h, params):
        frames = {t: bt.frame(ctx.feats, ctx.labels[h], t, h) for t in ("y_date_push", "y_cost_rev")}

        def fit(tr, cols, cats, yy):
            cut = tr.target_period.max()
            ms = {t: lgbm(params)(f[f.target_period <= cut], cols, cats, t) for t, f in frames.items()}
            direct = lgbm(params)(tr, cols, cats, yy)

            def predict(d):
                p_or = 1 - (1 - ms["y_date_push"][1](d)) * (1 - ms["y_cost_rev"][1](d))
                return p_or if mode == "or" else (p_or + direct[1](d)) / 2
            return ms, predict
        return fit
    return make


ES_ROUNDS, ES_MAX_TREES, ES_MIN_TREES = 50, 1500, 20


def inner_trees(tr, cols, cats, y, params, rounds=ES_ROUNDS):
    """(e) Tree count by early stopping (binary log loss, rounds without gain) on an inner time split of the training
    rows only: fitted on the rows whose outcome is known one quarter before the newest training t, stopped on the rows
    at the two newest training t; between ES_MIN_TREES and ES_MAX_TREES."""
    inner = tr.period.max() - pd.DateOffset(months=3)
    fi, va = tr[tr.target_period <= inner], tr[tr.period >= inner]
    ps = {k: v for k, v in params.items() if k != "half_life_q"}
    m = lgb.LGBMClassifier(**{**ps, "n_estimators": ES_MAX_TREES}).fit(
        bt.lgb_X(fi, cols, cats), fi[y], eval_set=[(bt.lgb_X(va, cols, cats), va[y])],
        callbacks=[lgb.early_stopping(rounds, verbose=False)])
    return max(int(m.best_iteration_ or ES_MAX_TREES), ES_MIN_TREES)


def early_stopped(params, weight=None):
    """(e) LightGBM refit on every training row with the inner_trees tree count."""
    def fit(tr, cols, cats, y):
        return lgbm({**params, "n_estimators": inner_trees(tr, cols, cats, y, params)}, weight)(tr, cols, cats, y)
    return fit


# (e) the search space of the tuning trials (tune); every trial sets its tree count by early stopping
TUNE_SPACE = {"learning_rate": [0.02, 0.03, 0.05, 0.08], "num_leaves": [7, 15, 31, 63],
              "min_child_samples": [20, 50, 100, 200, 400], "colsample_bytree": [0.4, 0.6, 0.8, 1.0],
              "subsample": [0.6, 0.8, 1.0], "reg_lambda": [0.0, 1.0, 5.0, 20.0], "reg_alpha": [0.0, 0.5, 2.0],
              "min_split_gain": [0.0, 0.02]}
TUNE_TREES = [150, 300, 600, 1000]     # the tree counts searched when early stopping is off
# tune("y_any_h2") picks, validation block only (model/experiments/tune_y_any_h2*.csv)
TUNED_ES = {"learning_rate": 0.02, "num_leaves": 7, "min_child_samples": 50, "colsample_bytree": 1.0,
            "subsample": 0.8, "reg_lambda": 20.0, "reg_alpha": 0.0, "min_split_gain": 0.0}
TUNED_TREES = {"learning_rate": 0.02, "num_leaves": 63, "min_child_samples": 20, "colsample_bytree": 0.8,
               "subsample": 0.8, "reg_lambda": 20.0, "reg_alpha": 0.0, "min_split_gain": 0.02, "n_estimators": 150}


def tune(key="y_any_h2", trials=24, seed=0, es=True, out=OUT):
    """(e) Random search over TUNE_SPACE for one target, scored on the VALIDATION block only (seed 0), so the flash
    block stays a holdout for the candidate run. With es the tree count of every trial comes from early_stopped,
    and trial 0 is the champion's params with early stopping; without it n_estimators is searched over TUNE_TREES.
    The best trial has the highest pooled validation PR-AUC among those whose ECE is at most the champion's +
    ECE_SLACK. Writes model/experiments/tune_<key>[_trees].csv and returns (table, best params)."""
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    y, h = next((y, h) for y, h in bt.TARGETS if f"{y}_h{h}" == key)
    cols, cats, params, _ = champion(registry.load(), key, man)
    d = bt.frame(feats, labels[h], y, h)
    val = pd.to_datetime(bt.windows(cov, d, y, h)["validation"])
    rng = np.random.default_rng(seed)
    base = block_metrics(cached(json.dumps([man["gold_version"], key, [str(c.date()) for c in val], cols, cats,
                                            {**params, "random_state": 0}], sort_keys=True),
                                lambda: bt.backtest(d, y, val, {"m": (lgbm({**params, "random_state": 0}), cols,
                                                                      cats)})[0]), h)
    rows = []
    for i in range(trials + 1):
        space = TUNE_SPACE if es else {**TUNE_SPACE, "n_estimators": TUNE_TREES}
        change = {} if i == 0 else {k: v[rng.integers(len(v))] for k, v in space.items()}
        change = {k: (v.item() if hasattr(v, "item") else v) for k, v in change.items()}
        ps = {**params, **change, "random_state": 0}
        t1 = time.time()
        trees = []

        def fit(tr, c, k, yy):
            m, p = (early_stopped(ps) if es else lgbm(ps))(tr, c, k, yy)
            trees.append(m.n_estimators)
            return m, p
        m = block_metrics(bt.backtest(d, y, val, {"m": (fit, cols, cats)})[0], h)
        rows.append({"trial": i, **change, "mean_trees": float(np.mean(trees)), "val_pr_auc": m.pr_auc,
                     "val_ece": m.ece, "val_precision_50": m.precision_50, "val_nyd_pr_auc": m.nyd_pr_auc,
                     "gain_vs_champion": m.pr_auc - base.pr_auc, "seconds": round(time.time() - t1, 1)})
        print(f"  trial {i}: {change} trees {np.mean(trees):.0f} val PR-AUC {m.pr_auc:.4f} "
              f"({m.pr_auc - base.pr_auc:+.4f}) ECE {m.ece:.4f}  {time.time() - t1:.0f}s", flush=True)
    t = pd.DataFrame(rows).assign(champion_val_pr_auc=base.pr_auc, champion_val_ece=base.ece)
    ok = t[t.val_ece <= base.ece + registry.ECE_SLACK]
    best = ok.loc[ok.val_pr_auc.idxmax()]
    t["selected"] = t.trial == best.trial
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / f"tune_{key}{'' if es else '_trees'}.csv", index=False)
    chosen = {k: best[k] for k in [*TUNE_SPACE, "n_estimators"] if k in best and pd.notna(best[k])}
    chosen = {k: (int(v) if k in ("num_leaves", "min_child_samples", "n_estimators") else float(v))
              for k, v in chosen.items()}
    print(f"tune {key}: best trial {int(best.trial)} {chosen} val PR-AUC {best.val_pr_auc:.4f} "
          f"(champion {base.pr_auc:.4f}), {time.time() - t0:.0f}s")
    return t, chosen


COVER = 0.90       # (g) the nominal coverage of the p05-p95 interval


def split_quantile(e, level):
    """The ceil((n + 1) level) / n empirical quantile of conformity scores e (0 when fewer than MIN_ROWS)."""
    e = np.asarray(e, float)
    if len(e) < bt.MIN_ROWS:
        return 0.0
    return float(np.quantile(e, min(1.0, np.ceil((len(e) + 1) * level) / len(e)), method="higher"))


def conformal_q(cal, level=COVER):
    """Conformalised quantile regression: the split quantile of max(p05 - y, y - p95) over calibration rows."""
    return split_quantile(np.maximum(cal.p05 - cal.y, cal.y - cal.p95), level)


def conformalise(p, pool, h, asym=False):
    """Each cutoff's p05 and p95 moved out (or in) by conformal_q of the pool rows at its calibration folds, whose
    labels are realised by the cutoff (backtest.calibration_folds); p50 is unchanged. asym: each tail on its own,
    p05 by the (1 + COVER) / 2 split quantile of p05 - y and p95 by that of y - p95, never across p50."""
    out = []
    for c, g in p.groupby("cutoff"):
        cal = pool[pool.cutoff.isin(bt.calibration_folds(c, h))]
        if asym:
            lo, hi = (split_quantile(e, (1 + COVER) / 2) for e in (cal.p05 - cal.y, cal.y - cal.p95))
        else:
            lo = hi = conformal_q(cal)
        out.append(g.assign(p05=np.minimum(g.p05 - lo, g.p50), p95=np.maximum(g.p95 + hi, g.p50),
                            conformal_q=(lo + hi) / 2))
    return pd.concat(out).loc[p.index]


def intervals(name="g_intervals", asym=False, out=OUT):
    """(g) Backtest of the score step's quantile intervals (months pushed and cost % by t + 2q) on the validation
    and flash blocks of their binary counterparts: coverage of p05-p95 (target COVER), pinball loss at each
    quantile, raw and conformalised (asym: each tail on its own). The conformal version is kept when its coverage is
    nearer COVER on both blocks (p50 and its pinball loss do not change)."""
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    cols, cats, *_ = champion(registry.load(), "y_any_h2", man)     # score.py: the p_any_2q champion's features
    rows = []
    for qn, (y, like) in bt.QUANTILE_TARGETS.items():
        d = bt.qframe(feats, labels[2], y)
        w = bt.windows(cov, bt.frame(feats, labels[2], like, 2), like, 2)
        blocks = {b: pd.to_datetime(w[k]) for b, k in BLOCKS.items() if w[k]}
        need = {c for cs in blocks.values() for x in cs for c in [x, *bt.calibration_folds(x, 2)]}
        pool = bt.quantile_backtest(d, y, sorted(c for c in need if (d.period == c).any()), cols, cats)
        for b, cs in blocks.items():
            raw = pool[pool.cutoff.isin(cs)]
            conf = conformalise(raw, pool, 2, asym)
            for method, p in (("raw", raw), ("conformal", conf)):
                rows.append({"candidate": name, "target": qn, "block": b, "method": method, "n_folds": len(cs),
                             **bt.interval_metrics(p), "mean_conformal_q": float(conf.conformal_q.mean())
                             if method == "conformal" else 0.0})
        print(f"  {qn}: " + "  ".join(f"{r['block']} {r['method']} coverage {r['coverage']:.3f} width "
                                      f"{r['mean_width']:.1f} pinball p50 {r['pinball_p50']:.3f}"
                                      for r in rows if r["target"] == qn), flush=True)
    t = pd.DataFrame(rows)
    gap = t.assign(gap=(t.coverage - COVER).abs()).pivot_table(index=["target", "block"], columns="method",
                                                                 values="gap")
    better = gap.conformal < gap.raw
    t["decision"] = t.target.map(lambda q: "pass" if better.loc[q].all() else "fail")
    t["runtime_s"] = round(time.time() - t0, 1)
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / f"{name}.csv", index=False)
    print(f"intervals: {out / f'{name}.csv'}, {time.time() - t0:.0f}s")
    return t


def calibration_methods(name="k1_isotonic", seed=0, out=OUT, targets=None):
    """(k) Calibration of every target's champion, raw against Platt and isotonic, each fitted per cutoff on the
    champion's own out-of-fold predictions at the cutoff's calibration folds (backtest.calibration_folds, realised
    by the cutoff) and applied to the validation and flash blocks: ECE, Brier, within-cutoff and pooled PR-AUC per
    block. A method passes for a target when its ECE is below raw's on both blocks and its within-cutoff PR-AUC is
    not below raw's by more than the block's noise margin (isotonic creates ties). Writes
    model/experiments/<name>.csv."""
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    reg = registry.load()
    rows = []
    for y, h in bt.TARGETS:
        key = f"{y}_h{h}"
        if targets and key not in targets:
            continue
        cols, cats, params, entry_id = champion(reg, key, man)
        d = bt.frame(feats, labels[h], y, h)
        blocks, cutoffs = block_cutoffs(cov, d, y, h)
        need = sorted({c for cs in blocks.values() for x in cs for c in [x, *bt.calibration_folds(x, h)]
                       if (d.period == c).any()})
        pool = champion_predictions(man, key, d, y, pd.DatetimeIndex(need), cols, cats,
                                    {**params, "random_state": seed}).assign(model="m")
        margins = registry.margins(key)
        res = {}
        for b, cs in blocks.items():
            raw = pool[pool.cutoff.isin(cs)]
            for method in ("raw", *bt.FITS):
                p = raw if method == "raw" else bt.calibrate(raw, pool, h, method)
                m = block_metrics(p, h)
                res[b, method] = {"candidate": name, "target": key, "block": b, "method": method,
                                  "champion_entry": entry_id, "n_folds": len(cs), "n_rows": len(p),
                                  "n_calibration_folds": bt.PLATT_FOLDS, "margin": margins.get(b, 0.0),
                                  "ece": m.ece, "brier": m.brier, "fold_pr_auc": m[registry.GAIN], "pr_auc": m.pr_auc,
                                  "precision_50": m.precision_50, "mean_p": float(p.p.mean()),
                                  "base_rate": m.base_rate}
        for method in bt.FITS:
            ok = all(res[b, method]["ece"] < res[b, "raw"]["ece"]
                     and res[b, method]["fold_pr_auc"] >= res[b, "raw"]["fold_pr_auc"] - margins.get(b, 0.0)
                     for b in blocks)
            for b in blocks:
                res[b, method]["decision"] = "pass" if ok else "fail"
        for b in blocks:
            res[b, "raw"]["decision"] = "-"
        rows += list(res.values())
        print(f"  {key}: " + "  ".join(f"{b} {m} ECE {r['ece']:.4f} PR-AUC {r['fold_pr_auc']:.4f}"
                                       for (b, m), r in res.items()) + f"  {time.time() - t0:.0f}s", flush=True)
    t = pd.DataFrame(rows).assign(runtime_s=round(time.time() - t0, 1))
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / f"{name}.csv", index=False)
    print(f"calibration: {out / f'{name}.csv'}, {time.time() - t0:.0f}s")
    return t


def hurdle(name="h1_hurdle", seed=0, out=OUT):
    """(h) Point forecasts of the magnitudes (months pushed and cost change % by t + 2q) on the validation and flash
    cutoffs of their binary counterparts: the served p50 quantile against a two-stage hurdle, P(step) x the
    conditional magnitude (a LightGBM classifier of y >= the label's step, times expm1 of a LightGBM regressor of
    log1p(y) fitted on the stepped rows only), and the floors zero and the training mean. MAE, RMSE, bias, and the
    MAE on the stepped and the unstepped rows. The hurdle passes for a target when its MAE is below p50's on both
    blocks. Writes model/experiments/<name>.csv."""
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    reg = registry.load()
    steps = {"y_months": float(gold.DATE_STEP), "y_cost_pct": (gold.COST_STEP - 1) * 100}
    rows = []
    for qn, (y, like) in bt.QUANTILE_TARGETS.items():
        cols, cats, params, entry_id = champion(reg, f"{like}_h2", man)
        params = {**params, "random_state": seed}
        d = bt.qframe(feats, labels[2], y)
        w = bt.windows(cov, bt.frame(feats, labels[2], like, 2), like, 2)
        step, res = steps[y], {}
        for b, key in BLOCKS.items():
            cs = pd.to_datetime(w[key])
            if not len(cs):
                continue
            parts = []
            for c in cs:
                tr, te = d[d.target_period <= c], d[d.period == c]
                pos = (tr[y] >= step).to_numpy()
                q50 = bt.fit_quantiles(tr, y, cols, cats)(te)[:, 1]
                p_step = lgbm(params)(tr.assign(_step=pos.astype(int)), cols, cats, "_step")[1](te)
                rg = lgb.LGBMRegressor(**{k: v for k, v in params.items() if k != "half_life_q"}).fit(
                    bt.lgb_X(tr[pos], cols, cats), np.log1p(tr.loc[pos, y].clip(lower=0)))
                mag = np.expm1(rg.predict(bt.lgb_X(te, cols, cats)))
                parts.append(pd.DataFrame({"cutoff": c, "y": te[y].to_numpy(float), "p50": q50,
                                           "hurdle": p_step * mag, "zero": 0.0, "train_mean": float(tr[y].mean()),
                                           "p_step": p_step}))
            p = pd.concat(parts, ignore_index=True)
            stepped = (p.y >= step).to_numpy()
            for method in ("p50", "hurdle", "zero", "train_mean"):
                e = (p.y - p[method]).to_numpy()
                res[b, method] = {"candidate": name, "target": qn, "label": y, "block": b, "method": method,
                                  "champion_entry": entry_id, "n_folds": len(cs), "n": len(p), "step": step,
                                  "share_stepped": float(stepped.mean()), "mae": float(np.abs(e).mean()),
                                  "rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean()),
                                  "mae_stepped": float(np.abs(e[stepped]).mean()) if stepped.any() else np.nan,
                                  "mae_unstepped": float(np.abs(e[~stepped]).mean()) if (~stepped).any() else np.nan,
                                  "mean_forecast": float(p[method].mean()), "mean_y": float(p.y.mean())}
        blocks_here = {b for b, _ in res}
        ok = all(res[b, "hurdle"]["mae"] < res[b, "p50"]["mae"] for b in blocks_here)
        for (b, m), r in res.items():
            r["decision"] = ("pass" if ok else "fail") if m == "hurdle" else "-"
            rows.append(r)
        print(f"  {qn}: " + "  ".join(f"{b} {m} MAE {r['mae']:.3f} (stepped {r['mae_stepped']:.2f})"
                                      for (b, m), r in res.items() if m in ("p50", "hurdle"))
              + f"  {time.time() - t0:.0f}s", flush=True)
    t = pd.DataFrame(rows).assign(runtime_s=round(time.time() - t0, 1))
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / f"{name}.csv", index=False)
    print(f"hurdle: {out / f'{name}.csv'}, {time.time() - t0:.0f}s")
    return t


SPECIAL = {"g_intervals": lambda: intervals("g_intervals"), "g2_intervals_asym": lambda: intervals(
    "g2_intervals_asym", asym=True), "k1_isotonic": calibration_methods, "h1_hurdle": hurdle}


CANDIDATES = {
    "null": Candidate("the champion against itself (harness sanity: every delta is 0)"),
    "a_feasibility": Candidate("deadline feasibility: required vs recent pace, projected overrun, deadline in "
                               "2q/4q", extra=feasibility),
    "b1_basis_fix": Candidate("revision events masked on a basis change (revisions_so_far, "
                              "months_since_last_revision)", extra=lambda ctx: basis_fixed(ctx.base)),
    "b2_slip_history": Candidate("b1 + slip change 2q/4q, last push size, pushes in 4q/8q, own realised slip and "
                                 "cost-revision rates", extra=slip_history),
    "b3_history_nofix": Candidate("b2's slip-history columns without the basis fix (revision counts unchanged)",
                                  extra=lambda ctx: slip_history(ctx).drop(columns=list(BASIS_FIXED))),
    "b4_own_rates": Candidate("only the key's own realised slip and cost-revision rates", extra=lambda ctx:
                              slip_history(ctx)[PK + ["own_slip_n", "own_slip_rate", "own_cost_rev_rate"]]),
    "b5_push_history": Candidate("only slip change 2q/4q, last push size and pushes in 4q/8q", extra=lambda ctx:
                                 slip_history(ctx)[PK + ["slip_change_2q", "slip_change_4q", "last_push_months",
                                                         "pushes_4q", "pushes_8q"]]),
    "c1_name_flags": Candidate("22 project-type keyword flags from the name", extra=name_flags),
    "c2_name_type": Candidate("the first project-type keyword as one categorical", extra=name_type,
                              cats=["name_type"]),
    "d1_decay_8q": Candidate("sample weights halving every 8 quarters of row age", fit=weighted(decay(8))),
    "d2_decay_16q": Candidate("sample weights halving every 16 quarters of row age", fit=weighted(decay(16))),
    "d3_flash_x3": Candidate("flash-report rows weighted 3x", fit=weighted(flash_weight(3))),
    "e1_tuned_es": Candidate("the best early-stopped trial of tune_y_any_h2.csv (chosen on validation only)",
                             fit=lambda seed, ctx, y, h, params: early_stopped({**params, **TUNED_ES})),
    "e1b_tuned_trees": Candidate("the best trial of tune_y_any_h2_trees.csv (tree count searched, no early stopping)",
                                 fit=lambda seed, ctx, y, h, params: lgbm({**params, **TUNED_TREES})),
    "e2_bag5": Candidate("mean of 5 LightGBM seeds", fit=bagged(5)),
    "h4_feas_decay8": Candidate("the two y_any_h4 keepers together: feasibility columns and the 8-quarter decay",
                                extra=feasibility, fit=weighted(decay(8)), targets=("y_any_h4",)),
    "f1_any_or": Candidate("y_any_h2 = 1 - (1 - p_date)(1 - p_cost)", fit=cross_target("or"), targets=("y_any_h2",)),
    "f2_any_avg": Candidate("y_any_h2 = mean(direct, 1 - (1 - p_date)(1 - p_cost))", fit=cross_target("avg"),
                            targets=("y_any_h2",)),
    # the September 2026 evaluation round (docs/MODEL_EVALUATION_2026-09.md)
    "m1_monotone": Candidate("monotone constraints on prior revisions, stall count, slip to date and cost growth",
                             fit=monotone()),
    "s1_survival": Candidate("discrete-time survival: one hazard LightGBM over (t, k) person-periods, P(event by h) "
                             "from the cumulative hazard", fit=survival_fit),
}


# ---------------------------------------------------------------------------------------------------- the run

def champion(reg, key, man, run=None):
    """(feature list, categoricals, params, entry_id) of the target's registry champion, or with run of that run's
    LightGBM entry of the target (lightgbm, else lightgbm_incumbent). Without a LightGBM champion: the manifest's full
    feature set with the target's lgb_params (entry_id None)."""
    if run:
        ids = [f"{run}/{m}/{key}" for m in ("lightgbm", "lightgbm" + registry.INCUMBENT)]
        e = next((r for i in ids for r in reg["runs"] if r["entry_id"] == i), None)
        assert e is not None, f"no LightGBM entry of {key} in run {run}"
    else:
        e = next((r for r in reg["runs"] if r["entry_id"] == reg["champions"].get(key, {}).get("entry_id")), None)
    if e is None or registry.family(e["model"]) != "lightgbm":
        y, h = key.rsplit("_h", 1)
        return bt.model_cols(man["features"]), man["categorical"], bt.lgb_params(y, int(h)), None
    return e["feature_list"], e["categorical"], dict(e["params"]), e["entry_id"]


def code_version():
    """What champion predictions depend on besides their tag: the source of ml/backtest.py (frame, windows, fit_lgbm,
    TRAIN_FROM, MIN_ROWS, ...) and the LightGBM version. Any edit there, comments included, starts a new cache."""
    return hashlib.sha256(Path(bt.__file__).read_bytes() + lgb.__version__.encode()).hexdigest()[:16]


def cached(tag, make):
    """Predictions frame from the cache file of tag and code_version(), else make() written there."""
    path = CACHE / f"{hashlib.sha256((tag + code_version()).encode()).hexdigest()[:20]}.parquet"
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


def block_cutoffs(cov, d, y, h):
    """(block -> cutoffs, the union of them) of backtest.windows for target (y, h)."""
    w = bt.windows(cov, d, y, h)
    blocks = {b: pd.to_datetime(w[k]) for b, k in BLOCKS.items() if w[k]}
    return blocks, pd.DatetimeIndex(sorted(set().union(*[set(c) for c in blocks.values()])))


def champion_predictions(man, key, d, y, cutoffs, cols, cats, ps, use_cache=True):
    """The champion configuration's rolling-origin predictions at cutoffs (params ps, seed included), cached."""
    tag = json.dumps([man["gold_version"], key, [str(c.date()) for c in cutoffs], cols, cats, ps], sort_keys=True)
    make = lambda: bt.backtest(d, y, cutoffs, {"m": (lgbm(ps), cols, cats)})[0]
    return cached(tag, make) if use_cache else make()


def seed_sd(seeds=SD_SEEDS, champion_run=None, out=OUT, targets=None):
    """The seed noise the promotion margin is made of: for each target's champion (champion_run: that run's entries),
    the SD over seeds (LightGBM random_state) of its within-cutoff PR-AUC on each block (registry.SEED_SD), and of its
    pooled PR-AUC for reference. targets: target keys (default all). Writes model/experiments/seed_sd.csv and
    returns the table."""
    t0 = time.time()
    feats, labels, cov, man = bt.load()
    reg = registry.load()
    rows = []
    for y, h in bt.TARGETS:
        key = f"{y}_h{h}"
        if targets and key not in targets:
            continue
        cols, cats, params, entry_id = champion(reg, key, man, champion_run)
        d = bt.frame(feats, labels[h], y, h)
        blocks, cutoffs = block_cutoffs(cov, d, y, h)
        ms = {b: [] for b in blocks}
        for s in seeds:
            p = champion_predictions(man, key, d, y, cutoffs, cols, cats, {**params, "random_state": s})
            for b, cs in blocks.items():
                ms[b].append(block_metrics(p[p.cutoff.isin(cs)], h))
        for b, m in ms.items():
            fold, pooled = [x[registry.GAIN] for x in m], [x.pr_auc for x in m]
            rows.append({"target": key, "block": b, "champion_entry": entry_id, "n_seeds": len(seeds),
                         "n_folds": len(blocks[b]), "fold_pr_auc_mean": float(np.mean(fold)),
                         "fold_pr_auc_sd": float(np.std(fold, ddof=1)), "pr_auc_sd": float(np.std(pooled, ddof=1)),
                         "fold_pr_auc_by_seed": "/".join(f"{v:.4f}" for v in fold),
                         "margin": registry.NOISE_SDS * float(np.std(fold, ddof=1))})
        print(f"  {key}: " + "  ".join(f"{r['block']} sd {r['fold_pr_auc_sd']:.4f} (pooled {r['pr_auc_sd']:.4f})"
                                       for r in rows if r["target"] == key) + f"  {time.time() - t0:.0f}s", flush=True)
    t = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "seed_sd.csv"
    if path.exists():           # a run on some targets replaces their rows and keeps the other targets'
        old = pd.read_csv(path)
        t = pd.concat([old[~old.target.isin(t.target)], t], ignore_index=True)
    t.to_csv(path, index=False)
    print(f"seed_sd: {path}, {time.time() - t0:.0f}s")
    return t


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
    """Pooled metrics of one model's predictions on a block (folds recomputed from the rows); pr_auc_fold_mean
    (registry.GAIN) is the within-cutoff PR-AUC."""
    folds = pd.DataFrame([{"cutoff": c, "model": "m", **bt.score(g.y, g.p)} for c, g in p.groupby("cutoff")])
    return bt.pooled(p.assign(model="m"), folds, h).iloc[0]


def fold_pr_auc(p):
    """cutoff -> PR-AUC of one model's predictions on a block."""
    return pd.Series({c: average_precision_score(g.y, g.p) for c, g in p.groupby("cutoff")})


def run(name, cand=None, seeds=SEEDS, targets=None, n_boot=BOOT, out=OUT, use_cache=True, champion_run=None):
    """Backtest the champion (champion_run: that run's entries, see champion) and the challenger on both blocks of
    every target; returns the result table."""
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
        cols, cats, params, entry_id = champion(reg, key, man, champion_run)
        ccols = cand.cols(cols, key) if cand.cols else cols + [c for c in new_cols if c not in cols]
        ccats = cats + [c for c in cand.cats if c not in cats]
        d, dc = bt.frame(feats, labels[h], y, h), bt.frame(cfeats, labels[h], y, h)
        assert d[PK].equals(dc[PK])
        blocks, cutoffs = block_cutoffs(cov, d, y, h)
        margins = registry.margins(key)
        champ, chall = [], []
        for s in seeds:
            ps = {**params, "random_state": s}
            champ.append(champion_predictions(man, key, d, y, cutoffs, cols, cats, ps, use_cache))
            fit = cand.fit(s, ctx, y, h, ps) if cand.fit else lgbm(ps)
            chall.append(bt.backtest(dc, y, cutoffs, {"m": (fit, ccols, ccats)})[0])
            assert (champ[-1][["cutoff", "project_key"]].values == chall[-1][["cutoff", "project_key"]].values).all()
        res = {}
        for b, cs in blocks.items():
            sel = [p[p.cutoff.isin(cs)].reset_index(drop=True) for p in champ + chall]
            a, c = sel[:len(seeds)], sel[len(seeds):]
            ma, mc = [block_metrics(p, h) for p in a], [block_metrics(p, h) for p in c]
            mean = lambda ms, k: float(np.mean([m[k] for m in ms]))
            sd = lambda ms, k: float(np.std([m[k] for m in ms], ddof=1)) if len(seeds) > 1 else np.nan
            deltas = {k: [x[k] - z[k] for x, z in zip(mc, ma)] for k in (registry.GAIN, "pr_auc")}
            yb, gb, fb = a[0].y.to_numpy(), a[0].project_key.to_numpy(), a[0].cutoff.to_numpy()
            pa, pc = [p.p.to_numpy() for p in a], [p.p.to_numpy() for p in c]
            boot = paired_bootstrap(yb, gb, pa, pc, n_boot=n_boot, folds=fb)
            (lo, hi), (plo, phi) = ci(boot), ci(paired_bootstrap(yb, gb, pa, pc, n_boot=n_boot))
            by_fold = (pd.concat([fold_pr_auc(p) for p in c], axis=1).mean(axis=1)
                       - pd.concat([fold_pr_auc(p) for p in a], axis=1).mean(axis=1))
            res[b] = {"candidate": name, "target": key, "block": b, "margin": margins.get(b, 0.0),
                      "champion_entry": entry_id,
                      "n_rows": len(a[0]), "n_projects": a[0].project_key.nunique(), "n_folds": len(cs),
                      "seeds": len(seeds),
                      "champion_fold_pr_auc": mean(ma, registry.GAIN),
                      "challenger_fold_pr_auc": mean(mc, registry.GAIN),
                      "delta_fold_pr_auc": float(np.mean(deltas[registry.GAIN])), "ci_lo": lo, "ci_hi": hi,
                      "boot_share_le_0": float((boot <= 0).mean()),
                      "seed_deltas": "/".join(f"{x:+.4f}" for x in deltas[registry.GAIN]),
                      "fold_deltas": " ".join(f"{pd.Timestamp(k):%Y-%m}:{v:+.4f}" for k, v in by_fold.items()),
                      "folds_up": int((by_fold > 0).sum()),
                      "champion_seed_sd": sd(ma, registry.GAIN), "challenger_seed_sd": sd(mc, registry.GAIN),
                      "champion_pr_auc": mean(ma, "pr_auc"), "challenger_pr_auc": mean(mc, "pr_auc"),
                      "delta_pr_auc": float(np.mean(deltas["pr_auc"])), "pooled_ci_lo": plo, "pooled_ci_hi": phi,
                      "pooled_seed_deltas": "/".join(f"{x:+.4f}" for x in deltas["pr_auc"]),
                      "champion_pooled_seed_sd": sd(ma, "pr_auc"),
                      **{f"{who}_{k}": mean(ms, k) for k in ["ece", "precision_50", "nyd_pr_auc", "brier", "roc_auc",
                                                             "pre_pr_auc_fold_mean", "pre_pr_auc", "pre_n",
                                                             "pre_base_rate"]
                         for who, ms in (("champion", ma), ("challenger", mc))}}
        gains = {b: r["delta_fold_pr_auc"] for b, r in res.items()}
        ok, why = registry.rule(gains, margins, res["val"]["challenger_ece"], res["val"]["champion_ece"])
        keep = robust(ok, res.values())
        for r in res.values():
            rows.append({**r, "decision": "pass" if ok else "fail", "reason": why,
                         "ship": "keep" if keep else "reject", "n_features": len(ccols),
                         "runtime_s": round(time.time() - t1, 1)})
        print(f"  {key}: {'PASS' if ok else 'fail'}{' (robust)' if keep else ''}  " + "  ".join(
            f"{b} {r['champion_fold_pr_auc']:.4f} -> {r['challenger_fold_pr_auc']:.4f} "
            f"({r['delta_fold_pr_auc']:+.4f} [{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}], {r['folds_up']}/{r['n_folds']} "
            f"folds up; pooled {r['delta_pr_auc']:+.4f})" for b, r in res.items())
              + f"  val ECE {res['val']['champion_ece']:.4f} -> {res['val']['challenger_ece']:.4f}"
              + f"  {time.time() - t1:.0f}s", flush=True)
    table = pd.DataFrame(rows)
    table["point_in_time"] = json.dumps(pit)
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / f"{name}.csv", index=False)
    print(f"experiment {name}: {out / f'{name}.csv'}, {time.time() - t0:.0f}s")
    return table


def summary_table(out=OUT, names=None):
    """Markdown tables of every experiment CSV (or the named ones): one table per target, one row per candidate,
    champion -> challenger within-cutoff PR-AUC (seed means), the deltas with their paired bootstrap CIs, the folds
    where the challenger ranks better and the pooled deltas for reference. Rule is the promotion rule, Ship the robust
    guard on top of it."""
    rows = []
    for path in sorted(out.glob("*.csv")):
        t = pd.read_csv(path, keep_default_na=False, na_values=[""])
        if (names and path.stem not in names) or "delta_fold_pr_auc" not in t:
            continue
        for key, g in t.groupby("target", sort=False):
            b = g.set_index("block")
            v = b.loc["val"]
            rows.append((key, path.stem, v, b.loc["flash"] if "flash" in b.index else None,
                         robust(v.decision == "pass", [r for _, r in b.iterrows()])))
    fmt = lambda r: f"{r.delta_fold_pr_auc:+.4f} [{r.ci_lo:+.4f}, {r.ci_hi:+.4f}]"
    arrow = lambda a, b, n=4: f"{a:.{n}f} -> {b:.{n}f}"
    lines = []
    for key in [f"{y}_h{h}" for y, h in bt.TARGETS]:
        mine = [r for r in rows if r[0] == key]
        if not mine:
            continue
        fm = f"{mine[0][3].margin:.4f}" if mine[0][3] is not None else "-"
        lines += [f"**{key}** (noise margin: validation {mine[0][2].margin:.4f}, flash {fm})", "",
                  "| Candidate | Val PR-AUC | Val pre-event PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | "
                  "Val delta [95% CI] | Flash delta [95% CI] | Val folds up | Pooled delta val / flash | Rule | Ship |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        pre = lambda r: (arrow(r.champion_pre_pr_auc_fold_mean, r.challenger_pre_pr_auc_fold_mean)
                         if "champion_pre_pr_auc_fold_mean" in r and pd.notna(r.champion_pre_pr_auc_fold_mean)
                         else "-")
        for _, name, v, f, keep in mine:
            lines.append(f"| {name} | {arrow(v.champion_fold_pr_auc, v.challenger_fold_pr_auc)} | {pre(v)} | "
                         + (f"{arrow(f.champion_fold_pr_auc, f.challenger_fold_pr_auc)} | "
                            f"{arrow(f.champion_precision_50, f.challenger_precision_50, 3)} | " if f is not None
                            else "- | - | ")
                         + f"{arrow(v.champion_ece, v.challenger_ece)} | {fmt(v)} | "
                         + (f"{fmt(f)} | " if f is not None else "- | ")
                         + f"{v.folds_up}/{v.n_folds} | {v.delta_pr_auc:+.4f} / "
                         + (f"{f.delta_pr_auc:+.4f}" if f is not None else "-")
                         + f" | {v.decision} | {'keep' if keep else '-'} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ml.experiment")
    ap.add_argument("candidate", nargs="?")
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--targets", default=None, help="comma-separated target keys, e.g. y_any_h2")
    ap.add_argument("--boot", type=int, default=BOOT)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--champion-run", default=None,
                    help="compare against this run's LightGBM entries instead of the current champions")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--seed-sd", action="store_true", help="measure the champions' seed SD per block")
    ap.add_argument("--tune", metavar="TARGET", help="random search on the validation block, e.g. y_any_h2")
    ap.add_argument("--trials", type=int, default=24)
    ap.add_argument("--no-es", action="store_true", help="tune: search the tree count instead of early stopping")
    a = ap.parse_args(argv)
    if a.tune:
        tune(a.tune, a.trials, es=not a.no_es)
    elif a.candidate == "k1_isotonic":
        calibration_methods(targets=a.targets.split(",") if a.targets else None)
    elif a.candidate in SPECIAL:
        SPECIAL[a.candidate]()
    elif a.list:
        print("\n".join(f"{n:24s} {c.about}" for n, c in CANDIDATES.items()))
        print("\n".join(f"{n:24s} (no ranking target: {f.__doc__.strip().splitlines()[0] if f.__doc__ else n})"
                        for n, f in SPECIAL.items()))
    elif a.table:
        print(summary_table())
    elif a.seed_sd:
        seed_sd(champion_run=a.champion_run, targets=a.targets.split(",") if a.targets else None)
    elif a.candidate:
        run(a.candidate, seeds=tuple(int(s) for s in a.seeds.split(",")),
            targets=a.targets.split(",") if a.targets else None, n_boot=a.boot, use_cache=not a.no_cache,
            champion_run=a.champion_run)
    else:
        ap.error("name a candidate, or --list / --table")


if __name__ == "__main__":
    main()
