import React from 'react'
import { cn } from '@/lib/formatters'
import { TIER_SENTIMENT, TIER_SHORT, tierKey } from '@/lib/riskPalette'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'critical' | 'warning' | 'stable' | 'accent' | 'muted'
  /** a project tier; null means untiered (no completion date) */
  tier?: string | null
}

/**
 * Minimal monospace status pip — NOT a colorful pill.
 * Format: [CRIT] [HIGH] [MED] [LOW] — tight, functional, zero decoration.
 */
export function Badge({
  variant = 'muted',
  tier,
  className,
  children,
  ...props
}: BadgeProps) {
  const t = tier === undefined ? null : tierKey(tier)
  const resolvedVariant = t ? TIER_SENTIMENT[t] : variant

  const variantClasses = {
    critical: 'text-critical',
    warning: 'text-warning',
    stable: 'text-stable',
    accent: 'text-accent',
    muted: 'text-fg-dimmed',
  }

  const labels: Record<string, string> = {
    critical: 'CRIT',
    warning: 'WARN',
    stable: 'STBL',
    accent: 'ACTV',
    muted: '----',
  }

  return (
    <span
      className={cn(
        'font-mono text-[10px] tracking-widest leading-none uppercase whitespace-nowrap',
        variantClasses[resolvedVariant],
        className
      )}
      {...props}
    >
      {children ?? `[${t ? TIER_SHORT[t] : labels[resolvedVariant]}]`}
    </span>
  )
}
