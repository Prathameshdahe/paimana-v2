# Model upgrades, September 2026

This round set out to raise the predictive quality of the four targets: the primary one, any slip or cost revision
within two quarters (`y_any_h2`), and also `y_date_push_h2`, `y_cost_rev_h2` and `y_any_h4`. Every change was
measured against the registry champion on the same rows and folds. A change was kept only if it beat the champion on
both the validation and the flash blocks.

**Outcome.** Nineteen candidates were measured on every target. Two changes shipped, each for one target:

- `y_cost_rev_h2` trains with regularised LightGBM params: learning rate 0.02, 63 leaves, lambda 20 and 150 trees.
- `y_any_h4` weights training rows by age, with a half-life of 8 quarters.

Nothing passed for `y_any_h2` or `y_date_push_h2`. Their champions are unchanged, and so are the tiers, which rank
`p_any_2q`.

Other changes this round:

- The registry now gates new features honestly.
- Every train run now backtests the served intervals.
- There is now a reusable experiment harness.

## Served champions, before and after

The numbers are the registry's (seed 0, as served; the cost revision is Platt-calibrated). The test fold of the
2-quarter targets (2026-01) is also a flash cutoff, so it is not independent. The y_any_h4 test fold (2024-04) is.

| Target | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Test PR-AUC | Decision |
|---|---|---|---|---|---|---|
| y_any_h2 | 0.7015 (unchanged) | 0.7753 | 0.913 | 0.0815 | 0.778 | no candidate passed; champion ML-20260927-222602 kept |
| y_date_push_h2 | 0.6287 (unchanged) | 0.7712 | 0.920 | 0.0512 | 0.764 | no candidate passed; champion kept |
| y_cost_rev_h2 | 0.1085 -> **0.1233** | 0.0995 -> **0.1263** | 0.147 -> 0.193 | 0.0072 -> 0.0085 | 0.184 -> 0.230 | tuned params, promoted (ML-20260928-051908) |
| y_any_h4 | 0.8690 -> **0.8811** | 0.8719 -> **0.8849** | 0.940 -> 1.000 | 0.0954 -> 0.0830 | 0.753 -> 0.756 | 8-quarter age weights, promoted (ML-20260928-051908) |

The harness means over 3 seeds, with the paired project bootstrap CI of each delta:

| Target | Change | Validation delta [95% CI] | Flash delta [95% CI] |
|---|---|---|---|
| y_cost_rev_h2 | `e1b_tuned_trees` | +0.0105 [-0.0052, +0.0251] | +0.0288 [+0.0077, +0.0499] |
| y_any_h4 | `d1_decay_8q` | +0.0124 [+0.0050, +0.0204] | +0.0031 [-0.0135, +0.0200] |

For y_any_h4, the served model also changes in two ways the delta table does not show:

- The not-yet-due slice falls slightly: validation nyd PR-AUC goes from 0.582 to 0.570.
- Flash-block ECE rises from 0.078 to 0.102. That block is a single fold of 335 rows.

The promotion rule does not use either number.

## What changed in the code

- **Experiment harness** (`ml/experiment.py`, `python -m ml.experiment <candidate>`). It compares the champion and a
  challenger on the validation and flash blocks of all four targets, over 3 seeds. It reports the paired project
  bootstrap CI of the PR-AUC delta, uses the promotion rule as the decision and writes
  `model/experiments/<candidate>.csv`.
  - Champion predictions are cached per gold version under `temp/`.
  - `--table` prints the tables below.
  - `--tune` runs the search.
  - The catalogue keeps every candidate of this round, so any result can be re-run.
- **Honest registry gate** (`ml/registry.py`). A run on a new gold version used to promote the new LightGBM with no
  metric check. So a new feature family, which always changes the gold version, was never gated. Now such a run also
  backtests the champion's own configuration on the new gold and folds, as `<type>_incumbent`: its type, feature list,
  categoricals and params. That re-scored configuration takes over first, and every new configuration must then beat
  it under the rule.
  - Across gold versions, only the same configuration may take over.
  - A champion whose features have left the gold is retired, and the decision is recorded.
  - The registry file format is unchanged, apart from an optional `rescored_from` field.
  - Scoring refits each champion with its entry's own params (`registry.fitter`).
