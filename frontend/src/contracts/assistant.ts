/**
 * src/contracts/assistant.ts
 *
 * The project assistant's wire format: POST /api/chat takes a ChatRequest and answers with a text/event-stream of
 * named events (`event: <name>` + one JSON `data:` line, camelCase keys; llm/agent.py, SPEC section 4). Cards carry
 * the data the answer is built from, so they arrive before the streamed narrative; `done` closes every answer.
 * Numbers in the narrative were checked against the tools' facts (backend.brief.validate) unless `validated` is
 * false; `[n]` in the text points at item n of the turn's sources card.
 */
import type { DatePrecision, Flag, OpinionConcern, Outlook, PlainDriver, Tier } from './project'

/** one earlier turn, text only; the backend keeps at most 12 and wants the last one from the user */
export interface ChatTurn {
  role: 'user' | 'assistant'
  /** at most 1000 characters */
  content: string
}

export interface ChatRequest {
  /** 1 to 12 turns, the last is the question */
  messages: ChatTurn[]
  /** the project open in the side panel or on its page: "this project" means it; at most 32 characters */
  projectKey?: string
}

export type ChatStage = 'routing' | 'planning' | 'tools' | 'writing' | 'checking'

/** what the backend is doing now; detail is a short line for the progress list */
export interface ChatStatus {
  stage: ChatStage
  detail: string | null
}

/** one tool call, sent when it starts and again when it ends (same id) */
export interface ChatTool {
  id: string
  name: string
  /** plain words for the progress list ("Looking up projects in Bihar") */
  label: string
  args: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  /** one line on what it found or why it failed; null while running */
  summary: string | null
}

/** a project row as the list tools return it (ProjectRow-like, public-safe fields only) */
export interface ChatProjectRow {
  key: string
  name: string | null
  sector: string | null
  state: string | null
  ministry: string | null
  agency: string | null
  tier: Tier | null
  /** a hidden number: null without the numbers feature */
  pAny2q: number | null
  /** the numbers in words; absent from an older backend */
  outlook?: Outlook | null
  anticipatedCostCr: number | null
  physicalProgressPct: number | null
  anticipatedCompletion: string | null
  flags: Flag[]
}

export interface ProjectsCard {
  type: 'projects'
  title: string
  /** every match; items holds the first few, riskiest first */
  total: number
  items: ChatProjectRow[]
}

export interface StatsRow {
  name: string | null
  n: number
  capitalCr: number | null
  /** null when the count is not known for the row (agency stats where the tiers were not counted), never 0 for it */
  nCritical: number | null
  nHigh: number | null
}

export interface StatsCard {
  type: 'stats'
  title: string
  /** state | sector | ministry | agency | tier */
  groupBy: string
  rows: StatsRow[]
}

/** one project in figures; also the items of a compare card */
export interface ProjectFacts {
  key: string
  name: string | null
  tier: Tier | null
  /** chance of a date push or cost revision within 2 quarters; a hidden number, as the three below */
  pAny2q: number | null
  pDatePush2q: number | null
  pCostRev2q: number | null
  /** median further slip, months */
  monthsP50: number | null
  /** the numbers in words; absent from an older backend */
  outlook?: Outlook | null
  progressPct: number | null
  costCr: number | null
  anticipatedCompletion: string | null
  /** flagged checklist rows in plain words */
  topRisksPlain: string[]
  flags: Flag[]
}

export interface ProjectCard extends ProjectFacts {
  type: 'project'
}

export interface Driver {
  feature: string
  /** the plain label (backend/labels.py, the same words as lib/featureLabels) */
  label: string
  value: unknown
  /** log-odds; above 0 raises the risk */
  contribution: number
}

export interface FlaggedCheck {
  dimension: string
  label: string
  evidence: string | null
}

/** officials only: why the model ranks the project where it does */
export interface ExplainCard {
  type: 'explain'
  key: string
  name: string | null
  tier: Tier | null
  /** the SHAP drivers in numbers: the developer's; [] for the four roles */
  drivers: Driver[]
  /** the drivers in words; absent from an older backend */
  driversPlain?: PlainDriver[] | null
  flagged: FlaggedCheck[]
}

export interface HistoryPoint {
  period: string
  progressPct: number | null
  costCr: number | null
  anticipatedCompletion: string | null
}

export interface HistoryCard {
  type: 'history'
  key: string
  name: string | null
  points: HistoryPoint[]
  /** what changed between reports, in plain words */
  changes: string[]
}

export interface CompareCard {
  type: 'compare'
  /** project cards; the `type` field may be left out */
  items: Array<ProjectFacts & { type?: 'project' }>
}

export interface ChatSource {
  /** the number the narrative cites as [n] */
  n: number
  /** project | research | news | event | external | help | doc | glossary | … */
  kind: string
  title: string
  source: string | null
  url: string | null
  date: string | null
  /** how much of `date` the source gave: a month-precise fact is stored as its first day and shows as the month */
  datePrecision?: DatePrecision | null
  projectKey: string | null
}

export interface SourcesCard {
  type: 'sources'
  items: ChatSource[]
}

/** officials only, the cached second opinion (chat never generates one) */
export interface OpinionCard {
  type: 'opinion'
  key: string
  concern: OpinionConcern
  headline: string
  narrative: string
  generatedAt: string | null
}

export type ChatCard =
  | ProjectsCard
  | StatsCard
  | ProjectCard
  | ExplainCard
  | HistoryCard
  | CompareCard
  | SourcesCard
  | OpinionCard

/**
 * why the narrative is what it is: 'ok' the LLM wrote it and it passed the check; 'unavailable' / 'busy' the LLM
 * was down or taken, so the text is a template built from the cards; 'skipped' no LLM was needed
 */
export type ChatLlm = 'ok' | 'unavailable' | 'busy' | 'skipped'

export interface ChatDone {
  /** the final narrative: replaces what was streamed */
  text: string
  /** every number traced to the tools' facts (templates always are) */
  validated: boolean
  reasons: string[]
  llm: ChatLlm
  elapsedMs: number
}

/** the SSE events of one answer, by event name */
export type ChatEvent =
  | { event: 'status'; data: ChatStatus }
  | { event: 'tool'; data: ChatTool }
  | { event: 'card'; data: ChatCard }
  | { event: 'token'; data: { text: string } }
  /**
   * clear the streamed text, a replacement follows: a draft failed the check against the data (the second attempt,
   * or after two failures the answer built from the data), or the local model stopped mid-answer (reasons
   * ['the local AI stopped answering'], then the answer built from the data)
   */
  | { event: 'retry'; data: { reasons: string[] } }
  | { event: 'done'; data: ChatDone }
  | { event: 'error'; data: { message: string } }

export type ChatEventName = ChatEvent['event']
