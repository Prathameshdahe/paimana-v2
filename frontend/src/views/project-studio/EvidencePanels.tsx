import { Card } from '@/components/ui/Card'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { formatDate, orDash, cn } from '@/lib/formatters'
import { formatQuarter, isLive } from '@/lib/external'
import type { EventRow, ProjectSignals } from '@/contracts/project'

function basename(path: string): string {
  return path.split('/').pop() ?? path
}

/**
 * Issues found in the report remarks (pipeline project_events), each quoted with its document and page. An open one
 * not mentioned within the live window is stale: it shows the quarter it was last known, not 'open'.
 */
export function ExternalEvents({ events, asof }: { events: EventRow[]; asof: string }) {
  const remarksUntil = events.find((e) => e.remarksLastSeen)?.remarksLastSeen

  return (
    <Card
      title={`Issues in the report remarks · ${events.length}`}
      titleRight={
        remarksUntil && (
          <span className="text-xs text-fg-dimmed">remarks read up to {formatDate(remarksUntil)}</span>
        )
      }
    >
      {events.length === 0 ? (
        <div className="px-5 py-6 text-center text-xs text-fg-dimmed">
          no land, clearance, litigation or contractor issue found in the report remarks (free text only through 2023)
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60">
          {events.map((e) => (
            <div key={`${e.category}-${e.eventNo}`} className="px-4 py-3 grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-2">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-fg-base">{e.category.replace(/_/g, ' ')}</span>
                  <span
                    className={cn(
                      'border px-1 py-0.5 text-xs',
                      e.status === 'open' && isLive(e.lastSeen, asof)
                        ? 'border-critical/40 text-critical'
                        : e.status === 'open' ? 'border-dashed border-fg-dimmed/60 text-fg-muted' : 'border-border-default text-fg-dimmed'
                    )}
                    title={e.status === 'open' && !isLive(e.lastSeen, asof) ? 'open when last mentioned; not mentioned since' : undefined}
                  >
                    {e.status === 'open' && !isLive(e.lastSeen, asof)
                      ? `stale · last known ${e.lastSeen ? formatQuarter(e.lastSeen) : 'n/a'}`
                      : (e.status ?? 'status unknown')}
                  </span>
                </div>
                <div className="text-xs text-fg-dimmed">
                  {e.subtype && `${e.subtype} · `}
                  {orDash(e.firstSeen, formatDate)} → {orDash(e.lastSeen, formatDate)}
                  {e.nQuarters !== null && ` · ${e.nQuarters}q`}
                  {e.authority && ` · ${e.authority}`}
                  {e.forestAreaHa !== null && ` · ${e.forestAreaHa} ha`}
                  {e.violation && ' · violation'}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-sm text-fg-base leading-relaxed border-l-2 border-border-default pl-3">
                  &ldquo;{e.evidence ?? 'no remark text'}&rdquo;
                </div>
                <div className="text-xs text-fg-dimmed mt-1 pl-3" title={e.sourceDocId ?? undefined}>
                  {e.sourceDocId ? basename(e.sourceDocId) : 'source unknown'}
                  {e.sourcePage !== null && ` p.${e.sourcePage}`}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

/** News the scout linked to this project; an empty list is "not found yet", never "clear". */
export function LinkedSignals({ data, error }: { data: ProjectSignals | undefined; error: unknown }) {
  const scouted = data?.lastScoutAt

  return (
    <Card
      title={`Linked news · ${data?.items.length ?? 0}`}
      titleRight={
        data && (
          <span className="text-xs text-fg-dimmed">
            {scouted ? `scouted ${new Date(scouted).toLocaleDateString('en-IN')}` : 'never scouted'}
          </span>
        )
      }
      className="h-full"
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="px-5 py-6 text-center text-xs text-fg-dimmed">loading signals...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-6 text-center text-xs text-fg-dimmed space-y-1">
          <div>no linked news yet — not the same as clear</div>
          <div className="text-xs">
            {scouted ? 'the news scout found nothing it could tie to this project' : 'the news scout has not searched this project yet'}
          </div>
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60">
          {data.items.map((s) => (
            <div key={s.id} className="px-4 py-2.5 space-y-1">
              <a href={s.url} target="_blank" rel="noreferrer" className="block text-xs font-medium text-fg-base hover:underline">
                {s.title ?? s.url}
              </a>
              <div className="text-xs text-fg-dimmed">
                {s.source ?? 'source unknown'} · {s.publishedAt ? new Date(s.publishedAt).toLocaleDateString('en-IN') : 'date unknown'}
                {s.category && ` · ${s.category.replace(/_/g, ' ')}`}
                {s.severity !== null && <span className={cn(s.severity >= 2 && 'text-critical')}> · severity {s.severity}</span>}
                {s.linkScore !== null && ` · link ${s.linkScore.toFixed(2)} (${s.method ?? 'match'})`}
              </div>
              <div className="text-xs text-fg-muted">
                {s.cufChangePeriod
                  ? `report of ${formatDate(s.cufChangePeriod)} then pushed the date or revised the cost (${s.leadDays} days after the article)`
                  : 'no later report has changed the date or cost yet'}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
