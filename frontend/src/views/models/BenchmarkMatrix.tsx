import type { ReactNode } from 'react'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { Badge } from '@/components/ui/Badge'
import { cn, formatProb, orDash } from '@/lib/formatters'
import type { BacktestModel, BacktestRow } from '@/contracts/audit'

// ml/backtest.py MAIN, in that order; the notes say what each one is, not how good it is
const MODELS: Array<{ key: BacktestModel; name: string; note: string }> = [
  { key: 'naive', name: 'Naive', note: 'slipped last period, slips next: the floor everything must beat' },
  { key: 'rule', name: 'Old rule score', note: 'the v1 composite rule score, ranked as it is' },
  { key: 'logreg', name: 'Logistic regression', note: 'same features, standardised: the statistical baseline' },
  { key: 'lightgbm', name: 'LightGBM', note: 'gradient-boosted trees on the same features' },
]
// what a positive row did within h quarters (pipeline/gold.py labels)
const OUTCOME: Record<string, string> = {
  y_any: 'slipped or revised cost',
  y_date_push: 'pushed the date',
  y_cost_rev: 'revised cost',
}
const SPLITS: Array<{ key: BacktestRow['split']; label: string }> = [
  { key: 'val', label: 'Validation' },
  { key: 'test', label: 'Test (held out)' },
]