- **Per-target params** (`backtest.TARGET_PARAMS`, `backtest.lgb_params`). One target can train with its own
  LightGBM params. `half_life_q` becomes sample weights inside `fit_lgbm`.
- **Interval backtest** (`intervals.csv` in every run). The score step's quantile models (5/50/95% of months pushed
  and cost change %) are backtested on the validation and flash cutoffs of `y_date_push_h2` and `y_cost_rev_h2`. The
  file reports p05-p95 coverage, the share below and above the band, mean width and pinball loss. `score.py` fits
  through the same `backtest.fit_quantiles`, and its outputs are unchanged.
- **Model version.** Champions can now come from different runs. The served `model_version` therefore lists every
  champion run, for example `lgbm-any2q-20260927-222602+20260928-051908`, because cached briefs and the prediction log
  are keyed on it.

## How a candidate was judged

- **Harness.** The champion of each target is its registry entry: its feature list, categoricals and LightGBM
  params. A challenger changes one thing: extra columns, a replaced column, another fit function or sample weights.
  Both are backtested with `ml/backtest.py` on the same rows and cutoffs, once per seed (0, 1 and 2):
  - the validation block: quarterly-report era, 6 cutoffs;
  - the flash block: every cutoff from 2025-07.

  All numbers are means over the three seeds.
- **Confidence interval.** Each block's PR-AUC delta gets a paired project bootstrap: 2,000 resamples of the block's
  projects with replacement. Each drawn project brings all its fold rows, and both models' seed-mean PR-AUC is
  recomputed on each resample.
- **Rule** (`registry.rule`, the same rule the registry promotes with). The challenger passes only if:
  - its PR-AUC gain is at least 0 on both blocks;
  - its gain is at least 2 x the measured seed SD (`registry.SEED_SD`) on at least one block;
  - its validation ECE is at most the champion's + 0.02.
- **Ship guard.** On top of the rule, some block that clears the margin must also have its bootstrap CI above 0.
  Nineteen candidates on four targets make many chances to pass by luck. The y_any_h4 flash block is one fold of 335
  rows, where seed-to-seed deltas swing by 0.012, and cost-revision PR-AUC sits near 0.1. Four target results passed
  the rule without passing the guard (see the tables).
- **Point in time.** A candidate's columns at a cutoff must be identical when built from data cut at that cutoff.
  This is checked at 2023-07 and 2025-10 before any fit. Every candidate reads only its own row or outcomes realised
  by t.
- **Raw scores.** The harness compares raw cost-revision scores. The registry's gate compares the Platt-calibrated
  ones.
- **Sanity.** The null candidate (the champion against itself) returns exactly zero deltas on every target.
- **Final confirmation.** The shipped configurations then went through the registry gate in a real train run, on the
  same gold (2676494d0207) and folds as the stored champions:
  - y_cost_rev_h2: validation +0.0149, flash +0.0269;
  - y_any_h4: validation +0.0121, flash +0.0130;
  - y_any_h2 and y_date_push_h2: the unchanged configuration re-scored at zero gain, so their champions stay.

## Results per target

Val and Flash show the champion's PR-AUC, then the challenger's; ECE is on the validation block. Rule is the promotion
rule; Ship is the rule plus the guard. The candidates are:

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

