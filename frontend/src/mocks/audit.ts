/**
 * src/mocks/audit.ts
 *
 * Typed data for the MoSPI Compliance & Audit Suite.
 *
 * Clause (b): AI/ML vs. Statistical model benchmark comparison matrix.
 * Clause (c): CUF field utility audit & missing variable roadmap.
 *
 * Clause (b) rows below are copied straight from model/metrics.json —
 * the real chronological backtest (train ends 2025-01, buffer to 2025-05,
 * test on 1,589 rows / 64 true positives) run by ml/train.py. Not
 * projections, not illustrative — this is the actual run's output. If the
 * model is retrained, re-sync these numbers from that file.
 */

import type { ModelBenchmarkRow, CUFFieldAuditRow } from '@/contracts/audit'

// ── Clause (b): Model Benchmark Data (real, from model/metrics.json) ──
// Baseline: "trust reported date" (do nothing). Thin positive class (64/1589
// test rows, ~4%) — treat PR-AUC/Recall@50 deltas as directional, not final.

export const MOCK_BENCHMARK_ROWS: ModelBenchmarkRow[] = [
  {
    modelName: 'Trust Reported Date',
    modelShortName: 'Trust Date',
    modelCategory: 'classical',
    prAuc: 0.0403,
    recallAt50: 0.0312,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: true,
    notes: 'Do-nothing floor: assumes the agency\'s currently reported date/cost is final. No model.',
  },
  {
    modelName: 'Earned-Schedule Extrapolation',
    modelShortName: 'Earned Sched.',
    modelCategory: 'classical',
    prAuc: 0.0439,
    recallAt50: 0.0156,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: false,
    notes: 'Rule-based: flags slip when pace-implied finish date exceeds the anticipated DOC by 3+ months.',
  },
  {
    modelName: 'Reference-Class Forecasting',
    modelShortName: 'Ref. Class',
    modelCategory: 'classical',
    prAuc: 0.0425,
    recallAt50: 0.0312,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: false,
    notes: 'Assigns each project its (sector × type × size-band) historical slip rate from the training split.',
  },
  {
    modelName: 'Logistic Regression (Tier 2 features)',
    modelShortName: 'Logistic Reg.',
    modelCategory: 'classical',
    prAuc: 0.0433,
    recallAt50: 0.0312,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: false,
    notes: 'Same engineered feature set as LightGBM Tier 2, linear model — the honest statistical comparator Clause (b) asks for.',
  },
  {
    modelName: 'LightGBM (Tier 1 — raw CUF fields only)',
    modelShortName: 'LightGBM T1',
    modelCategory: 'ml',
    prAuc: 0.0631,
    recallAt50: 0.0469,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: false,
    notes: 'No engineered features — ablation floor for Clause (c). Already beats every classical baseline.',
  },
  {
    modelName: 'LightGBM (Tier 2 — + engineered features)',
    modelShortName: 'LightGBM',
    modelCategory: 'ml',
    prAuc: 0.0786,
    recallAt50: 0.125,
    leadTimeMonths: 1.0,
    nTest: 1589,
    nPositive: 64,
    isBaseline: false,
    notes: 'Best on both metrics. Recommended model — powers the live Forecaster worker and the dashboard\'s risk scores.',
  },
]

/** Verbatim from model/metrics.json — surfaced so the audit view stays honest about limitations. */
export const BENCHMARK_NOTES: string[] = [
  'LightGBM Tier 2 strictly beats every baseline and the Tier 1 ablation on PR-AUC and Recall@50 — no baseline ties or beats it.',
  'Test split: 1,589 rows, only 64 true positives (~4% base rate) — small dataset, treat as directional not final.',
  'Buffer between train and test is 3 months, not the full 6-month horizon — data was too thin for the ideal buffer; logged here rather than hidden.',
  'Tier 3 (Scout external evidence) is not included — no Scout data exists yet to merge, no placeholder numbers were fabricated for it.',
]

// ── Clause (c): CUF Field Utility Audit Data ──────────────────────────────────
// "Currently collected" rows below use REAL info gain: TreeSHAP mean|contribution|
// from the trained Tier2 LightGBM on the test split, normalized to %
// (model/shap_test_sanity.json). Includes both raw CUF fields and
// signals already computable today from existing CUF data (no new collection
// needed) — that distinction is called out in each rationale.
// "Proposed" rows are genuinely un-measured: Tier 3 (Scout external evidence)
// hasn't been built yet, so no accuracy-delta number is claimed for them.

