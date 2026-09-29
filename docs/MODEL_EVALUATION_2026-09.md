# Model evaluation, September 2026

The upgrade round of 27 and 28 September (`docs/MODEL_UPGRADES_2026-09.md`) tuned how the models predict and found
almost nothing that moved the primary target. This round follows the reviewer's order of work: first fix what is
predicted, on which projects and at which horizons; then prove it on identical folds with prevalence next to every
number and an error analysis by sector, cost band, project age and data freshness; then try a survival formulation,
calibration, magnitudes and monotone constraints, each judged by the same rule as before (within-cutoff PR-AUC on
the validation and flash blocks, three seeds, paired project bootstrap, the registry's promotion rule and the ship
guard).

**Outcome.**

- The headline number is now the **pre-event cohort**: projects that have shown no cost or date step-up so far.
  For any slip or cost revision within two quarters (`y_any_h2`) the LightGBM champion scores a within-cutoff
  PR-AUC of **0.589 on the validation block (base rate 0.228)** and **0.753 on the flash block (base rate 0.425)**
  in that cohort, against 0.697 and 0.779 on the full population. The naive floor in the cohort is the base rate
  (every pre-event row has `slipped_last_period = 0`) and the logistic regression scores 0.423 and 0.677.
- **Labels at 3, 6, 12 and 18 months** (1, 2, 4 and 6 quarters) from one gold build; the backtest and the registry
  now carry all four, with prevalence per fold. The 3-month target is hard (0.461 on validation at a base rate of
  0.200); the 18-month one is easy (0.925 at 0.729) and on its single test fold the logistic regression ties it.
- **Label noise is low**: 1 to 2 per cent of date pushes and 2 to 5 per cent of cost revisions are gone one
  quarter later, so no label requires a push to persist two observations.
- **The error analysis** (`slices.csv` in every train run) shows where the model is useful: Roads & Highways
  (0.73 to 0.91) and not Railways (0.46 to 0.60), which gets almost none of the top-50 flags; projects past half
  of their schedule and not those under it (0.29 to 0.39 at a base rate of 0.08 to 0.13); and on the flash block a
  first cost revision is close to unpredictable (0.076 at 35 positives).
- **A discrete-time survival model** now gives the runway curve, P(first deterioration by 3 to 18 months) from one
  hazard model, served as `runway_any_1q` to `runway_any_6q` next to the per-horizon scores. Against the
  per-horizon champions it shows the regime flip already seen with slip history: better inside the quarterly-era
  validation folds, worse on the flash block, so the per-horizon LightGBM stays the served ranking.
- Isotonic calibration, a hurdle model for the months and cost magnitudes, and monotone constraints were measured
  and decided by the same rules (sections below).
- Nothing changed in the tiers: the champions were re-scored on the new gold at zero gain, the served
  `model_version` is `lgbm-any2q-20260929-070637`, and the tier counts are 70 Critical, 213 High, 425 Medium, 708
  Low and 347 Watch as before.

## What changed, and why it changes what the numbers mean

The September upgrade round (`docs/MODEL_UPGRADES_2026-09.md`) tuned how the model predicts. This round fixes what
it predicts, on which projects, and how that is proven, before any more tuning:

1. **The pre-event cohort.** The full population includes projects that have already revised a date or a cost,
   where "revised before, revises again" is easy and lifts PR-AUC. Every backtest table now also scores the same
   predictions on the rows whose project has shown no cost or date step-up so far (`revisions_so_far == 0`,
   `backtest.pre_event`): the projects a first warning is for. Both numbers are reported; the pre-event one is the
   headline. The stricter cut, on schedule and on cost against the original sanction, is a slice of the error
   analysis (`on_schedule`).
2. **The event.** A label is the first deterioration against the value at t within the horizon: the anticipated
   completion pushed by 3 months or more, or the anticipated cost up by 5 per cent or more (unchanged). The plan
   asked whether a pushed date is often pulled back the next quarter, in which case a push should have to persist
   two observations. It is measured in every gold build (`manifest.json` `label_noise`): 1.0 to 2.0 per cent of date
   pushes and 2.0 to 4.5 per cent of cost revisions are gone one quarter later, at every horizon. The labels stay as
   they are: a persistence requirement would cost one quarter of lead time for a 2 per cent gain in label purity.
3. **Horizons.** Labels now exist at every quarter from 1 to 6 (`labels_h1.parquet` to `labels_h6.parquet`), and
   the backtest scores `y_any` at 1, 2, 4 and 6 quarters (3, 6, 12 and 18 months) next to the three 2-quarter
   targets. Prevalence (`base_rate`, `n_pos`) stands next to every PR-AUC, per fold and per block, and
   `pr_auc_fold_sd` gives the fold-to-fold spread.
4. **Physical progress by era.** Coverage is 0 before 2014, 0.45 to 0.69 in 2014 to 2018 and 2023, and 0.9 or more
   otherwise (`progress_coverage_by_year`). On the rows without it the model reads the financial trajectory and the
   dates; the null itself is LightGBM's flag, so no separate `progress_source` column was added, and the error
   analysis reports the `progress_reported` slice so the difference is visible.
5. **Error analysis.** Every train run writes `slices.csv`: per target, block and model, the rows, positives, base
   rate, pooled and within-cutoff PR-AUC, ROC-AUC, Brier, ECE, the slice's share of the rows and of each fold's
   top-50 flags, and their ratio (lift), by sector, cost band, project age, data freshness, progress printed,
   pre-event cohort, on schedule, and report type. The per-sector table the plan asks for is its `sector` dimension.
6. **A discrete-time survival model** (`ml/survival.py`). Each feature row (project, t) is expanded into
   person-periods k = 1..6 quarters ahead while the project is at risk; the event at k is the horizon label at k;
   the row leaves after its first event or at the first unknown label (censored, so an ongoing project contributes
   every quarter it was observed). One LightGBM hazard model on the features plus k gives P(first deterioration by
   3, 6, 12 and 18 months) from the cumulative hazard: the runway curve, monotone in the horizon by construction.
   It is measured against the per-horizon champions on the same rows and folds (`s1_survival`), and served as the
   `runway_any_1q` to `runway_any_6q` columns of the predictions file next to the per-horizon scores.
7. **Calibration and magnitudes**, measured and decided by the same rules: isotonic against Platt against raw scores
   (`k1_isotonic`); a two-stage hurdle (P(step) x conditional magnitude) against the served p50 quantile for the
   months pushed and the cost change (`h1_hurdle`); monotone constraints on prior revisions, stall count, slip to
   date and cost growth (`m1_monotone`).

The rest of the proof was already in place and is unchanged: rolling-origin folds whose training rows are realised
by the cutoff (a buffer equal to the horizon), the naive, rule and logistic baselines on identical folds, the ablation
by feature group, Recall@50 and @100, and the lead time from the first flag to the slip.

