/**
 * src/lib/research.ts
 *
 * Reading the web research facts (contracts/project.ts ResearchFact; backend/serving.py research): which group a
 * fact goes in, its category's label and colour, its date at the precision the source gives, and the "searched on"
 * line. Research is evidence, never a model input; "nothing found" is not the same as "no problem".
 */
import { EVENT_CATEGORY, categoryLabel } from '@/lib/riskPalette'
import { formatINR, formatLooseDate } from '@/lib/formatters'
import type { DatePrecision, ResearchExternal, ResearchFact } from '@/contracts/project'

export type ResearchGroup = 'live' | 'resolved' | 'progress' | 'other'

/** in page order: live blockers first, then what was resolved, then progress, then the rest */
export const RESEARCH_GROUPS: Array<{ key: ResearchGroup; label: string; hint: string }> = [
  { key: 'live', label: 'Live blockers', hint: 'negative, not resolved, dated within 4 quarters of the as-of quarter' },
  { key: 'resolved', label: 'Resolved', hint: 'an issue the sources report as settled' },
  { key: 'progress', label: 'Progress', hint: 'work done, milestones and other good news' },
  { key: 'other', label: 'Older and other reports', hint: 'older issues and neutral reports' },
]

/**
 * live > resolved > progress (a positive fact, or the progress category unless the fact is negative) > other. A
 * negative fact never lands in Progress: a stalled or slipping milestone is categorised `progress` too, and it
 * belongs with the older issues, not the good news.
 */
export function researchGroup(f: Pick<ResearchFact, 'live' | 'status' | 'direction' | 'category'>): ResearchGroup {
  if (f.live) return 'live'
  if (f.status === 'resolved') return 'resolved'
  if (f.direction === 'negative') return 'other'
  if (f.category === 'progress' || f.direction === 'positive') return 'progress'
  return 'other'
}

const GREY = '#9a968c'

/** pipeline/research.py TAXONOMY_OF where the name changes; every other category is its own taxonomy name */
const TAXONOMY_OF: Record<string, string> = { funds: 'funding', natural_event: 'weather' }

/**
 * The web research's own categories, which the report-remark taxonomy (riskPalette EVENT_CATEGORY) does not have.
 * Kept apart from it: the Radar lists EVENT_CATEGORY as its filter, and scout signals never carry these.
 */
const RESEARCH_ONLY: Record<string, { label: string; color: string }> = {
  approvals_other: { label: 'Other approvals', color: '#1f9bb5' },
  design_scope: { label: 'Design or scope', color: '#9b6a3c' },
  progress: { label: 'Schedule & progress', color: '#6f9a2e' },
  other: { label: 'Other', color: GREY },
}

/** a research category's label and dot colour: the taxonomy's colour where it maps, its own label */
export function researchCategory(category: string, taxonomy?: string | null): { label: string; color: string } {
  const key = taxonomy ?? TAXONOMY_OF[category] ?? category
  const own = RESEARCH_ONLY[key] ?? RESEARCH_ONLY[category]
  const ev = EVENT_CATEGORY[key] ?? EVENT_CATEGORY[category] ?? own
  // natural_event maps to the weather taxonomy, but a landslide or a tunnel inflow is not weather
  const label = category === 'natural_event' ? 'Natural event' : own?.label ?? categoryLabel(key)
  return { label, color: ev?.color ?? GREY }
}

/** the event date at its precision ("Aug 2026", "2026"), else "published 19 Aug 2026"; null when neither */
export function factDate(f: { eventDate: string | null; datePrecision: DatePrecision | null; publishedDate: string | null }): string | null {
  if (f.eventDate) return formatLooseDate(f.eventDate, f.datePrecision)
  return f.publishedDate ? `published ${formatLooseDate(f.publishedDate)}` : null
}

/** "Researched on 28 Sep 2026" from the sweep's day or the agent's last run; null when never searched */
export function researchedOn(r: { searched: boolean; researchedOn: string | null; agentResearchedAt: string | null }): string | null {
  if (!r.searched) return null
  const d = r.researchedOn ?? r.agentResearchedAt
  return d ? `Researched on ${formatLooseDate(d)}` : 'Researched'
}

/** the latest figures the sources give, one short line each with the date it is as of */
export function externalLines(x: ResearchExternal | null | undefined): Array<{ key: string; text: string; asOf: string | null }> {
  if (!x) return []
  const out: Array<{ key: string; text: string; asOf: string | null }> = []
  const asOf = (v: string | null) => (v ? formatLooseDate(v) : null)
  if (x.landAcquiredPct?.value !== null && x.landAcquiredPct?.value !== undefined) {
    out.push({ key: 'land', text: `Land ${x.landAcquiredPct.value.toFixed(0)}% acquired`, asOf: asOf(x.landAcquiredPct.asOf) })
  }
  if (x.forestClearance?.stage) {
    out.push({ key: 'forest', text: `Forest clearance: ${x.forestClearance.stage}`, asOf: asOf(x.forestClearance.asOf) })
  }
  if (x.courtCase && (x.courtCase.court || x.courtCase.status)) {
    const c = x.courtCase
    out.push({ key: 'court', text: `${c.court ?? 'Court case'}${c.status ? `: ${c.status}` : ''}`, asOf: asOf(c.asOf) })
  }
  if (x.contractor && (x.contractor.company || x.contractor.status)) {
    const c = x.contractor
    out.push({ key: 'contractor', text: `Contractor ${c.company ?? ''}${c.status ? `: ${c.status}` : ''}`.replace(/\s+:/, ':'), asOf: asOf(c.asOf) })
  }
  if (x.newTarget?.date) {
    out.push({ key: 'target', text: `New target: ${formatLooseDate(x.newTarget.date)}`, asOf: asOf(x.newTarget.asOf) })
  }
  if (x.costRevision?.newCostCr !== null && x.costRevision?.newCostCr !== undefined) {
    out.push({ key: 'cost', text: `Cost revised to ${formatINR(x.costRevision.newCostCr)}`, asOf: asOf(x.costRevision.asOf) })
  }
  return out
}
