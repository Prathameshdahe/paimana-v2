import { MonoFigure } from '@/components/ui/MonoFigure'
import { cn } from '@/lib/formatters'
import type { ModelBenchmarkRow } from '@/contracts/audit'
import { BENCHMARK_NOTES } from '@/mocks/audit'

interface BenchmarkMatrixProps {
  rows: ModelBenchmarkRow[]
}

export function BenchmarkMatrix({ rows }: BenchmarkMatrixProps) {
  if (!rows || rows.length === 0) return null

  const baseline = rows.find((r) => r.isBaseline) ?? rows[0]
  const best = rows.find((r) => r.modelShortName === 'LightGBM') ?? rows[rows.length - 1]

  if (!baseline || !best) return null

  const prAucLift = ((best.prAuc - baseline.prAuc) / baseline.prAuc) * 100
  const recallLift = ((best.recallAt50 - baseline.recallAt50) / Math.max(baseline.recallAt50, 0.0001)) * 100

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="border border-border-subtle bg-surface-panel grid grid-cols-4 divide-x divide-border-subtle">
        <div className="px-5 py-4">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold mb-1.5">Recommended</div>
          <div className="font-mono text-lg font-medium text-fg-base">{best.modelShortName}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold mb-1.5">PR-AUC</div>
          <MonoFigure size="lg" sentiment="stable">{best.prAuc.toFixed(3)}</MonoFigure>
          <div className="text-xs font-mono text-stable mt-1 font-medium">+{prAucLift.toFixed(0)}% vs floor</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold mb-1.5">Recall@50</div>
          <MonoFigure size="lg" sentiment="stable">{(best.recallAt50 * 100).toFixed(1)}%</MonoFigure>
          <div className="text-xs font-mono text-stable mt-1 font-medium">+{recallLift.toFixed(0)}% vs floor</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold mb-1.5">Lead Time</div>
          <MonoFigure size="lg" sentiment="accent">{best.leadTimeMonths.toFixed(1)}mo</MonoFigure>
        </div>
      </div>

      {/* Full table */}
      <div className="border border-border-subtle bg-surface-panel">
        <div className="border-b border-border-subtle px-4 py-3">
          <span className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold">
            Clause (b) · AI/ML vs. Statistical Benchmark — real backtest, model/metrics.json
          </span>
        </div>

        <table className="w-full text-[13px] font-mono border-collapse">
          <thead>
            <tr className="border-b border-border-default text-fg-muted">
              <th className="py-3 px-4 text-left font-medium">Model</th>
              <th className="py-3 px-4 text-left font-medium">Type</th>
              <th className="py-3 px-4 text-right font-medium">PR-AUC ↑</th>
              <th className="py-3 px-4 text-right font-medium">Recall@50 ↑</th>
              <th className="py-3 px-4 text-right font-medium">Lead Time</th>
              <th className="py-3 px-4 text-right font-medium">n (test / pos)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isLightGBM = r.modelShortName === best.modelShortName
              const isBest = isLightGBM
              const isBase = r.isBaseline

              return (
                <tr
                  key={r.modelShortName}
                  className={cn(
                    'border-b transition-colors h-auto',
                    isLightGBM
                      ? 'bg-accent/10 border-l-2 border-l-accent border-b-border-subtle/80'
                      : isBest
                      ? 'bg-surface-elevated/50 border-b-border-subtle/60'
                      : 'border-b-border-subtle/60 hover:bg-surface-elevated/30'
                  )}
                >
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cn('text-fg-base', isLightGBM && 'font-semibold')}>{r.modelName}</span>
                      {isBase && <span className="text-[11px] text-fg-muted">[FLOOR]</span>}
                      {isLightGBM ? (
                        <span className="font-mono text-[11px] font-bold text-accent tracking-wider bg-accent/15 px-2 py-0.5 rounded-sm border border-accent/30 inline-flex items-center gap-1">
                          [● RECOMMENDED MODEL]
                        </span>
                      ) : isBest ? (
                        <span className="text-[11px] text-accent font-semibold">[PROD]</span>
                      ) : null}
                    </div>
                    <div className="text-xs text-fg-muted mt-1 max-w-lg leading-relaxed">
                      {r.notes}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span className={cn(
                      'text-xs uppercase font-medium',
                      r.modelCategory === 'ml' ? 'text-accent' : 'text-fg-muted'
                    )}>
                      {r.modelCategory}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <span className={isBest ? 'text-stable font-medium' : isBase ? 'text-critical font-medium' : 'text-fg-muted'}>
                      {r.prAuc.toFixed(3)}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <span className={isBest ? 'text-stable font-medium' : 'text-fg-muted'}>
                      {(r.recallAt50 * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right text-fg-muted">{r.leadTimeMonths.toFixed(1)}mo</td>
                  <td className="py-3 px-4 text-right text-fg-muted">{r.nTest} / {r.nPositive}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <div className="border-t border-border-subtle px-4 py-3 font-mono text-[11px] text-fg-muted space-y-1">
          {BENCHMARK_NOTES.map((note) => (
            <div key={note}>· {note}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
