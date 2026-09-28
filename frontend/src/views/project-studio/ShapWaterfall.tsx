import { MonoFigure } from '@/components/ui/MonoFigure'
import { InfoTip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/formatters'
import { featureLabel } from '@/lib/featureLabels'
import type { ShapValue } from '@/contracts/project'

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return 'missing'
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)
  return String(v)
}

/**
 * Top-5 TreeSHAP drivers of P(date push or cost revision, 2q) for one project,
 * as scored by the LightGBM champion. Contributions are in log-odds: red
 * pushes the probability up, green pulls it down.
 */
export function ShapWaterfall({ drivers }: { drivers: ShapValue[] }) {
  const sorted = [...drivers].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
  const maxAbs = Math.max(...drivers.map((d) => Math.abs(d.contribution)), 0.0001)

  return (
    <div className="bg-surface-panel flex flex-col border border-border-subtle overflow-hidden h-full rounded-xl shadow-card">
      <div className="border-b border-border-subtle px-5 py-3 flex items-center justify-between">
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-semibold text-fg-base">
          Why this score
          <InfoTip label="About the drivers">
            The top 5 TreeSHAP drivers of the LightGBM P(slip, 2q) model, in log-odds. Red raises the probability, green lowers it.
          </InfoTip>
        </span>
        {sorted[0] && (
          <span className="text-xs text-critical font-medium truncate ml-3">
            primary: {featureLabel(sorted[0].feature)}
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-fg-dimmed">
          no drivers — they explain P(slip, 2q), which is not scored for this project
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60 flex-1">
          {sorted.map((d, i) => {
            const up = d.contribution > 0
            return (
              <div key={d.feature} className="flex items-center px-4 py-3 gap-4 hover:bg-surface-elevated/40 transition-colors">
                <span className="text-xs text-fg-muted w-5 shrink-0">{i + 1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg-base font-medium truncate mb-1" title={d.feature}>
                    {featureLabel(d.feature)}
                    <span className="font-mono text-fg-dimmed"> = {formatValue(d.value)}</span>
                  </div>
                  <div className="h-1.5 w-full bg-surface-input">
                    <div
                      className={cn('h-full', up ? 'bg-critical' : 'bg-stable')}
                      style={{ width: `${(Math.abs(d.contribution) / maxAbs) * 100}%` }}
                    />
                  </div>
                </div>
                <MonoFigure size="sm" sentiment={up ? 'critical' : 'stable'} className="shrink-0 w-16 text-right">
                  {up ? '+' : ''}
                  {d.contribution.toFixed(2)}
                </MonoFigure>
              </div>
            )
          })}
        </div>
      )}

    </div>
  )
}