The plan's other feature ideas are already gold features or were measured in the upgrade round: the completion gap
(`a_feasibility`, rejected), revision history (`revisions_so_far`, `months_since_last_revision`; the slip-history
variants `b2` to `b5`, rejected), velocity, acceleration and stall count, the S-curve residual, agency and sector
rates with shrinkage recomputed per cutoff, months since the last observation and the data-quality score, and the
sector performance series. Remark embeddings stay out: free text ends in 2023-Q2 and no validation, flash or live row
has any.

## Headline results

Within-cutoff PR-AUC (each fold's own, averaged over the block) of the LightGBM champion of train run
`ML-20260929-070637` on the full population and on the pre-event cohort, with prevalence next to each. The
baselines' pre-event numbers are on the same rows. The validation block is the quarterly-report era (six cutoffs,
2023-07 to 2024-10 for the 2-quarter targets), the flash block the flash-report era from 2025-07, the test fold the
newest usable cutoff (for the 2-quarter targets also a flash cutoff, so not independent). Full tables:
`model/runs/ML-20260929-070637/backtest_summary.csv` (the `pre_*` columns) and `backtest_folds.csv`.

### Headline: full population against the pre-event cohort (LightGBM champions, within-cutoff PR-AUC)

| Target | Block | Folds | Rows (positives) | Base rate | PR-AUC all | Fold SD | Pre-event rows (positives) | Pre-event base rate | **PR-AUC pre-event** | Naive pre-event | Logistic pre-event | P@50 all / pre-event |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| y_any_h1 | val | 6 | 10,043 (2,007) | 0.200 | 0.461 | 0.094 | 3,948 (449) | 0.114 | **0.394** | 0.111 | 0.217 | 0.547 / 0.473 |
| y_any_h1 | flash | 4 | 4,284 (1,213) | 0.283 | 0.540 | 0.228 | 1,439 (358) | 0.249 | **0.499** | 0.243 | 0.433 | 0.650 / 0.505 |
| y_any_h1 | test | 1 | 1,412 (152) | 0.108 | 0.204 | - | 411 (35) | 0.085 | **0.306** | 0.085 | 0.187 | 0.280 / 0.300 |
| y_any_h2 | val | 6 | 9,349 (3,428) | 0.367 | 0.697 | 0.075 | 3,947 (899) | 0.228 | **0.589** | 0.225 | 0.423 | 0.827 / 0.703 |
| y_any_h2 | flash | 3 | 2,564 (1,293) | 0.504 | 0.779 | 0.023 | 890 (378) | 0.425 | **0.753** | 0.413 | 0.677 | 0.913 / 0.793 |
| y_any_h2 | test | 1 | 1,318 (678) | 0.514 | 0.778 | - | 537 (234) | 0.436 | **0.776** | 0.436 | 0.651 | 0.900 / 0.880 |
| y_any_h4 | val | 6 | 7,163 (4,347) | 0.607 | 0.884 | 0.064 | 3,129 (1,475) | 0.471 | **0.854** | 0.467 | 0.771 | 0.937 / 0.937 |
| y_any_h4 | flash | 1 | 335 (210) | 0.627 | 0.872 | - | 94 (58) | 0.617 | **0.877** | 0.617 | 0.837 | 0.940 / 0.840 |
| y_any_h4 | test | 1 | 1,476 (754) | 0.511 | 0.753 | - | 605 (214) | 0.354 | **0.608** | 0.354 | 0.511 | 0.800 / 0.700 |
| y_any_h6 | val | 6 | 5,855 (4,266) | 0.729 | 0.925 | 0.047 | 2,423 (1,588) | 0.655 | **0.920** | 0.658 | 0.846 | 0.963 / 0.950 |
| y_any_h6 | test | 1 | 1,190 (825) | 0.693 | 0.837 | - | 615 (358) | 0.582 | **0.793** | 0.582 | 0.818 | 0.940 / 0.880 |
| y_date_push_h2 | val | 6 | 10,063 (3,490) | 0.347 | 0.635 | 0.071 | 4,113 (928) | 0.226 | **0.551** | 0.220 | 0.402 | 0.743 / 0.661 |
| y_date_push_h2 | flash | 3 | 2,613 (1,250) | 0.478 | 0.778 | 0.022 | 906 (377) | 0.416 | **0.732** | 0.404 | 0.696 | 0.920 / 0.767 |
| y_date_push_h2 | test | 1 | 1,330 (629) | 0.473 | 0.764 | - | 541 (230) | 0.425 | **0.782** | 0.425 | 0.634 | 0.900 / 0.880 |
| y_cost_rev_h2 | val | 6 | 9,392 (401) | 0.043 | 0.184 | 0.060 | 3,960 (91) | 0.023 | **0.236** | 0.023 | 0.134 | 0.270 / 0.100 |
| y_cost_rev_h2 | flash | 3 | 3,617 (119) | 0.033 | 0.164 | 0.119 | 1,721 (35) | 0.020 | **0.076** | 0.022 | 0.067 | 0.193 / 0.040 |
| y_cost_rev_h2 | test | 1 | 1,641 (72) | 0.044 | 0.230 | - | 821 (15) | 0.018 | **0.029** | 0.018 | 0.053 | 0.360 / 0.020 |

Reading it:

- **The pre-event number is the honest one, and it still clears the baselines by a wide margin.** On the primary
  target the cohort removes 0.11 of validation PR-AUC (0.697 to 0.589) at a base rate that falls from 0.367 to
  0.228; the logistic regression falls further (0.537 to 0.423). On the flash block the two populations are close
  (0.779 and 0.753): in the flash era the model's ranking does not depend on a project's own revision history.
- **Where the flags go.** In the validation block 61 per cent of the top-50 flags fall on projects that had revised
  before, against 58 per cent of the rows (lift 1.06). In the flash and test blocks it is 87 to 90 per cent against
  59 to 65 per cent (lift 1.3 to 1.5): the flash-era model leans on revision history, and a first warning is rarer
  in its top 50.
- **The first cost revision is close to unpredictable in the flash era.** `y_cost_rev_h2` in the pre-event cohort:
  0.236 on validation (91 positives), 0.076 on the flash block (35 positives, base rate 0.020) and 0.029 on the test
  fold (15 positives). Its full-population numbers (0.184, 0.164, 0.230) come from projects that had already
  revised. Roads & Highways print no cost revision at all in the flash era (0 of 1,492 rows), so the cost target's
  flags are 60 to 67 per cent Railways.
- **The fold-to-fold SD** is 0.02 to 0.12: a single validation fold can move the block mean by more than any
  candidate of the upgrade round gained. The 2-quarter flash blocks are the steadiest (0.022 to 0.023).

## The runway horizons

