import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useBrief } from '@/lib/queries'
import { ApiError, isOffline } from '@/lib/api'
import { formatDateTime } from '@/lib/formatters'
import type { BriefRejected } from '@/contracts/project'

function BriefError({ error }: { error: unknown }) {
  if (isOffline(error) || !(error instanceof ApiError)) return <ApiErrorNote error={error} />
  if (error.status === 503) {
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-warning">Local LLM not running — start LM Studio</div>
        <div className="font-mono text-[10px] text-fg-dimmed">{error.message}</div>
      </div>
    )
  }
  if (error.status === 422) {
    const body = error.body as Partial<BriefRejected> | undefined
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-critical">
          Brief rejected: it cited numbers that are not in the panel
          {body?.attempts ? ` (${body.attempts} attempts)` : ''}
        </div>
        <ul className="list-disc pl-5 font-mono text-[11px] text-fg-muted">
          {(body?.reasons ?? [error.message]).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>
    )
  }
  if (error.status === 404) {
    return <div className="font-mono text-xs text-fg-dimmed">no brief: {error.message}</div>
  }
  return <ApiErrorNote error={error} />
}

/**
 * Two paragraphs from the local LLM on this project (GET /api/projects/{key}/brief). The backend
 * rejects any text with a number that is not in the facts it was given, so what shows here is
 * either validated or the reasons it was not.
 */
export function BriefCard({ projectKey }: { projectKey: string }) {
  const [requested, setRequested] = useState(false)
  const { data, error, isFetching, refetch } = useBrief(projectKey, requested)

  return (
    <div className="bg-surface-panel border border-border-subtle">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <span className="text-xs font-mono uppercase tracking-widest text-fg-muted">Brief · local LLM</span>
        {data ? (
          <span className="border border-stable/40 bg-stable/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-stable">
            validated: every number traced to the panel
          </span>
        ) : (
          <Button
            size="sm"
            disabled={isFetching}
            onClick={() => (requested ? refetch() : setRequested(true))}
          >
            {isFetching ? 'Writing…' : error ? 'Try again' : 'Generate brief'}
          </Button>
        )}
      </div>
      <div className="px-4 py-3">
        {isFetching && !data ? (
          <div className="font-mono text-xs text-fg-dimmed">asking the local model and checking every number it writes…</div>
        ) : error ? (
          <BriefError error={error} />
        ) : data ? (
          <div className="space-y-2">
            {data.paragraphs.map((p, i) => (
              <p key={i} className="text-sm leading-relaxed text-fg-base">{p}</p>
            ))}
            <div className="font-mono text-[10px] text-fg-dimmed">
              {data.nNumbersChecked ?? 0} numbers checked · {data.attempts ?? 1} attempt(s) · {data.modelVersion}
              {data.cached ? ' · cached' : ''}
              {data.generatedAt && ` · written ${formatDateTime(data.generatedAt)}`}
            </div>
          </div>
        ) : (
          <div className="font-mono text-xs text-fg-dimmed">
            A two-paragraph summary of this panel. Any number the model writes that is not in the panel's data rejects the brief.
          </div>
        )}
      </div>
    </div>
  )
}
