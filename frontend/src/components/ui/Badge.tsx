import React from 'react'
import { cn } from '@/lib/formatters'
import type { RiskTier } from '@/contracts/project'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'critical' | 'warning' | 'stable' | 'accent' | 'muted'
  tier?: RiskTier
}

/**
 * Minimal monospace status pip — NOT a colorful pill.
 * Format: [CRIT] [WARN] [STBL] — tight, functional, zero decoration.
 */
export function Badge({
  variant = 'muted',
  tier,
  className,
  children,
  ...props
}: BadgeProps) {
  let resolvedVariant = variant
  if (tier === 'CRITICAL') resolvedVariant = 'critical'
  if (tier === 'WARNING') resolvedVariant = 'warning'
  if (tier === 'NORMAL') resolvedVariant = 'stable'

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
        'font-mono text-[10px] tracking-widest leading-none uppercase',
        variantClasses[resolvedVariant],
        className
      )}
      {...props}
    >
      {children ?? `[${labels[resolvedVariant]}]`}
    </span>
  )
}
