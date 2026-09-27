import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ResponsiveContainer, Tooltip, Treemap } from 'recharts'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Page, PageHeader } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useBottleneck, useBottlenecks } from '@/lib/queries'
import { EVENT_CATEGORY, categoryLabel } from '@/lib/riskPalette'
import { cn, formatDate, formatINR, formatINRShort, formatProb, orDash } from '@/lib/formatters'
import type { TreemapNode } from 'recharts/types/util/types'
import type { Bottleneck } from '@/contracts/intel'

const CAVEAT = 'projects that would be affected — not a claim that resolving it speeds them up'
const OTHER_COLOR = { color: '#9a968c', ink: '#0b0b0b' }
const colorOf = (c: string) => EVENT_CATEGORY[c] ?? OTHER_COLOR

/** the one wording a bottleneck headline uses (guide §6.1) */
const headline = (b: Bottleneck) =>
  `Blocking ${b.nProjects} project${b.nProjects === 1 ? '' : 's'} worth ${formatINR(b.capitalExposedCr)}`

/** 'state · authority' (state first: a narrow treemap cell cuts the end); a state rollup spans every authority */
function place(b: Bottleneck): string {
  const who = b.level === 'state' ? 'all authorities' : !b.authority || b.authority === 'unspecified' ? 'authority not named' : b.authority
  return `${b.state ?? 'state unknown'} · ${who}`
}

type Node = Bottleneck & { name: string; size: number }

interface CellProps {
  x?: number
  y?: number
  width?: number
  height?: number
  bottleneckId?: string
  category?: string
  name?: string
  nProjects?: number
  capitalExposedCr?: number
  selected?: string | null
}

/** one treemap rectangle; recharts also calls this for the root, which has no bottleneckId */
function Cell({ x = 0, y = 0, width = 0, height = 0, bottleneckId, category = '', name, nProjects, capitalExposedCr, selected }: CellProps) {
  if (!bottleneckId) return null
  const { color, ink } = colorOf(category)
  const on = selected === bottleneckId
  return (
    <g style={{ cursor: 'pointer' }}>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={color}
        fillOpacity={selected && !on ? 0.45 : 0.9}
        stroke={on ? '#1f2937' : 'hsl(var(--color-surface-panel))'}
        strokeWidth={on ? 3 : 2}
      />
      {width > 90 && height > 36 && (
        <text x={x + 8} y={y + 18} fill={ink} fontSize={12} fontFamily="IBM Plex Mono, monospace" fontWeight={600}>
          {name && name.length * 6.6 > width - 16 ? `${name.slice(0, Math.max(4, Math.floor((width - 16) / 6.6) - 1))}…` : name}
        </text>
      )}
      {width > 90 && height > 52 && (
        <text x={x + 8} y={y + 34} fill={ink} fontSize={12} fontFamily="IBM Plex Mono, monospace">
          {nProjects} projects · {formatINRShort(capitalExposedCr ?? 0)}
        </text>
      )}
    </g>
  )
}

function NodeTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Node }> }) {
  const b = payload?.[0]?.payload
  if (!active || !b?.bottleneckId) return null
  return (
    <div className="border border-border-default bg-surface-panel px-3 py-2 text-xs text-fg-base space-y-0.5 max-w-[320px] rounded-lg shadow-pop overflow-hidden">
      <div className="font-semibold">{categoryLabel(b.category)} · {place(b)}</div>
      <div>{headline(b)}</div>
      <div className="text-fg-muted">
        {b.nCriticalHigh} critical/high · mean P(slip, 2q) {orDash(b.meanPAny2q, (p) => formatProb(p))} · {b.nSignals} news signals
      </div>
      <div className="text-fg-dimmed">
        open in remarks{b.nSignals > 0 && ' or news'} {orDash(b.earliestFirstSeen, formatDate)} → {orDash(b.lastSeen, formatDate)}
      </div>
    </div>
  )
}

