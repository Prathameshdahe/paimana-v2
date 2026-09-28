import { useState } from 'react'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { Card } from '@/components/ui/Card'
import { IconChip } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Input'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAckAlert, useAlerts } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { ALERT_KIND_ICON, ALERT_KIND_LABEL, alertVariant } from '@/lib/riskPalette'
import { scrubModelNumbers } from '@/lib/outlook'
import { formatDate, formatDateTime } from '@/lib/formatters'
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
  const panel = useProjectPanel()
  const { role } = useSession()
  const [page, setPage] = useState(1)
  const [kind, setKind] = useState<AlertKind | undefined>()
  const { data, error, isLoading } = useAlerts({ acked: false, kind, page, size: PAGE_SIZE })
  const ack = useAckAlert()
  const canAck = can(role, 'canAck')
  // stored alerts carry the watcher's probability in their detail: only the developer reads it
  const detailOf = (d: string | null) => (d && !can(role, 'canSeeNumbers') ? scrubModelNumbers(d) : d)
  const kinds = KINDS.filter((k) => k !== 'pipeline_error' || can(role, 'canSeePipelineErrors'))
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Card
      title="Early warnings"
      titleRight={
        <span className="flex items-center gap-2">
          {data && <span>{data.total} open</span>}
          <Select
            aria-label="alert kind"
            value={kind ?? ''}
            onChange={(e) => {
              setKind((e.target.value || undefined) as AlertKind | undefined)
              setPage(1)
            }}
          >
            <option value="">All kinds</option>
            {kinds.map((k) => (
              <option key={k} value={k}>{ALERT_KIND_LABEL[k]}</option>
            ))}
          </Select>
        </span>
      }
      className="h-full flex flex-col"
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : isLoading || !data ? (
        <div className="space-y-2 px-4 py-4" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-surface-input/60" />)}</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-dimmed">
          {kind
            ? `No open ${ALERT_KIND_LABEL[kind].toLowerCase()} alerts.`
            : 'No open alerts — every alert has been acknowledged.'}
        </div>
      ) : (
        <div className="divide-y divide-border-subtle flex-1 overflow-y-auto max-h-[760px]" data-lenis-prevent>
          {data.items.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-surface-elevated">
              <IconChip icon={ALERT_KIND_ICON[a.kind]} variant={alertVariant(a.severity)} title={ALERT_KIND_LABEL[a.kind] ?? a.kind} />
              <button
                onClick={() => a.projectKey && panel.open(a.projectKey)}
                disabled={!a.projectKey}
                className="flex-1 min-w-0 text-left disabled:cursor-default"
              >
                <div className="truncate text-sm font-medium text-fg-base">{a.title ?? ALERT_KIND_LABEL[a.kind]}</div>
                <div
                  className="truncate text-xs text-fg-dimmed"
                  title={[detailOf(a.detail), a.asof && `as of ${formatDate(a.asof)}`].filter(Boolean).join(' · ') || undefined}
                >
                  {ALERT_KIND_LABEL[a.kind] ?? a.kind}
                  {a.projectKey && <> · {a.projectKey}</>}
                  {' · '}
                  {formatDateTime(a.createdAt)}
                  {detailOf(a.detail) && <> · {detailOf(a.detail)}</>}
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
