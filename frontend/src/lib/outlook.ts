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

/** a delay of likely or worse */
export function likelyOrWorse(word: OutlookWord | null | undefined): boolean {
  return word === 'likely' || word === 'very likely'
}
