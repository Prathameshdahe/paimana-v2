import React from 'react'
import { Pause } from 'lucide-react'
import { cn } from '@/lib/formatters'
import { TIER_LABEL, TIER_SENTIMENT, TONE_CHIP, tierKey } from '@/lib/riskPalette'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'critical' | 'warning' | 'stable' | 'accent' | 'muted' | 'watch'
  /** a project tier; null (no score) reads as Watch */
  tier?: string | null
}

const RING: Record<NonNullable<BadgeProps['variant']>, string> = {
  critical: 'ring-critical/20',
  warning: 'ring-warning/20',
  stable: 'ring-stable/20',
  accent: 'ring-accent/25',
  muted: 'ring-fg-dimmed/20',
  watch: 'ring-watch/25',
}

/** Soft rounded pill. With `tier` it names the tier: Critical red, High amber, Medium blue-grey, Low green, Watch grey-violet. */
export function Badge({ variant = 'muted', tier, className, children, ...props }: BadgeProps) {
  const t = tier === undefined ? null : tierKey(tier)
  const v = t ? TIER_SENTIMENT[t] : variant

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center gap-1 px-2 py-0.5 text-xs font-medium leading-4 whitespace-nowrap ring-1 ring-inset',
        TONE_CHIP[v],
        RING[v],
        className
      )}
      {...props}
    >
      {children ?? (t ? TIER_LABEL[t] : null)}
    </span>
  )
}

/** The stagnation badge: no progress for 2+ quarters. A badge only; the tier stays by rank. */
export function StalledBadge({ quarters, className }: { quarters?: number | null; className?: string }) {
  return (
    <Badge
      variant="warning"
      className={className}
      title={`${quarters ? `${quarters.toFixed(0)} quarters` : '2+ quarters'} without progress; a badge only, the tier stays by rank (stalled projects slipped no more often in the backtest)`}
    >
      <Pause className="size-3" strokeWidth={2.5} aria-hidden="true" />
      Stalled
    </Badge>
  )
}

/** A soft rounded square holding one icon, tinted by sentiment: alert kinds, flags, stat tiles. */
export function IconChip({
  icon: Icon,
  variant = 'muted',
  size = 'md',
  className,
  ...props
}: { icon: React.ComponentType<{ className?: string; strokeWidth?: number }>; variant?: BadgeProps['variant']; size?: 'sm' | 'md' | 'lg' } & React.HTMLAttributes<HTMLSpanElement>) {
  const box = { sm: 'size-6 rounded-md', md: 'size-8 rounded-lg', lg: 'size-10 rounded-xl' }[size]
  const ico = { sm: 'size-3.5', md: 'size-4', lg: 'size-5' }[size]
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center', box, TONE_CHIP[variant], className)} {...props}>
      <Icon className={ico} strokeWidth={2} />
    </span>
  )
}