export const MOCK_CUF_AUDIT_ROWS: CUFFieldAuditRow[] = [
  // ── Currently Collected / Computable Today (real SHAP importance) ────────
  {
    fieldName: 'Physical Progress %',
    description: 'Civil work physical completion reported by nodal officer (%) — raw CUF field',
    currentlyCollected: true,
    infoGainPct: 14.8,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'existing',
    rationale:
      'Top-ranked feature by mean |SHAP| on the trained Tier2 LightGBM (test split). Already collected — no new field needed.',
  },
  {
    fieldName: 'Implementing Agency',
    description: 'Executing agency identity (NHAI, RVNL, NTPC, etc.) — raw CUF field',
    currentlyCollected: true,
    infoGainPct: 12.4,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'existing',
    rationale:
      '2nd by real SHAP importance — agencies carry a measurable track-record signal the model picks up directly from identity, before any of their reported numbers are even read.',
  },
  {
    fieldName: 'Revision Count (derived)',
    description: 'Number of prior DOC/cost revisions for this project — computed from consecutive CUF reports, not a new field',
    currentlyCollected: true,
    infoGainPct: 12.0,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      '3rd by real SHAP importance. Zero new data collection — MoSPI already has every prior report; this is a computation MoSPI\'s own systems could surface directly instead of leaving to downstream analysis.',
  },
  {
    fieldName: '% Schedule Time Elapsed (derived)',
    description: 'Time elapsed since sanction ÷ time budgeted to anticipated DOC — computed from existing date fields',
    currentlyCollected: true,
    infoGainPct: 11.1,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      '4th by real SHAP importance. Same raw dates CUF already collects — just never compared against physical progress in the current form/dashboard.',
  },
  {
    fieldName: 'Recorded Delay (months)',
    description: 'Delay vs. sanctioned DOC as of this report — raw CUF field',
    currentlyCollected: true,
    infoGainPct: 8.1,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'existing',
    rationale: '5th by real SHAP importance. Already collected.',
  },
  {
    fieldName: 'State',
    description: 'Project state/UT location — raw CUF field',
    currentlyCollected: true,
    infoGainPct: 8.0,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'existing',
    rationale: '6th by real SHAP importance — state-level execution capacity is a measurable, not just anecdotal, signal.',
  },
  {
    fieldName: 'Optimism Gap (derived)',
    description: '% time elapsed minus % physical progress — computed, not a new field',
    currentlyCollected: true,
    infoGainPct: 5.1,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      'Real SHAP importance, mid-table. The single computed metric closest to the PS\'s own "physical vs financial progress mismatch" framing.',
  },
  {
    fieldName: 'Agency Historical Slip Rate (derived)',
    description: 'Expanding-window slip rate of this agency\'s past projects, computed only from periods before the one scored',
    currentlyCollected: true,
    infoGainPct: 2.2,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      'Lower-ranked by real SHAP importance today (agency identity itself already captures most of this), but cheap to compute and worth surfacing on an agency scorecard.',
  },

  // ── Proposed Missing Variables — genuinely not measured ──────────────────
  {
    fieldName: 'EPC Contractor Liquidity Tier',
    description:
      'Credit rating / working capital health tier of the lead EPC contractor at time of reporting',
    currentlyCollected: false,
    infoGainPct: 0,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'short-term',
    rationale:
      'Not in the CUF today and not measurable yet — this is Tier 3 (Scout external evidence), not built yet, so no lift number is claimed. Qualitatively plausible (contractor cash-flow issues are a commonly cited delay cause in nodal remarks) but unquantified until Scout runs and that evidence is fed back into a retrained model.',
  },
  {
    fieldName: 'State Administrative Clearance Latency (Days)',
    description:
      'Median days for state revenue/forest departments to process pending clearances (land acquisition, utility NOCs, RoW handover)',
    currentlyCollected: false,
    infoGainPct: 0,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      'Same as above — plausible from delay remarks and several states already publish this publicly, but not merged into training data yet. Tier 3 candidate, unmeasured.',
  },
  {
    fieldName: 'Regional Monsoon Anomaly Index',
    description:
      'Standardised monsoon rainfall anomaly index for the project district (% deviation from 30-year average, IMD data)',
    currentlyCollected: false,
    infoGainPct: 0,
    projectedAccuracyDeltaPct: 0,
    earlyWarningLeadDays: 0,
    acquisitionFeasibility: 'immediate',
    rationale:
      'Publicly available (IMD, data.gov.in) and cheap to merge, but not yet in the training data. Unmeasured — listed here as a low-cost Tier 3 candidate, not a claimed result.',
  },
]
