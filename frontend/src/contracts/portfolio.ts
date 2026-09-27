/**
 * src/contracts/portfolio.ts
 *
 * Portfolio-level shapes as served by the FastAPI backend (backend/schemas.py;
 * keys are camelCase): data version, aggregates, alerts, external rollup.
 */
import type { TierFilter } from './project'

export interface Meta {
  asof: string
  modelVersion: string
  goldVersion: string
  silverVersion: string
  nCurrent: number
  nUntiered: number
  latestReportPeriod: string | null
  latestReportDoc: string | null
  models: Record<string, string>
  caveats: string[]
}

export interface Kpis {
  nProjects: number
  originalCostCr: number | null
  anticipatedCostCr: number | null
  expenditureCr: number | null
  overrunCr: number | null
  overrunPct: number | null
  avgProgressPct: number | null
}

export interface TierCount {
  tier: TierFilter
  n: number
  capitalCr: number
}

export interface GroupStat {
  name: string | null
  n: number
  capitalCr: number | null
  nCritical: number
  nHigh: number
}

export interface TopProject {
  key: string
  name: string | null
  sector: string | null
  state: string | null
  tier: string | null
  pAny2q: number | null
  anticipatedCostCr: number | null
}

export interface Portfolio {
  asof: string
  filters: Record<string, string | null>
  kpis: Kpis
  tiers: TierCount[]
  byState: GroupStat[]
  bySector: GroupStat[]
  byMinistry: GroupStat[]
  top: TopProject[]
}

export type AlertKind =
  | 'tier_up'
  | 'tier_down'
  | 'new_project'
  | 'slip_realised'
  | 'signal'
  | 'early_notice'
  | 'pipeline_error'

export interface Alert {
  id: number
  createdAt: string
  /** null only for a pipeline_error alert */
  projectKey: string | null
  kind: AlertKind
  severity: number
  title: string | null
  detail: string | null
  asof: string | null
  modelVersion: string | null
  source: string | null
  ackedBy: string | null
  ackedAt: string | null
}

export interface AlertPage {
  total: number
  page: number
  size: number
  items: Alert[]
}

/** gold/external_summary.json; the nested blocks keep the file's own snake_case keys. */
export interface ExternalSummary {
  asOfDate: string
  nProjects: number
  modelVersion: string
  rule: string
  factors: Record<string, unknown>
  earlyNotice: Record<string, unknown>
  noticeBacktest: Record<string, unknown>
  externalComposite: Record<string, unknown>
  coverage: Record<string, unknown>
  caveats: string[]
}
