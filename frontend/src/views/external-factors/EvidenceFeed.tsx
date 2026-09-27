import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useLiveStatus, useSignalFeed } from '@/lib/queries'
import { formatDate, formatDateTime, cn } from '@/lib/formatters'
import type { FeedItem } from '@/contracts/portfolio'

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('en-IN') : 'date unknown')

function SignalCard({ s }: { s: FeedItem }) {
  return (
    <div className="bg-surface-panel px-4 py-3 space-y-1.5 min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] text-fg-dimmed">
        <span className="text-fg-muted font-semibold">{s.source ?? 'source unknown'}</span>
        <span>{day(s.publishedAt)}</span>
        {s.category && (
          <span className="border border-border-default px-1 uppercase tracking-wider">{s.category.replace(/_/g, ' ')}</span>
        )}
        <span className={cn((s.severity ?? 0) >= 2 && 'text-critical font-semibold')}>
          severity {s.severity ?? 'unknown'}
        </span>
      </div>
      <a
        href={s.url}
        target="_blank"
        rel="noreferrer"
        className="block text-xs font-medium leading-snug text-fg-base hover:underline"
      >
        {s.title ?? s.url}
      </a>
      {s.summary && <div className="text-[11px] leading-snug text-fg-muted line-clamp-2">{s.summary}</div>}
      {s.projects.length === 0 ? (
        <div className="font-mono text-[10px] text-fg-dimmed">not linked: ambiguous or weak match to a project</div>
      ) : (
        s.projects.map((p) => (
          <div key={p.key} className="border-l-2 border-border-default pl-2 font-mono text-[10px] text-fg-dimmed space-y-0.5">
            <div className="flex items-center gap-1.5 min-w-0">
              <Badge tier={p.tier} />
              <Link to={`/projects/${p.key}`} className="text-accent hover:underline shrink-0">
                {p.key}
              </Link>
              <span className="truncate text-fg-muted" title={p.name ?? undefined}>{p.name ?? ''}</span>
            </div>
            <div>
              {p.state ?? 'state unknown'}
              {p.linkScore !== null && ` · link ${p.linkScore.toFixed(2)} (${p.method ?? 'match'})`}
              {' · '}
              {p.cufChangePeriod
                ? `report of ${formatDate(p.cufChangePeriod)} then moved the date or cost (${p.leadDays} days later)`
                : 'no later report has changed the date or cost yet'}
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
      title={`External Evidence · News${data ? ` · ${data.total}` : ''}`}
      titleRight={
        <span className="font-mono text-[11px] text-fg-dimmed">
          {lastRun?.finishedAt ? `news scout last ran ${formatDateTime(lastRun.finishedAt)}` : 'news scout has not run yet'}
        </span>
      }
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">loading news evidence...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed space-y-1">
          <div>no news evidence stored yet — not the same as no external trouble</div>
          <div className="text-[10px]">
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
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
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
