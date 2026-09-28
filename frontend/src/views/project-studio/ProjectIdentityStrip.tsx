import { Link } from 'react-router-dom'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatDate, formatINR, formatPct, orDash } from '@/lib/formatters'
import type { MasterRecord, ObservationRecord, ProjectDetail } from '@/contracts/project'

function basename(path: string): string {
  return path.split('/').pop() ?? path
}

/** asof -> model -> gold -> silver -> source document and page: where every number on the page comes from */
function ProvenanceLine({ detail }: { detail: ProjectDetail }) {
  const p = detail.provenance
  return (
    <div className="text-xs text-fg-dimmed flex flex-wrap gap-x-1.5">
      <span>asof {p.asof.slice(0, 7)}</span>·
      <span>model {p.modelVersion ?? 'not scored'}</span>·
      <span>gold {p.goldVersion}</span>·
      <span>silver {p.silverVersion}</span>·
      <span title={p.sourceDocId ?? undefined}>
        source: {p.sourceDocId ? basename(p.sourceDocId) : 'unknown'}
        {p.sourcePage !== null && ` p.${p.sourcePage}`}
        {p.period && ` (${p.periodType ?? 'report'}, ${formatDate(p.period)})`}
      </span>
    </div>
  )
}

export function ProjectIdentityStrip({ detail }: { detail: ProjectDetail }) {
  const m: MasterRecord = detail.master ?? {}
  const o: ObservationRecord = detail.latest ?? {}
  const codes = [o.projectCode, ...(m.codesSeen ?? '').split(';')]
    .filter((c, i, all): c is string => !!c && all.indexOf(c) === i)

  return (
    <div className="space-y-2">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-fg-dimmed">
        <Link to="/command" className="hover:text-fg-muted transition-colors">
          Command
        </Link>
        <span>/</span>
        <span className="text-fg-muted">{detail.key}</span>
      </div>

      {/* Identity bar — single horizontal strip */}
      <div className="border border-border-subtle bg-surface-panel rounded-xl shadow-card overflow-hidden">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 px-4 py-3">
          <div className="space-y-1 min-w-0">
            <div className="flex flex-wrap items-center gap-3 font-mono text-xs">
              <span className="text-fg-base font-medium">{detail.key}</span>
              <Badge tier={detail.scores ? detail.scores.tier : undefined} />
              {detail.scores?.stagnationOverride && <StalledBadge quarters={detail.scores.stagnationQuarters} />}
              <span className="text-fg-dimmed">{m.sector ?? 'sector unknown'}</span>
              {codes.length > 0 && <span className="text-fg-dimmed">codes {codes.join(' · ')}</span>}
            </div>

            <h1 className="text-base font-medium text-fg-base">{m.projectName ?? detail.key}</h1>

            <div className="flex flex-wrap items-center gap-x-4 text-xs text-fg-dimmed">
              <span>{m.ministry ?? 'ministry unknown'}</span>
              <span className="text-border-strong">│</span>
              <span>{m.agency ?? 'agency unknown'}</span>
              <span className="text-border-strong">│</span>
              <span>{m.state ?? 'state unknown'}</span>
              {m.sanctionDate && (
                <>
                  <span className="text-border-strong">│</span>
                  <span>sanctioned {formatDate(m.sanctionDate)}</span>
                </>
              )}
            </div>

            <ProvenanceLine detail={detail} />
          </div>

          {/* Key figures from the latest report — inline, right-aligned */}
          <div className="flex items-center gap-5 font-mono text-xs shrink-0">
            <div className="text-right">
              <div className="text-xs text-fg-dimmed">Anticipated cost</div>
              <MonoFigure size="lg">{orDash(o.anticipatedCostCr, formatINR)}</MonoFigure>
              <div className="text-xs text-fg-dimmed">orig {orDash(o.originalCostCr, formatINR)}</div>
            </div>
            <div className="w-px h-8 bg-border-subtle" />
            <div className="text-right">
              <div className="text-xs text-fg-dimmed">Progress</div>
              <MonoFigure size="lg">{orDash(o.physicalProgressPct, (v) => formatPct(v, 0))}</MonoFigure>
              <div className="text-xs text-fg-dimmed">spent {orDash(o.expenditureCr, formatINR)}</div>
            </div>
            <div className="w-px h-8 bg-border-subtle" />
            <div className="text-right">
              <div className="text-xs text-fg-dimmed">Completion</div>
              <MonoFigure size="lg">{orDash(o.anticipatedCompletion, formatDate)}</MonoFigure>
              <div className="text-xs text-fg-dimmed">scheduled {orDash(o.scheduledCompletion, formatDate)}</div>
            </div>
          </div>
        </div>

        {detail.review && (
          <div className="border-t border-warning/30 bg-warning/5 px-4 py-1.5 text-xs text-warning">
            Identity under review: {detail.review.note}
          </div>
        )}
      </div>
    </div>
  )
}
