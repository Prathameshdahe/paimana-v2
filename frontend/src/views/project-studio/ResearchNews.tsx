import { useState } from 'react'
import type { ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useResearch } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/formatters'
import { webUrl } from '@/lib/citations'
import { RESEARCH_GROUPS, externalLines, factDate, researchCategory, researchGroup, researchedOn, type ResearchGroup } from '@/lib/research'
import { Section } from './ProjectVisuals'
import type { ProjectResearch, ResearchFact } from '@/contracts/project'

const ABOUT =
  'Cited web sources about this project: a one-time research sweep, each fact checked by a second agent that ' +
  're-opened the source, and news items the in-app research agent judged with the local AI. The summaries are ' +
  'our own words; the link goes to the source. Evidence only, never a model input. Live: negative, not resolved ' +
  'and dated within 4 quarters. No news is not no problem: coverage favours large, much-reported projects.'

/** the left rule of a fact, by group */
const RULE: Record<ResearchGroup, string> = {
  live: 'border-critical/60',
  resolved: 'border-stable/50',
  progress: 'border-accent/50',
  other: 'border-border-default',
}

/** how many facts per group the side panel shows before "show all" */
const PANEL_PER_GROUP = 3

function origin(f: ResearchFact): { text: string; title: string } {
  if (f.origin === 'agent') {
    return { text: 'news, judged by the local AI', title: 'A news item the in-app research agent judged relevant from its headline and feed summary' }
  }
  return {
    text: f.verified ? 'source re-checked' : 'web research',
    title: f.verified === 'fix' ? 'Checked by a second agent that re-opened the source and corrected the summary' : 'Checked by a second agent that re-opened the source',
  }
}

function Fact({ f, group }: { f: ResearchFact; group: ResearchGroup }) {
  const cat = researchCategory(f.category, f.taxonomy)
  const date = factDate(f)
  const o = origin(f)
  const label = f.headline ?? f.source ?? f.domain ?? 'Source'
  const href = webUrl(f.url)
  return (
    <li className={cn('min-w-0 border-l-2 pl-3', RULE[group])}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="inline-flex items-center gap-1.5 font-medium text-fg-muted">
          <span className="size-2 shrink-0 rounded-full" style={{ background: cat.color }} aria-hidden="true" />
          {cat.label}
        </span>
        {date && <span className="text-fg-dimmed">{date}</span>}
        {f.status === 'ongoing' && <span className="rounded-full bg-warning/10 px-2 py-px font-medium text-warning">ongoing</span>}
        {f.status === 'resolved' && <span className="rounded-full bg-stable/10 px-2 py-px font-medium text-stable">resolved</span>}
        {f.direction === 'negative' && f.severity >= 3 && <span className="rounded-full bg-critical/10 px-2 py-px font-medium text-critical">severe</span>}
      </div>
      <p className="mt-1 text-sm leading-snug text-fg-base">{f.summary}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-fg-dimmed">
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-w-0 max-w-full items-center gap-1 text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            title={f.headline ?? href}
          >
            <span className="truncate">{label}</span>
            <ExternalLink className="size-3 shrink-0" aria-label="opens in a new tab" />
          </a>
        ) : (
          <span className="truncate text-fg-muted">{label}</span>
        )}
        {f.headline && f.source && <span className="truncate">· {f.source}</span>}
        <span title={o.title}>· {o.text}</span>
      </div>
    </li>
  )
}

function Body({ data, panel }: { data: ProjectResearch; panel: boolean }) {
  const [all, setAll] = useState(false)
  const lines = externalLines(data.external)
  const when = researchedOn(data)
  const groups = RESEARCH_GROUPS.map((g) => ({ ...g, facts: data.facts.filter((f) => researchGroup(f) === g.key) }))
    .filter((g) => g.facts.length > 0)
  const limit = panel && !all ? PANEL_PER_GROUP : Infinity
  const hidden = groups.reduce((n, g) => n + Math.max(0, g.facts.length - limit), 0)

  return (
    <div className="space-y-4">
      {(data.latestStatus || lines.length > 0) && (
        <div className="space-y-2">
          {data.latestStatus && (
            <p className="border-l-2 border-border-default pl-3 text-sm leading-relaxed text-fg-base">
              <span className="text-fg-muted">Latest from the sources: </span>
              {data.latestStatus}
            </p>
          )}
          {lines.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="What the sources say now">
              {lines.map((l) => (
                <li key={l.key} className="rounded-full bg-surface-elevated px-2.5 py-0.5 text-xs text-fg-base ring-1 ring-inset ring-border-subtle">
                  {l.text}
                  {l.asOf && <span className="text-fg-dimmed"> · as of {l.asOf}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {data.facts.length === 0 ? (
        <div className="py-2 text-center text-sm text-fg-dimmed">
          {when ?? 'Researched'}: nothing found. Not the same as no problem.
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.key} aria-label={g.label}>
            <h4 className="mb-2 flex items-baseline gap-1.5 text-xs font-semibold text-fg-muted" title={g.hint}>
              <span className={cn(g.key === 'live' && 'text-critical')}>{g.label}</span>
              <span className="font-normal tabular-nums text-fg-dimmed">{g.facts.length}</span>
            </h4>
            <ul className={cn('grid gap-3', !panel && 'gap-x-6 lg:grid-cols-2')}>
              {g.facts.slice(0, limit).map((f) => <Fact key={f.factId} f={f} group={g.key} />)}
            </ul>
          </section>
        ))
      )}

      {panel && (hidden > 0 || all) && (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          className="w-full rounded-lg py-1.5 text-center text-xs font-medium text-accent transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          {all ? 'Show fewer' : `Show all ${data.facts.length} facts`}
        </button>
      )}
    </div>
  )
}

/**
 * Research & news: the project's cited web facts (GET /api/projects/{key}/research, every role; the public gets
 * the redacted facts) — the sources' latest status and figures, then live blockers, resolved issues, progress and
 * the rest, each with its category, date at the source's precision, our own summary and the source link. "Not
 * researched yet" and "researched, nothing found" are different states and say so. panel: the side panel and
 * public page look (Section), a few facts per group; page: the full project page's card, every fact.
 */
export function ResearchNews({ projectKey, variant }: { projectKey: string | null; variant: 'panel' | 'page' }) {
  const { data, error } = useResearch(projectKey)
  const panel = variant === 'panel'
  const right = data ? (researchedOn(data) ?? 'Not researched yet') : null

  let body: ReactNode
  if (error) {
    body = error instanceof ApiError && error.status === 404
      ? <div className="py-3 text-center text-sm text-fg-dimmed">No research for this project in your view</div>
      : <ApiErrorNote error={error} className="py-3" />
  } else if (!data) {
    body = <div className="h-20 animate-pulse rounded-lg bg-surface-input/70" aria-busy="true" aria-label="Loading research" />
  } else if (!data.searched) {
    body = (
      <div className="py-2 text-center text-sm text-fg-dimmed">
        Not researched yet: no web search has been run for this project, which is not the same as no problem.
      </div>
    )
  } else {
    body = <Body data={data} panel={panel} />
  }

  if (panel) {
    return <Section title="Research & news" info={ABOUT} right={right}>{body}</Section>
  }
  return (
    <Card title="Research & news" info={ABOUT} titleRight={right}>
      <div className="px-5 py-4">{body}</div>
    </Card>
  )
}
