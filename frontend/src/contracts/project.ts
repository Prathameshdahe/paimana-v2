/**
 * src/contracts/project.ts
 *
 * One-project and project-list shapes as served by the FastAPI backend
 * (backend/schemas.py; keys are camelCase). Dates are ISO strings.
 */

/** Rank-based tier; a project without an anticipated completion date has no tier (null, "untiered"). */
export type Tier = 'Critical' | 'High' | 'Medium' | 'Low'
export type TierFilter = Tier | 'untiered'
export type Flag = 'land' | 'forest' | 'litigation' | 'contractor' | 'early_notice'
export type ProjectSort = 'risk' | 'cost' | 'slip' | 'name'

export interface ProjectRow {
  key: string
  name: string | null
  sector: string | null
  state: string | null
  agency: string | null
  ministry: string | null
  tier: Tier | null
  tierRankPct: number | null
  override: boolean | null
  pAny2q: number | null
  pDatePush2q: number | null
  pCostRev2q: number | null
  monthsP50: number | null
  monthsP95: number | null
  anticipatedCostCr: number | null
  expenditureCr: number | null
  physicalProgressPct: number | null
  anticipatedCompletion: string | null
  slipToDateMonths: number | null
  noCompletionDate: boolean | null
  flags: Flag[]
}

export interface ProjectPage {
  total: number
  page: number
  size: number
  items: ProjectRow[]
}

export interface ShapValue {
  feature: string
  value: unknown
  contribution: number
}

export interface Scores {
  pDatePush2q: number | null
  pCostRev2q: number | null
  pAny2q: number | null
  pAny4q: number | null
  monthsP05: number | null
  monthsP50: number | null
  monthsP95: number | null
  costPctP05: number | null
  costPctP50: number | null
  costPctP95: number | null
  tierRankPct: number | null
  tierByRank: Tier | null
  tier: Tier | null
  stagnationOverride: boolean | null
  noCompletionDate: boolean | null
  stagnationQuarters: number | null
  elapsedRatio: number | null
  shapTop5: ShapValue[]
}

export type RiskState = 'flagged' | 'clear' | 'unknown'

export interface RiskRow {
  dimension: string
  state: RiskState
  evidence: string | null
  source: string | null
  asOfDate: string | null
}

export interface EventRow {
  category: string
  eventNo: number
  firstSeen: string | null
  lastSeen: string | null
  nQuarters: number | null
  nMentions: number | null
  status: string | null
  resolved: boolean | null
  subtype: string | null
  authority: string | null
  forestAreaHa: number | null
  violation: boolean | null
  evidence: string | null
  sourceDocId: string | null
  sourcePage: number | null
  remarksLastSeen: string | null
}

/** Parquet rows passed through as they are; only the fields the UI reads are typed. */
export interface MasterRecord {
  projectName?: string | null
  codesSeen?: string | null
  sanctionDate?: string | null
  agency?: string | null
  ministry?: string | null
  sector?: string | null
  state?: string | null
  lastStatus?: string | null
  [field: string]: unknown
}

export interface ObservationRecord {
  period?: string | null
  projectCode?: string | null
  originalCostCr?: number | null
  anticipatedCostCr?: number | null
  expenditureCr?: number | null
  physicalProgressPct?: number | null
  scheduledCompletion?: string | null
  anticipatedCompletion?: string | null
  remarks?: string | null
  [field: string]: unknown
}

export interface External {
  fc: Record<string, unknown> | null
  land: Record<string, unknown> | null
  landPairs: Record<string, unknown>[]
  composite: Record<string, unknown> | null
  events: EventRow[]
}

export interface Provenance {
  asof: string
  modelVersion: string | null
  goldVersion: string
  silverVersion: string
  sourceDocId: string | null
  sourcePage: number | null
  period: string | null
  periodType: string | null
}

export interface ReviewBadge {
  nRows: number
  firstPeriod: string | null
  lastPeriod: string | null
  note: string
}

export interface ProjectDetail {
  key: string
  master: MasterRecord | null
  latest: ObservationRecord | null
  /** null: not in the current scored portfolio (e.g. completed) */
  scores: Scores | null
  flags: Flag[]
  riskProfile: RiskRow[]
  external: External
  provenance: Provenance
  review: ReviewBadge | null
}

export interface TimelinePoint {
  period: string
  physicalProgressPct: number | null
  expenditureCr: number | null
  anticipatedCostCr: number | null
  anticipatedCompletion: string | null
  sourceDocId: string | null
  sourcePage: number | null
  periodType: string | null
}

export interface Timeline {
  key: string
  points: TimelinePoint[]
}

export interface ScenarioPoint {
  step: number
  quarter: string
  /** own recent velocity */
  continue: number | null
  /** recover to sector-median velocity */
  recover: number | null
  /** follow the agency's historical pattern */
  agency: number | null
  agencyBasis: string | null
}

export interface Analogue {
  rank: number
  analogueKey: string
  analogueName: string | null
  analoguePeriod: string | null
  targetPeriod: string | null
  sector: string | null
  basis: string | null
  distance: number | null
  yMonths: number | null
  yCostPct: number | null
  yAny: number | null
  yDatePush: number | null
  yCostRev: number | null
}

export interface ScurvePoint {
  elapsedLo: number
  elapsedHi: number
  expectedProgress: number | null
  nProjects: number | null
  /** bin middle on the project's sanction-to-scheduled span */
  date: string | null
}

export interface BandPoint {
  quarter: string
  lo: number
  mid: number
  hi: number
}

export interface CompletionBand {
  anticipated: string | null
  monthsP05: number | null
  monthsP50: number | null
  monthsP95: number | null
  p05: string | null
  p50: string | null
  p95: string | null
}

export interface Forecast {
  key: string
  asof: string
  sector: string | null
  elapsedRatio: number | null
  physicalProgressPct: number | null
  scenarios: ScenarioPoint[]
  analogues: Analogue[]
  analogueSummary: string
  scurveFitYear: number | null
  scurve: ScurvePoint[]
  band: BandPoint[]
  completion: CompletionBand
  bandMethod: string
}

export interface Signal {
  id: number
  url: string
  title: string | null
  source: string | null
  publishedAt: string | null
  fetchedAt: string | null
  summary: string | null
  category: string | null
  severity: number | null
  linkScore: number | null
  method: string | null
  /** first report period after the article whose CUF row changed; null while none has */
  cufChangePeriod: string | null
  leadDays: number | null
}

export interface ProjectSignals {
  key: string
  /** null: the scout never searched this project, so no signals is unknown, not clear */
  lastScoutAt: string | null
  items: Signal[]
}
