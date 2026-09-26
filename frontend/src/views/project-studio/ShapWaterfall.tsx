import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatPct, cn } from '@/lib/formatters'
import type { ShapDriver } from '@/contracts/project'

interface ShapWaterfallProps {
  drivers: ShapDriver[]
  delayRemarks: string
  topBottleneck: string
  sandboxAction?: React.ReactNode
}

export function ShapWaterfall({ drivers, delayRemarks, topBottleneck, sandboxAction }: ShapWaterfallProps) {
  const sorted = [...drivers].sort((a, b) => Math.abs(b.impactMonths) - Math.abs(a.impactMonths))
  const maxImpact = Math.max(...drivers.map((d) => Math.abs(d.impactMonths)), 1)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 h-full">
      {/* SHAP Drivers — 2 cols */}
      <div className="lg:col-span-2 bg-surface-panel flex flex-col border border-border-subtle rounded-sm overflow-hidden">
        <div className="border-b border-border-subtle px-4 py-3 flex items-center justify-between">
          <span className="text-xs font-mono uppercase tracking-widest text-fg-muted">
            SHAP Root-Cause Attribution · Clause (a)
          </span>
          <span className="font-mono text-xs text-critical font-medium">
            primary: {topBottleneck}
          </span>
        </div>

        <div className="divide-y divide-border-subtle/60 flex-1">
          {sorted.map((d, i) => {
            const isWorsening = d.direction === 'worsening'
            const barW = `${(Math.abs(d.impactMonths) / maxImpact) * 100}%`

            return (
              <div key={i} className="flex items-center px-4 py-3 gap-4 hover:bg-surface-elevated/40 transition-colors">
                <span className="font-mono text-[11px] text-fg-muted w-5 shrink-0">
                  {i + 1}.
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg-base font-medium truncate mb-1">{d.feature}</div>
                  <div className="h-1.5 w-full bg-surface-input">
                    <div
                      className={cn('h-full', isWorsening ? 'bg-critical' : 'bg-stable')}
                      style={{ width: barW }}
                    />
                  </div>
                </div>
                <div className="font-mono text-[11px] text-fg-base shrink-0 w-10 text-right">
                  {formatPct(d.weight * 100, 0)}
                </div>
                <MonoFigure
                  size="sm"
                  sentiment={isWorsening ? 'critical' : 'stable'}
                  className="shrink-0 w-16 text-right"
                >
                  {d.impactMonths > 0 ? '+' : ''}{d.impactMonths.toFixed(1)}mo
                </MonoFigure>
              </div>
            )
          })}
        </div>

        <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-fg-muted">
          TreeSHAP on gradient boosted ensemble. Red = worsening delay.
        </div>

        {sandboxAction && (
          <div className="mt-auto px-4 py-5 border-t border-border-subtle">
            {sandboxAction}
          </div>
        )}
      </div>

      {/* CUF Delay Remarks — 1 col */}
      <div className="bg-surface-panel flex flex-col border border-border-subtle rounded-sm overflow-hidden">
        <div className="border-b border-border-subtle px-3 py-2">
          <span className="text-[10px] font-mono uppercase tracking-widest text-fg-dimmed">
            CUF Nodal Officer Remarks
          </span>
        </div>

        <div className="px-4 py-4">
          <div className="text-sm font-sans text-fg-base leading-relaxed border-l-2 border-border-default pl-4">
            &ldquo;{delayRemarks}&rdquo;
          </div>
        </div>

        <div className="border-t border-border-subtle px-4 py-3 space-y-1.5 font-mono text-[10px]">
          <div className="flex justify-between gap-2">
            <span className="text-fg-dimmed whitespace-nowrap">Filed by</span>
            <span className="text-fg-muted text-right">Nodal Exec. Engineer</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-fg-dimmed whitespace-nowrap">Status</span>
            <span className="text-stable text-right">IPMD Verified</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-fg-dimmed whitespace-nowrap">Classification</span>
            <span className="text-warning text-right line-clamp-2" title={topBottleneck}>{topBottleneck}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
