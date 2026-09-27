import { usePortfolio } from '@/lib/queries'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { TIERS, TIER_COLOR, TIER_TEXT } from '@/lib/riskPalette'
import { formatINRShort, formatPct, orDash } from '@/lib/formatters'

/**
 * KPI Ribbon — inline metric strip, NOT card soup.
 * Single horizontal band with pipe-delimited macro KPIs from /api/portfolio.
 * Matches Grafana/Datadog stat-bar pattern.
 */
export function KPIRibbon() {
  const { data: p, error, isLoading } = usePortfolio()

  if (error) {
    return (
      <div className="border border-border-subtle bg-surface-panel">
        <ApiErrorNote error={error} className="py-4" />
      </div>
    )
  }
  if (isLoading || !p) {
    return <div className="border border-border-subtle bg-surface-panel h-[84px]" />
  }

  const k = p.kpis
  const tierN = (t: string) => p.tiers.find((x) => x.tier === t)?.n ?? 0
  const untiered = tierN('untiered')
  const spentPct =
    k.expenditureCr !== null && k.anticipatedCostCr ? (k.expenditureCr / k.anticipatedCostCr) * 100 : null

  return (
    <div className="border border-border-subtle bg-surface-panel">
      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-border-subtle">
        {/* Anticipated capital */}
        <div className="px-4 py-3 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed mb-1">
            Anticipated Cost
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="default">
              {orDash(k.anticipatedCostCr, formatINRShort)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-fg-muted font-semibold bg-surface-elevated border border-border-subtle px-1.5 py-0.5 rounded-sm">
              orig <span className="font-mono tabular-nums">{orDash(k.originalCostCr, formatINRShort)}</span>
            </div>
          </div>
          <div className="text-[10px] font-mono text-fg-dimmed mt-1">{k.nProjects.toLocaleString()} open projects</div>
        </div>

        {/* Cost overrun so far */}
        <div className="px-4 py-3 bg-critical/5 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-critical mb-1 flex items-center justify-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-critical" />
            Cost Overrun To Date
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="critical">
              {orDash(k.overrunCr, formatINRShort)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-critical font-semibold bg-critical/10 px-1.5 py-0.5 rounded-sm">
              <span className="font-mono tabular-nums">{orDash(k.overrunPct, (v) => `+${formatPct(v)}`)}</span> vs original
            </div>
          </div>
        </div>

        {/* Tier distribution (by rank) */}
        <div className="px-4 py-3 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed mb-1">
            Risk Tiers · by rank
          </div>
          <div className="flex items-baseline justify-center gap-2.5 mt-1">
            {TIERS.map((t) => (
              <span key={t} className="flex items-baseline gap-1">
                <span className={`text-lg font-mono tabular-nums font-semibold ${TIER_TEXT[t]}`}>{tierN(t)}</span>
                <span className="text-[10px] font-sans text-fg-dimmed font-medium uppercase">{t.slice(0, 4)}</span>
              </span>
            ))}
          </div>

          {/* Proportional bar — minimal, no rounded corners */}
          <div className="flex h-1 w-3/4 mt-2 bg-surface-input">
            {[...TIERS, 'untiered' as const].map((t) => (
              <div
                key={t}
                style={{ width: `${(tierN(t) / Math.max(k.nProjects, 1)) * 100}%`, background: TIER_COLOR[t] }}
                className="h-full"
              />
            ))}
          </div>
          <div className="text-[10px] font-mono text-fg-dimmed mt-1">
            + {untiered} untiered (no completion date)
          </div>
        </div>

        {/* Spend and progress */}
        <div className="px-4 py-3 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed mb-1">
            Spent To Date
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="default">
              {orDash(k.expenditureCr, formatINRShort)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-fg-muted font-semibold bg-surface-elevated border border-border-subtle px-1.5 py-0.5 rounded-sm">
              <span className="font-mono tabular-nums">{orDash(spentPct, (v) => formatPct(v, 0))}</span> of cost
            </div>
          </div>
          <div className="text-[10px] font-mono text-fg-dimmed mt-1">
            avg physical progress {orDash(k.avgProgressPct, (v) => formatPct(v, 0))}
          </div>
        </div>
      </div>
    </div>
  )
}
