import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatDate, formatINR, formatPct, orDash } from '@/lib/formatters'
import type { MasterRecord, ObservationRecord, ProjectDetail } from '@/contracts/project'

function basename(path: string): string {
  return path.split('/').pop() ?? path
}

/** where the page's facts come from: the report, its document and page (the public gets none of these) */
function SourceLine({ detail }: { detail: ProjectDetail }) {
  const p = detail.provenance
  if (!p.period && !p.sourceDocId) return null
  return (
    <div className="text-xs text-fg-dimmed" title={p.sourceDocId ?? undefined}>
      From the {p.period ? `${formatDate(p.period)} ` : ''}report
      {p.sourceDocId && <> · {basename(p.sourceDocId)}{p.sourcePage !== null && `, p.${p.sourcePage}`}</>}
    </div>
  )
}

/**
 * The developer's provenance: as-of, model, gold and silver versions and the source document — where every number
 * on the Model detail tab comes from.
 */
export function ProvenanceLine({ detail }: { detail: ProjectDetail }) {
  const p = detail.provenance
  return (
    <div className="flex flex-wrap gap-x-1.5 text-xs text-fg-dimmed">
      <span>asof {p.asof.slice(0, 7)}</span>·
      <span>model {p.modelVersion ?? 'not scored'}</span>·
      <span>gold {p.goldVersion ?? '—'}</span>·
      <span>silver {p.silverVersion ?? '—'}</span>·
      <span title={p.sourceDocId ?? undefined}>
        source: {p.sourceDocId ? basename(p.sourceDocId) : 'unknown'}
        {p.sourcePage !== null && ` p.${p.sourcePage}`}
        {p.period && ` (${p.periodType ?? 'report'}, ${formatDate(p.period)})`}
      </span>
    </div>
  )
}

/**
 * The project page's header: back to the list, key, tier and stalled badges, the name, who runs it and where, and
 * the three report facts that frame it (anticipated cost, progress, expected completion). An identity under review
 * says so under it.
 */
export function ProjectIdentityStrip({ detail }: { detail: ProjectDetail }) {
  const m: MasterRecord = detail.master ?? {}
  const o: ObservationRecord = detail.latest ?? {}
  const who = [m.ministry, m.agency, m.state, m.sanctionDate ? `sanctioned ${formatDate(m.sanctionDate)}` : null].filter(Boolean)

  return (
    <header className="space-y-3">
      <Link to="/command" className="inline-flex items-center gap-1 rounded text-xs text-fg-dimmed transition-colors hover:text-fg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
        <ArrowLeft className="size-3.5" aria-hidden="true" /> All projects
      </Link>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-fg-dimmed">{detail.key}</span>
            {detail.scores && <Badge tier={detail.scores.tier} />}
            {detail.scores?.stagnationOverride && <StalledBadge quarters={detail.scores.stagnationQuarters} />}
          </div>
          <h1 className="max-w-4xl text-2xl font-semibold leading-tight tracking-tight text-fg-base">{m.projectName ?? detail.key}</h1>
          {who.length > 0 && <div className="text-sm text-fg-muted">{who.join(' · ')}</div>}
          <SourceLine detail={detail} />
        </div>

        <dl className="flex shrink-0 items-end gap-5">
          <div className="text-right">
            <dt className="text-xs text-fg-dimmed">Anticipated cost</dt>
            <dd><MonoFigure size="xl">{orDash(o.anticipatedCostCr, formatINR)}</MonoFigure></dd>
            <dd className="text-xs text-fg-dimmed">sanctioned {orDash(o.originalCostCr, formatINR)}</dd>
          </div>
          <div className="h-10 w-px bg-border-subtle" aria-hidden="true" />
          <div className="text-right">
            <dt className="text-xs text-fg-dimmed">Built</dt>
            <dd><MonoFigure size="xl">{orDash(o.physicalProgressPct, (v) => formatPct(v, 0))}</MonoFigure></dd>
            <dd className="text-xs text-fg-dimmed">spent {orDash(o.expenditureCr, formatINR)}</dd>
          </div>
          <div className="h-10 w-px bg-border-subtle" aria-hidden="true" />
          <div className="text-right">
            <dt className="text-xs text-fg-dimmed">Expected completion</dt>
            <dd><MonoFigure size="xl">{orDash(o.anticipatedCompletion, formatDate)}</MonoFigure></dd>
            <dd className="text-xs text-fg-dimmed">first planned {orDash(o.scheduledCompletion, formatDate)}</dd>
          </div>
        </dl>
      </div>

      {detail.review && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-2 text-xs text-warning">
          Identity under review: {detail.review.note}
        </div>
      )}
    </header>
  )
}
