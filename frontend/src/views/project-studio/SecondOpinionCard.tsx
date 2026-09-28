import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { CiteChip, CitedText } from '@/components/common/CitedText'
import { useCachedSecondOpinion, useSecondOpinion } from '@/lib/queries'
import { ApiError, isOffline } from '@/lib/api'
import { citedRefs, webUrl } from '@/lib/citations'
import { CONCERN, TIER_LABEL, tierKey } from '@/lib/riskPalette'
import { cn, formatDateTime, formatLooseDate } from '@/lib/formatters'
import { Section } from './ProjectVisuals'
import type { OpinionEvidence, OpinionVsModel, SecondOpinionOut, SecondOpinionRejected } from '@/contracts/project'

/** when the viewer asked, per project: the elapsed time survives closing and reopening the panel */
const askedAt = new Map<string, number>()

const KIND_LABEL: Record<string, string> = {
  status: 'Status', model: 'Model', check: 'Risk check', event: 'Report remark', parivesh: 'PARIVESH', land: 'Land register',
  research: 'Web research', news: 'News',
}

const TIER_NOTE = 'AI second opinion — it does not change the tier, which stays the model’s ranking.'

function evidenceOf(o: SecondOpinionOut): OpinionEvidence[] {
  return o.evidence ?? o.pack?.items ?? []
}

function vsModel(v: OpinionVsModel, tier: string | null | undefined): string {
  const t = tier ? `the model’s ${TIER_LABEL[tierKey(tier)]} tier` : 'the model’s tier'
  return v === 'higher' ? `Reads the risk higher than ${t}`
    : v === 'lower' ? `Reads the risk lower than ${t}`
    : `Agrees with ${t}`
}

/** seconds since `since`, ticking once a second while set */
function useElapsed(since: number | undefined): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since === undefined) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [since])
  return since === undefined ? null : Math.max(0, Math.round((now - since) / 1000))
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function OpinionError({ error }: { error: unknown }) {
  if (isOffline(error) || !(error instanceof ApiError)) return <ApiErrorNote error={error} className="py-3" />
  if (error.status === 503) {
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-warning">Local LLM not running — start LM Studio</div>
        <div className="text-xs text-fg-dimmed">{error.message}</div>
      </div>
    )
  }
  if (error.status === 422) {
    const body = error.body as Partial<SecondOpinionRejected> | undefined
    return (
      <div className="space-y-1">
        <div className="text-sm font-semibold text-critical">
          Second opinion rejected: it did not hold up against the evidence
          {body?.attempts ? ` (${body.attempts} attempts)` : ''}
        </div>
        <ul className="list-disc pl-5 text-xs text-fg-muted">
          {(body?.reasons ?? [error.message]).map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      </div>
    )
  }
  if (error.status === 404) return <div className="text-xs text-fg-dimmed">No second opinion: {error.message}</div>
  return <ApiErrorNote error={error} className="py-3" />
}

function Opinion({ o, tier }: { o: SecondOpinionOut; tier?: string | null }) {
  const ids = useId()
  const [active, setActive] = useState<string | null>(null)
  const items = evidenceOf(o)
  const byId = new Map(items.map((e) => [e.id, e]))
  const cited = [...new Set([...citedRefs(o.narrative, 'evidence'), ...o.keyEvidence])]
  const anchor = (id: string) => `${ids}-${id}`

  const pick = (id: string) => {
    setActive(id === active ? null : id)
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    document.getElementById(anchor(id))?.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' })
  }

  return (
    <div className="space-y-3">
      <p className="text-base font-semibold leading-snug text-fg-base">{o.headline}</p>
      <p className="text-sm leading-relaxed text-fg-base">
        <CitedText
          text={o.narrative}
          style="evidence"
          renderCite={(ref) => (
            <CiteChip label={ref} title={byId.get(ref)?.text ?? `Evidence ${ref}`} active={active === ref} onClick={() => pick(ref)} />
          )}
        />
      </p>
      <p className="text-xs font-medium text-fg-muted">{vsModel(o.vsModel, tier)}</p>

      {cited.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold text-fg-muted">Evidence cited</h4>
          <ol className="space-y-1">
            {cited.map((id) => {
              const e = byId.get(id)
              const stance = e?.direction ?? e?.stance
              const href = webUrl(e?.url)
              return (
                <li key={id} id={anchor(id)}
                  className={cn('flex gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors', active === id && 'bg-accent/10 ring-1 ring-inset ring-accent/30')}>
                  <span className={cn(
                    'mt-px inline-flex h-4 shrink-0 items-center rounded px-1 font-semibold leading-none',
                    stance === 'negative' ? 'bg-critical/10 text-critical' : stance === 'positive' ? 'bg-stable/10 text-stable' : 'bg-accent/15 text-accent'
                  )}>
                    {id}
                  </span>
                  {e ? (
                    <div className="min-w-0 space-y-0.5">
                      <div className="leading-snug text-fg-base">{e.text}</div>
                      <div className="text-fg-dimmed">
                        {KIND_LABEL[e.kind] ?? e.kind}
                        {e.date && ` · ${formatLooseDate(e.date)}`}
                        {href ? (
                          <> · <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">{e.source ?? 'source'}</a></>
                        ) : e.source ? ` · ${e.source}` : ''}
                      </div>
                    </div>
                  ) : (
                    <span className="text-fg-dimmed">in the evidence pack the model read</span>
                  )}
                </li>
              )
            })}
          </ol>
        </div>
      )}

      {o.gaps.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold text-fg-muted">What the evidence does not show</h4>
          <ul className="list-disc space-y-0.5 pl-5 text-xs leading-snug text-fg-muted marker:text-fg-dimmed">
            {o.gaps.map((g) => <li key={g}>{g}</li>)}
          </ul>
        </div>
      )}

      <div className="text-xs text-fg-dimmed">
        {[
          o.model,
          o.generatedAt && `written ${formatDateTime(o.generatedAt)}`,
          items.length ? `${items.length} evidence items read` : null,
          o.nNumbersChecked ? `${o.nNumbersChecked} numbers checked` : null,
          o.cached ? 'cached' : null,
        ].filter(Boolean).join(' · ')}
      </div>
    </div>
  )
}

