import { Button } from '@/components/ui/Button'
import { useLiveStatus, useWatchNow } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { formatDateTime, cn } from '@/lib/formatters'
import type { LiveJob } from '@/contracts/portfolio'

const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso) : 'never')

function lastAndNext(job: LiveJob, last: string | null | undefined) {
  if (job.running) return 'running now'
  return `${when(last)}${job.nextDue ? ` · next ${formatDateTime(job.nextDue)}` : ''}`
}

/**
 * The "Live" indicator from /api/live/status: last report check, last news
 * scout, inbox files waiting. IPMD analysts can run the inbox watcher now.
 */
export function LiveStatus() {
  const { role } = useRole()
  const { data, error } = useLiveStatus()
  const watch = useWatchNow()

  const state = error
    ? { label: 'OFFLINE', text: 'text-critical', dot: 'bg-critical' }
    : !data
      ? { label: 'LIVE …', text: 'text-fg-dimmed', dot: 'bg-fg-dimmed' }
      : data.enabled
        ? { label: 'LIVE', text: 'text-stable', dot: 'bg-stable animate-pulse' }
        : { label: 'LIVE JOBS OFF', text: 'text-warning', dot: 'bg-warning' }
  const ingest = data?.watch.lastRun

  return (
    <div className="border border-border-subtle bg-surface-panel px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-1.5 font-mono text-[11px] text-fg-muted">
      <span className={cn('flex items-center gap-1.5 font-semibold tracking-widest', state.text)}>
        <span className={cn('inline-block h-2 w-2 rounded-full', state.dot)} />
        {state.label}
      </span>

      {error ? (
        <span className="text-fg-dimmed">status unavailable — backend not reachable</span>
      ) : (
        data && (
          <>
            <span title="the watcher looks for new reports in dataset/raw/inbox/">
              report check{' '}
              <span className="text-fg-base">{lastAndNext(data.watch, data.watch.lastTick ?? ingest?.finishedAt)}</span>
            </span>
            <span>
              last ingest{' '}
              <span className={cn(ingest?.status === 'error' ? 'text-critical' : 'text-fg-base')}>
                {ingest ? `${ingest.status ?? 'unknown'} ${when(ingest.finishedAt)}` : 'none yet'}
              </span>
            </span>
            <span>
              news scout{' '}
              <span className="text-fg-base">
                {lastAndNext(data.scout, data.scout.lastRun?.finishedAt ?? data.scout.lastTick)}
              </span>
            </span>
            <span>
              inbox <span className={cn(data.inboxPending ? 'text-warning font-semibold' : 'text-fg-base')}>{data.inboxPending}</span> pending
            </span>
            {!data.enabled && (
              <span className="text-fg-dimmed">loops off (LIVE_JOBS=0); jobs still start from the API</span>
            )}
          </>
        )
      )}

      {role === 'ipmd_analyst' && (
        <Button
          size="sm"
          className="ml-auto"
          disabled={!data || watch.isPending || data.watch.running}
          onClick={() => watch.mutate(role)}
        >
          {watch.isPending ? 'Checking…' : 'Check inbox now'}
        </Button>
      )}

      {(data?.watch.lastError || data?.scout.lastError) && (
        <span className="w-full text-critical">
          {data.watch.lastError && `watcher: ${data.watch.lastError}`}
          {data.watch.lastError && data.scout.lastError && ' · '}
          {data.scout.lastError && `scout: ${data.scout.lastError}`}
        </span>
      )}
      {watch.data && <span className="w-full text-fg-dimmed">{watch.data.detail}</span>}
      {watch.isError && <span className="w-full text-critical">check failed: {String(watch.error)}</span>}
    </div>
  )
}
