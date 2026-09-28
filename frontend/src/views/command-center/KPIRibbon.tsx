/**
 * The portfolio's small pieces: the thin meter, the tier mix as one bar, and the portfolio line every home and the
 * command centre show under their opening sentence.
 */
import { usePortfolio } from '@/lib/queries'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { TIERS, TIER_COLOR, TIER_LABEL, TIER_TEXT } from '@/lib/riskPalette'
import { formatINRShort, formatPct, formatPctDelta, cn } from '@/lib/formatters'
import type { TierCount } from '@/contracts/portfolio'

/** a thin rounded bar: `pct` filled */
export function Meter({ pct, className }: { pct: number; className: string }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-surface-input">
      <div className={cn('h-full rounded-full transition-[width] duration-700', className)} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  )
}

/** the tier mix as one segmented bar, Watch last; each segment names its count on hover */
export function TierBar({ tiers, total, className = 'h-2' }: { tiers: TierCount[]; total: number; className?: string }) {
  const n = (t: string) => tiers.find((x) => x.tier === t)?.n ?? 0
  return (
    <div className={cn('flex gap-px overflow-hidden rounded-full bg-surface-input', className)}>
      {[...TIERS, 'Watch' as const].map((t) => (
        <Tooltip key={t} content={`${TIER_LABEL[t]}: ${n(t).toLocaleString()} projects`}>
          <div style={{ width: `${(n(t) / Math.max(total, 1)) * 100}%`, background: TIER_COLOR[t] }} className="h-full transition-[width] duration-700" />
        </Tooltip>
      ))}
    </div>
  )
}

/**
 * The portfolio in one line under a page's opening sentence: money, overrun over sanction, the built share, the five
 * tier counts and the tier bar. Report facts and counts only.
 */
export function PortfolioLine({ className }: { className?: string }) {
  const { data: p, error, isLoading } = usePortfolio()
  if (error) return <ApiErrorNote error={error} className="py-2 text-left" />
  if (isLoading || !p) return <div className={cn('h-10 animate-pulse rounded-lg bg-surface-input/70', className)} />
  const k = p.kpis
  const n = (t: string) => p.tiers.find((x) => x.tier === t)?.n ?? 0
  const facts = [
    k.anticipatedCostCr !== null && formatINRShort(k.anticipatedCostCr),
    k.overrunPct !== null && `${formatPctDelta(k.overrunPct)} over sanction`,
    k.avgProgressPct !== null && `${formatPct(k.avgProgressPct, 0)} built on average`,
  ].filter((x): x is string => !!x)
  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
        <span className="text-fg-muted">
          <span className="font-semibold text-fg-base">{k.nProjects.toLocaleString('en-IN')}</span> open projects
          {facts.length > 0 && <> · {facts.join(' · ')}</>}
        </span>
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {[...TIERS, 'Watch' as const].map((t) => (
            <span key={t} className="inline-flex items-baseline gap-1">
              <span className={cn('font-semibold tabular-nums', TIER_TEXT[t])}>{n(t).toLocaleString('en-IN')}</span>
              <span className="text-fg-dimmed">{TIER_LABEL[t]}</span>
            </span>
          ))}
        </span>
      </div>
      <TierBar tiers={p.tiers} total={k.nProjects} className="h-1.5" />
    </div>
  )
}
