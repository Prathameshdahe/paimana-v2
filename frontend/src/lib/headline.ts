/**
 * src/lib/headline.ts
 *
 * The deterministic sentences the pages open with (no LLM): the week's brief over the portfolio, one project's
 * headline, "due in 4 months" / "3 months overdue", and counts rounded to fraction words. Built from report facts,
 * tiers and the outlook words only; a sentence never carries a model number, and a missing field drops its clause
 * rather than printing a dash. A tier count and an outlook band are never merged into one claim.
 */
import { formatINRShort } from './formatters'
import { likelyOrWorse, outlookOf } from './outlook'
import type { AlertKind, Kpis, TierCount } from '@/contracts/portfolio'
import type { Flag, Outlook, ProjectDetail, Tier } from '@/contracts/project'

/** whole months from asof to date (calendar months, UTC): negative when the date has passed */
export function monthsUntil(asof: string, date: string): number {
  const a = new Date(asof)
  const b = new Date(date)
  return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth())
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString('en-IN')} ${n === 1 ? one : many}`

export interface Due {
  /** months from asof, negative when overdue */
  months: number
  overdue: boolean
  /** "due in 4 months", "due this month", "3 months overdue" */
  text: string
  /** "in 4 mo", "this month", "3 mo overdue" (tables) */
  short: string
}

/** when a project is due against asof; null without a completion date */
export function dueIn(anticipatedCompletion: string | null | undefined, asof: string | null | undefined): Due | null {
  if (!anticipatedCompletion || !asof) return null
  const m = monthsUntil(asof, anticipatedCompletion)
  if (Number.isNaN(m)) return null
  if (m === 0) return { months: 0, overdue: false, text: 'due this month', short: 'this month' }
  if (m < 0) return { months: m, overdue: true, text: `${plural(-m, 'month')} overdue`, short: `${-m} mo overdue` }
  return { months: m, overdue: false, text: `due in ${plural(m, 'month')}`, short: `in ${m} mo` }
}

/** k of n in words: "all", "nearly all", "most", "about half", "about a third", "about a quarter", "a few", "none" */
export function fractionWord(k: number, n: number): string {
  if (n <= 0 || k <= 0) return 'none'
  const f = k / n
  if (f >= 1) return 'all'
  if (f >= 0.9) return 'nearly all'
  if (f >= 0.6) return 'most'
  if (f >= 0.42) return 'about half'
  if (f >= 0.28) return 'about a third'
  if (f >= 0.18) return 'about a quarter'
  return 'a few'
}

// ------------------------------------------------------------------ one project

/** the opener by tier; null tier: not in the scored portfolio */
const OPENER: Record<Tier, string> = {
  Critical: 'Needs attention now',
  High: 'Watch closely',
  Medium: 'On the radar',
  Low: 'Steady',
  Watch: 'No completion date on record',
}

/** the outside issue an early notice names, from the list flags */
function noticeNoun(flags: Flag[]): string {
  if (flags.includes('land')) return 'a land issue'
  if (flags.includes('forest')) return 'a forest-clearance issue'
  if (flags.includes('litigation')) return 'a court case'
  if (flags.includes('contractor')) return 'a contractor issue'
  return 'an outside issue'
}

/** the fields a project headline reads; every one may be missing */
export interface HeadlineInput {
  tier: Tier | null
  physicalProgressPct?: number | null
  anticipatedCompletion?: string | null
  /** share of the sanctioned schedule used up (1 = all of it) */
  elapsedRatio?: number | null
  outlook?: Outlook | null
  stagnationOverride?: boolean | null
  stagnationQuarters?: number | null
  flags?: Flag[]
}

/** 99.6% built is "99% done", never "100%" */
function done(p: number): string {
  const r = Math.round(p)
  return `${r >= 100 && p < 100 ? 99 : r}% done`
}

/**
 * One project in a sentence: "Needs attention now: 60% done, 4 months from its expected date, the schedule already
 * used up; delay very likely, cost rise unlikely, likely slip 6 to 12 months; no progress for 3 quarters." An overdue
 * project reads "a further delay {word}" (the outlook is the next two quarters, not the past), so an overdue project
 * whose delay is unlikely does not contradict itself. Every clause drops when its field is missing.
 */
export function projectHeadline(input: HeadlineInput, asof: string | null | undefined): string {
  const opener = input.tier ? OPENER[input.tier] : 'Not in the current scored portfolio'
  const due = dueIn(input.anticipatedCompletion, asof)

  const facts: string[] = []
  const pct = input.physicalProgressPct
  if (pct !== null && pct !== undefined) facts.push(done(pct))
  if (due) {
    facts.push(due.overdue ? `${plural(-due.months, 'month')} past its expected date`
      : due.months === 0 ? 'due this month' : `${plural(due.months, 'month')} from its expected date`)
  }
  if (input.elapsedRatio !== null && input.elapsedRatio !== undefined && input.elapsedRatio >= 1) {
    facts.push('the schedule already used up')
  }

  const o = input.outlook
  const view: string[] = []
  if (o?.delay) view.push(`${due?.overdue ? 'a further delay' : 'delay'} ${o.delay}`)
  if (o?.cost) view.push(`cost rise ${o.cost}`)
  if (o?.slip && likelyOrWorse(o.delay)) view.push(`likely slip ${o.slip}`)

  const tail: string[] = []
  if (input.stagnationOverride) {
    const q = input.stagnationQuarters
    tail.push(q && q >= 1 ? `no progress for ${plural(Math.round(q), 'quarter')}`
      : 'no progress for two or more quarters')
  }
  if (input.flags?.includes('early_notice')) {
    tail.push(`${noticeNoun(input.flags)} on record with no slip in the numbers yet`)
  }

  const groups = [facts.join(', '), view.join(', '), ...tail].filter(Boolean)
  return groups.length ? `${opener}: ${groups.join('; ')}.` : `${opener}.`
}

/** the headline of a loaded project page; numbers: the developer, whose words may come from the numbers */
export function detailHeadline(d: ProjectDetail, numbers: boolean): string {
  return projectHeadline({
    tier: d.scores?.tier ?? null,
    physicalProgressPct: d.latest?.physicalProgressPct ?? null,
    anticipatedCompletion: d.latest?.anticipatedCompletion ?? null,
    elapsedRatio: d.scores?.elapsedRatio ?? null,
    outlook: outlookOf(d.scores, numbers),
    stagnationOverride: d.scores?.stagnationOverride ?? null,
    stagnationQuarters: d.scores?.stagnationQuarters ?? null,
    flags: d.flags,
  }, d.provenance.asof)
}

// ------------------------------------------------------------------ the week

/** a map or list row as the week's brief reads it */
export interface BriefRow {
  tier: Tier | null
  anticipatedCompletion: string | null
  outlook?: Outlook | null
  flags: Flag[]
}

export interface WeekBriefInput {
  asof: string | null
  /** every row in scope (or the fallback's riskiest), null while loading */
  rows: BriefRow[] | null
  /** the words the rows read (outlookOf per row); rows without words make the tier sentence */
  outlookOf: (r: BriefRow) => Outlook | null
  /** set when rows are only the riskiest few of the scope (the map endpoint is missing) */
  partial?: { shown: number; total: number } | null
  kpis?: Kpis | null
  tiers?: TierCount[] | null
  /** alert counts since last Monday by kind; null for the public (no alerts) */
  alerts?: Partial<Record<AlertKind, number>> | null
}

const SIX_MONTHS = 6

/**
 * At most three sentences for the top of a home or the command centre: what is due soon and likely to slip (or, with
 * no outlook words yet, what is Critical or High and due soon), how many of those have an outside issue with no
 * slip yet, and what changed since last Monday (officials). With no rows (the public, or loading) it is the
 * portfolio in facts: projects, money, built share, overrun.
 */
export function weekBrief(input: WeekBriefInput): string[] {
  const out: string[] = []
  const rows = input.rows
  if (rows && input.asof) {
    const soon = rows.filter((r) => {
      const d = dueIn(r.anticipatedCompletion, input.asof)
      return d !== null && !d.overdue && d.months <= SIX_MONTHS
    })
    const withWords = rows.some((r) => input.outlookOf(r))
    const hot = withWords
      ? soon.filter((r) => likelyOrWorse(input.outlookOf(r)?.delay))
      : soon.filter((r) => r.tier === 'Critical' || r.tier === 'High')
    const prefix = input.partial ? `Of the ${plural(input.partial.shown, 'project')} most at risk, ` : ''
    const n = hot.length
    const are = n === 1 ? 'is' : 'are'
    if (withWords) {
      out.push(n === 0
        ? `${prefix}${prefix ? 'none is' : 'No project is'} due within six months with a delay likely.`
        : `${prefix}${prefix ? n.toLocaleString('en-IN') : plural(n, 'project')} ${are} due within six months `
          + 'and likely to slip.')
    } else if (prefix) {
      const who = n === 0 ? 'none is' : `${n.toLocaleString('en-IN')} ${are}`
      out.push(`${prefix}${who} Critical or High and due within six months.`)
    } else {
      out.push(n === 0
        ? 'No Critical or High project is due within six months.'
        : `${plural(n, 'Critical or High project', 'Critical or High projects')} ${are} due within six months.`)
    }
    const notice = hot.filter((r) => r.flags.includes('early_notice')).length
    if (n > 0 && notice > 0) {
      const one = notice === 1
      const who = notice === n ? (one ? 'It' : 'All of them') : `${notice.toLocaleString('en-IN')} of them`
      out.push(`${who} ${one ? 'shows' : 'show'} no slip in the reports yet but ${one ? 'has' : 'have'} `
        + 'a land, forest, court or contractor issue on record.')
    }
  } else if (input.kpis) {
    const k = input.kpis
    const money = k.anticipatedCostCr !== null ? ` worth ${formatINRShort(k.anticipatedCostCr)}` : ''
    const built = k.avgProgressPct !== null ? `, on average ${Math.round(k.avgProgressPct)}% built` : ''
    out.push(`${plural(k.nProjects, 'open project')}${money}${built}.`)
    if (k.overrunPct !== null && k.overrunPct > 0.5) {
      out.push(`Together they now cost ${Math.round(k.overrunPct)}% more than first sanctioned.`)
    }
  }

  const a = input.alerts
  if (a) {
    const bits = [
      a.tier_up && `${plural(a.tier_up, 'project')} moved up a tier`,
      a.slip_realised && `${plural(a.slip_realised, 'project')} realised a slip`,
      a.early_notice && `${plural(a.early_notice, 'new early notice', 'new early notices')}`,
      a.signal && `${plural(a.signal, 'news item')} ${a.signal === 1 ? 'was' : 'were'} linked`,
    ].filter((x): x is string => !!x)
    if (bits.length) out.push(`Since last Monday: ${bits.join(', ')}.`)
  }
  return out.slice(0, 3)
}

/** last Monday 00:00 local time as an ISO string (the week the brief's changes count from) */
export function lastMonday(now = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const back = (d.getDay() + 6) % 7 || 7
  d.setDate(d.getDate() - back)
  return d.toISOString()
}
