/**
 * src/lib/riskPalette.ts
 * Single source of truth for the tier vocabulary and its colours — used by the
 * India map, the charts and the badges. Tiers go by rank (Critical/High/
 * Medium/Low); a project with no anticipated completion date is untiered.
 */
import {
  Building2, Bug, Calendar, CalendarX, CirclePlus, Clock, Gavel, HardHat, IndianRupee, LandPlot, Layers, Map as MapIcon,
  Newspaper, Pause, Repeat, Scale, Siren, Trees, TrendingDown, TrendingUp, Wallet, type LucideIcon,
} from 'lucide-react'
import type { Flag, RiskState, Tier, TierFilter } from '@/contracts/project'
import type { AlertKind } from '@/contracts/portfolio'

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

/** soft fill + ink per sentiment: badges, icon chips */
export const TONE_CHIP = {
  critical: 'bg-critical/10 text-critical',
  warning: 'bg-warning/10 text-warning',
  stable: 'bg-stable/10 text-stable',
  accent: 'bg-accent/10 text-accent',
  muted: 'bg-fg-dimmed/10 text-fg-muted',
} as const

/** list flags: a flagged risk-profile dimension, or early notice (flagged external factor, no slip in the numbers yet) */
export const FLAG_LABEL: Record<Flag, string> = {
  land: 'Land',
  forest: 'Forest',
  litigation: 'Litigation',
  contractor: 'Contractor',
  early_notice: 'Early notice',
}

/** icon chip per list flag */
export const FLAG_ICON: Record<Flag, LucideIcon> = {
  land: LandPlot,
  forest: Trees,
  litigation: Scale,
  contractor: HardHat,
  early_notice: Siren,
}

/** the 13 risk-profile dimensions (ml/risk_profile.py), in checklist order: full label, tile label, icon */
export const RISK_DIMENSION: Record<string, { label: string; short: string; icon: LucideIcon }> = {
  schedule_slip: { label: 'Schedule slip', short: 'Schedule', icon: Calendar },
  cost_escalation: { label: 'Cost escalation', short: 'Cost', icon: IndianRupee },
  execution_stagnation: { label: 'Execution stagnation', short: 'Stagnation', icon: Pause },
  expenditure_lag: { label: 'Expenditure lag', short: 'Spend lag', icon: Wallet },
  repeated_revisions: { label: 'Repeated revisions', short: 'Revisions', icon: Repeat },
  sector_headwind: { label: 'Sector headwind', short: 'Sector', icon: TrendingDown },
  agency_optimism: { label: 'Agency optimism', short: 'Agency', icon: Building2 },
  land_acquisition: { label: 'Land acquisition', short: 'Land', icon: MapIcon },
  forest_clearance: { label: 'Environment / forest clearance', short: 'Forest', icon: Trees },
  litigation: { label: 'Litigation', short: 'Litigation', icon: Gavel },
  contractor_stress: { label: 'Contractor stress', short: 'Contractor', icon: HardHat },
  data_staleness: { label: 'Data staleness', short: 'Data age', icon: Clock },
  external_composite: { label: 'External factor score', short: 'Land + forest', icon: Layers },
}

// unknown gets its own look (dashed, grey) so it never reads as clear
export const RISK_STATE_CHIP: Record<RiskState, string> = {
  flagged: 'bg-critical/10 text-critical ring-1 ring-inset ring-critical/25',
  clear: 'bg-stable/10 text-stable ring-1 ring-inset ring-stable/20',
  unknown: 'border border-dashed border-fg-dimmed/60 text-fg-dimmed',
}

export const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  tier_up: 'Tier up',
  tier_down: 'Tier down',
  new_project: 'New project',
  slip_realised: 'Slip realised',
  signal: 'News signal',
  early_notice: 'Early notice',
  pipeline_error: 'Pipeline error',
}

export const ALERT_KIND_ICON: Record<AlertKind, LucideIcon> = {
  tier_up: TrendingUp,
  tier_down: TrendingDown,
  new_project: CirclePlus,
  slip_realised: CalendarX,
  signal: Newspaper,
  early_notice: Siren,
  pipeline_error: Bug,
}

/** Badge variant per alert severity (3 highest) */
export const ALERT_SEVERITY = { 3: 'critical', 2: 'warning', 1: 'muted' } as const

export function alertVariant(severity: number) {
  return ALERT_SEVERITY[severity as 1 | 2 | 3] ?? 'muted'
}

/**
 * Report-remark / news event categories (pipeline/external.py TAXONOMY): label, fill and the ink
 * readable on that fill. Fixed per category, so a filter never repaints one.
 */
export const EVENT_CATEGORY: Record<string, { label: string; color: string; ink: string }> = {
  land: { label: 'Land', color: '#2a78d6', ink: '#ffffff' },
  forest_env: { label: 'Forest / environment', color: '#1baf7a', ink: '#0b0b0b' },
  litigation: { label: 'Litigation', color: '#eb6834', ink: '#0b0b0b' },
  contractor: { label: 'Contractor', color: '#eda100', ink: '#0b0b0b' },
  funding: { label: 'Funding', color: '#e87ba4', ink: '#0b0b0b' },
  utility_shifting: { label: 'Utility shifting', color: '#008300', ink: '#ffffff' },
  inter_agency: { label: 'Inter-agency', color: '#4a3aa7', ink: '#ffffff' },
  law_order: { label: 'Law & order', color: '#e34948', ink: '#ffffff' },
  weather: { label: 'Weather', color: '#8a8578', ink: '#ffffff' },
}

export function categoryLabel(c: string | null | undefined): string {
  return c ? (EVENT_CATEGORY[c]?.label ?? c.replace(/_/g, ' ')) : 'uncategorised'
}
