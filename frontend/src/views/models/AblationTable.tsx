import { InfoTip } from '@/components/ui/Tooltip'
import { cn, formatProb, orDash } from '@/lib/formatters'
import type { AblationRow } from '@/contracts/audit'

// pipeline/gold.py FEATURE_GROUPS, in words
const GROUPS: Record<string, string> = {
  state: 'progress, elapsed time, cost variation, spend vs build, SPI, months to completion, slip so far, revisions, cost size',
  dynamics: 'progress and spend velocity, acceleration, quarters without progress, velocity vs sector median',
  context: 'sector S-curve and output, agency track record, ministry / sector / state',
  freshness: 'reports in the quarter, months since the last report, data quality, report type',
  external: 'report-remark events (land, forest, litigation, contractor, utility, inter-agency), Parivesh forest rules, Bhoomi Rashi land linkage',
}

const f3 = (v: number | null) => orDash(v, (x) => x.toFixed(3))
const pct = (v: number | null) => orDash(v, (x) => formatProb(x, 1))

/** A step's gain over the step before; `points` shows a share as percentage points. */
function Gain({ v, points }: { v: number | null; points?: boolean }) {
  if (v === null) return <span className="text-fg-dimmed">—</span>
  // sign and colour go by the shown (rounded) value, so -0.00016 reads 0.000, not -0.000
  const shown = points ? Math.round(v * 1000) / 10 : Math.round(v * 1000) / 1000
  const text = points ? `${Math.abs(shown).toFixed(1)} pp` : Math.abs(shown).toFixed(3)
  return (
    <span className={cn('font-medium', shown > 0 ? 'text-stable' : shown < 0 ? 'text-critical' : 'text-fg-muted')}>
      {shown > 0 ? '+' : shown < 0 ? '-' : ''}
      {text}
    </span>
  )
}

interface AblationTableProps {
  /** ablation.csv rows of one target, in step order */
  rows: AblationRow[]
  runId: string
}

/** Clause (c): what each feature group adds to LightGBM for one target (the champion run's ablation). */
export function AblationTable({ rows, runId }: AblationTableProps) {
  const r0 = rows[0]
  if (!r0) {
    return (
      <div className="border border-border-subtle bg-surface-panel px-4 py-8 text-center text-xs text-fg-dimmed rounded-xl shadow-card overflow-hidden">
        no ablation rows for this target in model/runs/{runId}/ablation.csv
      </div>
    )
  }

  return (
    <div className="border border-border-subtle bg-surface-panel overflow-x-auto rounded-xl shadow-card">
      <div className="flex items-center gap-1.5 border-b border-border-subtle px-5 py-3 text-sm font-semibold text-fg-base">
        What each feature group adds
        <InfoTip label="About the ablation">
          <p>Clause (c): feature-group ablation, from model/runs/{runId}/ablation.csv.</p>
          <p>
            Validation folds only ({r0.nFolds} cutoffs, {r0.n.toLocaleString()} rows, base rate {pct(r0.baseRate)}). Each
            step retrains LightGBM with one more feature group; Δ is the step minus the step before, so a small or negative
            Δ means the group adds little beyond what the earlier groups already carry.
          </p>
          <p>The last step is the full feature set, the same model as the LightGBM row above.</p>
        </InfoTip>
      </div>
      <table className="w-full text-sm font-mono border-collapse">
        <thead className="font-sans">
          <tr className="border-b border-border-subtle text-xs text-fg-muted bg-surface-elevated/60">
            <th className="py-3 px-4 text-left font-medium">Step · group added</th>
            <th className="py-3 px-4 text-right font-medium">Features</th>
            <th className="py-3 px-4 text-right font-medium">PR-AUC</th>
            <th className="py-3 px-4 text-right font-medium">Δ</th>
            <th className="py-3 px-4 text-right font-medium">Precision@50</th>
            <th className="py-3 px-4 text-right font-medium">Δ</th>
            <th className="py-3 px-4 text-right font-medium">Recall@100</th>
            <th className="py-3 px-4 text-right font-medium">Δ</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle/60">
          {rows.map((r) => {
            const group = r.step.replace(/^\+/, '')
            return (
              <tr key={r.step} className="hover:bg-surface-elevated/30">
                <td className="py-3 px-4 align-top font-sans">
                  <div className="text-fg-base font-medium">{r.step}</div>
                  <div className="text-xs text-fg-muted mt-1 max-w-xl">{GROUPS[group] ?? r.groups}</div>
                </td>
                <td className="py-3 px-4 align-top text-right text-fg-muted">{r.nFeatures}</td>
                <td className="py-3 px-4 align-top text-right text-fg-base">{f3(r.prAuc)}</td>
                <td className="py-3 px-4 align-top text-right"><Gain v={r.prAucGain} /></td>
                <td className="py-3 px-4 align-top text-right text-fg-base">{pct(r.precision50)}</td>
                <td className="py-3 px-4 align-top text-right"><Gain v={r.precision50Gain} points /></td>
                <td className="py-3 px-4 align-top text-right text-fg-base">{pct(r.recall100)}</td>
                <td className="py-3 px-4 align-top text-right"><Gain v={r.recall100Gain} points /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
