import { useQueryClient } from '@tanstack/react-query'
import { ApiError, START_BACKEND, isOffline } from '@/lib/api'
import { cn } from '@/lib/formatters'

/**
 * What a panel shows instead of data when its request failed. Offline is said plainly, with the command that starts
 * the service on the server — there is no bundled fallback data to show instead.
 */
export function ApiErrorNote({ error, className }: { error: unknown; className?: string }) {
  const client = useQueryClient()
  const offline = isOffline(error)
  const message =
    error instanceof ApiError ? `This could not be loaded (${error.status}): ${error.message}` : String(error)

  return (
    <div role="status" className={cn('px-5 py-8 text-center text-xs text-fg-dimmed space-y-2', className)}>
      <div className={offline ? 'text-sm font-semibold text-critical' : 'text-sm text-fg-muted'}>
        {offline ? 'The data service is not answering.' : message}
      </div>
      {offline && <code className="block text-xs text-fg-muted">{START_BACKEND}</code>}
      <button
        type="button"
        onClick={() => client.refetchQueries({ type: 'active' })}
        className="rounded underline underline-offset-2 hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        Try again
      </button>
    </div>
  )
}