**y_any_h2** (noise margin 0.0076)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Rule | Ship |
|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.7014 -> 0.6881 | 0.7754 -> 0.7800 | 0.898 -> 0.924 | 0.0818 -> 0.0849 | -0.0134 [-0.0197, -0.0073] | +0.0047 [-0.0016, +0.0109] | fail | - |
| b1_basis_fix | 0.7014 -> 0.6989 | 0.7754 -> 0.7769 | 0.898 -> 0.902 | 0.0818 -> 0.0823 | -0.0025 [-0.0043, -0.0008] | +0.0015 [-0.0017, +0.0046] | fail | - |
| b2_slip_history | 0.7014 -> 0.7039 | 0.7754 -> 0.7783 | 0.898 -> 0.907 | 0.0818 -> 0.0856 | +0.0024 [-0.0012, +0.0060] | +0.0029 [-0.0026, +0.0086] | fail | - |
| b3_history_nofix | 0.7014 -> 0.6983 | 0.7754 -> 0.7743 | 0.898 -> 0.909 | 0.0818 -> 0.0860 | -0.0032 [-0.0068, +0.0005] | -0.0011 [-0.0065, +0.0046] | fail | - |
| b4_own_rates | 0.7014 -> 0.6988 | 0.7754 -> 0.7768 | 0.898 -> 0.898 | 0.0818 -> 0.0847 | -0.0027 [-0.0048, -0.0004] | +0.0014 [-0.0022, +0.0048] | fail | - |
| b5_push_history | 0.7014 -> 0.6997 | 0.7754 -> 0.7703 | 0.898 -> 0.900 | 0.0818 -> 0.0863 | -0.0017 [-0.0053, +0.0021] | -0.0051 [-0.0116, +0.0014] | fail | - |
| c1_name_flags | 0.7014 -> 0.6998 | 0.7754 -> 0.7766 | 0.898 -> 0.884 | 0.0818 -> 0.0798 | -0.0017 [-0.0040, +0.0005] | +0.0013 [-0.0026, +0.0050] | fail | - |
| c2_name_type | 0.7014 -> 0.7000 | 0.7754 -> 0.7700 | 0.898 -> 0.893 | 0.0818 -> 0.0783 | -0.0015 [-0.0042, +0.0014] | -0.0053 [-0.0112, +0.0001] | fail | - |
| d1_decay_8q | 0.7014 -> 0.6869 | 0.7754 -> 0.7572 | 0.898 -> 0.896 | 0.0818 -> 0.0778 | -0.0145 [-0.0223, -0.0073] | -0.0182 [-0.0296, -0.0062] | fail | - |
| d2_decay_16q | 0.7014 -> 0.6947 | 0.7754 -> 0.7643 | 0.898 -> 0.907 | 0.0818 -> 0.0806 | -0.0067 [-0.0119, -0.0017] | -0.0111 [-0.0191, -0.0032] | fail | - |
| d3_flash_x3 | 0.7014 -> 0.7014 | 0.7754 -> 0.7779 | 0.898 -> 0.902 | 0.0818 -> 0.0818 | +0.0000 [+0.0000, +0.0000] | +0.0026 [-0.0004, +0.0055] | fail | - |
| e1_tuned_es | 0.7014 -> 0.7041 | 0.7754 -> 0.7304 | 0.898 -> 0.802 | 0.0818 -> 0.0796 | +0.0027 [-0.0039, +0.0095] | -0.0450 [-0.0538, -0.0359] | fail | - |
| e1b_tuned_trees | 0.7014 -> 0.7026 | 0.7754 -> 0.7304 | 0.898 -> 0.758 | 0.0818 -> 0.0675 | +0.0011 [-0.0042, +0.0065] | -0.0449 [-0.0580, -0.0302] | fail | - |
| e2_bag5 | 0.7014 -> 0.7019 | 0.7754 -> 0.7801 | 0.898 -> 0.904 | 0.0818 -> 0.0823 | +0.0005 [-0.0008, +0.0018] | +0.0048 [+0.0025, +0.0070] | fail | - |
| f1_any_or | 0.7014 -> 0.6817 | 0.7754 -> 0.7727 | 0.898 -> 0.896 | 0.0818 -> 0.0598 | -0.0197 [-0.0265, -0.0128] | -0.0026 [-0.0096, +0.0043] | fail | - |
| f2_any_avg | 0.7014 -> 0.6929 | 0.7754 -> 0.7769 | 0.898 -> 0.904 | 0.0818 -> 0.0708 | -0.0085 [-0.0128, -0.0044] | +0.0015 [-0.0016, +0.0047] | fail | - |
| null | 0.7014 -> 0.7014 | 0.7754 -> 0.7754 | 0.898 -> 0.898 | 0.0818 -> 0.0818 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | fail | - |

