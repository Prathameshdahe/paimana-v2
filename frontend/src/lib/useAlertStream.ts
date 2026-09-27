import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '@/lib/api'

/**
 * Subscribes to GET /api/stream (Server-Sent Events). Each new alert refetches
 * the alert lists, the live status and the signal feed, so the bell and the
 * inbox update without polling. EventSource reconnects by itself and resumes
 * after Last-Event-ID; a reconnect also refetches, to catch up on anything
 * raised while the connection was down. Mount once (the top bar does).
 */
export function useAlertStream() {
  const client = useQueryClient()

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/stream`)
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
  }, [client])
}
