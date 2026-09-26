/**
 * src/contracts/audit.ts
 *
 * Type contracts for the MoSPI Compliance & Audit Suite (PROVE view).
 * Covers both evaluation clauses from PS-26103:
 *   Clause (b): AI/ML vs. Classical Statistical model benchmarking
 *   Clause (c): CUF field utility audit & missing variable roadmap
 */

// ── Clause (b): Model Benchmark ───────────────────────────────────────────────

/**
 * Model category — distinguishes statistical baselines from ML challengers.
 * Clause (b) requires a rigorous comparative assessment between these two categories.
 */
export type ModelCategory = 'classical' | 'ml'

/**
 * Single row in the AI/ML vs. Statistical benchmark comparison matrix.
 *
 * Sourced from model/metrics.json — the actual chronological
 * train/buffer/test backtest run against the real 2024-25+2025-26 panel
 * (ml/train.py). These are real numbers from a real run, not projections.
 */
export interface ModelBenchmarkRow {
  /** Full model name for display (e.g. "Trust Reported Date (do-nothing floor)") */
  modelName: string
  /** Short identifier for chart labels */
  modelShortName: string
  modelCategory: ModelCategory
  /** Precision-Recall AUC on the held-out temporal test split. Higher is better. */
  prAuc: number
  /** Of test rows that truly slipped, the fraction captured in the top-50-by-score list. */
  recallAt50: number
  /** Empirical months between the alerting report and the next observed report, for correctly-flagged true positives. */
  leadTimeMonths: number
  /** Test-split row count this model was scored on. */
  nTest: number
  /** True-positive count in the test split (the slip base rate is thin — see AuditSuite notes). */
  nPositive: number
  /**
   * True if this model serves as the do-nothing floor for relative comparison.
   * "Trust reported date" is the baseline per Clause (b) specification.
   */
  isBaseline: boolean
  /** Notes on what this method is / its limitation — factual, not marketing copy */
  notes: string
}

// ── Clause (c): CUF Field Audit ───────────────────────────────────────────────

/**
 * Single row in the CUF field utility audit table.
 * Each row assesses one data field — either currently collected or proposed.
 *
 * Grounded in PROJECT_CONTEXT.md Section 4 (CUF fields) and Section 5 (Clause c).
 */
export interface CUFFieldAuditRow {
  /** CUF parameter name or proposed variable name */
  fieldName: string
  /** Brief description of what this field captures */
  description: string
  /**
   * Is this field currently captured in the MoSPI CUF form?
   * true = existing field · false = proposed addition
   */
  currentlyCollected: boolean
  /**
   * Estimated information gain contribution to risk score prediction (%).
   * Derived from feature importance analysis on historical OCMS/PAIMANA data.
   */
  infoGainPct: number
  /**
   * For proposed fields (currentlyCollected = false):
   * The projected improvement in risk score prediction accuracy if this field were added (%).
   */
  projectedAccuracyDeltaPct: number
  /**
   * Additional early warning lead time (days) that this field would enable.
   * i.e., how many more days before overrun the model would flag the project as CRITICAL.
   */
  earlyWarningLeadDays: number
  /**
   * Data acquisition feasibility for missing variables.
   * 'immediate' = available from existing govt databases
   * 'short-term' = requires inter-ministry MoU (< 6 months)
   * 'medium-term' = requires new data collection mechanism (6–18 months)
   */
  acquisitionFeasibility: 'immediate' | 'short-term' | 'medium-term' | 'existing'
  /**
   * Policy justification for adding this field to the CUF.
   * Must reference specific PROJECT_CONTEXT.md bottleneck categories.
   */
  rationale: string
}

// ── Audit Suite Summary ───────────────────────────────────────────────────────

/**
 * Aggregate summary statistics for the benchmark comparison header.
 */
export interface BenchmarkSummary {
  bestModelName: string
  bestMaeMonths: number
  baselineMaeMonths: number
  maeImprovementPct: number
  bestR2Score: number
  baselineR2Score: number
}

/**
 * Summary for the CUF audit header — total potential gains from proposed fields.
 */
export interface CUFAuditSummary {
  currentFieldCount: number
  proposedAdditions: number
  projectedTotalAccuracyGainPct: number
  projectedMaxEarlyWarningDays: number
}
