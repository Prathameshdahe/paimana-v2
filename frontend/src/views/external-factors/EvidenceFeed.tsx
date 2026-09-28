import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useLiveStatus, useSignalFeed } from '@/lib/queries'
import { formatDate, formatDateTime, cn } from '@/lib/formatters'
import { EVENT_CATEGORY, categoryLabel } from '@/lib/riskPalette'
import type { FeedItem } from '@/contracts/portfolio'

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('en-IN') : 'date unknown')

export function SignalCard({ s }: { s: FeedItem }) {
  const panel = useProjectPanel()
  const cat = s.category ? EVENT_CATEGORY[s.category] : undefined
  const sev = s.severity ?? 0
  return (
    <div className="min-w-0 space-y-2 bg-surface-panel px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-dimmed">
        <span className="font-medium text-fg-muted">{s.source ?? 'source unknown'}</span>
        <span>{day(s.publishedAt)}</span>
        {s.category && (
          <span className="flex items-center gap-1 bg-surface-elevated px-2 py-0.5 text-fg-muted">
            <span className="size-2 rounded-full" style={{ background: cat?.color ?? '#9a968c' }} />
            {categoryLabel(s.category)}
          </span>
        )}
        <Badge variant={sev >= 3 ? 'critical' : sev >= 2 ? 'warning' : 'muted'} className="ml-auto">
          severity {s.severity ?? '?'}
        </Badge>
      </div>
      <a href={s.url} target="_blank" rel="noreferrer" className="block text-sm font-medium leading-snug text-fg-base hover:underline">
        {s.title ?? s.url}
      </a>
      {s.summary && <div className="text-xs leading-snug text-fg-muted line-clamp-2">{s.summary}</div>}
      {s.projects.length === 0 ? (
        <div className="text-xs text-fg-dimmed">not linked: ambiguous or weak match to a project</div>
      ) : (
        s.projects.map((p) => (
          <div key={p.key} className="space-y-1 rounded-lg bg-surface-elevated/70 px-3 py-2 text-xs text-fg-dimmed">
            <div className="flex min-w-0 items-center gap-1.5">
              <Badge tier={p.tier} />
              <button onClick={() => panel.open(p.key)} className="shrink-0 text-accent hover:underline">
                {p.key}
              </button>
              <span className="truncate text-fg-muted" title={p.name ?? undefined}>{p.name ?? ''}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2">
              <span>{p.state ?? 'state unknown'}</span>
              {p.linkScore !== null && (
                <span title={`matched by ${p.method ?? 'match'}`}>· link {p.linkScore.toFixed(2)}</span>
              )}
              {p.cufChangePeriod ? (
                <span
                  className=" bg-warning/10 px-2 py-0.5 font-medium text-warning"
                  title={`news ${day(s.publishedAt)}, then the report of ${formatDate(p.cufChangePeriod)} pushed the date or revised the cost`}
                >
                  report change {p.leadDays} days later
                </span>
              ) : (
                <span>· no later report change yet</span>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  )
}

/** News the scout stored (/api/signals/feed), one page at a time; an empty feed is "not searched or nothing found", never "clear". */
export function EvidenceFeed() {
  const [page, setPage] = useState(1)
  const { data, error, isFetching } = useSignalFeed(page)
  const scout = useLiveStatus().data?.scout
  const lastRun = scout?.lastRun
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1

  return (
    <Card
      title={<>News evidence <span className="font-normal text-fg-dimmed">{data ? data.total : ''}</span></>}
      info={lastRun?.finishedAt ? `The news scout last ran ${formatDateTime(lastRun.finishedAt)}.` : 'The news scout has not run yet.'}
      titleRight={
        <Link to="/radar" className="text-accent hover:underline">
          Filter and map on the Radar →
        </Link>
      }
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="px-5 py-8 text-center text-xs text-fg-dimmed">loading news evidence...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-dimmed space-y-1">
          <div>no news evidence stored yet — not the same as no external trouble</div>
          <div className="text-xs">
            {lastRun
              ? 'the news scout ran but found nothing it could store'
              : 'the news scout (Google News and PIB) has not run on this server: it runs every 24 hours, first 10 minutes after the backend starts, when LIVE_JOBS is on'}
          </div>
        </div>
      ) : (
        <div
          className={cn(
            'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border-subtle transition-opacity',
            isFetching && 'opacity-60'
          )}
        >
          {data.items.map((s) => (
            <SignalCard key={s.id} s={s} />
          ))}
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed">
          <span>
            page {page} of {pages}
          </span>
          <span className="flex gap-2">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Prev
            </Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </span>
        </div>
      )}
    </Card>
  )
}
