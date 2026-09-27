import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card } from '@/components/ui/Card'
import { featureLabel } from '@/lib/featureLabels'
import { cn, formatDate, formatDateTime, formatProb, orDash } from '@/lib/formatters'
import type { CalibrationBin, LiveAccuracy, RegistryDecision, RegistryEntry, ShapSummaryRow } from '@/contracts/audit'

const AXIS_TICK = { fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', fill: 'hsl(var(--color-fg-dimmed))' }
/** fixed per model, so a target without one model never repaints the other */
const MODEL_COLOR: Record<string, string> = { lightgbm: '#2a78d6', logreg: '#eb6834', rule: '#1baf7a' }
const pct = (v: number | null) => orDash(v, (x) => formatProb(x, 1))
const f3 = (v: number | null) => orDash(v, (x) => x.toFixed(3))
/** "ML-20260927-174106/lightgbm/y_any_h2" -> "lightgbm · ML-20260927-174106" */
const entry = (id: string | null) => {
  if (!id) return '—'
  const [run, model] = id.split('/')
  return `${model ?? id} · ${run}`
}

function CalTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: CalibrationBin }> }) {
  const b = payload?.[0]?.payload
  if (!active || !b) return null
  return (
    <div className="border border-border-default bg-surface-panel px-3 py-2 font-mono text-[11px] text-fg-base shadow-lg">
      <div className="font-semibold">{b.model} · bin {b.bin}</div>
      <div>predicted {pct(b.meanPred)} · observed {pct(b.obsRate)}</div>
      <div className="text-fg-dimmed">n {b.n.toLocaleString()}</div>
    </div>
  )
}