**y_date_push_h2** (noise margin 0.0050)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Rule | Ship |
|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.6260 -> 0.6286 | 0.7689 -> 0.7684 | 0.909 -> 0.900 | 0.0555 -> 0.0533 | +0.0026 [-0.0029, +0.0078] | -0.0005 [-0.0069, +0.0062] | fail | - |
| b1_basis_fix | 0.6260 -> 0.6264 | 0.7689 -> 0.7724 | 0.909 -> 0.911 | 0.0555 -> 0.0543 | +0.0005 [-0.0014, +0.0024] | +0.0035 [+0.0001, +0.0069] | fail | - |
| b2_slip_history | 0.6260 -> 0.6327 | 0.7689 -> 0.7553 | 0.909 -> 0.884 | 0.0555 -> 0.0600 | +0.0067 [+0.0031, +0.0107] | -0.0136 [-0.0201, -0.0075] | fail | - |
| b3_history_nofix | 0.6260 -> 0.6336 | 0.7689 -> 0.7590 | 0.909 -> 0.904 | 0.0555 -> 0.0601 | +0.0077 [+0.0041, +0.0117] | -0.0099 [-0.0168, -0.0033] | fail | - |
| b4_own_rates | 0.6260 -> 0.6268 | 0.7689 -> 0.7729 | 0.909 -> 0.907 | 0.0555 -> 0.0559 | +0.0008 [-0.0013, +0.0030] | +0.0040 [+0.0007, +0.0072] | fail | - |
| b5_push_history | 0.6260 -> 0.6297 | 0.7689 -> 0.7607 | 0.909 -> 0.909 | 0.0555 -> 0.0590 | +0.0038 [+0.0006, +0.0075] | -0.0082 [-0.0136, -0.0028] | fail | - |
| c1_name_flags | 0.6260 -> 0.6247 | 0.7689 -> 0.7694 | 0.909 -> 0.902 | 0.0555 -> 0.0526 | -0.0012 [-0.0039, +0.0017] | +0.0005 [-0.0033, +0.0039] | fail | - |
| c2_name_type | 0.6260 -> 0.6293 | 0.7689 -> 0.7693 | 0.909 -> 0.900 | 0.0555 -> 0.0518 | +0.0034 [-0.0003, +0.0076] | +0.0004 [-0.0041, +0.0048] | fail | - |
| d1_decay_8q | 0.6260 -> 0.6272 | 0.7689 -> 0.7530 | 0.909 -> 0.891 | 0.0555 -> 0.0556 | +0.0012 [-0.0068, +0.0097] | -0.0159 [-0.0243, -0.0072] | fail | - |
| d2_decay_16q | 0.6260 -> 0.6339 | 0.7689 -> 0.7577 | 0.909 -> 0.891 | 0.0555 -> 0.0543 | +0.0079 [+0.0017, +0.0139] | -0.0112 [-0.0179, -0.0048] | fail | - |
| d3_flash_x3 | 0.6260 -> 0.6260 | 0.7689 -> 0.7692 | 0.909 -> 0.907 | 0.0555 -> 0.0555 | +0.0000 [+0.0000, +0.0000] | +0.0003 [-0.0031, +0.0036] | fail | - |
| e1_tuned_es | 0.6260 -> 0.6326 | 0.7689 -> 0.7139 | 0.909 -> 0.762 | 0.0555 -> 0.0585 | +0.0067 [-0.0013, +0.0153] | -0.0550 [-0.0651, -0.0449] | fail | - |
| e1b_tuned_trees | 0.6260 -> 0.6358 | 0.7689 -> 0.7304 | 0.909 -> 0.807 | 0.0555 -> 0.0455 | +0.0098 [+0.0040, +0.0158] | -0.0385 [-0.0508, -0.0260] | fail | - |
| e2_bag5 | 0.6260 -> 0.6256 | 0.7689 -> 0.7694 | 0.909 -> 0.898 | 0.0555 -> 0.0546 | -0.0003 [-0.0019, +0.0014] | +0.0005 [-0.0020, +0.0027] | fail | - |
| null | 0.6260 -> 0.6260 | 0.7689 -> 0.7689 | 0.909 -> 0.909 | 0.0555 -> 0.0555 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | fail | - |