`y_any` at 1, 2, 4 and 6 quarters, LightGBM against the three baselines on identical folds. The 18-month target has
no flash block: its outcome quarters (2027) are not reported yet, and its test fold is 2023-10.

### The runway horizons (y_any, LightGBM against the baselines, within-cutoff PR-AUC; base rate in brackets)

| Horizon | Block | Folds | Rows | Base rate | Naive | Rule | Logistic | **LightGBM** | LightGBM pre-event (base rate) | P@50 | Recall@100 | Lead time (quarters) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1q (3 months) | val | 6 | 10,043 | 0.200 | 0.220 | 0.245 | 0.316 | **0.461** | 0.394 (0.114) | 0.547 | 0.164 | 1.63 |
| 1q (3 months) | flash | 4 | 4,284 | 0.283 | 0.317 | 0.274 | 0.443 | **0.540** | 0.499 (0.249) | 0.650 | 0.200 | 1.12 |
| 1q (3 months) | test | 1 | 1,412 | 0.108 | 0.097 | 0.123 | 0.109 | **0.204** | 0.306 (0.085) | 0.280 | 0.145 | 1.00 |
| 2q (6 months) | val | 6 | 9,349 | 0.367 | 0.425 | 0.438 | 0.537 | **0.697** | 0.589 (0.228) | 0.827 | 0.143 | 2.78 |
| 2q (6 months) | flash | 3 | 2,564 | 0.504 | 0.522 | 0.438 | 0.702 | **0.779** | 0.753 (0.425) | 0.913 | 0.202 | 2.15 |
| 2q (6 months) | test | 1 | 1,318 | 0.514 | 0.571 | 0.479 | 0.664 | **0.778** | 0.776 (0.436) | 0.900 | 0.131 | 2.00 |
| 4q (12 months) | val | 6 | 7,163 | 0.607 | 0.659 | 0.652 | 0.823 | **0.884** | 0.854 (0.471) | 0.937 | 0.130 | 4.65 |
| 4q (12 months) | flash | 1 | 335 | 0.627 | 0.607 | 0.578 | 0.801 | **0.872** | 0.877 (0.617) | 0.940 | 0.419 | 4.00 |
| 4q (12 months) | test | 1 | 1,476 | 0.511 | 0.579 | 0.541 | 0.610 | **0.753** | 0.608 (0.354) | 0.800 | 0.109 | 4.00 |
| 6q (18 months) | val | 6 | 5,855 | 0.729 | 0.758 | 0.732 | 0.851 | **0.925** | 0.920 (0.655) | 0.963 | 0.135 | 6.94 |
| 6q (18 months) | test | 1 | 1,190 | 0.693 | 0.741 | 0.776 | 0.841 | **0.837** | 0.793 (0.582) | 0.940 | 0.109 | 6.00 |

- PR-AUC rises with the horizon because the base rate does (0.20 to 0.73 on validation): most projects deteriorate
  within 18 months, and the question at 6 quarters is which few do not. Lift over the naive floor is largest at 2
  and 4 quarters (+0.27 and +0.22 on validation) and smallest at 6 (+0.17) and 1 (+0.24 at a low base rate, where
  precision@50 is 0.55).
- On the 18-month test fold (2023-10, 1,190 rows) the logistic regression (0.841) ties the LightGBM (0.837), and the
  LightGBM's ECE there is 0.16: one fold, and the model over-predicts on it. The 12-month test fold (2024-04) shows
  the same: 0.753 against 0.884 on validation, ECE 0.144.
- The tiers still rank `p_any_2q`. The other horizons are served as `p_any_1q`, `p_any_4q` and `p_any_6q`
  (independent models, not guaranteed to be monotone in the horizon) and as the survival model's runway curve
  (monotone by construction; below).

## Error analysis

`slices.csv` per target, block and model. The tables below are the LightGBM champion of the primary target. "Rows
-> flags" is the slice's share of the block's rows against its share of each fold's top-50 flags; their ratio is
the lift column of the file. A slice with fewer than about 30 positives has a PR-AUC that one project can move.

### y_any_h2 by sector (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Roads & Highways | 5355 | 0.394 | 0.734 | 0.57 -> 0.94 | 1191 | 0.662 | 0.908 | 0.46 -> 0.58 | 907 | 0.581 | 0.847 |
| Railways | 1245 | 0.322 | 0.554 | 0.13 -> 0.00 | 452 | 0.257 | 0.456 | 0.18 -> 0.01 | 128 | 0.406 | 0.598 |
| Petroleum & Natural Gas | 708 | 0.312 | 0.676 | 0.08 -> 0.01 | 254 | 0.496 | 0.882 | 0.10 -> 0.07 | 53 | 0.585 | 0.795 |
| Coal | 660 | 0.221 | 0.693 | 0.07 -> 0.01 | 94 | 0.319 | 0.724 | 0.04 -> 0.06 | 29 | 0.241 | 0.515 |
| Power | 511 | 0.436 | 0.665 | 0.05 -> 0.03 | 149 | 0.470 | 0.679 | 0.06 -> 0.08 | 57 | 0.368 | 0.740 |
| Civil Aviation | 198 | 0.399 | 0.828 | 0.02 -> 0.01 | 60 | 0.500 | 0.807 | 0.02 -> 0.01 | 20 | 0.350 | 0.493 |
| Water Resources | 153 | 0.353 | 0.802 | 0.02 -> 0.00 | 114 | 0.228 | 0.485 | 0.04 -> 0.05 | 35 | 0.143 | 0.152 |
| Urban Development & Housing | 145 | 0.283 | 0.470 | 0.02 -> 0.00 | 78 | 0.449 | 0.742 | 0.03 -> 0.01 | 26 | 0.154 | 0.504 |

- **Roads & Highways carries the model.** It is 46 to 69 per cent of the rows, scores 0.73 to 0.91, and takes 58
  to 100 per cent of the top-50 flags. Railways is the second-largest sector (13 to 18 per cent of rows), scores
  0.46 to 0.60 at a base rate of 0.26 to 0.41, and gets 0 to 1 per cent of the flags. Petroleum & Natural Gas
  (0.68 to 0.88) and Power (0.67 to 0.74) sit between. A single portfolio PR-AUC hides this; the per-sector table
  is the one to show, and per-sector calibration or a Railways model with a pooled fallback is the obvious next
  experiment (the external-factor lift was also sector-bound: 1.33 in Railways, 1.6 in Power).
- The same holds at 12 months: Roads 0.913 on validation, Railways 0.740.

