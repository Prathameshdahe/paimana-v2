import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { url } from '@/lib/api'
import { useScopeKey, useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'

/**
 * Subscribes to GET /api/stream (Server-Sent Events). Each new alert refetches
 * the alert lists, the live status and the signal feed, so the bell and the
 * inbox update without polling. EventSource reconnects by itself and resumes
 * after Last-Event-ID; a reconnect also refetches, to catch up on anything
 * raised while the connection was down. The session cookie is what names the
 * viewer (withCredentials carries it to a backend on another origin too); the
 * public has no alerts and opens none. Mount once (the top bar does); a
 * sign-in or sign-out reopens it.
 */
export function useAlertStream() {
  const client = useQueryClient()
  const { role } = useSession()
  const scope = useScopeKey()
  const on = can(role, 'canSeeAlerts')

  useEffect(() => {
    if (!on) return
    const es = new EventSource(url('/api/stream'), { withCredentials: true })
    let opened = false
    const refresh = () => {
      client.invalidateQueries({ queryKey: ['alerts'] })
      client.invalidateQueries({ queryKey: ['live'] })
      client.invalidateQueries({ queryKey: ['signals'] })
    }
    es.addEventListener('alert', refresh)
    es.onopen = () => {
      if (opened) refresh()
      opened = true
    }
    return () => es.close()
  }, [client, on, scope])
}
