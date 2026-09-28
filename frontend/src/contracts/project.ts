/**
 * src/contracts/project.ts
 *
 * One-project and project-list shapes as served by the FastAPI backend
 * (backend/schemas.py; keys are camelCase). Dates are ISO strings.
 */

/** Rank-based tier; a project without an anticipated completion date is in the Watch tier (no date-based score). */
export type Tier = 'Critical' | 'High' | 'Medium' | 'Low' | 'Watch'
export type TierFilter = Tier
export type Flag = 'land' | 'forest' | 'litigation' | 'contractor' | 'early_notice'
export type ProjectSort = 'risk' | 'cost' | 'slip' | 'name' | 'progress'

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

/** gold/external_fc_portal: the project's PARIVESH-linked proposals at as-of */
export interface PortalLink {
  linkSource: string
  nProposals: number
  proposals: string
  areaHa: number | null
  nOpen: number
  nStage1Only: number
  nFinal: number
  nDropped: number
  nOverdue: number
  stageAtAsof: string
  monthsInStage: number | null
  normMonths: number | null
  oldestOpenReceived: string | null
  openNotInReport: boolean
}

/** a proposal named in the report remarks, as the portal shows it */
export interface ProposalRow {
  proposalNo: string
  category: string | null
  areaHa: number | null
  received: string | null
  stage1: string | null
  stage2: string | null
  stageAtAsof: string
  openAtAsof: boolean
  monthsInStage: number | null
  normMonths: number | null
  overdue: boolean
  lastQueryOn: string | null
  lastQueryBy: string | null
  lastQueryReplied: boolean | null
  statusRetrieved: string | null
  retrieved: string | null
}

/** the last forest stage, land share and land step the remarks gave, each with the quarter it is as of */
export interface RemarkStatus {
  fcStage: string | null
  fcStageAsOf: string | null
  laPct: number | null
  laPctAsOf: string | null
  laStep: string | null
  laStepAsOf: string | null
  proposalNo: string | null
}

/** a measured hidden-delay prior that applies to the project (pipeline/hidden_delay.py) */
export interface HiddenDelayMatch {
  factor: 'forest_clearance' | 'land_progress' | 'land_complexity'
  group: string
  label: string
  nRows: number
  nProjects: number
  measurable: boolean
  extraMonths: number | null
  extraMonthsLo: number | null
  extraMonthsHi: number | null
  extraPush: number | null
  extraPushLo: number | null
  extraPushHi: number | null
  holmMonths: number | null
  holmPush: number | null
  /** what it was matched on */
  basis: string
  /** the remark quarter it is as of; null for the land register */
  asOf: string | null
  /** the status still describes the project at asof (a remark within 4 quarters, or the land register); else it is the last report's */
  current: boolean
}

/** portal, proposals, remarkStatus and hiddenDelay are empty on the public page */
export interface External {
  fc: Record<string, unknown> | null
  land: Record<string, unknown> | null
  landPairs: Record<string, unknown>[]
  composite: Record<string, unknown> | null
  events: EventRow[]
  portal: PortalLink | null
  proposals: ProposalRow[]
  remarkStatus: RemarkStatus | null
  hiddenDelay: HiddenDelayMatch[]
}

