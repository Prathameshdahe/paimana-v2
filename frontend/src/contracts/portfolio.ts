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
  nWatch: number
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
  /** the stagnation badge */
  override: boolean | null
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

/* live jobs (backend/live): GET /api/live/status, POST /api/jobs/watch, GET /api/signals/feed */

export interface JobRun {
  id: number
  job: string
  startedAt: string | null
  finishedAt: string | null
  status: string | null
  summary: unknown
}

/** one background loop: in-memory tick state and its last recorded run (null: never ran) */
export interface LiveJob {
  intervalS: number | null
  running: boolean
  lastTick: string | null
  nextDue: string | null
  lastError: string | null
  lastRun: JobRun | null
}

/** enabled false: LIVE_JOBS=0, the loops are not running (jobs still start from the API) */
export interface LiveStatus {
  enabled: boolean
  inboxPending: number
  watch: LiveJob
  scout: LiveJob
}

export interface JobStarted {
  started: boolean
  detail: string
  pending: number | null
  summary: Record<string, unknown> | null
}

export interface FeedProject {
  key: string
  name: string | null
  state: string | null
  tier: string | null
  linkScore: number | null
  method: string | null
  /** first report period after the article whose CUF row changed; null while none has */
  cufChangePeriod: string | null
  leadDays: number | null
}

/** a stored news signal; projects is empty for the unlinked pool (ambiguous or weak matches) */
export interface FeedItem {
  id: number
  url: string
  title: string | null
  source: string | null
  publishedAt: string | null
  fetchedAt: string | null
  summary: string | null
  category: string | null
  severity: number | null
  projects: FeedProject[]
}

/** stateHeat: signals of severity >= 2 in the last 90 days per state of their linked projects (not filtered) */
export interface SignalFeed {
  total: number
  page: number
  size: number
  items: FeedItem[]
  stateHeat: Array<{ state: string | null; n: number }>
}

export interface CountRow {
  /** category 'none' = uncategorised; severity rows carry the number */
  name: string | number | null
  n: number
}

/** GET /api/radar/summary: counts over signals published in the last windowDays; lead time over every linked signal */
export interface RadarSummary {
  windowDays: number
  since: string
  nSignalsTotal: number
  nWindow: number
  nLinked: number
  nUnlinked: number
  byCategory: CountRow[]
  bySeverity: CountRow[]
  bySource: CountRow[]
  nProjectsScouted: number
  leadTime: {
    nLinkedPairs: number
    nWithLaterChange: number
    medianLeadDays: number | null
    basis: string
  }
}

/* gold/external_summary.json: the nested blocks below keep the file's own snake_case keys */

export type ExternalFactorKey =
  | 'land'
  | 'forest_clearance'
  | 'litigation'
  | 'contractor'
  | 'utility_shifting'
  | 'inter_agency'

export interface ExternalProject {
  project_key: string
  project_name: string | null
  sector: string | null
  state: string | null
  anticipated_cost_cr: number | null
  tier: string | null
  p_any_2q: number | null
  slip_to_date_months: number | null
  /** "factor: evidence" lines from the risk profile; empty for the public (as the public project page) */
  evidence: string[]
  /** the factors flagged on it (the evidence lines' names; kept for the public) */
  factors?: string[]
  /** the stagnation badge (no progress for 2+ quarters; the tier stays by rank) */
  stalled?: boolean
}

/** a PARIVESH-linked current project with a proposal still open at as-of */
export interface PortalOpen extends Omit<ExternalProject, 'evidence' | 'factors'> {
  stage_at_asof: string
  months_in_stage: number | null
  /** the rule limit for that stage, months */
  norm_months: number | null
  overdue: boolean
  oldest_open_received: string | null
  open_not_in_report: boolean
  n_open: number
  /** ';'-separated proposal numbers */
  proposals: string
}

/** one proposal named in the report remarks, looked up on PARIVESH (gold/fc_proposal_status) */
export interface ProposalStatus {
  proposal_no: string
  found_in: string
  category: string | null
  area_ha: number | null
  received: string | null
  stage1: string | null
  stage2: string | null
  stage_at_asof: string
  open_at_asof: boolean
  months_in_stage: number | null
  norm_months: number | null
  norm_rule: string | null
  overdue: boolean
  last_query_on: string | null
  last_query_by: string | null
  last_query_replied: boolean | null
  status_retrieved: string | null
  retrieved: string | null
}

export interface ProposalCase {
  project_key: string
  project_name: string | null
  /** in the current portfolio (else a past project) */
  current: boolean
  proposals: ProposalStatus[]
}

