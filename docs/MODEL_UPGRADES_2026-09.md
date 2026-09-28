# Model upgrades, September 2026

This round set out to raise the predictive quality of the four targets: the primary one, any slip or cost revision
within two quarters (`y_any_h2`), and also `y_date_push_h2`, `y_cost_rev_h2` and `y_any_h4`. Every change was
measured against the registry champion on the same rows and folds. A change was kept only if it ranked projects better
than the champion inside the cutoffs of both the validation and the flash blocks.

**Outcome.** Nineteen candidates were measured on every target. One change ships:

- `y_cost_rev_h2` trains with regularised LightGBM params: learning rate 0.02, 63 leaves, lambda 20 and 150 trees. It
  is provisional (see [Caveats](#caveats)).

Nothing passed for `y_any_h2`, `y_date_push_h2` or `y_any_h4`. Their champions are the ones the round started from
(ML-20260927-222602), and so are the tiers, which rank `p_any_2q`.

The first version of this report also shipped 8-quarter age weights for `y_any_h4`. A review found that its gain came
from how pooled PR-AUC mixes folds, not from better ranking, and it was reverted. The review's corrections are listed
in [What the review changed](#what-the-review-changed).

Other changes this round:

- The registry now gates new features and new folds honestly, and can undo a promotion.
- Every train run now backtests the served intervals.
- There is now a reusable experiment harness.

## Served champions, before and after

The harness numbers: means over 3 seeds, on the champions' own validation and flash folds, with the paired project
bootstrap CI of each delta. PR-AUC is the within-cutoff one (each fold's own, averaged over the block); ECE is on the
validation block, and the cost revision's scores are raw here.

| Target | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | 3-seed delta, val / flash [95% CI] | Decision |
|---|---|---|---|---|---|---|
| y_any_h2 | 0.6962 | 0.7775 | 0.898 | 0.0818 | no candidate passed | champion kept |
| y_date_push_h2 | 0.6320 | 0.7751 | 0.909 | 0.0555 | no candidate passed | champion kept |
| y_cost_rev_h2 | 0.1751 -> **0.1824** | 0.1230 -> **0.1595** | 0.142 -> 0.193 | 0.0097 -> 0.0039 | +0.0073 [-0.0106, +0.0263] / +0.0365 [+0.0059, +0.0631] | tuned params, promoted (provisional) |
| y_any_h4 | 0.8844 | 0.8764 | 0.947 | 0.0959 | no candidate passed; the half-life: -0.0031 [-0.0097, +0.0035] / +0.0031 [-0.0135, +0.0200] | half-life reverted, champion kept |

What is served now is train run ML-20260928-072744, gated by the registry (seed 0, as served; the cost revision is
Platt-calibrated). Served version `lgbm-any2q-20260927-222602+20260928-072744`:

| Target | Champion | Val PR-AUC (pooled) | Flash PR-AUC (pooled) | Flash P@50 | Val ECE | Test PR-AUC |
|---|---|---|---|---|---|---|
| y_any_h2 | ML-20260927-222602 | 0.6970 (0.7015) | 0.7794 (0.7753) | 0.913 | 0.0815 | 0.778 |
| y_date_push_h2 | ML-20260927-222602 | 0.6350 (0.6287) | 0.7780 (0.7712) | 0.920 | 0.0512 | 0.764 |
| y_cost_rev_h2 | ML-20260928-072744 | 0.1841 (0.1470) | 0.1644 (0.1263) | 0.193 | 0.0091 | 0.230 (was 0.184) |
| y_any_h4 | ML-20260927-222602 | 0.8843 (0.8690) | 0.8719 (0.8719) | 0.940 | 0.0954 | 0.753 |

- The test fold of the 2-quarter targets (2026-01) is also a flash cutoff, so it is not independent. The y_any_h4
  test fold (2024-04) is.
- The cost revision's validation folds changed in this round (see below), so its seed-0 registry numbers have no
  "before" on the same folds; the harness row above is the comparison.
- p_any_2q, p_date_push_2q, the intervals and the tiers (70 Critical, 213 High, 425 Medium, 708 Low, 347 Watch) are
  unchanged. p_any_4q is again exactly the pre-round model's.

## What the review changed

An independent review of the first version found two major problems and four minor ones. All six were confirmed
against the code and fixed, except that the registry gate still scores one seed (point 3); every candidate was then
measured again.

1. **Pooled PR-AUC rewarded calibration, not ranking** (`registry.GAIN`, `ml/experiment.py`). Pooled PR-AUC
   concatenates the folds of a block, whose base rates differ (y_any_h4 validation: 0.67 down to 0.58). A model that
   only moves its score level toward each fold's base rate gains pooled PR-AUC without ranking any better inside a
   fold. That is what the y_any_h4 half-life did: +0.0124 pooled, but lower PR-AUC on 4 of the 6 validation folds
   (2022-10 to 2023-07) in every seed, and -0.0031 as a fold mean. A served score is only ever ranked against the
   other projects of its own as-of date, so the harness and the registry gate now judge the **within-cutoff PR-AUC**
   (`pr_auc_fold_mean`), and its bootstrap averages each fold's own PR-AUC. Pooled PR-AUC stays as a reference
   column. Calibration is still guarded by ECE. The half-life was reverted (`backtest.TARGET_PARAMS`, and
   `python -m ml.registry revert y_any_h4`, recorded in the registry with this evidence).
2. **The cost revision's two blocks shared folds** (`backtest.windows`). The cost fields stay reliable into the flash
   era, so y_cost_rev_h2 validated on 2024-01 to 2024-10 plus 2025-07 and 2025-10, and two of its three flash cutoffs
   were validation cutoffs too. Its biggest per-fold gain (2025-07) was counted twice. Validation now stops before
   2025-07 for every target, so the blocks are disjoint; y_cost_rev_h2 validates on 2023-07 to 2024-10 like the other
   2-quarter targets. Re-measured, the tuned params still pass, but the review's second point stands: this target and
   this variant were picked after the flash results had been seen, so no untouched block backs the promotion. It is
   provisional, with a pre-registered check (see [Caveats](#caveats)).
3. **One noise margin for blocks of very different noise** (`registry.SEED_SD`). The margin was twice the seed SD of
   pooled validation PR-AUC, applied to every block. The y_any_h4 flash block is one fold, whose seed-to-seed spread
   is 20 times the validation block's. `python -m ml.experiment --seed-sd` now measures the champion's within-cutoff
   PR-AUC over 5 seeds on each block (`model/experiments/seed_sd.csv`), and each block has its own margin. The
   registry gate scores seed 0 only, so it checks the configuration a run serves; it is not an independent
   confirmation of the harness. The headline table above is therefore the 3-seed harness result.
4. **The committed CSVs could not be reproduced after a promotion.** The harness compared with the current champion,
   so after the round `d1_decay_8q` would have stacked a second half-life on the first. `--champion-run RUN` compares
   with that run's entries, and every CSV row names its `champion_entry`. All CSVs of this round compare with
   ML-20260927-222602.
5. **The point-in-time check did not cut the labels** a candidate may read. A cut context now keeps only labels whose
   outcome quarter is by the cutoff. No measured candidate read labels that way, so no result changed.
6. **The champion prediction cache ignored code changes.** Its key now also hashes `ml/backtest.py` and the LightGBM
   version.

Two registry gaps surfaced while applying these:

- A train run re-scored the champion's configuration only on a new gold version. New folds on the same gold (the cost
  revision's, after point 2) now trigger the same re-score.
- The gate cannot undo a promotion by itself: the old configuration would have to beat the new one. `revert` restores
  the champion that a configuration's promotion replaced and records why.

## What changed in the code

- **Experiment harness** (`ml/experiment.py`, `python -m ml.experiment <candidate>`). It compares the champion and a
  challenger on the validation and flash blocks of all four targets, over 3 seeds. It reports the within-cutoff and
  pooled PR-AUC deltas with their paired project bootstrap CIs, each fold's delta (`fold_deltas`, `folds_up`), uses
  the promotion rule as the decision and writes `model/experiments/<candidate>.csv`.
  - `--champion-run` pins the champions; `--seed-sd` measures the noise margins.
  - Champion predictions are cached under `temp/`, keyed on the gold version and the backtest code.
  - `--table` prints the tables below; `--tune` runs the search.
  - The catalogue keeps every candidate of this round, so any result can be re-run.
- **Honest registry gate** (`ml/registry.py`).
  - The gain is the within-cutoff PR-AUC, with a noise margin per block (`registry.margins`).
  - A run on a new gold version or on new folds also backtests the champion's own configuration as
    `<type>_incumbent`: its type, feature list, categoricals and params. That re-scored configuration takes over
    first, and every new configuration must then beat it under the rule. It used to promote the new LightGBM with no
    metric check, so a new feature family was never gated.
  - A champion whose features have left the gold is retired, and the decision is recorded.
  - `python -m ml.registry revert <target> --reason "..."` undoes a configuration's promotion.
  - The registry file format is unchanged, apart from an optional `rescored_from` field and the `reverted` decision.
  - Scoring refits each champion with its entry's own params (`registry.fitter`).
- **Disjoint blocks** (`backtest.windows`). Validation takes only cutoffs before 2025-07.
- **Per-target params** (`backtest.TARGET_PARAMS`, `backtest.lgb_params`). One target can train with its own
  LightGBM params. `half_life_q` becomes sample weights inside `fit_lgbm`; no target uses it now.
- **Interval backtest** (`intervals.csv` in every run). The score step's quantile models (5/50/95% of months pushed
  and cost change %) are backtested on the validation and flash cutoffs of `y_date_push_h2` and `y_cost_rev_h2`. The
  file reports p05-p95 coverage, the share below and above the band, mean width and pinball loss. `score.py` fits
  through the same `backtest.fit_quantiles`, and its outputs are unchanged.
- **Model version.** Champions can now come from different runs. The served `model_version` therefore lists every
  champion run, for example `lgbm-any2q-20260927-222602+20260928-072744`, because cached briefs and the prediction
  log are keyed on it.

## How a candidate was judged

- **Harness.** The champion of each target is its registry entry in ML-20260927-222602: its feature list,
  categoricals and LightGBM params. A challenger changes one thing: extra columns, a replaced column, another fit
  function or sample weights. Both are backtested with `ml/backtest.py` on the same rows and cutoffs, once per seed
  (0, 1 and 2):
  - the validation block: quarterly-report era, 6 cutoffs (2023-07 to 2024-10 for the 2-quarter targets, 2022-10 to
    2024-01 for y_any_h4);
  - the flash block: every cutoff from 2025-07 (3 cutoffs; y_any_h4 has one, 2025-07, of 335 rows).

  The blocks share no cutoff. All numbers are means over the three seeds.
- **Metric.** The within-cutoff PR-AUC: each fold's own PR-AUC, averaged over the block's folds. The tables also
  show how many validation folds the challenger improves and the pooled deltas, for reference.
- **Confidence interval.** Each block's delta gets a paired project bootstrap: 2,000 resamples of the block's
  projects with replacement. Each drawn project brings all its fold rows, and both models' seed-mean within-cutoff
  PR-AUC is recomputed on each resample.
- **Rule** (`registry.rule`, the same rule the registry promotes with). The challenger passes only if:
  - its gain is at least 0 on both blocks;
  - its gain is at least 2 x that block's measured seed SD on at least one block;
  - its validation ECE is at most the champion's + 0.02.

  The seed SDs (5 seeds of the champion, `seed_sd.csv`) give these margins:

  | Target | Validation margin | Flash margin |
  |---|---|---|
  | y_any_h2 | 0.0024 | 0.0134 |
  | y_date_push_h2 | 0.0056 | 0.0134 |
  | y_cost_rev_h2 | 0.0068 | 0.0106 |
  | y_any_h4 | 0.0004 | 0.0094 |

- **Ship guard.** On top of the rule, some block that clears its margin must also have its bootstrap CI above 0.
  Nineteen candidates on four targets make many chances to pass by luck, and the y_any_h4 validation margin is tiny
  (its seeds agree to 0.0002), so there the guard does the work.
- **Point in time.** A candidate's columns at a cutoff must be identical when built from data cut at that cutoff,
  labels included. This is checked at 2023-07 and 2025-10 before any fit. Every candidate reads only its own row or
  outcomes realised by t.
- **Raw scores.** The harness compares raw cost-revision scores. The registry's gate compares the Platt-calibrated
  ones; Platt is monotone within a cutoff, so the within-cutoff PR-AUC is the same up to ties.
- **Sanity.** The null candidate (the champion against itself) returns exactly zero deltas on every target, and the
  pooled columns reproduce the first version's CSVs wherever the folds did not change.
- **Registry gate.** The shipped configuration then went through the gate in train run ML-20260928-072744, on the same
  gold (2676494d0207). Its folds had moved, so the tuned cost configuration was re-scored on them and took over; the
  other three targets re-scored their champions' configurations at zero gain.

## Results per target

Val and Flash show the champion's within-cutoff PR-AUC, then the challenger's; ECE is on the validation block. "Val
folds up" counts the validation folds where the challenger's seed-mean PR-AUC is higher. Rule is the promotion rule;
Ship is the rule plus the guard. The candidates are:

| Candidate | What it changes |
|---|---|
| a_feasibility | Deadline feasibility: the progress and spend pace needed against the recent pace, the projected months late at the current pace, and whether the deadline falls within 2 or 4 quarters. |
| b1_basis_fix | Revision events masked on a basis change, as the labels mask them. |
| b2_slip_history | b1, plus slip change over 2q and 4q, the size of the last push, pushes in the last 4 and 8 quarters, and the project's own realised slip and cost-revision rates. |
| b3_history_nofix | b2 without the fix. |
| b4_own_rates | Only the project's own realised rates. |
| b5_push_history | Only the push history. |
| c1_name_flags | 22 project-type keyword flags from the name. |
| c2_name_type | The first matching keyword, as one categorical. |
| d1_decay_8q / d2_decay_16q | Age weights halving every 8 or 16 quarters. |
| d3_flash_x3 | Flash-report rows weighted 3x. |
| e1_tuned_es | The best trial of the validation search, with early stopping. |
| e1b_tuned_trees | The best trial with the tree count searched instead. |
| e2_bag5 | The mean of 5 seeds. |
| f1_any_or | 1 - (1 - p_date)(1 - p_cost). |
| f2_any_avg | The mean of f1 and the direct model. |
| h4_feas_decay8 | a and d1 together, on y_any_h4. |
| null | The champion against itself. |

**y_any_h2** (noise margin: validation 0.0024, flash 0.0134)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Val folds up | Pooled delta val / flash | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.6962 -> 0.6905 | 0.7775 -> 0.7828 | 0.898 -> 0.924 | 0.0818 -> 0.0849 | -0.0057 [-0.0107, -0.0009] | +0.0053 [-0.0027, +0.0122] | 1/6 | -0.0134 / +0.0047 | fail | - |
| b1_basis_fix | 0.6962 -> 0.6929 | 0.7775 -> 0.7784 | 0.898 -> 0.902 | 0.0818 -> 0.0823 | -0.0033 [-0.0053, -0.0011] | +0.0008 [-0.0029, +0.0042] | 1/6 | -0.0025 / +0.0015 | fail | - |
| b2_slip_history | 0.6962 -> 0.7008 | 0.7775 -> 0.7738 | 0.898 -> 0.907 | 0.0818 -> 0.0856 | +0.0046 [+0.0008, +0.0082] | -0.0037 [-0.0098, +0.0021] | 4/6 | +0.0024 / +0.0029 | fail | - |
| b3_history_nofix | 0.6962 -> 0.6969 | 0.7775 -> 0.7712 | 0.898 -> 0.909 | 0.0818 -> 0.0860 | +0.0007 [-0.0029, +0.0043] | -0.0063 [-0.0116, -0.0004] | 3/6 | -0.0032 / -0.0011 | fail | - |
| b4_own_rates | 0.6962 -> 0.6942 | 0.7775 -> 0.7809 | 0.898 -> 0.898 | 0.0818 -> 0.0847 | -0.0020 [-0.0043, +0.0003] | +0.0034 [-0.0023, +0.0085] | 2/6 | -0.0027 / +0.0014 | fail | - |
| b5_push_history | 0.6962 -> 0.6979 | 0.7775 -> 0.7649 | 0.898 -> 0.900 | 0.0818 -> 0.0863 | +0.0018 [-0.0019, +0.0056] | -0.0126 [-0.0200, -0.0038] | 3/6 | -0.0017 / -0.0051 | fail | - |
| c1_name_flags | 0.6962 -> 0.6967 | 0.7775 -> 0.7759 | 0.898 -> 0.884 | 0.0818 -> 0.0798 | +0.0005 [-0.0019, +0.0030] | -0.0016 [-0.0066, +0.0031] | 2/6 | -0.0017 / +0.0013 | fail | - |
| c2_name_type | 0.6962 -> 0.6959 | 0.7775 -> 0.7691 | 0.898 -> 0.893 | 0.0818 -> 0.0783 | -0.0002 [-0.0034, +0.0031] | -0.0084 [-0.0161, -0.0005] | 3/6 | -0.0015 / -0.0053 | fail | - |
| d1_decay_8q | 0.6962 -> 0.6895 | 0.7775 -> 0.7553 | 0.898 -> 0.896 | 0.0818 -> 0.0778 | -0.0067 [-0.0144, +0.0010] | -0.0222 [-0.0351, -0.0070] | 3/6 | -0.0145 / -0.0182 | fail | - |
| d2_decay_16q | 0.6962 -> 0.6927 | 0.7775 -> 0.7643 | 0.898 -> 0.907 | 0.0818 -> 0.0806 | -0.0035 [-0.0087, +0.0019] | -0.0132 [-0.0226, -0.0030] | 3/6 | -0.0067 / -0.0111 | fail | - |
| d3_flash_x3 | 0.6962 -> 0.6962 | 0.7775 -> 0.7792 | 0.898 -> 0.902 | 0.0818 -> 0.0818 | +0.0000 [+0.0000, +0.0000] | +0.0017 [+0.0001, +0.0034] | 0/6 | +0.0000 / +0.0026 | fail | - |
| e1_tuned_es | 0.6962 -> 0.6957 | 0.7775 -> 0.7342 | 0.898 -> 0.802 | 0.0818 -> 0.0796 | -0.0005 [-0.0076, +0.0073] | -0.0433 [-0.0537, -0.0312] | 2/6 | +0.0027 / -0.0450 | fail | - |
| e1b_tuned_trees | 0.6962 -> 0.7022 | 0.7775 -> 0.7366 | 0.898 -> 0.758 | 0.0818 -> 0.0675 | +0.0060 [+0.0007, +0.0116] | -0.0409 [-0.0557, -0.0239] | 5/6 | +0.0011 / -0.0449 | fail | - |
| e2_bag5 | 0.6962 -> 0.6973 | 0.7775 -> 0.7835 | 0.898 -> 0.904 | 0.0818 -> 0.0823 | +0.0011 [-0.0004, +0.0028] | +0.0060 [+0.0020, +0.0094] | 5/6 | +0.0005 / +0.0048 | fail | - |
| f1_any_or | 0.6962 -> 0.6865 | 0.7775 -> 0.7720 | 0.898 -> 0.896 | 0.0818 -> 0.0598 | -0.0097 [-0.0164, -0.0030] | -0.0055 [-0.0180, +0.0051] | 2/6 | -0.0197 / -0.0026 | fail | - |
| f2_any_avg | 0.6962 -> 0.6937 | 0.7775 -> 0.7794 | 0.898 -> 0.904 | 0.0818 -> 0.0708 | -0.0025 [-0.0067, +0.0015] | +0.0019 [-0.0038, +0.0069] | 3/6 | -0.0085 / +0.0015 | fail | - |
| null | 0.6962 -> 0.6962 | 0.7775 -> 0.7775 | 0.898 -> 0.898 | 0.0818 -> 0.0818 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0/6 | +0.0000 / +0.0000 | fail | - |

**y_date_push_h2** (noise margin: validation 0.0056, flash 0.0134)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Val folds up | Pooled delta val / flash | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.6320 -> 0.6323 | 0.7751 -> 0.7758 | 0.909 -> 0.900 | 0.0555 -> 0.0533 | +0.0003 [-0.0045, +0.0053] | +0.0007 [-0.0068, +0.0080] | 3/6 | +0.0026 / -0.0005 | fail | - |
| b1_basis_fix | 0.6320 -> 0.6328 | 0.7751 -> 0.7779 | 0.909 -> 0.911 | 0.0555 -> 0.0543 | +0.0008 [-0.0013, +0.0028] | +0.0028 [-0.0011, +0.0069] | 2/6 | +0.0005 / +0.0035 | fail | - |
| b2_slip_history | 0.6320 -> 0.6371 | 0.7751 -> 0.7577 | 0.909 -> 0.884 | 0.0555 -> 0.0600 | +0.0051 [+0.0016, +0.0091] | -0.0174 [-0.0243, -0.0103] | 5/6 | +0.0067 / -0.0136 | fail | - |
| b3_history_nofix | 0.6320 -> 0.6390 | 0.7751 -> 0.7648 | 0.909 -> 0.904 | 0.0555 -> 0.0601 | +0.0070 [+0.0035, +0.0110] | -0.0102 [-0.0165, -0.0035] | 4/6 | +0.0077 / -0.0099 | fail | - |
| b4_own_rates | 0.6320 -> 0.6341 | 0.7751 -> 0.7794 | 0.909 -> 0.907 | 0.0555 -> 0.0559 | +0.0021 [-0.0003, +0.0043] | +0.0043 [+0.0002, +0.0087] | 5/6 | +0.0008 / +0.0040 | fail | - |
| b5_push_history | 0.6320 -> 0.6376 | 0.7751 -> 0.7634 | 0.909 -> 0.909 | 0.0555 -> 0.0590 | +0.0056 [+0.0026, +0.0094] | -0.0116 [-0.0179, -0.0049] | 5/6 | +0.0038 / -0.0082 | fail | - |
| c1_name_flags | 0.6320 -> 0.6323 | 0.7751 -> 0.7737 | 0.909 -> 0.902 | 0.0555 -> 0.0526 | +0.0003 [-0.0026, +0.0032] | -0.0014 [-0.0061, +0.0033] | 3/6 | -0.0012 / +0.0005 | fail | - |
| c2_name_type | 0.6320 -> 0.6348 | 0.7751 -> 0.7759 | 0.909 -> 0.900 | 0.0555 -> 0.0518 | +0.0028 [-0.0010, +0.0073] | +0.0008 [-0.0042, +0.0058] | 4/6 | +0.0034 / +0.0004 | fail | - |
| d1_decay_8q | 0.6320 -> 0.6380 | 0.7751 -> 0.7529 | 0.909 -> 0.891 | 0.0555 -> 0.0556 | +0.0060 [-0.0018, +0.0138] | -0.0222 [-0.0332, -0.0105] | 4/6 | +0.0012 / -0.0159 | fail | - |
| d2_decay_16q | 0.6320 -> 0.6392 | 0.7751 -> 0.7559 | 0.909 -> 0.891 | 0.0555 -> 0.0543 | +0.0072 [+0.0018, +0.0126] | -0.0192 [-0.0281, -0.0097] | 4/6 | +0.0079 / -0.0112 | fail | - |
| d3_flash_x3 | 0.6320 -> 0.6320 | 0.7751 -> 0.7756 | 0.909 -> 0.907 | 0.0555 -> 0.0555 | +0.0000 [+0.0000, +0.0000] | +0.0005 [-0.0014, +0.0025] | 0/6 | +0.0000 / +0.0003 | fail | - |
| e1_tuned_es | 0.6320 -> 0.6493 | 0.7751 -> 0.7171 | 0.909 -> 0.762 | 0.0555 -> 0.0585 | +0.0173 [+0.0083, +0.0261] | -0.0580 [-0.0702, -0.0435] | 5/6 | +0.0067 / -0.0550 | fail | - |
| e1b_tuned_trees | 0.6320 -> 0.6433 | 0.7751 -> 0.7359 | 0.909 -> 0.807 | 0.0555 -> 0.0455 | +0.0112 [+0.0050, +0.0177] | -0.0391 [-0.0537, -0.0223] | 6/6 | +0.0098 / -0.0385 | fail | - |
| e2_bag5 | 0.6320 -> 0.6335 | 0.7751 -> 0.7760 | 0.909 -> 0.898 | 0.0555 -> 0.0546 | +0.0015 [+0.0000, +0.0031] | +0.0009 [-0.0021, +0.0040] | 5/6 | -0.0003 / +0.0005 | fail | - |
| null | 0.6320 -> 0.6320 | 0.7751 -> 0.7751 | 0.909 -> 0.909 | 0.0555 -> 0.0555 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0/6 | +0.0000 / +0.0000 | fail | - |

**y_cost_rev_h2** (noise margin: validation 0.0068, flash 0.0106; raw scores)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Val folds up | Pooled delta val / flash | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.1751 -> 0.1713 | 0.1230 -> 0.1309 | 0.142 -> 0.153 | 0.0097 -> 0.0106 | -0.0038 [-0.0140, +0.0083] | +0.0079 [-0.0075, +0.0226] | 3/6 | +0.0052 / +0.0064 | fail | - |
| b1_basis_fix | 0.1751 -> 0.1757 | 0.1230 -> 0.1266 | 0.142 -> 0.151 | 0.0097 -> 0.0095 | +0.0005 [-0.0062, +0.0068] | +0.0036 [-0.0054, +0.0127] | 3/6 | +0.0012 / +0.0038 | fail | - |
| b2_slip_history | 0.1751 -> 0.1707 | 0.1230 -> 0.1208 | 0.142 -> 0.142 | 0.0097 -> 0.0097 | -0.0044 [-0.0139, +0.0052] | -0.0023 [-0.0190, +0.0111] | 2/6 | -0.0006 / -0.0030 | fail | - |
| b3_history_nofix | 0.1751 -> 0.1752 | 0.1230 -> 0.1181 | 0.142 -> 0.131 | 0.0097 -> 0.0094 | +0.0000 [-0.0093, +0.0106] | -0.0049 [-0.0213, +0.0092] | 3/6 | +0.0010 / -0.0056 | fail | - |
| b4_own_rates | 0.1751 -> 0.1740 | 0.1230 -> 0.1255 | 0.142 -> 0.140 | 0.0097 -> 0.0101 | -0.0011 [-0.0106, +0.0073] | +0.0025 [-0.0168, +0.0203] | 4/6 | +0.0015 / +0.0049 | fail | - |
| b5_push_history | 0.1751 -> 0.1745 | 0.1230 -> 0.1240 | 0.142 -> 0.138 | 0.0097 -> 0.0091 | -0.0007 [-0.0076, +0.0061] | +0.0010 [-0.0139, +0.0113] | 2/6 | +0.0016 / +0.0013 | fail | - |
| c1_name_flags | 0.1751 -> 0.1753 | 0.1230 -> 0.1198 | 0.142 -> 0.136 | 0.0097 -> 0.0086 | +0.0002 [-0.0069, +0.0091] | -0.0032 [-0.0205, +0.0086] | 3/6 | +0.0014 / -0.0010 | fail | - |
| c2_name_type | 0.1751 -> 0.1745 | 0.1230 -> 0.1298 | 0.142 -> 0.140 | 0.0097 -> 0.0093 | -0.0006 [-0.0098, +0.0091] | +0.0068 [-0.0097, +0.0208] | 3/6 | +0.0011 / +0.0048 | fail | - |
| d1_decay_8q | 0.1751 -> 0.1299 | 0.1230 -> 0.0958 | 0.142 -> 0.122 | 0.0097 -> 0.0110 | -0.0452 [-0.0638, -0.0236] | -0.0272 [-0.0612, -0.0053] | 0/6 | -0.0276 / -0.0235 | fail | - |
| d2_decay_16q | 0.1751 -> 0.1601 | 0.1230 -> 0.0995 | 0.142 -> 0.127 | 0.0097 -> 0.0105 | -0.0150 [-0.0270, +0.0005] | -0.0235 [-0.0484, -0.0077] | 1/6 | -0.0077 / -0.0173 | fail | - |
| d3_flash_x3 | 0.1751 -> 0.1751 | 0.1230 -> 0.1143 | 0.142 -> 0.138 | 0.0097 -> 0.0097 | +0.0000 [+0.0000, +0.0000] | -0.0087 [-0.0182, -0.0015] | 0/6 | +0.0000 / -0.0104 | fail | - |
| e1_tuned_es | 0.1751 -> 0.1900 | 0.1230 -> 0.1614 | 0.142 -> 0.164 | 0.0097 -> 0.0081 | +0.0149 [-0.0039, +0.0333] | +0.0384 [+0.0072, +0.0664] | 6/6 | -0.0032 / +0.0284 | pass | keep |
| **e1b_tuned_trees (shipped)** | 0.1751 -> 0.1824 | 0.1230 -> 0.1595 | 0.142 -> 0.193 | 0.0097 -> 0.0039 | +0.0073 [-0.0106, +0.0263] | +0.0365 [+0.0059, +0.0631] | 4/6 | +0.0049 / +0.0288 | pass | keep |
| e2_bag5 | 0.1751 -> 0.1802 | 0.1230 -> 0.1264 | 0.142 -> 0.158 | 0.0097 -> 0.0084 | +0.0051 [-0.0019, +0.0111] | +0.0034 [-0.0056, +0.0134] | 5/6 | +0.0055 / +0.0020 | fail | - |
| null | 0.1751 -> 0.1751 | 0.1230 -> 0.1230 | 0.142 -> 0.142 | 0.0097 -> 0.0097 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0/6 | +0.0000 / +0.0000 | fail | - |

**y_any_h4** (noise margin: validation 0.0004, flash 0.0094; the flash block is one fold of 335 rows)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Val folds up | Pooled delta val / flash | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.8844 -> 0.8853 | 0.8764 -> 0.8805 | 0.947 -> 0.960 | 0.0959 -> 0.1016 | +0.0009 [-0.0011, +0.0030] | +0.0041 [-0.0049, +0.0142] | 4/6 | +0.0060 / +0.0041 | pass | - |
| b1_basis_fix | 0.8844 -> 0.8835 | 0.8764 -> 0.8799 | 0.947 -> 0.980 | 0.0959 -> 0.0970 | -0.0009 [-0.0022, +0.0003] | +0.0035 [-0.0019, +0.0099] | 3/6 | -0.0015 / +0.0035 | fail | - |
| b2_slip_history | 0.8844 -> 0.8837 | 0.8764 -> 0.8809 | 0.947 -> 0.987 | 0.0959 -> 0.0990 | -0.0007 [-0.0025, +0.0011] | +0.0045 [-0.0035, +0.0135] | 3/6 | -0.0020 / +0.0045 | fail | - |
| b3_history_nofix | 0.8844 -> 0.8843 | 0.8764 -> 0.8802 | 0.947 -> 0.980 | 0.0959 -> 0.0979 | -0.0001 [-0.0020, +0.0017] | +0.0038 [-0.0031, +0.0115] | 3/6 | -0.0010 / +0.0038 | fail | - |
| b4_own_rates | 0.8844 -> 0.8841 | 0.8764 -> 0.8796 | 0.947 -> 0.953 | 0.0959 -> 0.0999 | -0.0003 [-0.0016, +0.0008] | +0.0032 [-0.0029, +0.0101] | 3/6 | -0.0021 / +0.0032 | fail | - |
| b5_push_history | 0.8844 -> 0.8830 | 0.8764 -> 0.8780 | 0.947 -> 0.967 | 0.0959 -> 0.1002 | -0.0014 [-0.0033, +0.0005] | +0.0016 [-0.0049, +0.0082] | 3/6 | -0.0021 / +0.0016 | fail | - |
| c1_name_flags | 0.8844 -> 0.8866 | 0.8764 -> 0.8746 | 0.947 -> 0.967 | 0.0959 -> 0.0922 | +0.0022 [-0.0004, +0.0047] | -0.0018 [-0.0093, +0.0066] | 5/6 | +0.0009 / -0.0018 | fail | - |
| c2_name_type | 0.8844 -> 0.8848 | 0.8764 -> 0.8792 | 0.947 -> 0.973 | 0.0959 -> 0.0876 | +0.0004 [-0.0035, +0.0041] | +0.0029 [-0.0047, +0.0116] | 3/6 | +0.0001 / +0.0029 | fail | - |
| **d1_decay_8q (shipped, then reverted)** | 0.8844 -> 0.8812 | 0.8764 -> 0.8795 | 0.947 -> 0.987 | 0.0959 -> 0.0836 | -0.0031 [-0.0097, +0.0035] | +0.0031 [-0.0135, +0.0200] | 2/6 | +0.0124 / +0.0031 | fail | - |
| d2_decay_16q | 0.8844 -> 0.8847 | 0.8764 -> 0.8777 | 0.947 -> 0.947 | 0.0959 -> 0.0933 | +0.0003 [-0.0040, +0.0043] | +0.0013 [-0.0089, +0.0114] | 2/6 | +0.0139 / +0.0013 | fail | - |
| d3_flash_x3 | 0.8844 -> 0.8844 | 0.8764 -> 0.8764 | 0.947 -> 0.947 | 0.0959 -> 0.0959 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0/6 | +0.0000 / +0.0000 | fail | - |
| e1_tuned_es | 0.8844 -> 0.8834 | 0.8764 -> 0.8593 | 0.947 -> 0.923 | 0.0959 -> 0.0770 | -0.0010 [-0.0047, +0.0025] | -0.0171 [-0.0463, +0.0111] | 4/6 | -0.0237 / -0.0171 | fail | - |
| e1b_tuned_trees | 0.8844 -> 0.8815 | 0.8764 -> 0.8646 | 0.947 -> 0.953 | 0.0959 -> 0.0671 | -0.0029 [-0.0070, +0.0009] | -0.0118 [-0.0293, +0.0042] | 1/6 | -0.0179 / -0.0118 | fail | - |
| e2_bag5 | 0.8844 -> 0.8844 | 0.8764 -> 0.8813 | 0.947 -> 0.973 | 0.0959 -> 0.0968 | -0.0000 [-0.0010, +0.0009] | +0.0049 [+0.0000, +0.0101] | 4/6 | -0.0007 / +0.0049 | fail | - |
| h4_feas_decay8 | 0.8844 -> 0.8848 | 0.8764 -> 0.8755 | 0.947 -> 0.940 | 0.0959 -> 0.0857 | +0.0004 [-0.0072, +0.0077] | -0.0009 [-0.0197, +0.0184] | 2/6 | +0.0174 / -0.0009 | fail | - |
| null | 0.8844 -> 0.8844 | 0.8764 -> 0.8764 | 0.947 -> 0.947 | 0.0959 -> 0.0959 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | 0/6 | +0.0000 / +0.0000 | fail | - |

## Why this one, and not the others

- **y_cost_rev_h2.** Both picks of the validation search pass the rule and the guard, with overlapping CIs:
  - early-stopped: +0.0149 validation (6 of 6 folds up) and +0.0384 flash;
  - tree count searched (`e1b_tuned_trees`): +0.0073 (4 of 6) and +0.0365.

  `e1b` was shipped in the first version as the simpler one: a fixed 150 trees, no inner fit, and the lower
  validation ECE (0.0039 against 0.0081 raw). It stays. Switching to the early-stopped pick because it now looks a
  little better on these same blocks would be one more choice made after seeing them.

  The params were chosen on `y_any_h2`'s validation block, but that block's quarters are this target's validation
  quarters too, and y_any labels include every cost-revision positive; the search itself chose among 21 trials on
  a gain of +0.0013 pooled, well inside the noise. So the params carry no independent evidence of their own. What
  backs them is the flash block: 3 of 3 folds up, with a CI above 0. The likely reason they help is
  regularisation: lambda 20, a 0.02 learning rate and 150 trees suit a label with 2-6% positives per fold.
- **y_any_h4.** Nothing ships.
  - The 8-quarter half-life, shipped first, ranks worse inside 4 of the 6 validation folds (2022-10 to 2023-07) in
    every seed: -0.0031 as a fold mean. Its pooled gain (+0.0124) came from lowering its score level on the later
    folds, where the champion over-predicts: on the last three, a mean score of 0.72 to 0.74 against slip rates of
    0.58 to 0.59, which the half-life brings down to 0.68 to 0.71 (seed 0). That is calibration across folds, and
    an as-of date only ever ranks its own projects. It also raised flash ECE (0.080 to
    0.106) and lowered the not-yet-due slice (validation 0.588 to 0.570). The 16-quarter half-life (+0.0003) and
    feasibility together with the 8-quarter one (+0.0004 / -0.0009) fail as well.
  - Feasibility (`a_feasibility`) passes the rule, +0.0009 validation and +0.0041 flash, but every CI includes 0:
    it clears the tiny validation margin (0.0004) without evidence of a gain. It stays out.
- **Passed the rule, not the guard.** a_feasibility on y_any_h4 (above) is the only one. The four results in this
  list in the first version (a_feasibility, b4_own_rates and c2_name_type on y_cost_rev_h2, c2_name_type on y_any_h4)
  no longer pass the rule at all on within-cutoff PR-AUC.

## Interval honesty (g)

These are the served intervals' coverage and pinball loss. The nominal p05-p95 coverage is 90%. The file is
`model/runs/ML-20260928-072744/intervals.csv`, and the same numbers are written in every train run. The cost %
validation block moved with the disjoint windows (2023-07 to 2024-10).

| Interval | Block | n | Coverage | Below p05 | Above p95 | Mean width | Pinball p05 | Pinball p50 | Pinball p95 |
|---|---|---|---|---|---|---|---|---|---|
| months pushed | validation | 10,063 | 0.915 | 0.033 | 0.052 | 12.5 | 0.643 | 1.671 | 0.822 |
| months pushed | flash | 2,613 | 0.883 | 0.018 | 0.099 | 11.4 | 0.426 | 2.062 | 1.068 |
| cost change % | validation | 9,392 | 0.956 | 0.013 | 0.031 | 9.6 | 0.205 | 0.859 | 1.345 |
| cost change % | flash | 3,617 | 0.955 | 0.023 | 0.022 | 11.0 | 0.454 | 0.783 | 1.118 |

The month intervals are about right in the quarterly era. In the flash era they miss on the upper side: 9.9% of flash
projects slipped more than p95. The cost intervals over-cover in both eras.

A conformal adjustment was tried in two forms, both fitted on the folds realised by each cutoff.

- **Symmetric (CQR).** The widening came out at exactly 0 on every fold, so nothing changed (`g_intervals`). The
  realised folds already cover at least 90%. The month labels are whole numbers with a mass at 0 months, so the 90th
  percentile of the conformity score lands exactly on 0.
- **Asymmetric** (each tail on its own, `g2_intervals_asym`). Month coverage moved away from 90% on validation (0.915
  to 0.917) and barely moved on flash (0.883 to 0.884). Cost was unchanged.

The keep criterion was coverage moving toward 90% on both blocks, with no worse pinball loss at p50. Neither form met
it, so neither ships. p50 and its pinball loss are unchanged by construction. Correcting the flash-era upper tail would
need calibration folds from the flash era itself, and too few are realised yet.

## Tuning (e)

- **The search.** There were 20 random trials over learning rate, leaves, minimum child samples, feature and row
  fractions, L1/L2 penalty and minimum split gain, scored on `y_any_h2`'s validation block only (seed 0), on pooled
  PR-AUC (the search ran before the review). The flash block was kept out of the search. Two searches ran:
  - with the tree count set by early stopping on an inner time split of the training rows (`tune_y_any_h2.csv`);
  - with the tree count as a search dimension of 150 to 1,000 trees (`tune_y_any_h2_trees.csv`).
- **Early stopping.** It keeps only about 50 to 400 trees (the mean per trial). The inner stopping set, the two
  newest training quarters, is a different era from most of the training rows. With the champion's params, early
  stopping alone lost 0.003 validation PR-AUC (trial 0).
- **The best trials.** The early-stopped search's best was trial 13: +0.0054 validation on the seed it was chosen on,
  the best of 21. The tree-count search's best was trial 14: +0.0013. Both are now fixed candidates, judged like any
  other. Both collapse on the flash block for the two date targets:
  - y_any_h2: -0.041 to -0.043;
  - y_date_push_h2: -0.039 to -0.058, although they gain on its validation block (+0.011 to +0.017, CIs above 0).

  They also lose on y_any_h4 (flash -0.012 to -0.017). The shared `LGB_PARAMS` stay untuned.
- **Seed bagging.** Five seeds (`e2_bag5`) stayed inside the noise everywhere. On y_any_h2 the flash gain was +0.0060
  with a CI above 0, but the flash margin is 0.0134.

## What was rejected, and why

All deltas are within-cutoff, validation / flash.

- **Deadline feasibility (a).** It cost y_any_h2 0.006 validation PR-AUC, with a CI below 0, and passed nowhere with
  the guard. Its progress-based ratios are null wherever progress is not printed: at three of the six validation
  folds (2023-07 to 2024-01) and in every row before 2014.
- **Basis-change revision fix (b1).** This masks a revision "event" when the printed value switches basis, for example
  from anticipated to revised. It lowered y_any_h2 validation (-0.0033, CI below 0). A basis change often goes with a
  real revision, so the unmasked event carries signal. `base()` keeps counting it, and the choice is recorded there.
- **Slip history (b2 to b5).** A regime flip on y_date_push_h2: validation gains of +0.005 to +0.007 with CIs above
  0 (b2, b3, b5), but flash losses of 0.010 to 0.017 with CIs below 0. In flash reports the date is the revised one,
  and a project's own history changes meaning. It was inside the noise elsewhere.
- **Name keywords (c1, c2).** Inside the noise on every target. Sector, state and cost band likely carry most of what
  the type says.
- **Age weights (d1, d2).** Lower on the flash block for every 2-quarter target (-0.013 to -0.027), and for
  y_cost_rev_h2 on validation too. On y_any_h4 they rank worse inside most validation folds (see above). The models
  need the older eras.
- **Flash rows 3x (d3).** No validation effect by construction, since flash rows are not yet in those folds' training.
  Flash gains stayed under the margin, and y_cost_rev_h2 flash fell by 0.009.
- **Cross-target ensembles for y_any_h2 (f1, f2).** Validation fell by 0.010 and 0.003 (f1's CI below 0). The better
  ECE (0.060 and 0.071) does not make up for the worse ranking. Stacking was not built: both fixed combinations lost,
  and its only honest inputs would be rolling-origin predictions from earlier folds, as with the Platt folds.
- **Tuning, early stopping and bagging (e) on the other targets.** Covered in the tuning section above.
- **Conformal intervals (g).** Covered in the interval section above.

Each rejection is recorded as a short comment where its knob lives:

- `pipeline/gold.py`: `FEATURE_GROUPS` and `base()`;
- `ml/backtest.py`: `TARGETS`, `LGB_PARAMS` / `TARGET_PARAMS`, and the module docstring for the intervals.

## Considered and not built

- **Remark-text features** (TF-IDF, keyword flags or out-of-fold text scores from the report remarks). Free text ends
  in 2023-Q2. None of the following see any: the 2-quarter validation folds (2023-07 to 2024-10), the flash folds,
  the test fold and live scoring. Later reports print only "start: YYYY-MM". Such a feature could show up only as an
  artefact on the four-quarter folds 2022-10 to 2023-04, and it has no value at serving time. Remark text stays as
  evidence for people and for retrieval, not a model input.
- **News or web-research counts as features** (articles, research facts or LLM notes per risk category). There is no
  point-in-time history: the signals table starts in 2026, so a backtest would train on nothing and score on nothing.
  Worse, the counts carry notoriety bias:
  - search results reflect later notoriety, so projects that ended up badly delayed have more coverage;
  - articles are written or edited after the fact;
  - the local LLM knows outcomes up to its training cutoff.

  A backtest on such counts would reward the leak. If they are ever used, it must be as a prospective shadow model,
  logged in prediction_log with dated queries, never as a backtested feature.

## Caveats

- **The cost revision's promotion is provisional.** Its evidence is the flash block (+0.0365, CI above 0, 3 of 3
  folds up); its validation gain (+0.0073) only just clears the margin, with a CI that includes 0. And the flash
  results of all four targets had been seen before this target and this variant were chosen. So a check was fixed in
  advance, before its data exist: the 2026-04 fold, once its outcome quarter (2026-10) is reported. Backtest the
  tuned params and `LGB_PARAMS` there (3 seeds, within-cutoff PR-AUC, champions of ML-20260927-222602 for the
  plain side). If the tuned params are lower, drop them from `TARGET_PARAMS` and run
  `python -m ml.registry revert y_cost_rev_h2`.
- **The primary target did not improve.** No candidate of this round moves y_any_h2 beyond seed noise on both
  blocks. Its largest remaining lever is still `months_to_anticipated_completion`, which carries 1.1 of SHAP mass
  against 0.23 for the next feature.
- **Multiple comparisons.** The guard reduces them, but does not remove them.
- **Small folds.** Within-cutoff PR-AUC averages folds of 20 to 90 cost-revision positives each, so a single fold can
  swing it (2025-10 has 21). The y_any_h4 validation margin is tiny (its seeds agree to 0.0002), so on that block the
  rule is easy to pass; the guard's CI is what keeps a pass honest there.
- **What the train run's gate compared.** Gold did not change in this round. y_any_h2, y_date_push_h2 and y_any_h4
  kept their folds and re-scored their champions' configurations at zero gain. The cost revision's folds moved, so
  its tuned configuration was re-scored on them and took over. The gate scores seed 0; the evidence for a change is
  the 3-seed harness.
- **Bottleneck files.** The profile step's risk profile and external summary were rebuilt. The bottleneck files were
  left as built: they depend on the app's live news signals, not on these models.

## Runtime (this laptop, 16 threads)

- **Harness.** 3 to 7 minutes per candidate on all four targets with the champion predictions cached, 13 minutes for
  five-seed bagging; up to 23 minutes when the machine was shared with other jobs. Two ran in parallel. The
  re-measurement of all 19 candidates took 66 minutes, and the 5-seed noise measurement 10 minutes.
- **Tuning.** 6 to 8 minutes per 20-trial search.
- **Interval experiments.** 1 to 2 minutes.
- **Pipeline.** train 245 s (the interval backtest adds about 40 s), score 19 s, risk profile 3 s.

## Reproduce

```
python -m ml.experiment --list                                  # the catalogue
python -m ml.experiment --seed-sd --champion-run ML-20260927-222602      # the noise margins
python -m ml.experiment d1_decay_8q --champion-run ML-20260927-222602    # one candidate -> model/experiments/
python -m ml.experiment --tune y_any_h2 [--no-es]
python -m ml.experiment g_intervals
python -m ml.experiment --table                                 # the tables above
python -m pipeline.run train                                    # the registry gate decides per target
python -m pipeline.run score
python -m pipeline.run profile
```

Without `--champion-run` the harness compares with the current champions, which for y_cost_rev_h2 is now the tuned
configuration.