**y_cost_rev_h2** (noise margin 0.0044; raw scores)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Rule | Ship |
|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.1082 -> 0.1115 | 0.0966 -> 0.1030 | 0.142 -> 0.153 | 0.0088 -> 0.0089 | +0.0033 [-0.0065, +0.0112] | +0.0064 [-0.0040, +0.0158] | pass | - |
| b1_basis_fix | 0.1082 -> 0.1105 | 0.0966 -> 0.1004 | 0.142 -> 0.151 | 0.0088 -> 0.0090 | +0.0022 [-0.0023, +0.0064] | +0.0038 [-0.0030, +0.0091] | fail | - |
| b2_slip_history | 0.1082 -> 0.1050 | 0.0966 -> 0.0936 | 0.142 -> 0.142 | 0.0088 -> 0.0089 | -0.0032 [-0.0148, +0.0047] | -0.0030 [-0.0171, +0.0056] | fail | - |
| b3_history_nofix | 0.1082 -> 0.1064 | 0.0966 -> 0.0911 | 0.142 -> 0.131 | 0.0088 -> 0.0089 | -0.0018 [-0.0112, +0.0047] | -0.0056 [-0.0167, +0.0014] | fail | - |
| b4_own_rates | 0.1082 -> 0.1090 | 0.0966 -> 0.1016 | 0.142 -> 0.140 | 0.0088 -> 0.0093 | +0.0008 [-0.0085, +0.0085] | +0.0049 [-0.0096, +0.0146] | pass | - |
| b5_push_history | 0.1082 -> 0.1115 | 0.0966 -> 0.0979 | 0.142 -> 0.138 | 0.0088 -> 0.0088 | +0.0033 [-0.0048, +0.0090] | +0.0013 [-0.0088, +0.0090] | fail | - |
| c1_name_flags | 0.1082 -> 0.1128 | 0.0966 -> 0.0956 | 0.142 -> 0.136 | 0.0088 -> 0.0087 | +0.0046 [-0.0029, +0.0097] | -0.0010 [-0.0115, +0.0057] | fail | - |
| c2_name_type | 0.1082 -> 0.1087 | 0.0966 -> 0.1014 | 0.142 -> 0.140 | 0.0088 -> 0.0097 | +0.0005 [-0.0092, +0.0089] | +0.0048 [-0.0065, +0.0147] | pass | - |
| d1_decay_8q | 0.1082 -> 0.0931 | 0.0966 -> 0.0731 | 0.142 -> 0.122 | 0.0088 -> 0.0124 | -0.0151 [-0.0333, -0.0028] | -0.0235 [-0.0523, -0.0091] | fail | - |
| d2_decay_16q | 0.1082 -> 0.1055 | 0.0966 -> 0.0793 | 0.142 -> 0.127 | 0.0088 -> 0.0110 | -0.0028 [-0.0162, +0.0069] | -0.0173 [-0.0389, -0.0063] | fail | - |
| d3_flash_x3 | 0.1082 -> 0.1082 | 0.0966 -> 0.0862 | 0.142 -> 0.138 | 0.0088 -> 0.0088 | +0.0000 [+0.0000, +0.0000] | -0.0104 [-0.0188, -0.0046] | fail | - |
| e1_tuned_es | 0.1082 -> 0.1195 | 0.0966 -> 0.1250 | 0.142 -> 0.164 | 0.0088 -> 0.0111 | +0.0113 [-0.0022, +0.0240] | +0.0284 [+0.0087, +0.0477] | pass | keep |
| **e1b_tuned_trees (shipped)** | 0.1082 -> 0.1187 | 0.0966 -> 0.1254 | 0.142 -> 0.193 | 0.0088 -> 0.0077 | +0.0105 [-0.0052, +0.0251] | +0.0288 [+0.0077, +0.0499] | pass | keep |
| e2_bag5 | 0.1082 -> 0.1126 | 0.0966 -> 0.0986 | 0.142 -> 0.158 | 0.0088 -> 0.0078 | +0.0044 [+0.0001, +0.0109] | +0.0020 [-0.0051, +0.0072] | fail | - |
| null | 0.1082 -> 0.1082 | 0.0966 -> 0.0966 | 0.142 -> 0.142 | 0.0088 -> 0.0088 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | fail | - |

**y_any_h4** (noise margin 0.0022; the flash block is one fold of 335 rows)

