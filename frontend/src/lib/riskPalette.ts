/**
 * src/lib/riskPalette.ts
 * Single source of truth for the tier vocabulary and its colours — used by the
 * India map, the charts and the badges. Tiers go by rank (Critical/High/
 * Medium/Low); a project with no anticipated completion date is untiered.
 */
import type { Flag, Tier, TierFilter } from '@/contracts/project'

export const TIERS: Tier[] = ['Critical', 'High', 'Medium', 'Low']

export function tierKey(tier: string | null | undefined): TierFilter {
  return tier === 'Critical' || tier === 'High' || tier === 'Medium' || tier === 'Low' ? tier : 'untiered'
}

export const TIER_LABEL: Record<TierFilter, string> = {
  Critical: 'Critical',
  High: 'High',
  Medium: 'Medium',
  Low: 'Low',
  untiered: 'No completion date',
}

export const TIER_SHORT: Record<TierFilter, string> = {
  Critical: 'CRIT',
  High: 'HIGH',
  Medium: 'MED',
  Low: 'LOW',
  untiered: 'NO DATE',
}

/** bright chart/map colours */
export const TIER_COLOR: Record<TierFilter, string> = {
  Critical: '#ff4d5e',
  High: '#ffb020',
  Medium: '#8ea3c4',
  Low: '#22c55e',
  untiered: '#b5b0a6',
}

/** text token per tier (deep variants of TIER_COLOR, readable on the sand canvas) */
export const TIER_TEXT: Record<TierFilter, string> = {
  Critical: 'text-critical',
  High: 'text-warning',
  Medium: 'text-accent',
  Low: 'text-stable',
  untiered: 'text-fg-dimmed',
}

/** MonoFigure/Badge sentiment per tier */
export const TIER_SENTIMENT = {
  Critical: 'critical',
  High: 'warning',
  Medium: 'accent',
  Low: 'stable',
  untiered: 'muted',
} as const satisfies Record<TierFilter, string>

/** list flags: a flagged risk-profile dimension, or early notice (flagged external factor, no slip in the numbers yet) */
export const FLAG_LABEL: Record<Flag, string> = {
  land: 'land',
  forest: 'forest',
  litigation: 'litigation',
  contractor: 'contractor',
  early_notice: 'early notice',
}
