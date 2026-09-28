/**
 * src/lib/forecast.ts
 *
 * Reading GET /api/projects/{key}/forecast in either shape (contracts/project.ts Forecast): the developer's numbers
 * (Analogue rows with distances and outcomes in 0/1) or the four roles' words (AnalogueBrief, the completion window
 * as a band). The analogue sentence counts outcomes, which both shapes carry; no distance, slip or rate is read.
 */
import { monthsUntil } from './headline'
import type { Analogue, AnalogueBrief, AnalogueOutcome, Forecast } from '@/contracts/project'

/** an analogue row in numbers (the developer's), as opposed to the four roles' AnalogueBrief */
export function isNumericAnalogue(a: Analogue | AnalogueBrief): a is Analogue {
  return 'analogueKey' in a
}

/** the numeric analogue rows only: the developer's table */
export function numericAnalogues(f: Forecast | undefined): Analogue[] {
  return (f?.analogues ?? []).filter(isNumericAnalogue)
}

export interface AnalogueChip {
  key: string | null
  name: string
  sector: string | null
  outcome: AnalogueOutcome
  /** whole years between the analogue's report and this project's as-of; null when unknown */
  yearsAgo: number | null
}

function outcomeOf(a: Analogue | AnalogueBrief): AnalogueOutcome {
  if (!isNumericAnalogue(a)) return a.outcome
  return a.yAny === 1 ? 'slipped' : a.yAny === 0 ? 'held' : 'unknown'
}

/** every analogue as a chip: name, sector, what happened, how long ago */
export function analogueChips(f: Forecast | undefined): AnalogueChip[] {
  if (!f) return []
  return f.analogues.map((a) => {
    if (!isNumericAnalogue(a)) {
      const { sector, outcome, yearsAgo } = a
      return { key: a.key ?? null, name: a.name ?? 'an unnamed project', sector, outcome, yearsAgo }
    }
    const months = a.analoguePeriod ? -monthsUntil(f.asof, a.analoguePeriod) : null
    return {
      key: a.analogueKey,
      name: a.analogueName ?? a.analogueKey,
      sector: a.sector,
      outcome: outcomeOf(a),
      yearsAgo: months === null || Number.isNaN(months) ? null : Math.max(0, Math.round(months / 12)),
    }
  })
}

/**
 * "Of 10 similar past projects at this stage, 7 slipped and 3 held" (the unknown ones named last); null without
 * analogues. Counts of what happened, never a rate.
 */
export function analogueSentence(f: Forecast | undefined): string | null {
  const chips = analogueChips(f)
  if (chips.length === 0) return null
  const n = (o: AnalogueOutcome) => chips.filter((c) => c.outcome === o).length
  const parts = [
    n('slipped') > 0 && `${n('slipped')} slipped within a year`,
    n('held') > 0 && `${n('held')} held`,
    n('unknown') > 0 && `${n('unknown')} cannot be told`,
  ].filter((x): x is string => !!x)
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]
  const noun = chips.length === 1 ? 'similar past project' : 'similar past projects'
  return `Of ${chips.length} ${noun} at this stage, ${list}.`
}

/** 'slipped' in its ink */
export const OUTCOME_TONE: Record<AnalogueOutcome, string> = {
  slipped: 'text-critical',
  held: 'text-stable',
  unknown: 'text-fg-dimmed',
}