### y_any_h4 by sector (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Roads & Highways | 3835 | 0.676 | 0.913 | 0.54 -> 0.86 | - | - | - | - -> - | 878 | 0.500 | 0.741 |
| Railways | 927 | 0.508 | 0.740 | 0.13 -> 0.00 | 120 | 0.533 | 0.724 | 0.36 -> 0.04 | 198 | 0.540 | 0.777 |
| Petroleum & Natural Gas | 637 | 0.553 | 0.860 | 0.09 -> 0.06 | 50 | 0.960 | 0.995 | 0.15 -> 0.64 | 96 | 0.438 | 0.858 |
| Coal | 632 | 0.339 | 0.834 | 0.09 -> 0.01 | 23 | 0.478 | 0.715 | 0.07 -> 0.12 | 92 | 0.370 | 0.811 |
| Power | 417 | 0.633 | 0.842 | 0.06 -> 0.04 | 31 | 0.710 | 0.928 | 0.09 -> 0.12 | 75 | 0.787 | 0.961 |

### y_cost_rev_h2 by sector (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Roads & Highways | 5392 | 0.027 | 0.061 | 0.57 -> 0.02 | 1492 | 0.000 | - | 0.41 -> 0.02 | 951 | 0.000 | - |
| Railways | 1250 | 0.096 | 0.361 | 0.13 -> 0.67 | 612 | 0.100 | 0.233 | 0.17 -> 0.60 | 168 | 0.292 | 0.518 |
| Petroleum & Natural Gas | 708 | 0.051 | 0.126 | 0.08 -> 0.09 | 302 | 0.056 | 0.295 | 0.08 -> 0.03 | 100 | 0.070 | 0.406 |
| Coal | 660 | 0.021 | 0.269 | 0.07 -> 0.00 | 357 | 0.008 | 0.035 | 0.10 -> 0.01 | 119 | 0.000 | - |
| Power | 512 | 0.061 | 0.434 | 0.05 -> 0.08 | 248 | 0.060 | 0.272 | 0.07 -> 0.10 | 89 | 0.067 | 0.143 |

- For the cost revision the roles flip: Railways is where cost revisions happen (base rate 0.10 to 0.29 against
  0.00 to 0.03 for Roads), so the cost model's flags are 60 to 67 per cent Railways and its Roads PR-AUC is 0.06.

### y_any_h2 by age (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| half to due | 3100 | 0.330 | 0.638 | 0.33 -> 0.40 | 792 | 0.350 | 0.678 | 0.31 -> 0.07 | 443 | 0.397 | 0.684 |
| over 1.5x schedule | 2660 | 0.453 | 0.724 | 0.28 -> 0.25 | 665 | 0.645 | 0.819 | 0.26 -> 0.32 | 334 | 0.635 | 0.764 |
| due to 1.5x | 1974 | 0.511 | 0.755 | 0.21 -> 0.34 | 922 | 0.600 | 0.817 | 0.36 -> 0.60 | 460 | 0.615 | 0.839 |
| under half of schedule | 1483 | 0.098 | 0.393 | 0.16 -> 0.01 | 166 | 0.127 | 0.356 | 0.06 -> 0.00 | 78 | 0.077 | 0.288 |
| unknown | 132 | 0.341 | 0.597 | 0.01 -> 0.00 | 19 | 0.684 | 0.694 | 0.01 -> 0.01 | 3 | 0.333 | 0.333 |

- **Project age is the strongest slice.** Projects under half of their original schedule slip at 8 to 13 per cent
  within two quarters and the model ranks them at 0.29 to 0.39: little signal before a project is half-way. Projects
  between due and 1.5 times their schedule slip most (0.51 to 0.62) and take 34 to 60 per cent of the flags. This is
  the early-warning problem in one table: the model is good where the deadline is near, and an early warning for a
  young project needs signals the reports do not print.

### y_any_h2 by on_schedule (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| behind or over | 5919 | 0.457 | 0.723 | 0.63 -> 0.69 | 2055 | 0.565 | 0.802 | 0.80 -> 0.97 | 1030 | 0.577 | 0.794 |
| on schedule and cost | 3430 | 0.211 | 0.577 | 0.37 -> 0.31 | 509 | 0.257 | 0.529 | 0.20 -> 0.03 | 288 | 0.292 | 0.611 |

- The stricter cohort, on schedule and on cost against the original sanction (20 to 37 per cent of rows): 0.577 on
  validation and 0.529 on the flash block, at base rates of 0.21 and 0.26, with 3 to 31 per cent of the flags.

### y_any_h2 by cost_band (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| under 500 cr | 3925 | 0.340 | 0.690 | 0.42 -> 0.46 | 856 | 0.519 | 0.757 | 0.33 -> 0.24 | 458 | 0.472 | 0.703 |
| 1000-5000 cr | 2709 | 0.397 | 0.712 | 0.29 -> 0.29 | 932 | 0.553 | 0.821 | 0.36 -> 0.47 | 489 | 0.605 | 0.834 |
| 500-1000 cr | 2171 | 0.384 | 0.727 | 0.23 -> 0.24 | 536 | 0.474 | 0.773 | 0.21 -> 0.21 | 301 | 0.488 | 0.781 |
| over 5000 cr | 544 | 0.338 | 0.650 | 0.06 -> 0.01 | 240 | 0.333 | 0.715 | 0.09 -> 0.08 | 70 | 0.271 | 0.645 |

- Cost bands are even: 0.65 to 0.83 everywhere, the largest projects (over Rs 5,000 crore) lowest and least
  flagged.

### y_any_h2 by progress_reported (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| yes | 4937 | 0.331 | 0.638 | 0.53 -> 0.50 | 2563 | 0.504 | 0.779 | 1.00 -> 1.00 | 1317 | 0.514 | 0.778 |
| no | 4412 | 0.406 | 0.756 | 0.47 -> 0.50 | 1 | 1.000 | - | 0.00 -> 0.00 | 1 | 1.000 | - |

- In the validation block 47 per cent of rows print no physical progress (the 2023 reports), and the model scores
  them higher (0.756 against 0.638), at a higher base rate (0.41 against 0.33): on those rows it reads dates and
  money, and the rows that print no progress are older, later projects. Every flash and test row prints progress.
  Coverage by year: 2014 0.48, 2015 0.52, 2016 0.69, 2017 0.62, 2018 0.66, 2021 0.97, 2022 0.92, 2023 0.45, 2024 0.74, 2025 1.00, 2026 0.99; 0 before 2014.

### y_any_h2 by freshness (LightGBM; rows, base rate, within-cutoff PR-AUC, share of rows -> share of top-50 flags)

