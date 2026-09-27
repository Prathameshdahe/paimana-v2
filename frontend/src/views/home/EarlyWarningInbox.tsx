import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAckAlert, useAlerts } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { formatDate } from '@/lib/formatters'

const PAGE_SIZE = 30

const KIND_LABEL: Record<string, string> = {
  tier_up: 'tier up',
  tier_down: 'tier down',
  new_project: 'new project',
  slip_realised: 'slip realised',
  signal: 'news signal',
  early_notice: 'early notice',
  pipeline_error: 'pipeline error',
}

const SEVERITY = { 3: 'critical', 2: 'warning', 1: 'muted' } as const

/**
 * Action-oriented alert feed from /api/alerts (SQLite, written by the monthly
 * run, the report watcher and the news scout) — distinct from the Triage
 * Table's browse/sort/filter register. Acknowledging is stored server-side
 * against the signed-in role.
 */
export function EarlyWarningInbox() {
  const navigate = useNavigate()
  const { role } = useRole()
  const [page, setPage] = useState(1)
  const { data, error, isLoading } = useAlerts({ acked: false, page, size: PAGE_SIZE })
  const ack = useAckAlert()
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Card
      title="Early Warning Inbox"
      titleRight={
        <span className="text-[11px] font-mono text-fg-dimmed">{data ? `${data.total} open` : ''}</span>
      }
      className="h-full flex flex-col"
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : isLoading || !data ? (
        <div className="px-5 py-8 text-center text-xs font-mono text-fg-dimmed">loading alerts...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center text-xs font-mono text-fg-dimmed">
          No open alerts — every alert has been acknowledged.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle flex-1 overflow-y-auto max-h-[760px]" data-lenis-prevent>
          {data.items.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-elevated">
              <Badge variant={SEVERITY[a.severity as 1 | 2 | 3] ?? 'muted'} className="w-[92px] shrink-0">
                [{(KIND_LABEL[a.kind] ?? a.kind).toUpperCase()}]
              </Badge>
              <button
                onClick={() => a.projectKey && navigate(`/projects/${a.projectKey}`)}
                disabled={!a.projectKey}
                className="flex-1 min-w-0 text-left disabled:cursor-default"
              >
                <div className="truncate text-xs font-medium text-fg-base">{a.title ?? a.kind}</div>
                <div className="truncate text-[11px] font-mono text-fg-dimmed" title={a.detail ?? undefined}>
                  {a.projectKey && <>{a.projectKey} · </>}
                  {a.detail}
                  {a.asof && <> · asof {formatDate(a.asof)}</>}
                </div>
              </button>
              <Button
                size="sm"
                variant="ghost"
                disabled={!role || (ack.isPending && ack.variables?.id === a.id)}
                title={role ? undefined : 'sign in to acknowledge'}
                onClick={() => role && ack.mutate({ id: a.id, role })}
              >
                Acknowledge
              </Button>
            </div>
          ))}
        </div>
      )}

      {ack.isError && (
        <div className="border-t border-border-subtle px-5 py-1.5 font-mono text-[10px] text-critical">
          acknowledge failed: {String(ack.error)}
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
          <span>
            page {page} of {pages}
          </span>
          <span className="flex gap-2">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Prev
            </Button>
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </span>
        </div>
      )}
    </Card>
  )
}
