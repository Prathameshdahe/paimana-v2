/**
 * src/lib/outlook.ts
 *
 * The numbers policy's words as the pages read them (SPEC9_ui section 6): tone and icon per outlook word, the plain
 * drivers' strength dots, and the one place that chooses words over numbers. The backend sends the four roles words
 * only. A backend from before the policy sends numbers without words; for the developer alone (canSeeNumbers) the
 * words are then derived here from the numbers by the backend's fixed bands, so their Briefing tab reads the same.
 * Nothing here turns a hidden number into words for any other viewer: without words they read "not available yet".
 */
import { CalendarX, Clock, IndianRupee, type LucideIcon } from 'lucide-react'
import { featureLabel } from './featureLabels'
import type { Outlook, OutlookWord, PlainDriver, ShapValue, SlipBand } from '@/contracts/project'

/** strongest first: the risk map's lanes, top to bottom */
export const OUTLOOK_WORDS: OutlookWord[] = ['very likely', 'likely', 'possible', 'unlikely']

export type OutlookTone = 'critical' | 'warning' | 'watch' | 'stable'

/** the auditor ink per word; accent is never an outlook tone (it marks the viewer's own action) */
export const OUTLOOK_TONE: Record<OutlookWord, OutlookTone> = {
  'very likely': 'critical',
  likely: 'warning',
  possible: 'watch',
  unlikely: 'stable',
}

export const TONE_TEXT: Record<OutlookTone | 'muted', string> = {
  critical: 'text-critical',
  warning: 'text-warning',
  watch: 'text-watch',
  stable: 'text-stable',
  muted: 'text-fg-muted',
}

export const TONE_DOT: Record<OutlookTone | 'muted', string> = {
  critical: 'bg-critical',
  warning: 'bg-warning',
  watch: 'bg-watch',
  stable: 'bg-stable',
  muted: 'bg-fg-dimmed/50',
}

/** one icon per outlook part */
export const OUTLOOK_ICON: Record<'delay' | 'cost' | 'slip', LucideIcon> = {
  delay: CalendarX,
  cost: IndianRupee,
  slip: Clock,
}

/** the parts' names in a sentence ("Delay likely", "Cost rise unlikely", "Likely slip 6 to 12 months") */
export const OUTLOOK_NOUN = { delay: 'Delay', cost: 'Cost rise', slip: 'Likely slip' } as const

export const DEFAULT_HORIZON = 'next two quarters'

/** delay or cost word from a probability, the backend's fixed bands; only ever called for the developer */
export function bandOf(p: number | null | undefined): OutlookWord | null {
  if (p === null || p === undefined || Number.isNaN(p)) return null
  return p >= 0.75 ? 'very likely' : p >= 0.5 ? 'likely' : p >= 0.25 ? 'possible' : 'unlikely'
}

/** the slip band from the median further slip in months; only ever called for the developer */
export function slipBandOf(months: number | null | undefined): SlipBand | null {
  if (months === null || months === undefined || Number.isNaN(months)) return null
  return months < 6 ? 'under 6 months' : months < 12 ? '6 to 12 months' : months < 24 ? '1 to 2 years' : 'over 2 years'
}

/** what carries an outlook: scores, list and map rows, portfolio top, bottleneck members, chat cards */
export interface OutlookSource {
  outlook?: Outlook | null
  pDatePush2q?: number | null
  pCostRev2q?: number | null
  monthsP50?: number | null
}

/**
 * The outlook the viewer reads: the backend's words when it sent them; else, for the developer only, words from the
 * numbers; else null (not available: an older backend, or a project the model does not rank).
 */
export function outlookOf(src: OutlookSource | null | undefined, numbers: boolean): Outlook | null {
  if (!src) return null
  if (src.outlook) return src.outlook
  if (!numbers) return null
  const o: Outlook = {
    delay: bandOf(src.pDatePush2q),
    cost: bandOf(src.pCostRev2q),
    slip: slipBandOf(src.monthsP50),
    horizon: DEFAULT_HORIZON,
  }
  return o.delay || o.cost || o.slip ? o : null
}