| Value | Val rows | Val base rate | Val PR-AUC | Val rows -> flags | Flash rows | Flash base rate | Flash PR-AUC | Flash rows -> flags | Test rows | Test base rate | Test PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current (3 months) | 8722 | 0.382 | 0.701 | 0.93 -> 0.99 | 1202 | 0.492 | 0.754 | 0.47 -> 0.56 | 843 | 0.537 | 0.756 |
| unknown | 596 | 0.133 | 0.418 | 0.06 -> 0.01 | 567 | 0.478 | 0.855 | 0.22 -> 0.07 | 382 | 0.448 | 0.853 |
| 4-6 months | 27 | 0.444 | 0.609 | 0.00 -> 0.00 | 702 | 0.538 | 0.799 | 0.27 -> 0.32 | 1 | 1.000 | - |
| over 6 months | 4 | 0.250 | - | 0.00 -> 0.00 | 93 | 0.570 | 0.844 | 0.04 -> 0.05 | 92 | 0.576 | 0.844 |

- Freshness: a row whose project has no earlier observation (unknown months since the last one) is 22 to 29 per
  cent of the flash and test rows, scores well (0.85) and is rarely flagged (7 to 8 per cent of the top 50): the
  model has no history for a project new to the report and ranks it low.

## Label noise

The share of events at horizon h that are gone at h + 1 (the pushed date back under 3 months of the value at t, or
the cost back under 5 per cent up), from the gold manifest (`label_noise`): events / share reverted.

| Horizon | Date push | Cost revision | Either |
|---|---|---|---|
| h1 (3 months) | 8,813 / 1.9 per cent | 1,508 / 4.5 per cent | 9,364 / 1.7 per cent |
| h2 (6 months) | 13,400 / 1.4 per cent | 2,529 / 3.7 per cent | 13,883 / 1.2 per cent |
| h3 (9 months) | 15,250 / 1.1 per cent | 3,289 / 2.8 per cent | 15,517 / 0.9 per cent |
| h4 (12 months) | 15,668 / 1.0 per cent | 3,764 / 2.3 per cent | 15,822 / 0.8 per cent |
| h5 (15 months) | 15,268 / 0.9 per cent | 4,123 / 2.0 per cent | 15,390 / 0.7 per cent |

A persistence rule (the push must hold for two observations) would cost one quarter of lead time to remove 1 to 2
per cent of date labels. The labels stay as they are, and the number is rebuilt with every gold build.

## The survival model

`s1_survival`, against the champions of ML-20260929-070637 on their own validation and flash folds, three seeds,
paired project bootstrap; the pre-event column is the within-cutoff PR-AUC on the pre-event cohort (seed means).
CSV: `model/experiments/s1_survival.csv`.

| Target | Block | Folds | Champion PR-AUC | Challenger PR-AUC | Delta [95% CI] | Folds up | Pre-event: champion -> challenger | Val ECE: champion -> challenger | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| y_any_h2 | val | 6 | 0.6962 | 0.7002 | +0.0040 [-0.0032, +0.0115] | 5/6 | 0.588 -> 0.586 | 0.0818 -> 0.0581 | fail | reject |
| y_any_h2 | flash | 3 | 0.7775 | 0.7397 | -0.0378 [-0.0498, -0.0235] | 0/3 | 0.740 -> 0.699 | - -> - | fail | reject |
| y_date_push_h2 | val | 6 | 0.6320 | 0.6539 | +0.0219 [+0.0152, +0.0287] | 6/6 | 0.547 -> 0.552 | 0.0555 -> 0.0420 | fail | reject |
| y_date_push_h2 | flash | 3 | 0.7751 | 0.7237 | -0.0514 [-0.0640, -0.0359] | 0/3 | 0.721 -> 0.654 | - -> - | fail | reject |
| y_cost_rev_h2 | val | 6 | 0.1824 | 0.1822 | -0.0002 [-0.0152, +0.0122] | 4/6 | 0.228 -> 0.209 | 0.0039 -> 0.0041 | fail | reject |
| y_cost_rev_h2 | flash | 3 | 0.1595 | 0.1899 | +0.0304 [-0.0050, +0.0622] | 3/3 | 0.076 -> 0.097 | - -> - | fail | reject |
| y_any_h4 | val | 6 | 0.8844 | 0.8892 | +0.0048 [-0.0007, +0.0099] | 2/6 | 0.856 -> 0.852 | 0.0959 -> 0.0719 | fail | reject |
| y_any_h4 | flash | 1 | 0.8764 | 0.8418 | -0.0346 [-0.0687, -0.0025] | 0/1 | 0.874 -> 0.797 | - -> - | fail | reject |
| y_any_h1 | val | 6 | 0.4621 | 0.4656 | +0.0035 [-0.0044, +0.0114] | 4/6 | 0.394 -> 0.384 | 0.0220 -> 0.0229 | fail | reject |
| y_any_h1 | flash | 4 | 0.5311 | 0.4982 | -0.0328 [-0.0457, -0.0194] | 1/4 | 0.491 -> 0.476 | - -> - | fail | reject |
| y_any_h6 | val | 6 | 0.9254 | 0.9305 | +0.0051 [+0.0000, +0.0107] | 3/6 | 0.922 -> 0.930 | 0.0534 -> 0.0460 | pass | keep |

runtime: 346 s

