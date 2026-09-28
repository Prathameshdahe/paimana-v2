/**
 * src/lib/external.ts
 *
 * Shared reading of the external evidence: remark flags live vs stale, remark quarters and the measured
 * hidden-delay priors (pipeline/hidden_delay.py), for the External Factors page and the project blocks. The measured
 * months, push and CIs are hidden numbers (SPEC9_ui section 6): the four roles read the backend's word band and the
 * project count; only the developer (numbers) reads the figures.
 */
import { EXTERNAL_FACTORS } from './riskPalette'
import { formatINRShort } from './formatters'
import type { ExternalSummary, HiddenDelayPrior } from '@/contracts/portfolio'
import type { DelayWord, HiddenDelayMatch } from '@/contracts/project'

/** the one DelayWord that is not an extra delay (unit G's serving.NO_EXTRA: the interval does not lie above zero) */
export const NO_EXTRA_DELAY: DelayWord = 'no measurable extra delay'

/**
 * The outside factors' one line, from the summary's counts: "Land acquisition is on record for 212 projects worth
 * ₹5.10L Cr; 38 of them show no slip in the reports yet." for the factor on record for the most projects.
 */
export function delaysTakeaway(s: ExternalSummary | undefined): string | null {
  if (!s) return null
  const top = EXTERNAL_FACTORS
    .map((f) => ({ ...f, x: s.factors[f.key], notice: s.earlyNotice.by_factor[f.key] ?? 0 }))
    .filter((r) => r.x && r.x.n_flagged > 0)
    .sort((a, b) => (b.x?.n_flagged ?? 0) - (a.x?.n_flagged ?? 0))[0]
  if (!top?.x) return null
  const n = top.x.n_flagged.toLocaleString('en-IN')
  const notice = top.notice > 0 ? `; ${top.notice.toLocaleString('en-IN')} of them show no slip in the reports yet.` : '.'
  return `${top.label} is on record for ${n} projects worth ${formatINRShort(top.x.capital_exposed_cr)}${notice}`
}

/** pipeline/gold.OPEN_MAX_AGE_Q: a remark flag is open today only within this many quarters of its last mention */
export const LIVE_QUARTERS = 4

/** '2023-04-01' -> '2023-Q2' (the pipeline's quarter label) */
export function formatQuarter(iso: string): string {
  const d = new Date(iso)
  return `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`
}

/** a remark mention still counts as open at asof (backend serving._remark_block) */
export function isLive(lastSeen: string | null, asof: string): boolean {
  if (!lastSeen) return false
  const a = new Date(asof)
  return Date.parse(lastSeen) > Date.UTC(a.getUTCFullYear(), a.getUTCMonth() - 3 * LIVE_QUARTERS, a.getUTCDate())
}

/** one measured prior, whichever casing it came in */
export interface Estimate {
  label: string
  measurable: boolean
  nProjects: number
  nRows: number
  /** extra months of completion push over the next 4 quarters: value, 95% CI */
  months: [number, number, number] | null
  /** extra chance (0-1) of a 3+ month date push: value, 95% CI */
  push: [number, number, number] | null
  holm: number | null
  /** the extra months in words; undefined: an older backend that sends none */
  word: DelayWord | null | undefined
}

const trio = (v: number | null, lo: number | null, hi: number | null): [number, number, number] | null =>
  v === null || lo === null || hi === null ? null : [v, lo, hi]

export function fromPrior(p: HiddenDelayPrior): Estimate {
  return {
    label: p.label, measurable: p.measurable, nProjects: p.n_projects, nRows: p.n_rows,
    months: trio(p.extra_months, p.extra_months_lo, p.extra_months_hi),
    push: trio(p.extra_push, p.extra_push_lo, p.extra_push_hi),
    holm: p.holm_months === null && p.holm_push === null ? null : Math.min(p.holm_months ?? 1, p.holm_push ?? 1),
    // unit G sends the summary's nested keys snake_case; undefined only when neither casing is there
    word: p.extra_months_word !== undefined ? p.extra_months_word : p.extraMonthsWord,
  }
}

