import React from 'react'
import { cn } from '@/lib/formatters'
import { TIER_LABEL, TIER_SENTIMENT, tierKey } from '@/lib/riskPalette'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'critical' | 'warning' | 'stable' | 'accent' | 'muted'
  /** a project tier; null means untiered (no completion date) */
  tier?: string | null
}

const VARIANT: Record<NonNullable<BadgeProps['variant']>, string> = {
  critical: 'bg-critical/10 text-critical ring-critical/20',
  warning: 'bg-warning/10 text-warning ring-warning/20',
  stable: 'bg-stable/10 text-stable ring-stable/20',
  accent: 'bg-accent/10 text-accent ring-accent/25',
  muted: 'bg-fg-dimmed/10 text-fg-muted ring-fg-dimmed/20',
}

/** Soft rounded pill. With `tier` it names the tier: Critical red, High amber, Medium blue-grey, Low green, no date grey. */
export function Badge({ variant = 'muted', tier, className, children, ...props }: BadgeProps) {
  const t = tier === undefined ? null : tierKey(tier)
  const v = t ? TIER_SENTIMENT[t] : variant

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium leading-4 whitespace-nowrap ring-1 ring-inset',
        VARIANT[v],
        className
      )}
      {...props}
    >
      {children ?? (t ? (t === 'untiered' ? 'No date' : TIER_LABEL[t]) : null)}
    </span>
  )
}