| Candidate | Val PR-AUC | Flash PR-AUC | Flash P@50 | Val ECE | Val delta [95% CI] | Flash delta [95% CI] | Rule | Ship |
|---|---|---|---|---|---|---|---|---|
| a_feasibility | 0.8691 -> 0.8751 | 0.8764 -> 0.8805 | 0.947 -> 0.960 | 0.0959 -> 0.1016 | +0.0060 [+0.0035, +0.0090] | +0.0041 [-0.0049, +0.0142] | pass | keep |
| b1_basis_fix | 0.8691 -> 0.8675 | 0.8764 -> 0.8799 | 0.947 -> 0.980 | 0.0959 -> 0.0970 | -0.0015 [-0.0027, -0.0003] | +0.0035 [-0.0019, +0.0099] | fail | - |
| b2_slip_history | 0.8691 -> 0.8671 | 0.8764 -> 0.8809 | 0.947 -> 0.987 | 0.0959 -> 0.0990 | -0.0020 [-0.0040, -0.0000] | +0.0045 [-0.0035, +0.0135] | fail | - |
| b3_history_nofix | 0.8691 -> 0.8681 | 0.8764 -> 0.8802 | 0.947 -> 0.980 | 0.0959 -> 0.0979 | -0.0010 [-0.0031, +0.0010] | +0.0038 [-0.0031, +0.0115] | fail | - |
| b4_own_rates | 0.8691 -> 0.8670 | 0.8764 -> 0.8796 | 0.947 -> 0.953 | 0.0959 -> 0.0999 | -0.0021 [-0.0035, -0.0008] | +0.0032 [-0.0029, +0.0101] | fail | - |
| b5_push_history | 0.8691 -> 0.8670 | 0.8764 -> 0.8780 | 0.947 -> 0.967 | 0.0959 -> 0.1002 | -0.0021 [-0.0043, +0.0000] | +0.0016 [-0.0049, +0.0082] | fail | - |
| c1_name_flags | 0.8691 -> 0.8700 | 0.8764 -> 0.8746 | 0.947 -> 0.967 | 0.0959 -> 0.0922 | +0.0009 [-0.0019, +0.0038] | -0.0018 [-0.0093, +0.0066] | fail | - |
| c2_name_type | 0.8691 -> 0.8692 | 0.8764 -> 0.8792 | 0.947 -> 0.973 | 0.0959 -> 0.0876 | +0.0001 [-0.0040, +0.0042] | +0.0029 [-0.0047, +0.0116] | pass | - |
| **d1_decay_8q (shipped)** | 0.8691 -> 0.8815 | 0.8764 -> 0.8795 | 0.947 -> 0.987 | 0.0959 -> 0.0836 | +0.0124 [+0.0050, +0.0204] | +0.0031 [-0.0135, +0.0200] | pass | keep |
| d2_decay_16q | 0.8691 -> 0.8829 | 0.8764 -> 0.8777 | 0.947 -> 0.947 | 0.0959 -> 0.0933 | +0.0139 [+0.0083, +0.0198] | +0.0013 [-0.0089, +0.0114] | pass | keep |
| d3_flash_x3 | 0.8691 -> 0.8691 | 0.8764 -> 0.8764 | 0.947 -> 0.947 | 0.0959 -> 0.0959 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | fail | - |
| e1_tuned_es | 0.8691 -> 0.8453 | 0.8764 -> 0.8593 | 0.947 -> 0.923 | 0.0959 -> 0.0770 | -0.0237 [-0.0292, -0.0182] | -0.0171 [-0.0463, +0.0111] | fail | - |
| e1b_tuned_trees | 0.8691 -> 0.8512 | 0.8764 -> 0.8646 | 0.947 -> 0.953 | 0.0959 -> 0.0671 | -0.0179 [-0.0233, -0.0129] | -0.0118 [-0.0293, +0.0042] | fail | - |
| e2_bag5 | 0.8691 -> 0.8684 | 0.8764 -> 0.8813 | 0.947 -> 0.973 | 0.0959 -> 0.0968 | -0.0007 [-0.0016, +0.0001] | +0.0049 [+0.0000, +0.0101] | fail | - |
| h4_feas_decay8 | 0.8691 -> 0.8865 | 0.8764 -> 0.8755 | 0.947 -> 0.940 | 0.0959 -> 0.0857 | +0.0174 [+0.0082, +0.0271] | -0.0009 [-0.0197, +0.0184] | fail | - |
| null | 0.8691 -> 0.8691 | 0.8764 -> 0.8764 | 0.947 -> 0.947 | 0.0959 -> 0.0959 | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | fail | - |

