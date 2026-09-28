import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useBrief } from '@/lib/queries'
import { ApiError, isOffline } from '@/lib/api'
import { cn, formatDateTime } from '@/lib/formatters'

/** "27 Sept" (the day it was written; the time only in the developer's footer) */
const writtenOn = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
import type { BriefRejected } from '@/contracts/project'

function BriefError({ error }: { error: unknown }) {
  if (isOffline(error) || !(error instanceof ApiError)) return <ApiErrorNote error={error} />
  if (error.status === 503) {
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-warning">The local AI model is not running, so no brief can be written now</div>
        <div className="text-xs text-fg-dimmed">{error.message}</div>
      </div>
    )
  }
  if (error.status === 422) {
    const body = error.body as Partial<BriefRejected> | undefined
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-critical">
          The brief was set aside: it said something the project&rsquo;s record does not support
          {body?.attempts ? ` (${body.attempts} attempts)` : ''}
        </div>
        <ul className="list-disc pl-5 text-xs text-fg-muted">
          {(body?.reasons ?? [error.message]).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>
    )
  }
  if (error.status === 404) {
    return <div className="text-sm text-fg-muted">No brief: {error.message}</div>
  }
  return <ApiErrorNote error={error} />
}

/**
 * Two paragraphs from the local LLM on this project (GET /api/projects/{key}/brief). The backend rejects any text
 * with a figure that is not in the facts it was given (and gives the four roles facts without model numbers), so
 * what shows here was checked against the project's record, or the reason it was set aside. numbers (the
 * developer): the footer also counts the figures checked, the attempts and the model version. autoRequest: write it
 * at once (the side panel opens it on demand).
 */
export function BriefCard({ projectKey, className, numbers = false, autoRequest = false }: {
  projectKey: string
  className?: string
  numbers?: boolean
  autoRequest?: boolean
}) {
  const [requested, setRequested] = useState(autoRequest)
  const { data, error, isFetching, refetch } = useBrief(projectKey, requested)

  return (
    <div className={cn('bg-surface-panel border border-border-subtle rounded-xl shadow-card overflow-hidden', className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border-subtle px-5 py-3">
        <span className="text-sm font-semibold text-fg-base">AI brief <span className="font-normal text-fg-dimmed">· local model</span></span>
        {data ? (
          <span className="rounded-full bg-stable/10 px-2.5 py-0.5 text-xs font-medium text-stable ring-1 ring-inset ring-stable/20">
            Checked against the project&rsquo;s record
          </span>
        ) : (
          <Button
            size="sm"
            disabled={isFetching}
            onClick={() => (requested ? refetch() : setRequested(true))}
          >
            {isFetching ? 'Writing…' : error ? 'Try again' : 'Write the brief'}
          </Button>
        )}
      </div>
      <div className="px-5 py-4" aria-live="polite">
        {isFetching && !data ? (
          <div className="space-y-2">
            <p className="text-sm text-fg-muted">The local model is writing; every figure it uses is checked against the record.</p>
            <div className="h-4 w-11/12 animate-pulse rounded bg-surface-input/70" />
            <div className="h-4 w-4/5 animate-pulse rounded bg-surface-input/70" />
          </div>
        ) : error ? (
          <BriefError error={error} />
        ) : data ? (
          <div className="space-y-2.5">
            {data.paragraphs.map((p, i) => (
              <p key={i} className="text-sm leading-relaxed text-fg-base">{p}</p>
            ))}
            <div className="text-xs text-fg-dimmed">
              {numbers
                ? <>
                    {data.nNumbersChecked ?? 0} numbers checked · {data.attempts ?? 1} attempt(s) · {data.modelVersion}
                    {data.cached ? ' · cached' : ''}
                    {data.generatedAt && ` · written ${formatDateTime(data.generatedAt)}`}
                  </>
                : data.generatedAt ? `Written ${writtenOn(data.generatedAt)}` : 'Written from the latest report'}
            </div>
          </div>
        ) : (
          <p className="text-sm text-fg-muted">
            Two paragraphs on where this project stands and why, written by the local AI model from the project&rsquo;s
            record. Anything it says that the record does not support sets the brief aside.
          </p>
        )}
      </div>
    </div>
  )
}
