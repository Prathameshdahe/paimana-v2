import { Link } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { formatDate, formatPct, orDash, cn } from '@/lib/formatters'
import type { Forecast } from '@/contracts/project'

/** The 10 nearest historical projects at the same stage and what happened to them within 4 quarters. */
export function AnaloguesTable({ forecast }: { forecast: Forecast | undefined }) {
  const rows = forecast?.analogues ?? []

  return (
    <Card title={`Analogue Projects · ${rows.length}`} className="h-full">
      <div className="px-4 py-2.5 border-b border-border-subtle text-xs text-fg-base">
        {forecast ? forecast.analogueSummary : <span className="text-fg-dimmed">no forecast for this project</span>}
      </div>
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border-default text-fg-dimmed font-sans text-xs">
                <th className="py-2 px-4 font-semibold">#</th>
                <th className="py-2 px-4 font-semibold">Project</th>
                <th className="py-2 px-4 font-semibold">At stage</th>
                <th className="py-2 px-4 font-semibold text-right" title="feature distance to this project (lower = more alike)">Distance</th>
                <th className="py-2 px-4 font-semibold">Within 4q</th>
                <th className="py-2 px-4 font-semibold text-right">Slip</th>
                <th className="py-2 px-4 font-semibold text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.rank} className="border-b border-border-subtle/60 hover:bg-surface-elevated/40">
                  <td className="py-2 px-4 text-fg-dimmed">{a.rank}</td>
                  <td className="py-2 px-4 max-w-[320px]">
                    <Link to={`/projects/${a.analogueKey}`} className="block truncate font-sans text-fg-base hover:underline" title={a.analogueName ?? undefined}>
                      {a.analogueName ?? a.analogueKey}
                    </Link>
                    <span className="text-xs text-fg-dimmed">{a.analogueKey} · {a.basis ?? ''} pool</span>
                  </td>
                  <td className="py-2 px-4 text-fg-muted">{orDash(a.analoguePeriod, formatDate)}</td>
                  <td className="py-2 px-4 text-right text-fg-muted">{orDash(a.distance, (v) => v.toFixed(2))}</td>
                  <td className="py-2 px-4 whitespace-nowrap">
                    {a.yAny === null ? (
                      <span className="text-fg-dimmed">unknown</span>
                    ) : (
                      <span className={cn(a.yAny === 1 ? 'text-critical' : 'text-stable')}>
                        {a.yAny === 1
                          ? [a.yDatePush === 1 && 'date pushed', a.yCostRev === 1 && 'cost revised'].filter(Boolean).join(' + ')
                          : 'no change'}
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-4 text-right text-fg-base">{orDash(a.yMonths, (v) => `${v.toFixed(0)}mo`)}</td>
                  <td className="py-2 px-4 text-right text-fg-base">{orDash(a.yCostPct, (v) => formatPct(v, 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
