/**
 * src/contracts/intel.ts
 *
 * Cross-project intelligence as served by the FastAPI backend (backend/schemas.py;
 * keys are camelCase): the Agency Performance Matrix (GET /api/agencies/matrix) and
 * Bottleneck Intelligence (GET /api/bottlenecks, /api/bottlenecks/{id}).
 */

import type { Outlook } from './project'

/** an agency's past schedule in words (backend, from the hidden schedule bias); 'too few projects' under the floor */
export type ScheduleWord = 'usually later' | 'about on time' | 'usually earlier' | 'too few projects'
/** an agency's past cost in words, from the hidden cost bias */
export type CostWord = 'usually costs more' | 'about as planned' | 'usually costs less' | 'too few projects'

/**
 * One canonical agency (printed names merged, gold/agency_map.csv). Biases are ratios
 * (0.56 = 56% longer / costlier than first planned). scheduleBias / costBias are shrunk
 * toward the sector median when n < 10; the *Raw ones are not; the CIs are bootstrap
 * 90% intervals of the raw median. Every bias, quantile, CI, the shrink weight and the trend are hidden numbers (null
 * without the numbers feature); the counts and capital stay, and the two words say the pattern.
 */
export interface AgencyPoint {
  agency: string
  /** every printed name merged into this agency, " | " separated */
  names: string | null
  sector: string | null
  ministry: string | null
  nProjects: number
  nOpen: number
  capitalCr: number
  scheduleBias: number | null
  scheduleBiasRaw: number | null
  scheduleBiasQ25: number | null
  scheduleBiasQ75: number | null
  scheduleBiasCiLo: number | null
  scheduleBiasCiHi: number | null
  costBias: number | null
  costBiasRaw: number | null
  costBiasQ25: number | null
  costBiasQ75: number | null
  costBiasCiLo: number | null
  costBiasCiHi: number | null
  nCost: number
  sectorScheduleBias: number | null
  sectorCostBias: number | null
  /** n / (n + 10); 1 when not shrunk */
  shrinkWeight: number | null
  shrunk: boolean
  /** n < 5: left out unless include_hidden */
  hidden: boolean
  /** median schedule bias of projects sanctioned in the last 3 years minus earlier ones */
  trend: number | null
  nRecent: number
  /** the signed-in agency official's own agency */
  isSelf: boolean
  /** absent from an older backend */
  scheduleWord?: ScheduleWord | null
  /** absent from an older backend */
  costWord?: CostWord | null
}

export interface AgencyMatrix {
  asof: string
  nAgencies: number
  nHidden: number
  method: string
  points: AgencyPoint[]
}

export interface MemberBrief {
  key: string
  name: string | null
  tier: string | null
  /** a hidden number */
  pAny2q: number | null
  /** absent from an older backend */
  outlook?: Outlook | null
  anticipatedCostCr: number | null
}

/**
 * Current projects sharing an open issue (category, authority, state); level 'state' is the
 * rollup over every authority. headline + note: the projects that would be affected, not a
 * causal claim about what resolving it would change.
 */
export interface Bottleneck {
  bottleneckId: string
  level: 'authority' | 'state'
  /** event category: land, forest_env, litigation, ... */
  category: string
  /** 'unspecified' when the remarks name none; null on a state rollup */
  authority: string | null
  state: string | null
  nProjects: number
  capitalExposedCr: number
  /** hidden numbers, as meanMonthsP50 */
  meanPAny2q: number | null
  meanMonthsP50: number | null
  nCriticalHigh: number
  earliestFirstSeen: string | null
  lastSeen: string | null
  nSignals: number
  evidence: string[]
  headline: string
  note: string
  topMembers: MemberBrief[]
}

/** summary: gold/bottlenecks_summary.json with the file's own snake_case keys */
export interface BottleneckSummary {
  as_of_date: string
  min_projects: number
  n_bottlenecks: number
  n_rollups: number
  n_projects: number
  capital_exposed_cr: number
  by_category: Record<string, number>
  signals_used: number
  signals_source: string
  note: string
}

export interface BottleneckPage {
  asof: string
  total: number
  page: number
  size: number
  summary: Partial<BottleneckSummary>
  items: Bottleneck[]
}

/** one line of evidence: a report-remark event (doc + page) or a linked news signal (url) */
export interface MemberEvidence {
  kind: 'event' | 'signal'
  authority: string | null
  firstSeen: string | null
  lastSeen: string | null
  evidence: string | null
  sourceDocId: string | null
  sourcePage: number | null
  url: string | null
}

export interface BottleneckMember {
  key: string
  name: string | null
  sector: string | null
  state: string | null
  agency: string | null
  tier: string | null
  /** hidden numbers, as monthsP50 */
  pAny2q: number | null
  monthsP50: number | null
  /** absent from an older backend */
  outlook?: Outlook | null
  anticipatedCostCr: number | null
  evidence: MemberEvidence[]
}

export interface BottleneckDetail {
  asof: string
  bottleneck: Bottleneck
  total: number
  page: number
  size: number
  members: BottleneckMember[]
}
