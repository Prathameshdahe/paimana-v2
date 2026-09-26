/**
 * src/contracts/portfolio.ts
 *
 * Portfolio-level aggregate summary type.
 * Powers the Persistent Top Bar ticker and Macro KPI Ribbon.
 * All figures must remain consistent with PROJECT_CONTEXT.md baseline.
 */

export interface PortfolioSummary {
  /** Total monitored projects — authoritative: 1,981 */
  totalProjects: number
  /** Total projects flagged as CRITICAL risk tier */
  criticalCount: number
  /** Total projects flagged as WARNING risk tier */
  warningCount: number
  /** Total projects at NORMAL risk tier */
  normalCount: number
  /** Original sanctioned cost of entire portfolio (₹ Cr) — authoritative: 3,713,000 */
  originalPortfolioCostCr: number
  /** Revised anticipated cost of entire portfolio (₹ Cr) — authoritative: 4,278,000 */
  revisedPortfolioCostCr: number
  /** Cumulative expenditure to date across portfolio (₹ Cr) — authoritative: 2,036,000 */
  cumulativeExpenditureCr: number
  /** Documented capital escalation (₹ Cr) — authoritative: 565,000 */
  cumulativeOverrunCr: number
  /**
   * Data snapshot label for the reporting cycle.
   * Displayed in the top bar: "Apr 2026 Snapshot"
   */
  reportingCycle: string
  /** Average Physical-Financial disparity across the monitored portfolio (%) */
  avgDisparityDeltaPct: number
}
