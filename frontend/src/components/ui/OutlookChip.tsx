import { TONE_DOT, toneOf } from '@/lib/outlook'
import { tierKey } from '@/lib/riskPalette'
import { cn } from '@/lib/formatters'
import type { Outlook } from '@/contracts/project'

/**
 * The delay outlook as a small chip ("Delay likely" with its tone dot) for lists: a Watch project reads "not ranked",
 * a project without words from this backend a dash. No number, ever.
 */
export function OutlookChip({ outlook, tier, className }: { outlook: Outlook | null; tier: string | null | undefined; className?: string }) {
  if (tierKey(tier) === 'Watch') {
    return <span className={cn('shrink-0 text-xs text-fg-dimmed', className)} title="No completion date in the reports, so the delay risk is not ranked">not ranked</span>
  }
  if (!outlook?.delay) {
    return <span className={cn('shrink-0 text-xs text-fg-dimmed', className)} title="The outlook in words is not available for this project yet">—</span>
  }
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs font-medium text-fg-base', className)}>
      <span className={cn('size-1.5 rounded-full', TONE_DOT[toneOf(outlook.delay)])} aria-hidden="true" />
      Delay {outlook.delay}
    </span>
  )
}
