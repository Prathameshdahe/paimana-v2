import type React from 'react'
import { Gauge, IndianRupee, ShieldAlert, TrendingUp } from 'lucide-react'
import { usePortfolio } from '@/lib/queries'
import { IconChip } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { TIERS, TIER_COLOR, TIER_LABEL, TIER_TEXT } from '@/lib/riskPalette'
import { formatINRShort, formatPct, formatPctDelta, orDash, cn } from '@/lib/formatters'
import type { TierCount } from '@/contracts/portfolio'

const tile = 'rounded-xl border border-border-subtle bg-surface-panel p-4 shadow-card animate-card-in'

/** a stat tile: icon chip, label, one big figure, and whatever sits under it */
export function Tile({ icon, tone, label, value, children }: {
  icon: React.ComponentType<{ className?: string }>
  tone: 'critical' | 'accent' | 'stable' | 'warning'
  label: string
  value?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <div className={tile}>
      <div className="flex items-center gap-2.5">
        <IconChip icon={icon} variant={tone} />
        <span className="text-sm font-medium text-fg-muted">{label}</span>
      </div>
      {value !== undefined && (
        <div className="mt-3 text-2xl font-semibold tabular-nums leading-none tracking-tight text-fg-base">{value}</div>
      )}
      {children}
    </div>
  )
}

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

/**
 * Four stat tiles from /api/portfolio: capital, overrun, the tier mix as one bar, and spend with
 * physical progress.
 */
export function KPIRibbon() {
  const { data: p, error, isLoading } = usePortfolio()

  if (error) {
    return (
      <div className={tile}>
        <ApiErrorNote error={error} className="py-4" />
      </div>
    )
  }
  if (isLoading || !p) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <div key={i} className={cn(tile, 'h-[128px] animate-pulse')} />)}
      </div>
    )
  }

  const k = p.kpis
  const tierN = (t: string) => p.tiers.find((x) => x.tier === t)?.n ?? 0
  const spentPct =
    k.expenditureCr !== null && k.anticipatedCostCr ? (k.expenditureCr / k.anticipatedCostCr) * 100 : null

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Tile icon={IndianRupee} tone="accent" label="Anticipated cost" value={orDash(k.anticipatedCostCr, formatINRShort)}>
        <div className="mt-2 text-xs text-fg-dimmed">
          {k.nProjects.toLocaleString()} open projects · originally {orDash(k.originalCostCr, formatINRShort)}
        </div>
      </Tile>

      <Tile icon={TrendingUp} tone="critical" label="Cost overrun so far" value={<span className="text-critical">{orDash(k.overrunCr, formatINRShort)}</span>}>
        <div className="mt-2 text-xs text-fg-dimmed">
          <span className="font-semibold text-critical">{orDash(k.overrunPct, formatPctDelta)}</span> over the original cost
        </div>
      </Tile>

      <Tile icon={ShieldAlert} tone="warning" label="Risk tiers">
        <div className="mt-3 flex items-baseline justify-between gap-2">
          {TIERS.map((t) => (
            <span key={t} className="flex flex-col">
              <span className={cn('text-xl font-semibold tabular-nums leading-none', TIER_TEXT[t])}>{tierN(t)}</span>
              <span className="mt-1 text-xs text-fg-dimmed">{t}</span>
            </span>
          ))}
        </div>
        <TierBar tiers={p.tiers} total={k.nProjects} className="mt-2.5 h-2" />
        {tierN('Watch') > 0 && (
          <div className="mt-1.5 text-xs text-fg-dimmed">
            + <span className="text-watch">{tierN('Watch').toLocaleString()} Watch</span>: no completion date
          </div>
        )}
      </Tile>

      <Tile icon={Gauge} tone="stable" label="Spent so far" value={orDash(k.expenditureCr, formatINRShort)}>
        <div className="mt-2.5 space-y-1.5 text-xs text-fg-dimmed">
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0">spent</span>
            <div className="flex-1"><Meter pct={spentPct ?? 0} className="bg-accent" /></div>
            <span className="w-9 text-right font-mono tabular-nums text-fg-muted">{orDash(spentPct, (v) => formatPct(v, 0))}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0">progress</span>
            <div className="flex-1"><Meter pct={k.avgProgressPct ?? 0} className="bg-stable" /></div>
            <span className="w-9 text-right font-mono tabular-nums text-fg-muted">{orDash(k.avgProgressPct, (v) => formatPct(v, 0))}</span>
          </div>
        </div>
      </Tile>
    </div>
  )
}