## Why these two, and not the others that passed

- **y_any_h4.** Three candidates passed the rule and the guard:
  - feasibility: +0.0060 validation and +0.0041 flash;
  - the 8-quarter half-life: +0.0124 and +0.0031;
  - the 16-quarter half-life: +0.0139 and +0.0013.

  Only one change can ship for a target unless the changes are measured together. Feasibility together with the
  8-quarter half-life (`h4_feas_decay8`) failed the rule: validation rose by 0.0174, but flash fell by 0.0009. So
  only one of the three shipped.

  Weighted by precision, the two half-lives gain the same (0.0108 and 0.0109), both well above feasibility (0.0059).
  The 8-quarter half-life was declared first, so it ships. The 16-quarter result is the same finding again, not a
  better one.

  A half-life is the soft version of the `TRAIN_FROM` cut that was reverted earlier. That cut trained from 2014 only
  and lost 0.024 on the same flash fold; the half-life does not lose there on average.
- **y_cost_rev_h2.** Both picks of the validation search passed with overlapping CIs:
  - early-stopped: +0.0113 validation and +0.0284 flash;
  - tree count searched: +0.0105 and +0.0288.

  The simpler one ships: a fixed 150 trees, no inner fit, and the lower validation ECE (0.0077 against 0.0111).

  The params were chosen on `y_any_h2`'s validation block, not on this target, so the cost gains carry no selection
  bias from the search itself. The likely reason they help is regularisation: lambda 20, a 0.02 learning rate and 150
  trees suit a label with 5% positives.
- **Passed the rule, not the guard.** These stayed out because every CI they have includes 0:
  - a_feasibility, b4_own_rates and c2_name_type on y_cost_rev_h2;
  - c2_name_type on y_any_h4.

## Interval honesty (g)

These are the served intervals' coverage and pinball loss. The nominal p05-p95 coverage is 90%. The file is
`model/runs/ML-20260928-051908/intervals.csv`, and the same numbers are written in every train run.

| Interval | Block | n | Coverage | Below p05 | Above p95 | Mean width | Pinball p05 | Pinball p50 | Pinball p95 |
|---|---|---|---|---|---|---|---|---|---|
| months pushed | validation | 10,063 | 0.915 | 0.033 | 0.052 | 12.5 | 0.643 | 1.671 | 0.822 |
| months pushed | flash | 2,613 | 0.883 | 0.018 | 0.099 | 11.4 | 0.426 | 2.062 | 1.068 |
| cost change % | validation | 8,410 | 0.960 | 0.014 | 0.026 | 9.8 | 0.219 | 0.756 | 1.246 |
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
  fractions, L1/L2 penalty and minimum split gain, scored on `y_any_h2`'s validation block only (seed 0). The flash
  block was kept as the holdout. Two searches ran:
  - with the tree count set by early stopping on an inner time split of the training rows (`tune_y_any_h2.csv`);
  - with the tree count as a search dimension of 150 to 1,000 trees (`tune_y_any_h2_trees.csv`).
- **Early stopping.** It keeps only about 50 to 400 trees (the mean per trial). The inner stopping set, the two
  newest training quarters, is a different era from most of the training rows. With the champion's params, early
  stopping alone lost 0.003 validation PR-AUC (trial 0).
- **The best trials.** The early-stopped search's best was trial 13: +0.0054 validation on the seed it was chosen on,
  the best of 21. The tree-count search's best was trial 14: +0.0013. Both collapsed on the flash block for the two
  date targets:
  - y_any_h2: -0.045;
  - y_date_push_h2: -0.039 to -0.055.

  They also lost 0.018 to 0.024 on y_any_h4 validation. The shared `LGB_PARAMS` stay untuned.