/** does any row carry words (or, for the developer, numbers to derive them from)? The risk map's lane mode */
export function hasOutlook(rows: OutlookSource[], numbers: boolean): boolean {
  return rows.some((r) => !!outlookOf(r, numbers))
}

export type Strength = PlainDriver['strength']

/** strength as filled dots out of three: strong 3, moderate 2, slight 1 */
export function strengthDots(s: Strength): number {
  return s === 'strong' ? 3 : s === 'moderate' ? 2 : 1
}

/**
 * The plain drivers, strongest first: the backend's when sent; else, for the developer only, from the SHAP top 5
 * with the backend's rule (strength by the driver's third within the project's five, by |contribution|).
 */
export function driversOf(
  src: { driversPlain?: PlainDriver[] | null; shapTop5?: ShapValue[] } | null | undefined,
  numbers: boolean,
): PlainDriver[] {
  if (!src) return []
  if (src.driversPlain) return src.driversPlain
  if (!numbers || !src.shapTop5?.length) return []
  const top = [...src.shapTop5].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, 5)
  return top.map((d, i) => ({
    label: featureLabel(d.feature),
    direction: d.contribution > 0 ? 'raises' : 'lowers',
    strength: i / top.length < 1 / 3 ? 'strong' : i / top.length < 2 / 3 ? 'moderate' : 'slight',
  }))
}

/** "Delay likely · cost rise unlikely": the outlook's delay and cost in one line; '' when it has neither */
export function outlookLine(o: Outlook | null, sep = ' · '): string {
  if (!o) return ''
  const parts = [o.delay && `delay ${o.delay}`, o.cost && `cost rise ${o.cost}`].filter((x): x is string => !!x)
  const line = parts.join(sep)
  return line.charAt(0).toUpperCase() + line.slice(1)
}

/** the delay word's tone, muted when there is none */
export function toneOf(word: OutlookWord | null | undefined): OutlookTone | 'muted' {
  return word ? OUTLOOK_TONE[word] : 'muted'
}

/** the slip band's tone: longer is worse */
export function slipTone(band: SlipBand | null | undefined): OutlookTone | 'muted' {
  return !band ? 'muted' : band === 'under 6 months' ? 'watch' : band === '6 to 12 months' ? 'warning' : 'critical'
}

/** where the tier sits, in a sentence (ml/score.py TIER_TOP 5/20/50%): the ring's caption */
export const TIER_PLAIN: Record<string, string> = {
  Critical: 'Among the few open projects most likely to be delayed or cost more over the next two quarters.',
  High: 'Among the open projects more likely than most to be delayed or cost more over the next two quarters.',
  Medium: 'In the riskier half of open projects for a delay or a cost rise over the next two quarters.',
  Low: 'In the less risky half of open projects for a delay or a cost rise over the next two quarters.',
  Watch: 'No completion date on record, so the delay risk is not ranked.',
}

/** a delay of likely or worse */
export function likelyOrWorse(word: OutlookWord | null | undefined): boolean {
  return word === 'likely' || word === 'very likely'
}

const N = String.raw`[+-]?\d+`   // pipeline/hidden_delay.fmt: '+3', '-2', '0'
const MO = String.raw`(${N}) months? over the next year \(CI ${N} to ${N}\)`
const PTS = String.raw`(${N}) pts date-push risk \(CI ${N} to ${N}\)`

/** a measured prior's months and push as their direction only (the size is a hidden number) */
function priorWords(_: string, months?: string, pushWith?: string, pushAlone?: string, n?: string): string {
  const m = months === undefined ? 0 : Number(months)
  const p = Number(pushWith ?? pushAlone ?? 0)
  const parts = [
    m > 0 ? 'more delay than matched projects' : m < 0 ? 'less delay than matched projects' : null,
    p > 0 ? 'a higher chance of a date push' : p < 0 ? 'a lower chance of a date push' : null,
  ].filter(Boolean)
  return `${parts.length ? parts.join(' and ') : 'no clear difference from matched projects'}, measured on ${n} projects`
}

