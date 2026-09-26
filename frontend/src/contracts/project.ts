/**
 * src/contracts/project.ts
 *
 * Core domain type contracts for PAIMANA Early Warning Radar.
 * All fields are aligned to MoSPI Common Upload Form (CUF) parameters
 * and engineered indicators documented in PROJECT_CONTEXT.md.
 *
 * DO NOT invent fields not grounded in CUF or PROJECT_CONTEXT.md.
 */

// ── Enumerations ─────────────────────────────────────────────────────────────

/**
 * Risk tier classification for executive triage.
 * Maps to semantic color tokens: critical / warning / stable.
 */
export type RiskTier = 'CRITICAL' | 'WARNING' | 'NORMAL'

/**
 * Infrastructure sectors monitored by MoSPI IPMD.
 * 17 Central Ministries covering 22 sectors — primary sectors represented.
 */
export type Sector =
  | 'Road Transport and Highways'
  | 'Railways'
  | 'Power'
  | 'Petroleum'
  | 'Coal'
  | 'Civil Aviation'
  | 'Atomic Energy'
  | 'Telecommunications'
  | 'Urban Development'
  | 'Water Resources'
  | 'Health and Family Welfare'
  | 'Department of Higher Education'
  | 'Steel'
  | 'Mines'
  | 'Shipping and Ports'
  | 'DPIIT'
  | (string & {})

/**
 * Direction of a SHAP feature's impact on project risk.
 * worsening: increases delay/cost · improving: reduces risk · neutral: minimal effect
 */
export type ShapDirection = 'worsening' | 'improving' | 'neutral'

// ── Sub-Interfaces ────────────────────────────────────────────────────────────

/**
 * SHAP feature attribution entry for the root-cause waterfall chart.
 * Represents the explainability output (Clause a) for a single bottleneck factor.
 */
export interface ShapDriver {
  /** Human-readable bottleneck label — must reference real CUF delay categories */
  feature: string
  /** Normalised attribution weight (0–1). Sum of all drivers ≈ 1 for a project. */
  weight: number
  /**
   * Estimated delay contribution in months.
   * Positive = adds delay (worsening). Negative = reduces delay (improving).
   */
  impactMonths: number
  direction: ShapDirection
}

/**
 * Single quarter data point for the Earned Value S-Curve chart.
 * Plots Planned Baseline vs. Actual Spend vs. Physical Progress % vs. Projected.
 */
export interface SCurveDataPoint {
  /** Quarter label — e.g. "Q3 FY24", "Q1 FY25" */
  quarter: string
  /** Cumulative planned (baseline) expenditure in ₹ Cr */
  plannedSpendCr: number
  /** Actual cumulative expenditure to date in ₹ Cr */
  actualSpendCr: number
  /**
   * Physical civil work progress as a percentage (0–100).
   * Key indicator: when physicalProgressPct << (actualSpendCr / revisedCostCr * 100),
   * it signals the Physical-Financial Disparity (Δ P-F) — a leading overrun indicator.
   */
  physicalProgressPct: number
  /**
   * ML-projected cumulative spend for future quarters.
   * For past quarters: set equal to actualSpendCr.
   * For future quarters: model-projected trajectory.
   */
  projectedSpendCr: number
}

/**
 * Confidence interval for the predicted completion delay (Clause a).
 * Represents the 90% confidence band around the point estimate.
 */
export interface DelayCI {
  lowerMonths: number
  upperMonths: number
}

// ── Core Project Interface ────────────────────────────────────────────────────

/**
 * Full project record as consumed by all PAIMANA views.
 * Fields are grouped by their CUF source category.
 */
export interface Project {
  // ── CUF Metadata Fields ──────────────────────────────────────────────────
  /** Internal PAIMANA UUID */
  id: string
  /** MoSPI project code — ministry prefix + sector code + sequence (e.g. "MOR-ROD-048") */
  code: string
  name: string
  /** Sponsoring Central Ministry (e.g. "Ministry of Road Transport & Highways") */
  ministry: string
  sector: Sector
  /** Implementing agency — the executing entity (NHAI, RVNL, NTPC, HPCL, CIL, etc.) */
  agency: string
  /** Primary state(s) where project is located */
  state: string
  /** Work category tagged from project name (construction, upgradation, doubling, etc.) */
  projectType?: string
  /** Provenance of the sector/state fields — for the data-confidence badge */
  dataConfidence?: {
    sectorSource: 'pdf_reparse' | 'cross_period_vote' | 'name_keyword_rule' | 'original_extraction'
    stateSource: 'pdf_reparse' | 'cross_period_vote' | 'original_extraction'
  }

  // ── CUF Financial Telemetry ──────────────────────────────────────────────
  /** Original Approved Cost at sanction (₹ Cr) */
  originalCostCr: number
  /** Latest Revised Approved Cost (₹ Cr) — reflects cost revisions submitted to MoSPI */
  revisedCostCr: number
  /** Cumulative expenditure to date (₹ Cr) */
  currentExpenditureCr: number
  /**
   * Physical-Financial Disparity Index Δ(P-F).
   * Formula: (financialProgressPct - physicalProgressPct)
   * where financialProgressPct = (currentExpenditureCr / revisedCostCr) * 100
   * Positive value = financial burn ahead of physical work = cost escalation signal.
   */
  disparityDeltaPct: number
  /** ML-predicted final cost overrun vs. revised cost (₹ Cr) */
  overrunForecastCr: number

  // ── CUF Timeline Telemetry ───────────────────────────────────────────────
  /** Original Date of Commissioning at sanction (ISO 8601 date string) */
  sanctionedDoc: string
  /** Administratively revised DOC submitted to MoSPI (ISO 8601 date string) */
  revisedDoc: string
  /** ML-predicted actual completion date (ISO 8601 date string) */
  predictedDoc: string
  /** Point estimate of total delay vs. revisedDoc (months) */
  predictedDelayMonths: number
  /** 90% confidence interval on predictedDelayMonths (Clause a) */
  delayCI: DelayCI

  // ── Engineered Risk Indicators ───────────────────────────────────────────
  /**
   * Composite Project Risk Score — normalised 0 to 100 (Clause a).
   * Aggregates cost overrun probability, schedule delay severity, and disparity index.
   * 0 = minimal risk · 100 = maximum risk / Point of No Return exceeded.
   */
  compositeRiskScore: number
  /**
   * Days remaining until the Point of No Return (actionable intervention window).
   * When this reaches 0, administrative intervention can no longer prevent the overrun.
   * Drives the X-axis of the Portfolio Urgency Matrix.
   */
  actionableRunwayDays: number
  /**
   * Float depletion velocity — % of schedule buffer consumed per month.
   * High velocity signals accelerating risk even before RunwayDays hits zero.
   */
  floatDepletionVelocity: number
  riskTier: RiskTier

  // ── Explainability ───────────────────────────────────────────────────────
  /** Primary bottleneck — the single most impactful delay cause (human-readable label) */
  topBottleneck: string
  /** SHAP feature attributions for the root-cause waterfall chart (Clause a) */
  shapDrivers: ShapDriver[]
  /**
   * CUF delay remarks field — authentic-style nodal officer submission text.
   * Provides qualitative context for the quantitative risk indicators.
   */
  delayRemarks: string

  // ── Earned Value S-Curve ─────────────────────────────────────────────────
  /**
   * 8-quarter time series for the S-Curve chart.
   * Quarters ordered chronologically. Last 1–2 entries are future projections.
   */
  sCurve: SCurveDataPoint[]
}
