/**
 * src/contracts/sandbox.ts
 *
 * Type contracts for the What-If Prescriptive Sandbox (PRESCRIBE view).
 * All levers correspond to administratively actionable interventions
 * documented in PROJECT_CONTEXT.md Section 3 (root cause categories).
 */

// ── Sandbox Inputs ────────────────────────────────────────────────────────────

/**
 * The three policy levers available to administrators in the sandbox.
 * Each lever maps to a real administrative action category from IPMD intervention playbooks.
 */
export interface SandboxControls {
  /**
   * Days of statutory clearance process accelerated via central facilitation.
   * Targets: land acquisition (Section 11/19), MoEFCC forest clearance Stage-II,
   * utility shifting NOCs.
   * Range: 0 (no acceleration) to 90 days maximum.
   */
  clearanceAccelerationDays: number

  /**
   * Additional capital tranche injected via emergency fund release.
   * Addresses EPC contractor working capital crunch and fund utilisation lag.
   * Range: ₹0 Cr to ₹300 Cr.
   */
  capitalTrancheInjectionCr: number

  /**
   * Percentage increase in contractor workforce mobilization.
   * Represents deployment of additional labour, equipment, and sub-contractors.
   * Range: 0% (no change) to +50% increase.
   */
  workforceMobilizationPct: number
}

// ── Sandbox Outputs ───────────────────────────────────────────────────────────

/**
 * Recalculated project outcome after applying SandboxControls.
 * The client-side surrogate model must compute this in < 16ms (single frame).
 */
export interface SandboxOutcome {
  /** Revised predicted completion date (ISO 8601 date string) */
  predictedDocRevised: string
  /** Revised total delay months vs. revisedDoc */
  predictedDelayMonthsRevised: number
  /** Revised ML-projected final cost overrun (₹ Cr) */
  overrunForecastCrRevised: number
  /** Revised composite risk score (0–100) */
  compositeRiskScoreRevised: number
}

/**
 * Net delta between baseline and simulated outcomes.
 * Displayed in the Comparative Delta Card — the key executive summary.
 */
export interface SandboxDelta {
  /** Months of schedule recovered (positive = improvement) */
  monthsRecovered: number
  /** Public capital saved vs. baseline overrun forecast (₹ Cr, positive = saving) */
  capitalSavedCr: number
  /** Risk score points reduced (positive = risk reduction) */
  riskScoreReduction: number
}

// ── Full Sandbox State ────────────────────────────────────────────────────────

/**
 * Complete sandbox session state for a single project simulation.
 * Baseline is the unmodified project outcome.
 * Simulated updates in real-time as levers change.
 */
export interface SandboxState {
  /** The project currently loaded in the sandbox */
  projectId: string
  /** Unmodified outcome (from mock data — never changes during a session) */
  baseline: SandboxOutcome
  /** Current simulated outcome (recalculates on every lever change) */
  simulated: SandboxOutcome
  /** Delta between baseline and simulated (recalculates on every lever change) */
  delta: SandboxDelta
  /** Current lever positions */
  controls: SandboxControls
}

// ── Surrogate Model Coefficient Type ─────────────────────────────────────────

/**
 * Linear surrogate model coefficients for client-side recalculation.
 * These encode the approximate marginal impact of each lever on outcomes.
 * Values are project-specific and embedded in mock data or future API response.
 */
export interface SurrogateCoefficients {
  /** Months saved per day of clearance acceleration */
  clearancePerDay: number
  /** Months saved per ₹100 Cr of capital injection */
  capitalPer100Cr: number
  /** Months saved per 10% workforce increase */
  workforcePer10Pct: number
  /** Cost overrun reduced per day of clearance acceleration (₹ Cr) */
  costClearancePerDay: number
  /** Cost overrun reduced per ₹100 Cr injection (₹ Cr) */
  costCapitalPer100Cr: number
}