/**
 * The AI second opinion on one project (officials; GET /api/projects/{key}/second-opinion): the local LLM reads the
 * project's evidence pack (status, model tier, flagged checks, report remarks, PARIVESH, land, web research and news,
 * each an [E#]) and says how concerned it is, why, and where it sits against the model — every citation and number
 * checked by the backend, so what shows is validated or the reasons it was not. A stored opinion for the current
 * evidence shows at once (?cached=1); a new one is written only when asked, like the brief, and can take a minute or
 * two: the fetch keeps going when the panel closes. It never changes the tier.
 * panel: the side panel's block (Section); page: the full page's card beside the brief.
 */
export function SecondOpinionCard({ projectKey, variant, tier, className }: {
  projectKey: string
  variant: 'panel' | 'page'
  /** the model's tier, for the "against the model" line */
  tier?: string | null
  className?: string
}) {
  const cached = useCachedSecondOpinion(projectKey)
  const [requested, setRequested] = useState(false)
  const gen = useSecondOpinion(projectKey, requested)
  const stored = cached.data?.status === 'ok' ? cached.data : undefined
  const opinion = gen.data ?? stored
  const writing = gen.isFetching
  const elapsed = useElapsed(writing ? askedAt.get(projectKey) : undefined)

  const ask = () => {
    askedAt.set(projectKey, Date.now())
    if (requested) void gen.refetch()
    else setRequested(true)
  }

  const concern = opinion ? (CONCERN[opinion.concern] ?? CONCERN.watch) : null
  const right = concern ? (
    <Badge variant={concern.variant}>{concern.label}</Badge>
  ) : (
    <Button size="sm" disabled={writing || cached.isLoading} onClick={ask}>
      {writing ? 'Writing…' : gen.error ? 'Try again' : 'Get a second opinion'}
    </Button>
  )

  let body: ReactNode
  if (opinion) {
    body = <Opinion o={opinion} tier={tier} />
  } else if (writing) {
    body = (
      <div className="space-y-1.5 text-xs text-fg-muted" role="status">
        <div className="font-medium text-fg-base">
          The local model is reading the evidence{elapsed !== null && <span className="font-normal tabular-nums text-fg-dimmed"> · {clock(elapsed)}</span>}
        </div>
        <p>
          This usually takes one to two minutes on this machine; every citation and number is checked before it shows.
          You can close the panel and come back: it keeps going.
        </p>
      </div>
    )
  } else if (gen.error) {
    body = <OpinionError error={gen.error} />
  } else {
    body = (
      <p className="text-xs leading-relaxed text-fg-muted">
        The local model reads this project&rsquo;s evidence — status, flagged checks, report remarks, PARIVESH, land,
        web research and news — and says how concerned it is and why, citing each item. A cited item that does not
        exist or a number that is not in the evidence rejects the opinion.
      </p>
    )
  }

  const note = (
    <p className="flex items-start gap-1.5 text-xs text-fg-dimmed">
      <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
      {TIER_NOTE}
    </p>
  )

  if (variant === 'panel') {
    return (
      <Section title={<>AI second opinion <span className="font-normal text-fg-dimmed">· local LLM</span></>} right={right} className={className}>
        <div className="space-y-3">{body}{note}</div>
      </Section>
    )
  }
  return (
    <div className={cn('overflow-hidden rounded-xl border border-border-subtle bg-surface-panel shadow-card', className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border-subtle px-5 py-3">
        <span className="text-sm font-semibold text-fg-base">AI second opinion <span className="font-normal text-fg-dimmed">· local LLM</span></span>
        {right}
      </div>
      <div className="space-y-3 px-4 py-3">{body}{note}</div>
    </div>
  )
}
