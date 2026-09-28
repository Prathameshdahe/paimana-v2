import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectPanel } from '@/lib/useProjectPanel'
import * as Popover from '@radix-ui/react-popover'
import { Bell } from 'lucide-react'
import { IconChip } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAckAlert, useAlerts } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { ALERT_KIND_ICON, ALERT_KIND_LABEL, alertVariant } from '@/lib/riskPalette'
import { formatDateTime } from '@/lib/formatters'

const SEEN_KEY = 'paimana.alertsSeenAt'

function readSeen(): string | undefined {
  try {
    return localStorage.getItem(SEEN_KEY) ?? undefined
  } catch {
    return undefined
  }
}

/**
 * Top-bar bell: open alerts raised since the bell was last opened (all open
 * ones before the first open), and a dropdown of the latest open alerts.
 * Refreshed by useAlertStream; shown to officials only, and only their projects' alerts
 * (backend scope). Analysts and ministry officials can acknowledge (lib/auth/access.ts).
 */
export function AlertBell() {
  const { role } = useSession()
  const panel = useProjectPanel()
  const [seenAt, setSeenAt] = useState(readSeen)
  const latest = useAlerts({ acked: false, size: 8 })
  const unread = useAlerts({ acked: false, since: seenAt, size: 1 })
  const ack = useAckAlert()
  const n = unread.data?.total ?? 0
  const canAck = can(role, 'canAck')

  const markSeen = () => {
    const newest = latest.data?.items[0]?.createdAt
    if (!newest) return
    // server clock, one second past the newest: `since` is inclusive
    const next = new Date(Date.parse(newest) + 1000).toISOString()
    setSeenAt(next)
    try {
      localStorage.setItem(SEEN_KEY, next)
    } catch {
      // storage disabled: unread resets on reload
    }
  }

  return (
    <Popover.Root onOpenChange={(open) => open && markSeen()}>
      <Popover.Trigger
        aria-label={`alerts: ${n} unread`}
        className="relative flex size-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Bell className="h-4 w-4" />
        {n > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-critical text-white text-xs font-semibold leading-[18px] text-center tabular-nums ring-2 ring-surface-base">
            {n > 99 ? '99+' : n}
          </span>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={16}
          className="z-50 w-[400px] max-w-[calc(100vw-32px)] overflow-hidden rounded-xl border border-border-default bg-surface-panel shadow-pop"
        >
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
            <span className="text-sm font-semibold text-fg-base">
              Open alerts{latest.data ? ` · ${latest.data.total}` : ''}
            </span>
            <Popover.Close asChild>
              <Link to="/" className="text-xs text-fg-dimmed hover:text-fg-base hover:underline">
                All alerts &rarr;
              </Link>
            </Popover.Close>
          </div>

          {latest.error ? (
            <ApiErrorNote error={latest.error} className="py-4" />
          ) : !latest.data ? (
            <div className="space-y-2 px-4 py-4" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-lg bg-surface-input/60" />)}</div>
          ) : latest.data.items.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-fg-dimmed">no open alerts</div>
          ) : (
            <div className="divide-y divide-border-subtle max-h-[420px] overflow-y-auto" data-lenis-prevent>
              {latest.data.items.map((a) => (
                <div key={a.id} className="flex gap-3 px-4 py-3">
                  <IconChip icon={ALERT_KIND_ICON[a.kind]} variant={alertVariant(a.severity)} title={ALERT_KIND_LABEL[a.kind]} />
                  <div className="min-w-0 flex-1 space-y-1">
                  <div className="text-sm font-medium text-fg-base leading-snug line-clamp-2">{a.title ?? ALERT_KIND_LABEL[a.kind]}</div>
                  <div className="flex items-center justify-between gap-2 text-xs text-fg-dimmed">
                    {a.projectKey ? (
                      <Popover.Close asChild>
                        <button
                          onClick={() => a.projectKey && panel.open(a.projectKey)}
                          className="text-xs text-accent hover:underline"
                        >
                          {a.projectKey} &rarr;
                        </button>
                      </Popover.Close>
                    ) : (
                      <span>{formatDateTime(a.createdAt)}</span>
                    )}
                    {a.projectKey && <span className="ml-auto">{formatDateTime(a.createdAt)}</span>}
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
                  </div>
                </div>
              ))}
            </div>
          )}

          {ack.isError && (
            <div className="border-t border-border-subtle px-4 py-1.5 text-xs text-critical">
              acknowledge failed: {String(ack.error)}
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
