import { useState } from 'react'
import { Link } from 'react-router-dom'
import * as Popover from '@radix-ui/react-popover'
import { Bell } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { ACK_ROLES, useAckAlert, useAlerts } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { ALERT_KIND_LABEL, alertVariant } from '@/lib/riskPalette'
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
 * Refreshed by useAlertStream; analysts and ministry officials can acknowledge.
 */
export function AlertBell() {
  const { role } = useRole()
  const [seenAt, setSeenAt] = useState(readSeen)
  const latest = useAlerts({ acked: false, size: 8 })
  const unread = useAlerts({ acked: false, since: seenAt, size: 1 })
  const ack = useAckAlert()
  const n = unread.data?.total ?? 0
  const canAck = !!role && ACK_ROLES.includes(role)

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
        className="relative flex h-8 w-8 items-center justify-center text-fg-dimmed hover:text-fg-base focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
      >
        <Bell className="h-4 w-4" />
        {n > 0 && (
          <span className="absolute top-0 right-0 min-w-[16px] h-4 px-1 rounded-full bg-critical text-white font-mono text-[9px] leading-4 text-center tabular-nums">
            {n > 99 ? '99+' : n}
          </span>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={16}
          className="z-50 w-[400px] max-w-[calc(100vw-32px)] border border-border-default bg-surface-panel shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
            <span className="text-xs font-mono font-semibold uppercase tracking-widest text-fg-muted">
              Open alerts{latest.data ? ` · ${latest.data.total}` : ''}
            </span>
            <Popover.Close asChild>
              <Link to="/" className="font-mono text-[11px] text-fg-dimmed hover:text-fg-base hover:underline">
                inbox &rarr;
              </Link>
            </Popover.Close>
          </div>

          {latest.error ? (
            <ApiErrorNote error={latest.error} className="py-4" />
          ) : !latest.data ? (
            <div className="px-4 py-6 text-center font-mono text-xs text-fg-dimmed">loading alerts...</div>
          ) : latest.data.items.length === 0 ? (
            <div className="px-4 py-6 text-center font-mono text-xs text-fg-dimmed">no open alerts</div>
          ) : (
            <div className="divide-y divide-border-subtle max-h-[420px] overflow-y-auto" data-lenis-prevent>
              {latest.data.items.map((a) => (
                <div key={a.id} className="px-4 py-2.5 space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={alertVariant(a.severity)}>[{ALERT_KIND_LABEL[a.kind].toUpperCase()}]</Badge>
                    <span className="ml-auto font-mono text-[10px] text-fg-dimmed">{formatDateTime(a.createdAt)}</span>
                  </div>
                  <div className="text-xs font-medium text-fg-base leading-snug">{a.title ?? a.kind}</div>
                  <div className="flex items-center justify-between gap-2">
                    {a.projectKey ? (
                      <Popover.Close asChild>
                        <Link
                          to={`/projects/${a.projectKey}`}
                          className="font-mono text-[11px] text-accent hover:underline"
                        >
                          {a.projectKey} &rarr;
                        </Link>
                      </Popover.Close>
                    ) : (
                      <span className="font-mono text-[11px] text-fg-dimmed">no project</span>
                    )}
                    {canAck && role && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={ack.isPending && ack.variables?.id === a.id}
                        onClick={() => ack.mutate({ id: a.id, role })}
                      >
                        Acknowledge
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {ack.isError && (
            <div className="border-t border-border-subtle px-4 py-1.5 font-mono text-[10px] text-critical">
              acknowledge failed: {String(ack.error)}
            </div>
          )}
          {!canAck && (
            <div className="border-t border-border-subtle px-4 py-1.5 font-mono text-[10px] text-fg-dimmed">
              sign in as an IPMD analyst or ministry official to acknowledge
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
