import { useEffect } from 'react'
import type { BeaconStatus } from '@/components/brand/ParakhMark'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { useUnseenAlerts } from '@/lib/alertsSeen'

export interface Beacon {
  status: BeaconStatus
  /** in words, for a tooltip; empty for a viewer without alerts */
  label: string
}

/**
 * The PARAKH mark's beacon follows the alert bell: critical while an alert the viewer has not seen yet has
 * severity 3 (a project newly Critical, a pipeline error), watch for any other unseen alert, stable when there is
 * none, and stable for viewers without alerts (the public). While it is critical the tab icon's beacon turns red too
 * (public/favicon-alert.svg).
 */
export function useBeaconStatus(): Beacon {
  const { role } = useSession()
  const enabled = can(role, 'canSeeAlerts')
  const unseen = useUnseenAlerts(enabled)
  const items = enabled ? unseen.data?.items ?? [] : []
  const total = enabled ? unseen.data?.total ?? 0 : 0
  const severe = items.filter((a) => a.severity >= 3).length
  const status: BeaconStatus = severe > 0 ? 'critical' : total > 0 ? 'watch' : 'stable'
  const label = !enabled
    ? ''
    : total === 0
      ? 'no new alerts'
      : `${total} new alert${total === 1 ? '' : 's'}${severe ? `, ${severe}${items.length < total ? '+' : ''} severe` : ''}`

  useEffect(() => {
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]')
    if (!icon) return
    icon.href = status === 'critical' ? '/favicon-alert.svg' : '/favicon.svg'
    return () => {
      icon.href = '/favicon.svg'
    }
  }, [status])

  return { status, label }
}
