import { useQueryClient } from '@tanstack/react-query'
import { ApiError, START_BACKEND, isOffline } from '@/lib/api'
import { cn } from '@/lib/formatters'

/**
 * What a panel shows instead of data when its request failed. Offline is said
 * plainly (start uvicorn) — there is no bundled fallback data to show instead.
 */
export function ApiErrorNote({ error, className }: { error: unknown; className?: string }) {
  const client = useQueryClient()
  const offline = isOffline(error)
  const message =
    error instanceof ApiError ? `API error ${error.status}: ${error.message}` : String(error)

  return (
    <div className={cn('px-5 py-8 text-center text-xs text-fg-dimmed space-y-2', className)}>
      <div className={offline ? 'text-critical font-semibold' : 'text-fg-muted'}>
        {offline ? 'backend not reachable — start uvicorn' : message}
      </div>
      {offline && <code className="block text-xs text-fg-muted">{START_BACKEND}</code>}
      <button
        onClick={() => client.refetchQueries({ type: 'active' })}
        className="underline underline-offset-2 hover:text-fg-base"
      >
        retry
      </button>
    </div>
  )
}