/** Predicted vs observed slip rate per probability bin (calibration.csv, pooled validation folds). */
export function CalibrationChart({ bins, runId }: { bins: CalibrationBin[]; runId: string }) {
  const models = Object.keys(MODEL_COLOR).filter((m) => bins.some((b) => b.model === m))
  return (
    <Card title={`Calibration · model/runs/${runId}/calibration.csv`}>
      {models.length === 0 ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">no calibration bins for this target</div>
      ) : (
        <div className="h-[320px] px-2 pt-3">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 4 }}>
              <CartesianGrid stroke="hsl(var(--color-border-subtle))" strokeDasharray="2 4" />
              <XAxis
                type="number"
                dataKey="meanPred"
                domain={[0, 1]}
                ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
                tickFormatter={(v: number) => formatProb(v)}
                tick={AXIS_TICK}
                label={{ value: 'predicted probability (bin mean)', position: 'insideBottom', offset: -12, fontSize: 10, fill: 'hsl(var(--color-fg-muted))' }}
              />
              <YAxis
                type="number"
                dataKey="obsRate"
                domain={[0, 1]}
                ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
                tickFormatter={(v: number) => formatProb(v)}
                tick={AXIS_TICK}
                label={{ value: 'observed rate', angle: -90, position: 'insideLeft', fontSize: 10, fill: 'hsl(var(--color-fg-muted))' }}
              />
              <ReferenceLine
                segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                stroke="hsl(var(--color-border-strong))"
                strokeDasharray="4 4"
                ifOverflow="hidden"
              />
              <Tooltip content={<CalTooltip />} />
              <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: 11, fontFamily: 'IBM Plex Mono, monospace' }} />
              {models.map((m) => (
                <Scatter
                  key={m}
                  name={m}
                  data={bins.filter((b) => b.model === m).sort((a, b) => a.meanPred - b.meanPred)}
                  fill={MODEL_COLOR[m]}
                  line={{ stroke: MODEL_COLOR[m], strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
        dashed diagonal: perfectly calibrated. Tiers go by rank, so the probabilities are read as a ranking.
      </div>
    </Card>
  )
}

/** Mean |SHAP| of the champion's top 20 features (shap_summary.csv; any slip, 2 quarters). */
export function ShapSummary({ rows, runId }: { rows: ShapSummaryRow[]; runId: string }) {
  const data = rows.map((r) => ({ ...r, label: featureLabel(r.feature) }))
  return (
    <Card title={`What the model leans on · any slip, 2q · ${runId}`}>
      {data.length === 0 ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">no shap_summary.csv in this run</div>
      ) : (
        <div className="px-2 pt-3" style={{ height: 40 + data.length * 22 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 8 }} barCategoryGap={4}>
              <CartesianGrid stroke="hsl(var(--color-border-subtle))" strokeDasharray="2 4" horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK} tickFormatter={(v: number) => v.toFixed(2)} />
              <YAxis type="category" dataKey="label" width={250} tick={{ ...AXIS_TICK, fill: 'hsl(var(--color-fg-muted))' }} interval={0} />
              <Tooltip
                cursor={{ fill: 'hsl(var(--color-surface-elevated))' }}
                formatter={(v: number) => [v.toFixed(3), 'mean |SHAP| (log-odds)']}
                labelFormatter={(l: string, p) => `${l} · group ${(p?.[0]?.payload as ShapSummaryRow | undefined)?.group ?? '?'}`}
                contentStyle={{ fontSize: 11, fontFamily: 'IBM Plex Mono, monospace' }}
              />
              <Bar dataKey="meanAbsShap" fill="#2a78d6" radius={[0, 4, 4, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
        mean absolute TreeSHAP contribution in log-odds over the validation rows: how much a feature moves scores, not which way
      </div>
    </Card>
  )
}

/** Champion / challenger decisions with their reasons, and the registered entries for one target. */
export function RegistryHistory({ decisions, entries }: { decisions: RegistryDecision[]; entries: RegistryEntry[] }) {
  const th = 'py-2 px-3 font-medium'
  return (
    <Card title={`Registry history · ${decisions.length} decisions`}>
      {decisions.length === 0 ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">no decision recorded for this target</div>
      ) : (
        <div className="overflow-x-auto max-h-[360px]">
          <table className="w-full text-[12px] font-mono border-collapse">
            <thead className="sticky top-0 bg-surface-base">
              <tr className="border-b border-border-default text-fg-muted text-left">
                <th className={th}>When</th>
                <th className={th}>Challenger</th>
                <th className={th}>Champion before</th>
                <th className={th}>Decision</th>
                <th className={th}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {[...decisions].reverse().map((d, i) => (
                <tr key={`${d.at}-${d.challenger}-${i}`} className="border-b border-border-subtle align-top">
                  <td className="py-1.5 px-3 whitespace-nowrap text-fg-dimmed">{formatDateTime(d.at)}</td>
                  <td className="py-1.5 px-3 whitespace-nowrap">{entry(d.challenger)}</td>
                  <td className="py-1.5 px-3 whitespace-nowrap text-fg-muted">{entry(d.championBefore)}</td>
                  <td className={cn('py-1.5 px-3 font-semibold', d.decision === 'promoted' ? 'text-stable' : 'text-fg-muted')}>
                    {d.decision}
                  </td>
                  <td className="py-1.5 px-3 text-fg-muted">{d.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {entries.length > 0 && (
        <div className="overflow-x-auto border-t border-border-subtle">
          <table className="w-full text-[12px] font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-fg-muted bg-surface-base">
                <th className={cn(th, 'text-left')}>Registered entry</th>
                <th className={cn(th, 'text-left')}>Registered</th>
                <th className={cn(th, 'text-right')}>Val PR-AUC</th>
                <th className={cn(th, 'text-right')}>Val ECE</th>
                <th className={cn(th, 'text-right')}>Test PR-AUC</th>
              </tr>
            </thead>
            <tbody>
              {[...entries].reverse().map((e) => (
                <tr key={e.entryId} className={cn('border-b border-border-subtle', e.champion && 'bg-stable/5')}>
                  <td className="py-1.5 px-3 whitespace-nowrap">
                    {entry(e.entryId)}
                    {e.champion && <span className="ml-2 text-stable font-semibold">champion</span>}
                  </td>
                  <td className="py-1.5 px-3 text-fg-dimmed whitespace-nowrap">{e.createdAt ? formatDateTime(e.createdAt) : '—'}</td>
                  <td className="py-1.5 px-3 text-right tabular-nums">{f3(e.prAuc)}</td>
                  <td className="py-1.5 px-3 text-right tabular-nums">{f3(e.ece)}</td>
                  <td className="py-1.5 px-3 text-right tabular-nums">{f3(e.testPrAuc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** the report whose data realises an asof's 2-quarter outcome */
function horizonReport(asof: string, quarters = 2): string {
  const d = new Date(asof)
  d.setMonth(d.getMonth() + 3 * quarters)
  return formatDate(d.toISOString())
}

/** Live accuracy of logged predictions (gold/prediction_log.parquet); nothing is estimated before outcomes land. */
export function LiveAccuracyCard({ live }: { live: LiveAccuracy }) {
  const stat = (label: string, value: string) => (
    <div className="bg-surface-panel px-4 py-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-fg-dimmed">{label}</div>
      <div className="font-mono text-lg font-semibold text-fg-base tabular-nums">{value}</div>
    </div>
  )
  return (
    <Card title="Live accuracy · logged predictions vs what happened">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-border-subtle border-b border-border-subtle">
        {stat('logged', live.nLogged.toLocaleString())}
        {stat('realised', live.nRealised.toLocaleString())}
        {stat('precision, critical + high', pct(live.precisionCriticalHigh))}
        {stat('base rate', pct(live.baseRate))}
        {stat('PR-AUC', f3(live.prAuc))}
      </div>
      <div className="px-5 py-3 space-y-1">
        {live.nRealised === 0 && (
          <div className="text-sm text-fg-base">
            No prediction has reached its horizon yet
            {live.firstAsof &&
              `: the earliest is logged at ${formatDate(live.firstAsof)}, so the first realised outcomes arrive with the ${horizonReport(live.firstAsof)} report`}
            .
          </div>
        )}
        <div className="font-mono text-[10px] text-fg-dimmed">{live.note}</div>
      </div>
    </Card>
  )
}