export interface Provenance {
  asof: string
  modelVersion: string | null
  /** null on the public page, as are the model version and the source document */
  goldVersion: string | null
  silverVersion: string | null
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

/* web research (backend/serving.py research; pipeline/research.py): cited evidence, never a model input */

/** the sweep's categories (pipeline/research.py TAXONOMY_OF keys) */
export type ResearchCategory =
  | 'land'
  | 'forest_env'
  | 'litigation'
  | 'contractor'
  | 'funds'
  | 'utility_shifting'
  | 'inter_agency'
  | 'law_order'
  | 'natural_event'
  | 'approvals_other'
  | 'design_scope'
  | 'progress'
  | 'other'

export type DatePrecision = 'day' | 'month' | 'year'

/**
 * A cited web fact. origin 'sweep': found by a research agent and checked by a second one that re-opened the source
 * (verified keep | fix); 'agent': a news item the in-app research agent judged with the local LLM from its headline
 * and feed summary. live: negative, not resolved, dated within 4 quarters of the as-of quarter. headline is the
 * citation label; the public gets no matchReason and no headline on agent facts (label those by source).
 */
export interface ResearchFact {
  factId: string
  category: ResearchCategory | string
  /** the pipeline/external.py taxonomy name (funds -> funding, natural_event -> weather; the rest as is) */
  taxonomy: string
  direction: 'negative' | 'positive' | 'neutral'
  /** 1-3 */
  severity: number
  /** the first of the month or year when datePrecision is coarser than a day */
  eventDate: string | null
  datePrecision: DatePrecision | null
  publishedDate: string | null
  /** ongoing | resolved | unknown */
  status: string
  /** our own paraphrase, never the article text */
  summary: string
  headline: string | null
  source: string | null
  url: string
  domain: string | null
  /** high | medium: how surely the item is about this project */
  match: string | null
  matchReason: string | null
  verified: 'keep' | 'fix' | null
  origin: 'sweep' | 'agent'
  researchedOn: string | null
  live: boolean
  signalId: number | null
  judgedAt: string | null
}

/** the latest figure the researched sources give, each as of its own date ('YYYY-MM' or 'YYYY-MM-DD'); null when none */
export interface ResearchExternal {
  landAcquiredPct: { value: number | null; asOf: string | null } | null
  forestClearance: { stage: string | null; asOf: string | null } | null
  courtCase: { court: string | null; status: string | null; asOf: string | null } | null
  contractor: { company: string | null; status: string | null; asOf: string | null } | null
  /** date: 'YYYY-MM' as the source gives it */
  newTarget: { date: string | null; asOf: string | null } | null
  costRevision: { newCostCr: number | null; asOf: string | null } | null
}

/**
 * The project page's research block (in ProjectDetail). searched false: not researched yet; searched with nFacts 0:
 * searched, nothing found (not the same as clear). top: up to 3 facts, live blockers first.
 */
export interface ResearchBrief {
  researchedOn: string | null
  searched: boolean
  /** the in-app agent's last run on this project (ISO time) */
  agentResearchedAt: string | null
  latestStatus: string | null
  nFacts: number
  nNegativeLive: number
  top: ResearchFact[]
}

/** GET /api/projects/{key}/research (every role; the public gets the redacted facts): newest first */
export interface ProjectResearch {
  key: string
  researchedOn: string | null
  searched: boolean
  agentResearchedAt: string | null
  latestStatus: string | null
  external: ResearchExternal
  nFacts: number
  nNegativeLive: number
  facts: ResearchFact[]
}

export interface ProjectDetail {
  key: string
  master: MasterRecord | null
  latest: ObservationRecord | null
  /** null: not in the current scored portfolio (e.g. completed) */
  scores: Scores | null
  flags: Flag[]
  riskProfile: RiskRow[]
  /** up to 3 flagged checklist rows in plain words (the public page's top risks) */
  topRisksPlain: string[]
  external: External
  provenance: Provenance
  review: ReviewBadge | null
  /** the web research counts and top facts; null when the backend has none for it */
  research: ResearchBrief | null
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

/**
 * GET /api/projects/{key}/brief, status 200: two paragraphs from the local LLM whose every number
 * was traced to payload (the facts it was given). 422 carries BriefRejected, 503 LM Studio down.
 */
export interface BriefOut {
  status: 'ok'
  key: string
  asof: string
  modelVersion: string
  text: string
  paragraphs: string[]
  cached: boolean
  generatedAt: string | null
  nNumbersChecked: number | null
  attempts: number | null
  payload: Record<string, unknown>
}

/** the 422 body: numbers in the text that are not in the payload */
export interface BriefRejected {
  status: 'rejected'
  reasons: string[]
  attempts: number
}

/* the AI second opinion (llm/second_opinion.py, SPEC section 5): officials, never changes the tier */

/** the second opinion's reading of the evidence */
export type OpinionConcern = 'none' | 'watch' | 'concern'
/** against the model's tier: the same, more worried, less worried */
export type OpinionVsModel = 'agrees' | 'higher' | 'lower'

/** one item of the evidence pack the model read, cited as [E#] */
export interface OpinionEvidence {
  /** 'E1' .. 'En' */
  id: string
  /** status | model | check | event | parivesh | land | research | news */
  kind: string
  date: string | null
  text: string
  /** negative | positive | neutral (the pack may call it stance) */
  direction?: string | null
  stance?: string | null
  source?: string | null
  url?: string | null
}

/**
 * GET /api/projects/{key}/second-opinion, status 200 (need insights): the LLM's JSON after validation — every [E#]
 * exists, numbers traced to the pack, a 'concern' cites at least one negative item. 422 carries
 * SecondOpinionRejected, 503 LM Studio down, 404 not scored. The fields after `gaps` are the envelope; the evidence
 * list may come as `evidence` or `pack.items`.
 */
export interface SecondOpinionOut {
  status: 'ok'
  key: string
  concern: OpinionConcern
  /** at most 15 words */
  headline: string
  /** at most 90 words with [E#] citations */
  narrative: string
  keyEvidence: string[]
  vsModel: OpinionVsModel
  /** up to 3: what the evidence does not tell */
  gaps: string[]
  asof?: string | null
  model?: string | null
  promptVersion?: string | null
  evidenceHash?: string | null
  generatedAt?: string | null
  cached?: boolean | null
  attempts?: number | null
  nNumbersChecked?: number | null
  evidence?: OpinionEvidence[] | null
  pack?: { items?: OpinionEvidence[] | null } | null
}

/** ?cached=1 with no opinion for the current evidence yet */
export interface SecondOpinionNone {
  status: 'none'
}

/** the 422 body: why the opinion was rejected after its retry */
export interface SecondOpinionRejected {
  status: 'rejected'
  reasons: string[]
  attempts: number
}