/** [pattern, replacement] per free-text form a backend from before the numbers policy writes a statistic in */
const MODEL_TEXT: Array<[RegExp, string | ((match: string, ...groups: string[]) => string)]> = [
  // ml/risk_profile.py, the model checks: 'P = 0.77 (High-tier cut 0.62); velocity ...'
  [/P\s*=\s*\d*\.?\d+\s*\(High-tier cut\s*\d*\.?\d+\)(?:;\s*)?/g, ''],
  // the watcher and the seed alerts: '; P(date push or cost revision, 2q) = 0.81'
  [/;?\s*P\([^)]*\)\s*=\s*\d*\.?\d+%?/g, ''],
  // the watcher's slip_realised: '(P = 0.81)'
  [/\s*\(P\s*=\s*\d*\.?\d+%?\)/g, ''],
  // any other 'P = 0.81'
  [/;?\s*\bP\s*=\s*\d*\.?\d+%?/g, ''],
  // agency_optimism: 'agency timelines run +23% vs schedule (median of 12 projects); 2q slip rate 40%'
  [/agency timelines run [+-]?\d+(?:\.\d+)?% vs schedule \(median of (\d+) projects\)(?:; 2q slip rate \d+(?:\.\d+)?%)?/g,
    'agency timelines checked against schedule on $1 past projects'],
  // external_composite: 'score 0.63 (fc+la): '
  [/\bscore (?:\d*\.?\d+|n\/a) \([^)]*\):\s*/g, ''],
  // pipeline/hidden_delay.text, not significant: 'no measurable extra delay (+1 month over the next year, CI -2 to
  // +4; +3 pts date-push risk, CI -1 to +5; 43 projects)'
  [new RegExp(String.raw`no measurable extra delay \(${N} months? over the next year, CI ${N} to ${N}; ${N} pts `
    + String.raw`date-push risk, CI ${N} to ${N}; (\d+) projects\)`, 'g'), 'no measurable extra delay ($1 projects)'],
  // pipeline/hidden_delay.text, measured: '+3 months over the next year (CI +1 to +5) and +8 pts date-push risk (CI +2
  // to +14), measured on 16 projects'
  [new RegExp(String.raw`(?:${MO}(?: and ${PTS})?|${PTS}), measured on (\d+) projects`, 'g'), priorWords],
  // the chat's project summary (llm/tools._tier_words): ', with a 81% chance of a schedule or cost slip within 2 quarters'
  [/,?\s*with an? \d+(?:\.\d+)?% chance of a[^;.]*/g, ''],
  // the chat's agency summary: ', median schedule overrun 23%, cost overrun 12%'
  [/,\s*(?:median schedule overrun|cost overrun) [+-]?\d+(?:\.\d+)?%/g, ''],
]

/**
 * A text without the model's numbers and statistics that a backend from before the numbers policy writes into it:
 * the model checks' 'P = 0.77 (High-tier cut 0.62)', an alert's 'P(date push or cost revision, 2q) = 0.81' or
 * '(P = 0.81)', the agency's timeline bias and slip rate, the composite score, a measured prior's months, push and
 * intervals (their direction and project count stay), and the chat's chance of a slip and agency overruns. Report
 * facts (progress, spend, velocity, dates, counts) stay as written. Unit G's backend writes these in words already.
 */
export function scrubModelNumbers(text: string): string {
  let out = text
  for (const [rx, to] of MODEL_TEXT) out = typeof to === 'string' ? out.replace(rx, to) : out.replace(rx, to)
  return out
    .replace(/\s*;\s*(?=;|$)/g, '')
    .replace(/^\s*[;,]\s*/, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

/** a stored text as the viewer may read it: as sent for the developer, else without the model's numbers; null if empty */
export function plainText(text: string | null | undefined, numbers: boolean): string | null {
  if (!text) return null
  if (numbers) return text
  return scrubModelNumbers(text) || null
}