function Members({ id }: { id: string }) {
  const [page, setPage] = useState(1)
  const { data, error, isFetching } = useBottleneck(id, page)
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1
  if (error) return <ApiErrorNote error={error} />
  if (!data) return <div className="px-5 py-8 text-center text-xs text-fg-dimmed">loading projects...</div>
  const b = data.bottleneck
  return (
    <>
      <div className="border-b border-border-subtle px-5 py-3 space-y-1">
        <div className="text-sm font-semibold text-fg-base">{headline(b)}</div>
        <div className="text-xs text-fg-muted">{categoryLabel(b.category)} · {place(b)}</div>
        <div className="text-xs text-fg-dimmed">{CAVEAT}</div>
      </div>
      <div className={cn('divide-y divide-border-subtle transition-opacity', isFetching && 'opacity-60')}>
        {data.members.map((m) => (
          <div key={m.key} className="px-5 py-2.5 space-y-1">
            <div className="flex items-center gap-2 min-w-0">
              <Badge tier={m.tier} />
              <Link to={`/projects/${m.key}`} className="text-xs text-accent hover:underline shrink-0">
                {m.key}
              </Link>
              <span className="truncate text-xs text-fg-base" title={m.name ?? undefined}>{m.name ?? ''}</span>
            </div>
            <div className="text-xs text-fg-dimmed">
              P(slip, 2q) {orDash(m.pAny2q, (p) => formatProb(p))} · {orDash(m.anticipatedCostCr, formatINR)} ·{' '}
              {m.agency ?? 'agency unknown'}
            </div>
            {m.evidence.map((e, i) => (
              <div key={i} className="border-l-2 border-border-default pl-2 text-xs leading-snug text-fg-muted">
                <span className="text-xs text-fg-dimmed">
                  {e.kind === 'signal' ? 'news' : 'report remark'} {orDash(e.firstSeen, formatDate)}
                  {e.lastSeen && e.lastSeen !== e.firstSeen && ` → ${formatDate(e.lastSeen)}`}:{' '}
                </span>
                {e.evidence ?? '(no text)'}
                {e.url ? (
                  <a href={e.url} target="_blank" rel="noreferrer" className="ml-1 text-xs text-accent hover:underline">
                    source ↗
                  </a>
                ) : (
                  e.sourceDocId && (
                    <span className="block text-xs text-fg-dimmed truncate" title={e.sourceDocId}>
                      {e.sourceDocId.split('/').pop()}
                      {e.sourcePage !== null && ` p.${e.sourcePage}`}
                    </span>
                  )
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed">
          <span>page {page} of {pages}</span>
          <span className="flex gap-2">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </span>
        </div>
      )}
    </>
  )
}

const chip = (on: boolean) =>
  cn(
    'border border-border-default px-2 py-0.5 text-xs',
    on ? 'bg-fg-base text-fg-inverse' : 'text-fg-muted hover:text-fg-base'
  )
const selectCls =
  'bg-surface-input border border-border-default px-2 py-0.5 text-xs font-sans font-semibold text-fg-muted focus:outline-none max-w-[200px]'

/**
 * Bottleneck Intelligence (/bottlenecks, guide §6.1) over /api/bottlenecks: current projects that
 * share an open land or clearance issue by authority and state, sized by the capital that would
 * be affected. A grouping of report remarks and linked news, never a causal claim.
 */
export function Bottlenecks() {
  const { data, error } = useBottlenecks()
  const [level, setLevel] = useState<'authority' | 'state'>('authority')
  const [category, setCategory] = useState<string | null>(null)
  const [state, setState] = useState<string | null>(null)
  const [sort, setSort] = useState<'capital' | 'count'>('capital')
  const [selected, setSelected] = useState<string | null>(null)

  const items = data?.items ?? []
  const categories = [...new Set(items.map((b) => b.category))].sort()
  const states = [...new Set(items.map((b) => b.state).filter((s): s is string => !!s))].sort()
  const shown = items
    .filter((b) => b.level === level && (!category || b.category === category) && (!state || b.state === state))
    .sort((a, b) =>
      sort === 'capital' ? b.capitalExposedCr - a.capitalExposedCr : b.nProjects - a.nProjects || b.capitalExposedCr - a.capitalExposedCr
    )
  const nodes: Node[] = shown.map((b) => ({ ...b, name: place(b), size: b.capitalExposedCr }))
  const lastEvidence = items.map((b) => b.lastSeen).filter((d): d is string => !!d).sort().pop()
  const s = data?.summary

  return (
    <Page>
      <PageHeader
        title="Bottlenecks"
        subtitle="Open issues shared by several current projects in one place"
        info={<>Each cluster lists the {CAVEAT}.</>}
        actions={
          data && (
            <span className="text-xs text-fg-dimmed">
              as of {formatDate(data.asof)}
              {s?.n_bottlenecks !== undefined && ` · ${s.n_bottlenecks} clusters + ${s.n_rollups} state rollups`}
              {s?.n_projects !== undefined && ` · ${s.n_projects} projects`}
              {s?.capital_exposed_cr !== undefined && ` · ${formatINRShort(s.capital_exposed_cr)}`}
            </span>
          )
        }
      />

      <div className="border border-warning/40 bg-warning/10 px-4 py-2 text-xs text-warning space-y-0.5">
        <div>
          Issues come from report remarks, which are free text only through 2023; after that only linked news
          {s?.signals_used !== undefined && ` (${s.signals_used} severe items used)`} can add to a cluster
          {lastEvidence && ` — latest evidence here: ${formatDate(lastEvidence)}`}.
        </div>
        <div>A cluster needs {s?.min_projects ?? 3} or more current projects. {s?.note}</div>
      </div>

      {error ? (
        <Card>
          <ApiErrorNote error={error} />
        </Card>
      ) : !data ? (
        <div className="h-48 flex items-center justify-center text-xs text-fg-dimmed">loading bottlenecks...</div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {(['authority', 'state'] as const).map((l) => (
              <button key={l} onClick={() => { setLevel(l); setSelected(null) }} className={chip(level === l)}>
                {l === 'authority' ? 'by authority' : 'state rollups'}
              </button>
            ))}
            <span className="text-border-strong">│</span>
            <button onClick={() => setCategory(null)} className={chip(category === null)}>all</button>
            {categories.map((c) => (
              <button key={c} onClick={() => setCategory(c)} className={chip(category === c)}>
                <span className="inline-block h-2 w-2 mr-1.5" style={{ background: colorOf(c).color }} />
                {categoryLabel(c)}
              </button>
            ))}
            <span className="text-border-strong">│</span>
            <select className={selectCls} value={state ?? ''} onChange={(e) => setState(e.target.value || null)}>
              <option value="">all states</option>
              {states.map((st) => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>
            <span className="text-border-strong">│</span>
            <span className="text-xs text-fg-dimmed">sort</span>
            <button onClick={() => setSort('capital')} className={chip(sort === 'capital')}>capital</button>
            <button onClick={() => setSort('count')} className={chip(sort === 'count')}>projects</button>
          </div>

          {shown.length === 0 ? (
            <Card>
              <div className="px-5 py-8 text-center text-xs text-fg-dimmed">
                no cluster matches these filters — not the same as no open issues: remarks stop in 2023
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
              <div className="lg:col-span-2 space-y-4">
                <Card title={`Capital that would be affected · ${shown.length}`}>
                  <div className="h-[380px] p-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <Treemap
                        data={nodes}
                        dataKey="size"
                        isAnimationActive={false}
                        content={<Cell selected={selected} />}
                        onClick={(n: TreemapNode) => typeof n.bottleneckId === 'string' && setSelected(n.bottleneckId)}
                      >
                        <Tooltip content={<NodeTooltip />} />
                      </Treemap>
                    </ResponsiveContainer>
                  </div>
                  <div className="border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed">
                    area: capital of the member projects · colour: issue category · click a block for its projects
                  </div>
                </Card>

                <Card title="Clusters">
                  <div className="divide-y divide-border-subtle">
                    {shown.map((b) => (
                      <button
                        key={b.bottleneckId}
                        onClick={() => setSelected(b.bottleneckId)}
                        className={cn(
                          'block w-full px-5 py-3 text-left hover:bg-surface-elevated',
                          selected === b.bottleneckId && 'bg-surface-elevated'
                        )}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="flex items-center gap-2 text-sm font-semibold text-fg-base">
                            <span className="inline-block h-2.5 w-2.5" style={{ background: colorOf(b.category).color }} />
                            {headline(b)}
                          </span>
                          <span className="text-xs text-fg-muted">
                            {categoryLabel(b.category)} · {place(b)}
                          </span>
                        </div>
                        <div className="text-xs text-fg-dimmed mt-0.5">
                          {b.nCriticalHigh} critical/high · mean P(slip, 2q) {orDash(b.meanPAny2q, (p) => formatProb(p))} ·{' '}
                          {b.nSignals} news signals · open {orDash(b.earliestFirstSeen, formatDate)} → {orDash(b.lastSeen, formatDate)}
                        </div>
                        {b.evidence[0] && <div className="mt-1 text-xs text-fg-muted line-clamp-1">{b.evidence[0]}</div>}
                      </button>
                    ))}
                  </div>
                </Card>
              </div>

              <Card
                title="Projects that would be affected"
                titleRight={
                  selected && (
                    <button onClick={() => setSelected(null)} className="text-xs text-fg-dimmed hover:text-fg-base">
                      close ✕
                    </button>
                  )
                }
              >
                {selected ? (
                  <Members key={selected} id={selected} />
                ) : (
                  <div className="px-5 py-8 text-center text-xs text-fg-dimmed">
                    pick a cluster to list its projects and the remarks or news behind each
                  </div>
                )}
              </Card>
            </div>
          )}
        </>
      )}
    </Page>
  )
}
