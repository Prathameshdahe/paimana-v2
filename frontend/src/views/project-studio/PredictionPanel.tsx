import { MonoFigure } from '@/components/ui/MonoFigure'
import { TIER_LABEL, TIER_SENTIMENT, tierKey } from '@/lib/riskPalette'
import { formatPct, formatProb, orDash, cn } from '@/lib/formatters'
import type { ProjectDetail } from '@/contracts/project'

const NOT_SCORED = 'No completion date in reports — schedule not scored'

function Row({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs font-mono" title={hint}>
      <span className="text-fg-muted">{label}</span>
      <span className={cn('tabular-nums', strong ? 'text-fg-base font-semibold' : 'text-fg-base')}>{value}</span>
    </div>
  )
}

function interval(p05: number | null, p50: number | null, p95: number | null, f: (v: number) => string) {
  return { mid: orDash(p50, f), band: p05 === null || p95 === null ? 'interval —' : `90%: ${f(p05)} – ${f(p95)}` }
}

/**
 * AI prediction panel (guide §5.1): tier by rank, the four probabilities, and
 * the predicted slip and cost revision over the next 2 quarters with their
 * 5th–95th percentile interval. An untiered project has no date-based scores,
 * which is said in words rather than shown as zeros.
 */
export function PredictionPanel({ detail }: { detail: ProjectDetail }) {
  const s = detail.scores

  if (!s) {
    return (
      <div className="border border-border-subtle bg-surface-panel rounded-sm px-4 py-6 font-mono text-xs text-fg-dimmed text-center">
        Not in the current scored portfolio (asof {detail.provenance.asof})
        {detail.master?.lastStatus && <> — last status: {detail.master.lastStatus}</>}.
      </div>
    )
  }

  const t = tierKey(s.tier)
  const untiered = t === 'untiered'
  const slip = interval(s.monthsP05, s.monthsP50, s.monthsP95, (v) => `${v.toFixed(0)} mo`)
  const cost = interval(s.costPctP05, s.costPctP50, s.costPctP95, (v) => formatPct(v, 1))

  return (
    <div className="border border-border-subtle bg-surface-panel h-full rounded-sm">
      <div className="flex flex-col divide-y divide-border-subtle h-full">
        {/* Tier */}
        <div className="px-4 py-3 space-y-1.5">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted">AI Prediction · next 2 quarters</div>
          {untiered ? (
            <div className="font-mono text-sm text-fg-muted border-l-2 border-border-strong pl-3 py-1">{NOT_SCORED}</div>
          ) : (
            <div className="flex items-baseline gap-3">
              <MonoFigure size="3xl" sentiment={TIER_SENTIMENT[t]}>
                {TIER_LABEL[t]}
              </MonoFigure>
              <span className="font-mono text-xs text-fg-muted">
                {orDash(s.tierRankPct, (v) => `top ${formatPct(v * 100, v < 0.01 ? 1 : 0)}`)} by P(slip, 2q)
              </span>
            </div>
          )}
          {s.stagnationOverride && (
            <div className="font-mono text-[11px] text-warning">
              tier raised by the stagnation rule ({orDash(s.stagnationQuarters, (v) => v.toFixed(0))} quarters without
              progress; by rank alone: {s.tierByRank ?? 'untiered'})
            </div>
          )}
        </div>

        {/* Probabilities */}
        <div className="px-4 py-3 space-y-1.5">
          {untiered ? (
            <Row label="P(date push, 2q) · P(slip, 2q / 4q)" value="not scored" hint={NOT_SCORED} />
          ) : (
            <>
              <Row label="P(date push, 2q)" value={orDash(s.pDatePush2q, formatProb)} strong />
              <Row
                label="P(date push or cost revision)"
                value={`${orDash(s.pAny2q, formatProb)} (2q) · ${orDash(s.pAny4q, formatProb)} (4q)`}
              />
            </>
          )}
          <Row label="P(cost revision, 2q)" value={orDash(s.pCostRev2q, formatProb)} strong />
        </div>

        {/* Slip months */}
        <div className="px-4 py-3 space-y-1">
          <div className="text-xs font-mono text-fg-muted">Expected slip, next 2 quarters (p50)</div>
          {untiered ? (
            <div className="font-mono text-xs text-fg-dimmed">{NOT_SCORED}</div>
          ) : (
            <div className="flex items-baseline gap-3">
              <MonoFigure size="2xl" sentiment="warning">{slip.mid}</MonoFigure>
              <span className="font-mono text-xs text-fg-muted">{slip.band}</span>
            </div>
          )}
        </div>

        {/* Cost % */}
        <div className="px-4 py-3 space-y-1">
          <div className="text-xs font-mono text-fg-muted">Expected cost revision, next 2 quarters (p50)</div>
          <div className="flex items-baseline gap-3">
            <MonoFigure size="2xl" sentiment="critical">{cost.mid}</MonoFigure>
            <span className="font-mono text-xs text-fg-muted">{cost.band}</span>
          </div>
        </div>

        <div className="px-4 py-2 font-mono text-[10px] text-fg-dimmed leading-relaxed">
          Probabilities rank projects against each other (tiers go by rank); they are not calibrated frequencies.
          Intervals are the 5th–95th percentile of LightGBM quantile models.
        </div>
      </div>
    </div>
  )
}
