import { useSyncExternalStore } from 'react'
import { useAlerts } from '@/lib/queries'

/**
 * When the viewer last opened the alert bell (server time of the newest alert then, plus one second), shared by the
 * bell's unread badge and the PARAKH mark's beacon (useBeaconStatus): both count the alerts raised since. Kept in
 * localStorage; with storage disabled it lives in memory until a reload.
 */
const KEY = 'paimana.alertsSeenAt'
const EVENT = 'paimana:alerts-seen'
let memory: string | undefined

function read(): string | undefined {
  try {
    return localStorage.getItem(KEY) ?? memory
  } catch {
    return memory
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

export function useAlertsSeenAt(): string | undefined {
  return useSyncExternalStore(subscribe, read)
}

export function markAlertsSeen(at: string): void {
  memory = at
  try {
    localStorage.setItem(KEY, at)
  } catch {
    // storage disabled: memory holds it until a reload
  }
  window.dispatchEvent(new Event(EVENT))
}

/** The open alerts raised since the bell was last opened (all open ones before the first open); one query for the
 * bell and the beacon. enabled false: not asked (a viewer without alerts). */
export function useUnseenAlerts(enabled = true) {
  const since = useAlertsSeenAt()
  return useAlerts({ acked: false, since, size: 50 }, enabled)
}
