import { useState } from 'react'
import { ExternalLink, Newspaper } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useResearchSummary } from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { cn, formatLooseDate } from '@/lib/formatters'
import { factDate, researchCategory } from '@/lib/research'
import { webUrl } from '@/lib/citations'
import type { ResearchBlocker, ResearchSummary } from '@/contracts/portfolio'

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'critical' }) {
  return (
    <div className="bg-surface-panel px-5 py-4">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={cn('mt-1.5 text-xl font-semibold tabular-nums leading-none', tone === 'critical' ? 'text-critical' : 'text-fg-base')}>{value}</div>
      {sub && <div className="mt-1.5 text-xs text-fg-dimmed">{sub}</div>}
    </div>
  )
}

/** live blockers per category as bars, most first; categories with none are left out */
function ByCategory({ s }: { s: ResearchSummary }) {
  const rows = s.byCategory.filter((r) => r.nLive > 0).sort((a, b) => b.nLive - a.nLive)
  const max = Math.max(1, ...rows.map((r) => r.nLive))
  return (
    <div className="bg-surface-panel px-5 py-4">
      <div className="text-xs text-fg-muted">Live blockers by category</div>
      {rows.length === 0 ? (
        <div className="mt-2 text-xs text-fg-dimmed">none in view</div>
      ) : (
        <div className="mt-2 space-y-1.5">
          {rows.map((r) => {
            const c = researchCategory(r.category, r.taxonomy)
            return (
              <div key={r.category} className="grid grid-cols-[7.5rem_1fr_auto] items-center gap-2 text-xs"
                title={`${r.nLive} live on ${r.nProjectsLive} project${r.nProjectsLive === 1 ? '' : 's'}; ${r.negative} negative, ${r.positive} positive, ${r.neutral} neutral facts in all`}>
                <span className="flex min-w-0 items-center gap-1.5 text-fg-base">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: c.color }} aria-hidden="true" />
                  <span className="truncate">{c.label}</span>
                </span>
                <div className="h-1.5 overflow-hidden bg-surface-input">
                  <div className="h-full bg-critical/70" style={{ width: `${(r.nLive / max) * 100}%` }} />
                </div>
                <span className="text-right tabular-nums text-fg-base">{r.nLive}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** one blocker: officials get our summary, the project (opens the side panel) and the source; the public the headline and date */
function Blocker({ b }: { b: ResearchBlocker }) {
  const panel = useProjectPanel()
  const date = factDate(b)
  const cat = b.category ? researchCategory(b.category) : null
  const href = webUrl(b.url)
  return (
    <li className="min-w-0 space-y-1 px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-dimmed">
        {cat && (
          <span className="inline-flex items-center gap-1.5 font-medium text-fg-muted">
            <span className="size-2 rounded-full" style={{ background: cat.color }} aria-hidden="true" />
            {cat.label}
          </span>
        )}
        {date && <span>{date}</span>}
        {b.severity !== null && b.severity >= 3 && <span className=" bg-critical/10 px-2 py-px font-medium text-critical">severe</span>}
      </div>
      {b.summary && <p className="text-sm leading-snug text-fg-base">{b.summary}</p>}
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" title={b.headline}
          className={cn('inline-flex max-w-full items-center gap-1 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40', b.summary ? 'text-xs text-accent' : 'text-sm font-medium text-fg-base')}>
          <span className="line-clamp-2">{b.headline}</span>
          <ExternalLink className="size-3 shrink-0 text-fg-dimmed" aria-label="opens in a new tab" />
        </a>
      ) : (
        <span className={b.summary ? 'text-xs text-fg-muted' : 'text-sm font-medium text-fg-base'}>{b.headline}</span>
      )}
      {b.source && <span className="text-xs text-fg-dimmed"> · {b.source}</span>}
      {b.projectKey && (
        <div className="flex min-w-0 items-center gap-2 text-xs">
          {b.tier && <Badge tier={b.tier} />}
          <button type="button" onClick={() => panel.open(b.projectKey ?? '')}
            className="min-w-0 truncate text-left font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            title={b.projectName ?? undefined}>
            {b.projectName ?? b.projectKey}
          </button>
          {b.state && <span className="shrink-0 text-fg-dimmed">{b.state}</span>}
        </div>
      )}
    </li>
  )
}

const SHOWN = 6

/**
 * Web research over the viewer's projects (GET /api/research/summary): how many were searched and have cited facts,
 * the live blockers by category and by state, and the newest blockers, each opening its project in the side panel.
 * The public gets the counts and, of the blockers, the checked sweep's headlines and dates only.
 */
export function ResearchPanel() {
  const { data: s, error } = useResearchSummary()
  const [all, setAll] = useState(false)

  if (error) return <Card title="Web research"><ApiErrorNote error={error} /></Card>
  if (!s) return <div className="h-40 animate-pulse rounded-xl bg-surface-input/70" aria-busy="true" aria-label="Loading web research" />

  const c = s.coverage
  const blockers = all ? s.topRecentBlockers : s.topRecentBlockers.slice(0, SHOWN)
  const states = s.byState.filter((r) => r.nProjectsNegativeLive > 0).slice(0, 8)
  const range = s.researchedOn.last
    ? `searched ${s.researchedOn.first && s.researchedOn.first !== s.researchedOn.last ? `${formatLooseDate(s.researchedOn.first)} to ` : ''}${formatLooseDate(s.researchedOn.last)}`
    : 'not searched yet'

  return (
    <Card
      title={<><Newspaper className="size-4 text-accent" /> Web research</>}
      info={s.note}
      titleRight={<span>{range}{s.agentLastRun && ` · news agent ${formatLooseDate(s.agentLastRun)}`}</span>}
    >
      <div className="grid grid-cols-2 gap-px border-b border-border-subtle bg-border-subtle lg:grid-cols-4">
        <Tile label="Projects researched" value={`${c.nSearched.toLocaleString('en-IN')} of ${c.nCurrent.toLocaleString('en-IN')}`}
          sub={`${c.nWithFacts.toLocaleString('en-IN')} with cited facts`} />
        <Tile label="Cited facts" value={c.nFacts.toLocaleString('en-IN')}
          sub={c.nAgentFacts ? `${c.nAgentFacts} from news the local AI judged` : 'from the checked web sweep'} />
        <Tile label="Live blockers" value={c.nNegativeLive.toLocaleString('en-IN')} tone={c.nNegativeLive ? 'critical' : undefined}
          sub={`on ${c.nProjectsNegativeLive} project${c.nProjectsNegativeLive === 1 ? '' : 's'}, within ${s.liveWindowQuarters} quarters`} />
        <ByCategory s={s} />
      </div>

      <div className={cn('grid grid-cols-1', states.length > 0 && 'lg:grid-cols-3')}>
        <div className={cn(states.length > 0 && 'lg:col-span-2 lg:border-r lg:border-border-subtle')}>
          <h4 className="px-5 pt-4 text-sm font-medium text-fg-base">Newest blockers</h4>
          {s.topRecentBlockers.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-fg-dimmed">
              No live blocker in the research for your projects. Not the same as no problem: news coverage favours large, much-reported projects.
            </div>
          ) : (
            <>
              <ul className="divide-y divide-border-subtle/70">
                {blockers.map((b, i) => <Blocker key={b.factId ?? `${b.url}-${i}`} b={b} />)}
              </ul>
              {s.topRecentBlockers.length > SHOWN && (
                <button type="button" onClick={() => setAll((v) => !v)}
                  className="w-full border-t border-border-subtle px-5 py-2.5 text-center text-xs font-medium text-accent hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                  {all ? 'Show fewer' : `Show all ${s.topRecentBlockers.length}`}
                </button>
              )}
            </>
          )}
        </div>
        {states.length > 0 && (
          <div className="border-t border-border-subtle px-5 py-4 lg:border-t-0">
            <h4 className="mb-2 text-sm font-medium text-fg-base">Where they are</h4>
            <ul className="space-y-1.5">
              {states.map((r) => (
                <li key={r.state ?? 'unknown'} className="flex items-baseline justify-between gap-3 text-xs">
                  <span className="truncate text-fg-base">{r.state ?? 'state unknown'}</span>
                  <span className="shrink-0 tabular-nums text-fg-muted" title="projects with a live blocker, of the projects researched in this state">
                    <span className="font-semibold text-critical">{r.nProjectsNegativeLive}</span> of {r.nSearched} projects
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