export function fromMatch(m: HiddenDelayMatch): Estimate {
  return {
    label: m.label, measurable: m.measurable, nProjects: m.nProjects, nRows: m.nRows,
    months: trio(m.extraMonths, m.extraMonthsLo, m.extraMonthsHi),
    push: trio(m.extraPush, m.extraPushLo, m.extraPushHi),
    holm: m.holmMonths === null && m.holmPush === null ? null : Math.min(m.holmMonths ?? 1, m.holmPush ?? 1),
    word: m.extraMonthsWord,
  }
}

/** the 95% interval excludes zero */
export const clear = (t: [number, number, number] | null) => !!t && (t[1] > 0 || t[2] < 0)

const sign = (v: number, digits: number) => {
  const s = v.toFixed(digits)
  return Number(s) === 0 ? (0).toFixed(digits) : `${v > 0 ? '+' : '−'}${s.replace('-', '')}`
}
export const months1 = (v: number) => `${sign(v, 1)} mo`
export const pts = (v: number) => `${sign(v * 100, 0)} pts`

export interface Verdict {
  text: string
  tone: 'warning' | 'stable' | 'muted'
  also?: string
}

/**
 * The short verdict. With numbers (the developer): '+2.5 mo' when the months or push interval excludes zero, 'none
 * measurable' when both span zero. Without: the backend's word ('a few months more'), 'none measurable' for its 'no
 * measurable extra delay' or no word, 'not available yet' from a backend that sends no words. 'too few to measure'
 * under the project floor.
 */
export function verdict(e: Estimate, numbers = true): Verdict {
  if (!e.measurable) return { text: 'too few to measure', tone: 'muted' }
  if (!numbers) {
    if (e.word === NO_EXTRA_DELAY) return { text: 'none measurable', tone: 'muted' }
    if (e.word) return { text: `${e.word} more`, tone: 'warning' }
    return e.word === null ? { text: 'none measurable', tone: 'muted' } : { text: 'not available yet', tone: 'muted' }
  }
  if (!e.months) return { text: 'too few to measure', tone: 'muted' }
  if (clear(e.months)) {
    return {
      text: months1(e.months[0]), tone: e.months[0] > 0 ? 'warning' : 'stable',
      also: e.push && clear(e.push) ? `${pts(e.push[0])} push risk` : undefined,
    }
  }
  if (e.push && clear(e.push)) return { text: `${pts(e.push[0])} push risk`, tone: e.push[0] > 0 ? 'warning' : 'stable' }
  return { text: 'none measurable', tone: 'muted' }
}

/** the InfoTip lines: with numbers both estimates with their CI, n and the multiple-testing note; without, the count */
export function details(e: Estimate, minProjects = 15, numbers = true): string[] {
  if (!e.measurable) {
    return [`${e.nProjects} projects with this status in 2014 to 2023: too few to measure (need ${minProjects}).`]
  }
  if (!numbers) {
    return [
      `Measured against matched projects over the next four quarters, on ${e.nProjects} real projects with this status. `
        + 'Exploratory, not a forecast.',
    ]
  }
  if (!e.months || !e.push) {
    return [`${e.nProjects} projects with this status in 2014 to 2023: too few to measure (need ${minProjects}).`]
  }
  const [m, mlo, mhi] = e.months
  const [p, plo, phi] = e.push
  return [
    `Next 4 quarters, against matched projects: completion pushed ${months1(m)} more (95% CI ${months1(mlo)} to ${months1(mhi)}); chance of a 3+ month push ${pts(p)} (CI ${pts(plo)} to ${pts(phi)}).`,
    `Measured on ${e.nProjects} real projects (${e.nRows} project-quarters)${e.holm !== null ? `; Holm-adjusted p ${e.holm.toFixed(2)} over every group` : ''}. Exploratory, not a forecast.`,
  ]
}
