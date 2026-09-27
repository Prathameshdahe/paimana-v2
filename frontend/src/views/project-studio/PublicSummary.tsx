import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { TIER_LABEL, TIER_SENTIMENT, tierKey } from '@/lib/riskPalette'
import { formatDate, formatINR, orDash } from '@/lib/formatters'
import type { ProjectDetail } from '@/contracts/project'

/**
 * The public project summary (no drivers, intervals or model internals): risk tier, progress, cost,
 * completion and the top risks in plain words (backend topRisksPlain).
 */
export function PublicSummary({ detail }: { detail: ProjectDetail }) {
  const o = detail.latest ?? {}
  const t = tierKey(detail.scores?.tier ?? null)
  const progress = o.physicalProgressPct ?? null

  return (
    <div className="h-full space-y-5 border border-border-subtle bg-surface-panel px-5 py-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-widest text-fg-muted">Delay risk</div>
        {t === 'untiered' ? (
          <div className="mt-1 text-sm text-fg-muted">Not rated — the reports give no completion date.</div>
        ) : (
          <MonoFigure size="3xl" sentiment={TIER_SENTIMENT[t]}>
            {TIER_LABEL[t]}
          </MonoFigure>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-fg-muted">Work done</span>
          <span className="font-mono font-semibold tabular-nums text-fg-base">{orDash(progress, (v) => `${v.toFixed(0)}%`)}</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-surface-elevated">
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-700"
            style={{ width: `${Math.min(100, Math.max(0, progress ?? 0))}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-fg-muted">Cost</div>
          <div className="font-mono font-semibold tabular-nums text-fg-base">{orDash(o.anticipatedCostCr, formatINR)}</div>
        </div>
        <div>
          <div className="text-fg-muted">Expected completion</div>
          <div className="font-mono font-semibold tabular-nums text-fg-base">{orDash(o.anticipatedCompletion, formatDate)}</div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-widest text-fg-muted">Top risks</div>
        {detail.topRisksPlain.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-stable">
            <CheckCircle2 className="size-4 shrink-0" /> No risk flagged in the latest reports.
          </div>
        ) : (
          <ul className="space-y-2">
            {detail.topRisksPlain.map((r) => (
              <li key={r} className="flex items-start gap-2 text-sm text-fg-base">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                {r}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