- **Seed bagging.** Five seeds (`e2_bag5`) were inside the noise everywhere. On y_any_h2 the flash gain was +0.0048
  with a CI above 0, but the margin is 0.0076. On y_cost_rev_h2 the validation gain was +0.00438, just under the
  0.0044 margin.

## What was rejected, and why

- **Deadline feasibility (a).** It helped y_any_h4 and y_cost_rev_h2 but cost y_any_h2 0.013 validation PR-AUC, with
  a CI below 0. Its progress-based ratios are null wherever progress is not printed: at three of the six validation
  folds (2023-07 to 2024-01) and in every row before 2014. It ships nowhere: on y_any_h4 the half-life beats it, and
  the two together fail.
- **Basis-change revision fix (b1).** This masks a revision "event" when the printed value switches basis, for example
  from anticipated to revised. It lowered y_any_h2 and y_any_h4 validation, with CIs below 0. A basis change often
  goes with a real revision, so the unmasked event carries signal. `base()` keeps counting it, and the choice is
  recorded there.
- **Slip history (b2 to b5).** A regime flip on y_date_push_h2: validation gains of +0.004 to +0.008 with CIs above
  0, but flash losses of 0.008 to 0.014 with CIs below 0. In flash reports the date is the revised one, and a
  project's own history changes meaning. It was inside the noise elsewhere.
- **Name keywords (c1, c2).** Inside the noise on every target. Sector, state and cost band likely carry most of what
  the type says.
- **Age weights (d1, d2) for the 2-quarter targets.** Lower on both blocks for y_any_h2 (-0.015 and -0.018 at 8
  quarters) and y_cost_rev_h2, and on the flash block for y_date_push_h2. The 2-quarter models need the older eras.
- **Flash rows 3x (d3).** No validation effect by construction, since flash rows are not yet in those folds' training.
  Flash gains stayed under the margin, and y_cost_rev_h2 flash fell by 0.010.
- **Cross-target ensembles for y_any_h2 (f1, f2).** Validation fell by 0.020 and 0.009, with CIs below 0. The better
  ECE (0.060 and 0.071) does not make up for the worse ranking. Stacking was not built: both fixed combinations lost
  clearly, and its only honest inputs would be rolling-origin predictions from earlier folds, as with the Platt folds.
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

- **The primary target did not improve.** No candidate of this round moves y_any_h2 beyond seed noise on both
  blocks. Its largest remaining lever is still `months_to_anticipated_completion`, which carries 1.1 of SHAP mass
  against 0.23 for the next feature.
- **Multiple comparisons.** The guard reduces them, but does not remove them. The y_any_h4 decision rests on the
  validation block; its flash block is a single fold, where seeds disagree in sign.
- **The y_any_h4 trade-offs.** Its not-yet-due slice and its flash ECE got slightly worse (see the table notes above).
- **What the train run's gate compared.** Gold did not change in this round, so the run compared the new
  configurations with the stored champions' metrics directly. The incumbent re-score path, which runs when gold
  changes, is covered by tests (`tests/test_registry.py`) and was not exercised by this run.
- **Bottleneck files.** The profile step was run for the risk profile and the external summary. The bottleneck files
  were left as built: they depend on the app's live news signals, not on these models.

## Runtime (this laptop, 16 threads)

- **Harness.** 3.5 to 6 minutes per candidate on all four targets, with the champion predictions cached. Two ran in
  parallel. Five-seed bagging took 13 minutes, and the null candidate, which also fills the cache, 5.5 minutes.
- **Tuning.** 6 to 8 minutes per 20-trial search.
- **Interval experiments.** 2 to 4 minutes.
- **Pipeline.** gold 7 s, train 207 s (the interval backtest adds about 45 s), score 16 s, profile 47 s.
- **Total.** The whole round was about 2.5 hours of compute.

## Reproduce

```
python -m ml.experiment --list                 # the catalogue
python -m ml.experiment d1_decay_8q            # one candidate, 3 seeds, all targets -> model/experiments/
python -m ml.experiment --tune y_any_h2 [--no-es]
python -m ml.experiment g_intervals
python -m ml.experiment --table                # the tables above
python -m pipeline.run gold
python -m pipeline.run train                   # the registry gate decides per target
python -m pipeline.run score
python -m pipeline.run profile
```
