import type { ReactNode } from 'react'
import { Download, FileSearch, Inbox, Newspaper, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { InfoTip } from '@/components/ui/Tooltip'
import { useLiveStatus, useWatchNow } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { formatDateTime, cn } from '@/lib/formatters'
import type { LiveJob } from '@/contracts/portfolio'

const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso) : 'never')

function lastAndNext(job: LiveJob, last: string | null | undefined) {
  if (job.running) return 'running now'
  return `${when(last)}${job.nextDue ? ` · next ${formatDateTime(job.nextDue)}` : ''}`
}

/**
 * The "Live" indicator from /api/live/status: last report check, last news
 * scout, inbox files waiting. Officials see it, IPMD analysts can run the inbox watcher now
 * (lib/auth/access.ts).
 */
export function LiveStatus() {
  const { role } = useRole()
  return can(role, 'canSeeLive') ? <Strip canRun={can(role, 'canRunJobs')} /> : null
}

function Item({ icon: Icon, label, hint, children }: { icon: LucideIcon; label: string; hint?: string; children: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5" title={hint}>
      <Icon className="size-3.5 text-fg-dimmed" />
      <span className="text-fg-dimmed">{label}</span>
      <span className="text-fg-base">{children}</span>
    </span>
  )
}

function Strip({ canRun }: { canRun: boolean }) {
  const { data, error } = useLiveStatus()
  const watch = useWatchNow()

  const state = error
    ? { label: 'Offline', text: 'text-critical', dot: 'bg-critical' }
    : !data
      ? { label: 'Live …', text: 'text-fg-dimmed', dot: 'bg-fg-dimmed' }
      : data.enabled
        ? { label: 'Live', text: 'text-stable', dot: 'bg-stable animate-pulse' }
        : { label: 'Live jobs off', text: 'text-warning', dot: 'bg-warning' }
  const ingest = data?.watch.lastRun

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-border-subtle bg-surface-panel px-4 py-2.5 text-xs text-fg-muted shadow-card animate-card-in">
      <span className={cn('flex items-center gap-1.5 bg-surface-elevated px-2.5 py-1 font-semibold', state.text)}>
        <span className={cn('inline-block h-2 w-2 rounded-full', state.dot)} />
        {state.label}
        {data && !data.enabled && (
          <InfoTip label="About live jobs">The background loops are off (LIVE_JOBS=0); jobs still start from the API.</InfoTip>
        )}
      </span>

      {error ? (
        <span className="text-fg-dimmed">status unavailable — backend not reachable</span>
      ) : (
        data && (
          <>
            <Item icon={FileSearch} label="Report check" hint="the watcher looks for new reports in dataset/raw/inbox/">
              {lastAndNext(data.watch, data.watch.lastTick ?? ingest?.finishedAt)}
            </Item>
            <Item icon={Download} label="Last ingest">
              <span className={cn(ingest?.status === 'error' && 'text-critical')}>
                {ingest ? `${ingest.status ?? 'unknown'} ${when(ingest.finishedAt)}` : 'none yet'}
              </span>
            </Item>
            <Item icon={Newspaper} label="News scout">
              {lastAndNext(data.scout, data.scout.lastRun?.finishedAt ?? data.scout.lastTick)}
            </Item>
            <Item icon={Inbox} label="Inbox">
              <span className={cn(data.inboxPending ? 'text-warning font-semibold' : '')}>{data.inboxPending} pending</span>
            </Item>
          </>
        )
      )}

      {canRun && (
        <Button
          size="sm"
          className="ml-auto"
          disabled={!data || watch.isPending || data.watch.running}
          onClick={() => watch.mutate()}
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
