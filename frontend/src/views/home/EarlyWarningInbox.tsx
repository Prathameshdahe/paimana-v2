import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAckAlert, useAlerts } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { ALERT_KIND_LABEL, alertVariant } from '@/lib/riskPalette'
import { formatDate, formatDateTime, cn } from '@/lib/formatters'
import type { AlertKind } from '@/contracts/portfolio'

const PAGE_SIZE = 30
const KINDS = Object.keys(ALERT_KIND_LABEL) as AlertKind[]

/**
 * Action-oriented alert feed from /api/alerts (SQLite, written by the monthly
 * run, the report watcher and the news scout) — distinct from the Triage
 * Table's browse/sort/filter register. Live: /api/stream refetches it when an
 * alert is raised; only the viewer's projects (backend scope). Acknowledging
 * (analysts, ministry officials; lib/auth/access.ts) is stored against the role.
 */
export function EarlyWarningInbox() {
  const navigate = useNavigate()
  const { role } = useRole()
  const [page, setPage] = useState(1)
  const [kind, setKind] = useState<AlertKind | undefined>()
  const { data, error, isLoading } = useAlerts({ acked: false, kind, page, size: PAGE_SIZE })
  const ack = useAckAlert()
  const canAck = can(role, 'canAck')
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Card
      title="Early Warning Inbox"
      titleRight={
        <span className="text-xs text-fg-dimmed">{data ? `${data.total} open` : ''}</span>
      }
      className="h-full flex flex-col"
    >
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border-subtle px-5 py-2.5">
        {([undefined, ...KINDS] as Array<AlertKind | undefined>).map((k) => (
          <button
            key={k ?? 'all'}
            aria-pressed={kind === k}
            onClick={() => {
              setKind(k)
              setPage(1)
            }}
            className={cn(
              'border px-2 py-0.5 text-xs transition-colors',
              kind === k
                ? 'border-fg-base bg-fg-base text-fg-inverse'
                : 'border-border-default text-fg-dimmed hover:text-fg-base hover:border-border-strong'
            )}
          >
            {k ? ALERT_KIND_LABEL[k] : 'All'}
          </button>
        ))}
      </div>

      {error ? (
        <ApiErrorNote error={error} />
      ) : isLoading || !data ? (
        <div className="px-5 py-8 text-center text-xs text-fg-dimmed">loading alerts...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center text-xs text-fg-dimmed">
          {kind
            ? `No open ${ALERT_KIND_LABEL[kind].toLowerCase()} alerts.`
            : 'No open alerts — every alert has been acknowledged.'}
        </div>
      ) : (
        <div className="divide-y divide-border-subtle flex-1 overflow-y-auto max-h-[760px]" data-lenis-prevent>
          {data.items.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-elevated">
              <Badge variant={alertVariant(a.severity)} className="w-[92px] shrink-0">
                {ALERT_KIND_LABEL[a.kind] ?? a.kind}
              </Badge>
              <button
                onClick={() => a.projectKey && navigate(`/projects/${a.projectKey}`)}
                disabled={!a.projectKey}
                className="flex-1 min-w-0 text-left disabled:cursor-default"
              >
                <div className="truncate text-xs font-medium text-fg-base">{a.title ?? a.kind}</div>
                <div className="truncate text-xs text-fg-dimmed" title={a.detail ?? undefined}>
                  {a.projectKey && <>{a.projectKey} · </>}
                  {a.detail}
                  {a.asof && <> · asof {formatDate(a.asof)}</>}
                  {' · '}
                  {formatDateTime(a.createdAt)}
                </div>
              </button>
              {canAck && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={ack.isPending && ack.variables === a.id}
                  onClick={() => ack.mutate(a.id)}
                >
                  Acknowledge
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {ack.isError && (
        <div className="border-t border-border-subtle px-5 py-1.5 text-xs text-critical">
          acknowledge failed: {String(ack.error)}
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed">
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
