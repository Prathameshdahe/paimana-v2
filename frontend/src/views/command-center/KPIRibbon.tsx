import { usePortfolioSummary } from '@/mocks'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatINRShort, formatPct } from '@/lib/formatters'

/**
 * KPI Ribbon — inline metric strip, NOT card soup.
 * Single horizontal band with pipe-delimited macro KPIs.
 * Matches Grafana/Datadog stat-bar pattern.
 */
export function KPIRibbon() {
  const { data: s } = usePortfolioSummary()
  if (!s) return null

  const overrunPct = (s.cumulativeOverrunCr / s.originalPortfolioCostCr) * 100

  return (
    <div className="border border-border-subtle bg-surface-panel">
      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-border-subtle">
        {/* Sanctioned Capital */}
        <div className="px-4 py-3 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed mb-1">
            Revised Sanctioned
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="default">
              {formatINRShort(s.revisedPortfolioCostCr)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-fg-muted font-semibold bg-surface-elevated border border-border-subtle px-1.5 py-0.5 rounded-sm">
              orig <span className="font-mono tabular-nums">{formatINRShort(s.originalPortfolioCostCr)}</span>
            </div>
          </div>
        </div>

        {/* Cumulative Overrun */}
        <div className="px-4 py-3 bg-critical/5 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-critical mb-1 flex items-center justify-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-critical" />
            Cumulative Overrun
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="critical">
              {formatINRShort(s.cumulativeOverrunCr)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-critical font-semibold bg-critical/10 px-1.5 py-0.5 rounded-sm">
              <span className="font-mono tabular-nums">+{formatPct(overrunPct)}</span> escalation
            </div>
          </div>
        </div>

        {/* Triage Distribution */}
        <div className="px-4 py-3 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed mb-1">
            Risk Triage
          </div>
          <div className="flex items-baseline justify-center gap-3 mt-1">
            <span className="text-lg font-mono tabular-nums font-semibold text-critical">{s.criticalCount}</span>
            <span className="text-[11px] font-sans text-fg-dimmed font-medium">CRIT</span>
            <span className="text-lg font-mono tabular-nums font-semibold text-warning">{s.warningCount}</span>
            <span className="text-[11px] font-sans text-fg-dimmed font-medium">WARN</span>
            <span className="text-lg font-mono tabular-nums font-semibold text-stable">{s.normalCount}</span>
            <span className="text-[11px] font-sans text-fg-dimmed font-medium">STBL</span>
          </div>

          {/* Proportional bar — minimal, no rounded corners */}
          <div className="flex h-1 w-3/4 mt-2 bg-surface-input">
            <div
              style={{ width: `${(s.criticalCount / s.totalProjects) * 100}%` }}
              className="bg-critical h-full"
            />
            <div
              style={{ width: `${(s.warningCount / s.totalProjects) * 100}%` }}
              className="bg-warning h-full"
            />
            <div
              style={{ width: `${(s.normalCount / s.totalProjects) * 100}%` }}
              className="bg-stable h-full"
            />
          </div>
        </div>

        {/* P-F Disparity Leading Indicator */}
        <div className="px-4 py-3 bg-warning/5 flex flex-col items-center text-center justify-center">
          <div className="text-[11px] font-sans font-semibold uppercase tracking-widest text-warning mb-1">
            Avg Budget / Work Gap
          </div>
          <div className="flex items-center justify-center gap-2 mt-1">
            <MonoFigure size="xl" sentiment="warning">
              +{formatPct(s.avgDisparityDeltaPct)}
            </MonoFigure>
            <div className="text-[10px] font-sans text-warning font-semibold bg-warning/10 px-1.5 py-0.5 rounded-sm">
              financial burn ahead of physical
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