const f3 = (v: number | null) => orDash(v, (x) => x.toFixed(3))
const pct = (v: number | null) => orDash(v, (x) => formatProb(x, 1))
const pp = (v: number) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)} pp`

interface BenchmarkMatrixProps {
  /** backtest_summary.csv rows of one target (both splits, every model) */
  rows: BacktestRow[]
  /** the registry champion's model for this target, if any */
  champion?: string
  runId: string
}

/** Clause (b): the champion run's rolling-origin backtest, ML against the baselines, for one target. */
export function BenchmarkMatrix({ rows, champion, runId }: BenchmarkMatrixProps) {
  const get = (split: string, model: string) => rows.find((r) => r.split === split && r.model === model)
  const head = rows.some((r) => r.split === 'test') ? 'test' : 'val'
  const best = champion ? get(head, champion) : undefined
  const floor = get(head, 'naive')
  const h = rows[0]?.horizon
  const outcome = OUTCOME[rows[0]?.target ?? ''] ?? 'positive'

  return (
    <div className="space-y-4">
      {best && floor && (
        <div className="border border-border-subtle bg-surface-panel grid grid-cols-2 md:grid-cols-4 divide-x divide-border-subtle rounded-xl shadow-card overflow-hidden">
          <Stat label="Champion">
            <div className="text-lg font-semibold text-fg-base">{MODELS.find((m) => m.key === best.model)?.name ?? best.model}</div>
            <div className="text-xs text-fg-muted mt-1">{head === 'test' ? 'held-out test cutoff' : 'validation folds'}</div>
          </Stat>
          <Stat label="PR-AUC">
            <MonoFigure size="lg" sentiment="stable">{f3(best.prAuc)}</MonoFigure>
            <div className="text-xs text-fg-muted mt-1">naive {f3(floor.prAuc)} · base rate {pct(best.baseRate)}</div>
          </Stat>
          <Stat label="Precision@50">
            <MonoFigure size="lg" sentiment="stable">{pct(best.precision50)}</MonoFigure>
            <div className="text-xs text-fg-muted mt-1">
              naive {pct(floor.precision50)}
              {best.precision50 !== null && floor.precision50 !== null && ` · ${pp(best.precision50 - floor.precision50)}`}
            </div>
          </Stat>
          <Stat label="Rows / positive">
            <MonoFigure size="lg" sentiment="accent">{best.n.toLocaleString()}</MonoFigure>
            <div className="text-xs text-fg-muted mt-1">{best.nPos.toLocaleString()} {outcome} within {h}q</div>
          </Stat>
        </div>
      )}

      <div className="border border-border-subtle bg-surface-panel overflow-x-auto rounded-xl shadow-card">
        <div className="border-b border-border-subtle px-4 py-3">
          <span className="text-xs text-fg-muted font-semibold">
            Clause (b) · ML vs statistical baselines — model/runs/{runId}/backtest_summary.csv
          </span>
        </div>

        <table className="w-full text-sm font-mono border-collapse">
          <thead>
            <tr className="border-b border-border-default text-fg-muted">
              <th className="py-3 px-4 text-left font-medium">Model</th>
              <th className="py-3 px-4 text-right font-medium">PR-AUC ↑</th>
              <th className="py-3 px-4 text-right font-medium">ROC-AUC ↑</th>
              <th className="py-3 px-4 text-right font-medium">Brier ↓</th>
              <th className="py-3 px-4 text-right font-medium">ECE ↓</th>
              <th className="py-3 px-4 text-right font-medium">Precision@50 ↑</th>
              <th className="py-3 px-4 text-right font-medium">Recall@100 ↑</th>
              <th className="py-3 px-4 text-right font-medium">Lead time</th>
            </tr>
          </thead>
          {SPLITS.map((s) => {
            const split = MODELS.map((m) => get(s.key, m.key)).filter((r): r is BacktestRow => !!r)
            const r0 = split[0]
            if (!r0) return null
            const top = Math.max(...split.map((r) => r.prAuc ?? -1))
            return (
              <tbody key={s.key}>
                <tr className="border-b border-border-subtle bg-surface-base text-fg-muted">
                  <td colSpan={8} className="py-2 px-4 text-xs">
                    <span className="text-fg-base font-semibold uppercase tracking-wider">{s.label}</span>
                    {' · '}{r0.nFolds} cutoff{r0.nFolds === 1 ? '' : 's'} · {r0.n.toLocaleString()} rows ·{' '}
                    {r0.nPos.toLocaleString()} {outcome} (base rate {pct(r0.baseRate)})
                  </td>
                </tr>
                {split.map((r) => {
                  const info = MODELS.find((m) => m.key === r.model)
                  const isChamp = r.model === champion
                  return (
                    <tr
                      key={r.model}
                      className={cn(
                        'border-b border-b-border-subtle/60',
                        isChamp ? 'bg-accent/10 border-l-2 border-l-accent' : 'hover:bg-surface-elevated/30'
                      )}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={cn('text-fg-base', isChamp && 'font-semibold')}>{info?.name ?? r.model}</span>
                          {r.model === 'naive' && <Badge>floor</Badge>}
                          {isChamp && <Badge variant="accent">champion</Badge>}
                        </div>
                        {info && <div className="text-xs text-fg-muted mt-1">{info.note}</div>}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <span className={r.prAuc === top ? 'text-stable font-medium' : 'text-fg-muted'}>{f3(r.prAuc)}</span>
                      </td>
                      <td className="py-3 px-4 text-right text-fg-muted">{f3(r.rocAuc)}</td>
                      <td className="py-3 px-4 text-right text-fg-muted">{f3(r.brier)}</td>
                      <td className="py-3 px-4 text-right text-fg-muted">{f3(r.ece)}</td>
                      <td className="py-3 px-4 text-right text-fg-muted">{pct(r.precision50)}</td>
                      <td className="py-3 px-4 text-right text-fg-muted">{pct(r.recall100)}</td>
                      <td className="py-3 px-4 text-right text-fg-muted">{orDash(r.leadTimeQ, (x) => `${x.toFixed(1)}q`)}</td>
                    </tr>
                  )
                })}
              </tbody>
            )
          })}
        </table>

        <div className="border-t border-border-subtle px-4 py-3 text-xs text-fg-muted space-y-1">
          <div>· Rolling origin: each cutoff trains only on labels known by that cutoff and scores the rows at it. Test is the newest usable cutoff, held out; validation is the cutoffs before it (model/runs/{runId}/windows.json).</div>
          <div>· PR-AUC starts at the base rate (a random ranking), not at 0: read it against the naive row.</div>
          <div>· Lead time: mean quarters from a project's first top-100 flag to the slip it was flagged for. With one test cutoff it is {h} quarters by construction.</div>
          <div>· Probabilities rank projects (tiers go by rank); Brier and ECE show they are not calibrated frequencies.</div>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="px-5 py-4">
      <div className="text-xs text-fg-muted font-semibold mb-1.5">{label}</div>
      {children}
    </div>
  )
}
