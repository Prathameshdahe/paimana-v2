**SYNTHETIC DATA. Nothing in this folder describes a real project. Never feed it to the model, the gold features, the predictions, the risk profile or the app.**

Two mock files from Garvit's external-factor bootstrap (docs/EXTERNAL_FACTORS_GUIDE.md section 4), kept only as
test fixtures for the formulas (tests/test_external_crosscheck.py, tests/test_external.py):

| File | Rows | Columns | Composite |
|---|---|---|---|
| `external_factor_mock_v0.csv` | 150 | 23 | 0.5 x fc/7 + 0.5 x la/5 |
| `external_factor_mock_v1_gatishakti.csv` | same 150 ids | 23 + 6 `gs_*` | (fc/7 + la/5 + gs/4) / 3 |

Derived from real data:
- FC profile: `fc_scenario_id`, `fc_authority_level`, `fc_complexity_score` and `fc_violation_flag` are draws from the
  real Parivesh rulebook (`../parivesh_fc_scenarios.csv`); all 89 FC rows match it.
- LA profile: parcel, area, district and span patterns are sampled from the real Maharashtra Bhoomi Rashi stretches
  (`../land_acquisition_maharashtra.csv`).

Invented:
- project ids `PAIMANA-1000` to `PAIMANA-1149` (not PAIMANA projects), costs, sectors (Rural Road, State Highway and
  Bridge are not in the portfolio), states and dates;
- the outcome columns `actual_time_overrun_days` and `overrun_flag`, built to correlate with the composite (r 0.87);
- `la_state_fragmentation_factor` (Bihar 1.5, UP 1.35, ..., a guess, not measured), applied after the LA score, so the
  LA rule reproduces only about half of the mock LA scores;
- `fc_status` and `fc_duration_days` (there is no Parivesh proposal-level data yet);
- every `gs_*` GatiShakti column.

See docs/EXTERNAL_DATA_CROSSCHECK.md for the full cross-check.