/** one state: the Bhoomi Rashi register and the current road projects there */
export interface LandState {
  state: string
  has_data: boolean
  stretches: number | null
  parcels: number | null
  area_ha: number | null
  last_notif: string | null
  n_road: number
  n_rated: number
  n_flagged: number
  n_possible: number
}

export interface ExternalFactor {
  n_flagged: number
  capital_exposed_cr: number
  top: ExternalProject[]
}

export interface EarlyNotice {
  /** broad rule: slip to date <= 0 or tier Low/Medium */
  n_projects: number
  capital_exposed_cr: number
  by_factor: Partial<Record<ExternalFactorKey, number>>
  n_flagged_any: number
  capital_flagged_any_cr: number
  /** strict rule: slip to date <= 0 */
  no_slip_to_date: { n_projects: number; capital_exposed_cr: number }
  top: ExternalProject[]
}

/** notice backtest: past rows with no slip to date; slip = completion pushed >= 3 months by t + 4 quarters */
export interface Lift {
  n_with: number
  slip_rate_with: number | null
  n_without: number
  slip_rate_without: number | null
  lift: number | null
}

export interface NoticeLift extends Lift {
  projects_with: number
  /** Mantel-Haenszel lift within sector x year */
  lift_within_sector_year: number | null
  by_sector: Record<string, Lift>
}

export interface CompositeDistribution {
  n_projects: number
  n_score_ge_high: number
  mean: number
  min: number
  '25%': number
  '50%': number
  '75%': number
  max: number
}

/** pipeline/hidden_delay.py: extra slip over the next 4 quarters against matched projects */
export interface HiddenDelayPrior {
  factor: 'forest_clearance' | 'land_progress' | 'land_complexity' | 'land_complexity_nh'
  group: string
  label: string
  strata: string
  n_rows: number
  n_projects: number
  /** false: fewer projects than min_projects, no estimate */
  measurable: boolean
  extra_months: number | null
  extra_months_lo: number | null
  extra_months_hi: number | null
  /** extra probability (0-1) of a 3+ month date push */
  extra_push: number | null
  extra_push_lo: number | null
  extra_push_hi: number | null
  holm_months: number | null
  holm_push: number | null
  /** current projects in scope it applies to; null for the NH/district grouping (not rated) */
  n_current?: number | null
  garvit_status: string
  garvit_band: string
  as_of_note: string
}

export interface ExternalSummary {
  asOfDate: string
  nProjects: number
  modelVersion: string
  rule: string
  factors: Partial<Record<ExternalFactorKey, ExternalFactor>>
  earlyNotice: EarlyNotice
  noticeBacktest: Partial<Record<'land_or_forest' | 'land' | 'forest_env', NoticeLift>>
  externalComposite: {
    rule: string
    by_coverage: Partial<Record<'fc+la' | 'fc_only', CompositeDistribution>>
  }
  coverage: {
    n_current: number
    /** rated: a km match on the land register */
    land_linked: number
    /** a link on the NH or district alone, shown but not rated */
    land_possible: number
    forest_area_known: number
    composite_fc_la: number
    composite_fc_only: number
  }
  caveats: string[]
  /** remark-derived events: open by the remark rule vs live at as-of (free text ends in 2023-Q2) */
  remarkFlags: {
    last_remark_quarter: string
    live_window_quarters: number
    n_projects_open_by_remark_rule: number
    n_projects_live: number
    n_projects_stale: number
    /** per category: projects open by the remark rule, live today, the newest last mention of the stale ones */
    by_category?: Record<string, { open: number; live: number; last_known: string | null }>
  } | null
  /** PARIVESH-linked current projects */
  portal: {
    source: string
    n_linked: number
    n_open: number
    n_overdue: number
    n_open_not_in_report: number
    capital_open_cr: number
    by_stage: Record<string, number>
    top_overdue: ExternalProject[]
    /** every open one in scope, overdue first; empty for the public */
    open_list?: PortalOpen[]
    /** proposals the report remarks name, with their portal dates; empty for the public */
    cases?: ProposalCase[]
  } | null
  landCoverage: {
    states_with_data: number
    n_rated: number
    n_flagged: number
    n_possible: number
    link_check?: Record<string, { n: number; correct: number; ci_lo: number; ci_hi: number }>
    by_state?: LandState[]
  } | null
  hiddenDelayPriors: { note: string; min_projects: number; rows: HiddenDelayPrior[] } | null
}

/** GET /api/scopes: the sign-in picker */
export interface ScopeOption {
  name: string
  /** current projects */
  n: number
  /** agencies: every printed name, " | " separated */
  names: string | null
  ministry: string | null
}

export interface Scopes {
  ministries: ScopeOption[]
  agencies: ScopeOption[]
}