- **Every target that has a flash block fails**, with the same shape: better inside the quarterly-era validation
  folds (+0.004 to +0.022; the date push 6 of 6 folds up with a CI above 0) and worse on the flash block (-0.033 to
  -0.051, 0 of 3, 0 of 1 and 1 of 4 folds up, every CI below 0). The pre-event cohort shows it too (0.740 to 0.699
  on the primary target's flash block). It is the regime flip of the upgrade round's slip-history candidates: in
  flash reports the date field is the revised one, so the meaning of a quarter-by-quarter step differs, and a model
  that learns the shape of the event sequence from the quarterly era follows that era. The cost revision is the
  mirror image (-0.0002 validation, +0.0304 flash with 3 of 3 folds up but a CI that includes 0) and fails the rule
  by 0.0002 on the validation block.
- **The 18-month target passes the rule and the guard on its single block** (+0.0051 [+0.0000, +0.0107], 3 of 6
  folds up, validation ECE 0.053 to 0.046). One block, a lower bound at zero and half the folds: it is recorded as
  passed and not promoted. The tiers do not rank this target, and promoting it would need a survival model type in
  the registry with no flash block to confirm it; the check is the 2025-07 and later cutoffs once their 2027 outcome
  quarters are reported.
- **Calibration** is where the survival model is better: validation ECE falls on five of six targets (the primary
  0.082 to 0.058, the 12-month 0.096 to 0.072), because the cumulative hazard is a probability of the event by h
  built from six quarterly hazards rather than one classifier's score.
- **What is served.** The runway curve, `runway_any_1q` to `runway_any_6q`, from the hazard model fitted on every
  person-period realised by the as-of date (141,797 for 2026-07) with the primary champion's features and params;
  the rows the classifiers do not score (no completion date) are not scored either. On the current portfolio it
  correlates 0.91 with `p_any_2q` and 0.94 with `p_any_4q`, and it is monotone in the horizon on every row, which
  the four independent per-horizon models are not. It is a probability, hidden from the four roles like the others;
  the tiers still rank `p_any_2q`, the model that holds on both blocks.
- The harness shares one hazard model across the y_any horizons of a run (the same cutoff gives every horizon), so
  the six targets took 346 s together.

## Calibration: isotonic against Platt

`k1_isotonic`: the champion's own out-of-fold predictions at the four cutoffs realised by each fold
(`backtest.calibration_folds`) fit a Platt scaler and an isotonic regression, applied to the fold; raw is the
served state for every target but the cost revision, whose served scores are the Platt ones. A method passes when
its ECE is below raw's on both blocks and its within-cutoff PR-AUC is not below raw's by more than the block's noise
margin. CSV: `model/experiments/k1_isotonic.csv`.

| Target | Block | Folds | Rows | Base rate | Method | ECE | Brier | Within-cutoff PR-AUC | Mean score | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| y_any_h2 | val | 6 | 9,349 | 0.367 | raw | 0.0815 | 0.1754 | 0.6970 | 0.448 | - |
| y_any_h2 | val | 6 | 9,349 | 0.367 | platt | 0.0474 | 0.1724 | 0.6970 | 0.411 | fail |
| y_any_h2 | val | 6 | 9,349 | 0.367 | isotonic | 0.0537 | 0.1739 | 0.6820 | 0.413 | fail |
| y_any_h2 | flash | 3 | 2,564 | 0.504 | raw | 0.0597 | 0.1937 | 0.7794 | 0.447 | - |
| y_any_h2 | flash | 3 | 2,564 | 0.504 | platt | 0.1345 | 0.2100 | 0.7794 | 0.370 | fail |
| y_any_h2 | flash | 3 | 2,564 | 0.504 | isotonic | 0.1315 | 0.2092 | 0.7610 | 0.374 | fail |
| y_date_push_h2 | val | 6 | 10,063 | 0.347 | raw | 0.0512 | 0.1775 | 0.6350 | 0.398 | - |
| y_date_push_h2 | val | 6 | 10,063 | 0.347 | platt | 0.0204 | 0.1755 | 0.6350 | 0.354 | fail |
| y_date_push_h2 | val | 6 | 10,063 | 0.347 | isotonic | 0.0277 | 0.1766 | 0.6176 | 0.356 | fail |
| y_date_push_h2 | flash | 3 | 2,613 | 0.478 | raw | 0.0617 | 0.1880 | 0.7780 | 0.417 | - |
| y_date_push_h2 | flash | 3 | 2,613 | 0.478 | platt | 0.1211 | 0.2014 | 0.7780 | 0.357 | fail |
| y_date_push_h2 | flash | 3 | 2,613 | 0.478 | isotonic | 0.1197 | 0.2023 | 0.7604 | 0.359 | fail |
| y_cost_rev_h2 | val | 6 | 9,392 | 0.043 | raw | 0.0038 | 0.0388 | 0.1841 | 0.045 | - |
| y_cost_rev_h2 | val | 6 | 9,392 | 0.043 | platt | 0.0091 | 0.0390 | 0.1841 | 0.049 | fail |
| y_cost_rev_h2 | val | 6 | 9,392 | 0.043 | isotonic | 0.0099 | 0.0402 | 0.1579 | 0.051 | fail |
| y_cost_rev_h2 | flash | 3 | 3,617 | 0.033 | raw | 0.0100 | 0.0305 | 0.1644 | 0.042 | - |
| y_cost_rev_h2 | flash | 3 | 3,617 | 0.033 | platt | 0.0050 | 0.0304 | 0.1644 | 0.036 | fail |
| y_cost_rev_h2 | flash | 3 | 3,617 | 0.033 | isotonic | 0.0053 | 0.0305 | 0.1196 | 0.037 | fail |
| y_any_h4 | val | 6 | 7,163 | 0.607 | raw | 0.0954 | 0.1691 | 0.8843 | 0.701 | - |
| y_any_h4 | val | 6 | 7,163 | 0.607 | platt | 0.1447 | 0.1839 | 0.8843 | 0.752 | fail |
| y_any_h4 | val | 6 | 7,163 | 0.607 | isotonic | 0.1461 | 0.1855 | 0.8740 | 0.752 | fail |
| y_any_h4 | flash | 1 | 335 | 0.627 | raw | 0.0782 | 0.1738 | 0.8719 | 0.688 | - |
| y_any_h4 | flash | 1 | 335 | 0.627 | platt | 0.1078 | 0.1804 | 0.8719 | 0.525 | fail |
| y_any_h4 | flash | 1 | 335 | 0.627 | isotonic | 0.0973 | 0.1789 | 0.8555 | 0.534 | fail |
| y_any_h1 | val | 6 | 10,043 | 0.200 | raw | 0.0218 | 0.1318 | 0.4608 | 0.222 | - |
| y_any_h1 | val | 6 | 10,043 | 0.200 | platt | 0.0175 | 0.1325 | 0.4608 | 0.208 | fail |
| y_any_h1 | val | 6 | 10,043 | 0.200 | isotonic | 0.0140 | 0.1327 | 0.4451 | 0.208 | fail |
| y_any_h1 | flash | 4 | 4,284 | 0.283 | raw | 0.0339 | 0.1709 | 0.5397 | 0.317 | - |
| y_any_h1 | flash | 4 | 4,284 | 0.283 | platt | 0.0605 | 0.1806 | 0.5397 | 0.339 | fail |
| y_any_h1 | flash | 4 | 4,284 | 0.283 | isotonic | 0.0833 | 0.1826 | 0.5177 | 0.343 | fail |
| y_any_h6 | val | 6 | 5,855 | 0.729 | raw | 0.0546 | 0.1352 | 0.9252 | 0.776 | - |
| y_any_h6 | val | 6 | 5,855 | 0.729 | platt | 0.0706 | 0.1418 | 0.9252 | 0.797 | fail |
| y_any_h6 | val | 6 | 5,855 | 0.729 | isotonic | 0.0721 | 0.1431 | 0.9188 | 0.797 | fail |

- **No method passes for any target.** Isotonic lowers validation ECE where the raw scores are worst calibrated
  (the primary target 0.082 to 0.054, the date push 0.051 to 0.028, the 3-month target 0.022 to 0.014) and raises
  flash ECE everywhere (0.060 to 0.132, 0.062 to 0.120, 0.034 to 0.083): calibrators fitted on quarterly-era folds
  pull the flash-era scores down, where the slip rate is higher. Platt did the same in the upgrade round, and does
  here. Isotonic also costs 0.015 to 0.045 of within-cutoff PR-AUC through the ties its steps create, more than any
  block's margin.
- **The served Platt scaler of the cost revision** halves flash ECE (0.010 to 0.005) and doubles validation ECE
  (0.004 to 0.009), both inside 0.01; it stays, and ranks are unchanged by construction.
- The way to calibrate the flash era is with flash-era folds, and only three or four are realised. `CALIBRATION` in
  `ml/backtest.py` is unchanged; the code can serve an isotonic calibrator when one earns it.

## Magnitudes: the hurdle model

`h1_hurdle`: point forecasts of the months pushed and the cost change by t + 2 quarters on the validation and
flash cutoffs of `y_date_push_h2` and `y_cost_rev_h2`: the served p50 quantile against a two-stage hurdle (a
LightGBM classifier of "y at or above the label's step" times expm1 of a LightGBM regressor of log1p(y) fitted on
the stepped rows), and the floors zero and the training mean. The hurdle passes when its MAE is below p50's on both
blocks. CSV: `model/experiments/h1_hurdle.csv`.

| Magnitude | Block | Folds | Rows | Share stepped | Method | MAE | RMSE | Bias | MAE stepped | MAE unstepped | Mean forecast (mean y) | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| months | val | 6 | 10,063 | 0.347 | p50 | 3.341 | 8.023 | +0.651 | 5.87 | 2.00 | 1.97 (2.62) | - |
| months | val | 6 | 10,063 | 0.347 | hurdle | 3.561 | 8.181 | +1.933 | 7.83 | 1.30 | 0.68 (2.62) | fail |
| months | val | 6 | 10,063 | 0.347 | zero | 3.642 | 8.441 | +2.617 | 8.82 | 0.89 | 0.00 (2.62) | - |
| months | val | 6 | 10,063 | 0.347 | train_mean | 4.431 | 8.036 | -0.399 | 5.82 | 3.70 | 3.02 (2.62) | - |
| months | flash | 3 | 2,613 | 0.478 | p50 | 4.123 | 9.405 | +2.462 | 7.01 | 1.47 | 2.25 (4.71) | - |
| months | flash | 3 | 2,613 | 0.478 | hurdle | 4.795 | 10.265 | +3.996 | 9.09 | 0.86 | 0.72 (4.71) | fail |
| months | flash | 3 | 2,613 | 0.478 | zero | 5.078 | 10.627 | +4.712 | 10.04 | 0.53 | 0.00 (4.71) | - |
| months | flash | 3 | 2,613 | 0.478 | train_mean | 5.023 | 9.693 | +1.793 | 7.12 | 3.10 | 2.92 (4.71) | - |
| cost_pct | val | 6 | 9,392 | 0.043 | p50 | 1.719 | 10.896 | +1.433 | 36.35 | 0.17 | 0.02 (1.46) | - |
| cost_pct | val | 6 | 9,392 | 0.043 | hurdle | 1.768 | 10.892 | +1.381 | 36.33 | 0.23 | 0.08 (1.46) | fail |
| cost_pct | val | 6 | 9,392 | 0.043 | zero | 1.708 | 10.917 | +1.458 | 36.50 | 0.16 | 0.00 (1.46) | - |
| cost_pct | val | 6 | 9,392 | 0.043 | train_mean | 3.614 | 10.840 | -0.665 | 34.37 | 2.24 | 2.12 (1.46) | - |
| cost_pct | flash | 3 | 3,617 | 0.033 | p50 | 1.565 | 9.498 | +0.741 | 34.59 | 0.44 | 0.01 (0.76) | - |
| cost_pct | flash | 3 | 3,617 | 0.033 | hurdle | 1.613 | 9.497 | +0.683 | 34.52 | 0.49 | 0.07 (0.76) | fail |
| cost_pct | flash | 3 | 3,617 | 0.033 | zero | 1.551 | 9.515 | +0.755 | 34.67 | 0.42 | 0.00 (0.76) | - |
| cost_pct | flash | 3 | 3,617 | 0.033 | train_mean | 3.419 | 9.568 | -1.259 | 32.66 | 2.42 | 2.01 (0.76) | - |

- **The hurdle fails for both magnitudes on both blocks**: months 3.56 against 3.34 (validation) and 4.80 against
  4.12 (flash); cost 1.77 against 1.72 and 1.61 against 1.57. It under-forecasts (mean forecast 0.68 months
  against 2.62 observed, bias +1.9): the back-transform of a log1p regression sits below the conditional mean, and
  P(step) times that is smaller still. RMSE is flat across every method (8.0 to 8.4 and 9.4 to 10.6 months).
- **The MAE is flat because the magnitudes are.** The median is the MAE-optimal point forecast, and the median
  further slip within two quarters is near zero for most projects: on validation the served p50 beats forecasting
  zero by 0.30 months (3.34 against 3.64) and on the flash block by 0.96 (4.12 against 5.08); on the stepped rows
  it is 5.9 to 7.0 months off. For the cost change forecasting zero has the lowest MAE of all (1.71 against p50's
  1.72; 1.55 against 1.57): with 3 to 4 per cent of rows revising, the informative outputs are `p_cost_rev_2q` and
  the p95 band, not a point.
- Not shipped; there is no expected-months column. The plan's remedy for a flat MAE was the hurdle; the measurement
  says the flatness is the label's, and the classifier plus the 5-95 band is the right shape of output.

## Monotone constraints

`m1_monotone`: the champion's LightGBM with `monotone_constraints` (+1, the advanced method) on prior revisions
(`revisions_so_far`), the stall count (`stagnation_quarters`), the slip to date (`slip_to_date_months`) and the cost
growth (`cost_variation_pct`); the implied completion gap is not a gold feature (its stand-in was measured in the
upgrade round as `a_feasibility` and left out). CSV: `model/experiments/m1_monotone.csv`.

| Target | Block | Folds | Champion PR-AUC | Challenger PR-AUC | Delta [95% CI] | Folds up | Pre-event: champion -> challenger | Val ECE: champion -> challenger | Rule | Ship |
|---|---|---|---|---|---|---|---|---|---|---|
| y_any_h2 | val | 6 | 0.6962 | 0.6904 | -0.0058 [-0.0088, -0.0029] | 1/6 | 0.588 -> 0.578 | 0.0818 -> 0.0811 | fail | reject |
| y_any_h2 | flash | 3 | 0.7775 | 0.7803 | +0.0028 [-0.0014, +0.0071] | 3/3 | 0.740 -> 0.742 | - -> - | fail | reject |
| y_date_push_h2 | val | 6 | 0.6320 | 0.6285 | -0.0035 [-0.0057, -0.0012] | 2/6 | 0.547 -> 0.538 | 0.0555 -> 0.0528 | fail | reject |
| y_date_push_h2 | flash | 3 | 0.7751 | 0.7699 | -0.0052 [-0.0104, -0.0001] | 0/3 | 0.721 -> 0.707 | - -> - | fail | reject |
| y_cost_rev_h2 | val | 6 | 0.1824 | 0.1790 | -0.0035 [-0.0098, +0.0030] | 3/6 | 0.228 -> 0.218 | 0.0039 -> 0.0046 | fail | reject |
| y_cost_rev_h2 | flash | 3 | 0.1595 | 0.1640 | +0.0044 [-0.0063, +0.0151] | 1/3 | 0.076 -> 0.083 | - -> - | fail | reject |
| y_any_h4 | val | 6 | 0.8844 | 0.8831 | -0.0013 [-0.0034, +0.0008] | 3/6 | 0.856 -> 0.852 | 0.0959 -> 0.0964 | fail | reject |
| y_any_h4 | flash | 1 | 0.8764 | 0.8809 | +0.0045 [-0.0039, +0.0138] | 1/1 | 0.874 -> 0.876 | - -> - | fail | reject |
| y_any_h1 | val | 6 | 0.4621 | 0.4612 | -0.0009 [-0.0043, +0.0023] | 3/6 | 0.394 -> 0.387 | 0.0220 -> 0.0218 | fail | reject |
| y_any_h1 | flash | 4 | 0.5311 | 0.5346 | +0.0035 [-0.0024, +0.0085] | 3/4 | 0.491 -> 0.501 | - -> - | fail | reject |
| y_any_h6 | val | 6 | 0.9254 | 0.9240 | -0.0014 [-0.0033, +0.0004] | 3/6 | 0.922 -> 0.918 | 0.0534 -> 0.0508 | fail | reject |

runtime: 261 s

- **Fails on all six targets.** Inside the validation folds the constrained model ranks worse everywhere (-0.001 to
  -0.006; the primary target and the date push with CIs below 0, 1 and 2 folds up of 6); on the flash blocks it is
  inside the noise (-0.005 to +0.005). The trees use reversals the constraints forbid: many revisions with a long
  time since the last one, or a large slip to date on a project whose anticipated date is now far out, read as
  lower risk within two quarters, not higher. Four constrained features of 62 buy no stability that the seeds do not
  already show (the champion's seed SD is 0.001 to 0.008), and the explanations already come from SHAP with the
  sign of each contribution. Not shipped.

## What ships, and what does not

Shipped in this round (train run `ML-20260929-070637`, gold `2bc1eebd3f65`, served `lgbm-any2q-20260929-070637`):

- **Pre-event metrics** (`pre_*`) in `backtest_summary.csv` and every registry entry, and the **error analysis**
  `slices.csv` in every train run; the fold-to-fold SD of PR-AUC (`pr_auc_fold_sd`); the harness reports the
  pre-event PR-AUC of champion and challenger (`--table` shows it).
- **Labels at every quarter to 18 months** (`labels_h1.parquet` to `labels_h6.parquet`), `label_noise` and
  `progress_coverage_by_year` in the gold manifest, and two new backtest targets, `y_any_h1` and `y_any_h6`, whose
  first LightGBM champions were promoted over the logistic regression under the rule (+0.1445 and +0.0741 validation
  within-cutoff PR-AUC), served as `p_any_1q` and `p_any_6q`. Their seed noise is in `seed_sd.csv` and
  `registry.SEED_SD`.
- **The runway curve** `runway_any_1q` to `runway_any_6q` from the survival model (`ml/survival.py`), fitted on
  every realised person-period at scoring time; not a champion, and not what the tiers rank.
- **A window rule fix**: validation takes the newest reliable block that has a usable cutoff before 2025-07 (for
  the 1-quarter target the newest block is flash-era only).
- Calibrator plumbing for an isotonic method (`backtest.isotonic_fit`, `platt_apply` reads both kinds, `platt.json`
  records the method per target); no target uses it.
- Four candidates in the catalogue (`s1_survival`, `m1_monotone`, `k1_isotonic`, `h1_hurdle`) with their CSVs.

Not shipped: the survival model as a champion (fails every flash block; its 18-month pass is one block with a lower
bound at zero), monotone constraints (worse inside the validation folds on every target), isotonic calibration
(raises flash ECE, costs ranking), the hurdle point forecast (higher MAE than the served median on both blocks). The
four existing champions were re-scored on the new gold at zero gain, so the tiers and every served probability of
the four original targets are unchanged.

## Caveats

- **The pre-event cohort is defined by the panel.** `revisions_so_far` counts step-ups observed in the reports since
  a project entered the panel; a project that entered already behind its original schedule is in the cohort with
  its slip to date as a feature. The stricter `on_schedule` slice (no slip to date, no cost growth) is 20 to 37 per
  cent of rows and scores 0.53 to 0.61.
- **Small slices.** The cost target's pre-event positives are 15 to 91 per block; Railways on the 2-quarter test
  fold has 52 positives; the 12-month flash block is one fold of 335 rows. Read those cells as directions, not
  numbers.
- **The 3-month target's test fold** (2026-04, 152 positives) scores 0.204 at a base rate of 0.108 with ECE 0.19:
  the 2026-07 report is one quarter of outcomes, and the flash block (four cutoffs, 0.540) is the better estimate.
- **Regime.** Every result in this round repeats the finding of the upgrade round: what helps inside the
  quarterly-report validation folds (2023-07 to 2024-10) can hurt on the flash block (2025-07 on), and the served
  ranking must hold on both.
- **Nothing here is a lead-time gain.** The lead time from the first top-100 flag to the slip is unchanged at 2.8
  quarters on validation and 2.1 to 2.2 on the flash block for the primary target.

## Runtime (this laptop, 16 threads)

- Gold: 9.6 s (six horizons; the label files are byte-identical for 2 and 4 quarters).
- Train: 238 s for six targets with the slices and the interval backtest.
- Score: about 45 s including the survival model's 141,797 person-periods.
- Harness: `s1_survival` 346 s for six targets (one hazard model per cutoff and seed, shared across the y_any horizons), `m1_monotone` 261 s, `k1_isotonic` 50 s and `h1_hurdle` 46 s (both on cached champion predictions), the seed SD of the two new targets 62 s.

## Reproduce

```
python -m pipeline.run gold                                     # labels_h1..h6, label_noise, progress coverage
python -m pipeline.run train                                    # six targets, backtest_summary.csv pre_* columns, slices.csv
python -m ml.experiment --seed-sd --champion-run ML-20260929-070637 --targets y_any_h1,y_any_h6
python -m ml.experiment s1_survival --champion-run ML-20260929-070637
python -m ml.experiment m1_monotone --champion-run ML-20260929-070637
python -m ml.experiment k1_isotonic
python -m ml.experiment h1_hurdle
python -m ml.experiment --table                                 # the candidate tables, with the pre-event column
python -m pipeline.run score                                    # p_any_1q/6q and runway_any_1q..6q
```
