import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ResponsiveContainer, Tooltip, Treemap } from 'recharts'
import { Building2, CalendarClock, Gauge, Newspaper, ShieldAlert } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Input'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Page, PageHeader } from '@/components/layout/Page'
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

/** where a cluster's evidence comes from: remarks, plus news when it has signals */
const sourceOf = (b: Bottleneck) => (b.nSignals > 0 ? 'remarks or news' : 'remarks')

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
  const fit = Math.max(4, Math.floor((width - 16) / 7) - 1)
  return (
    <g style={{ cursor: 'pointer' }}>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={6}
        fill={color}
        fillOpacity={selected && !on ? 0.45 : 0.9}
        stroke={on ? '#1f2937' : 'hsl(var(--color-surface-panel))'}
        strokeWidth={on ? 3 : 2}
      />
      {width > 90 && height > 36 && (
        <text x={x + 8} y={y + 19} fill={ink} fontSize={12} fontFamily="IBM Plex Sans, sans-serif" fontWeight={600}>
          {name && name.length > fit ? `${name.slice(0, fit)}…` : name}
        </text>
      )}
      {width > 90 && height > 54 && (
        <text x={x + 8} y={y + 36} fill={ink} fontSize={12} fontFamily="IBM Plex Sans, sans-serif" opacity={0.85}>
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
    <div className="max-w-[320px] space-y-0.5 overflow-hidden rounded-lg border border-border-default bg-surface-panel px-3 py-2 text-xs text-fg-base shadow-pop">
      <div className="font-semibold">{categoryLabel(b.category)} · {place(b)}</div>
      <div>{headline(b)}</div>
      <div className="text-fg-muted">
        {b.nCriticalHigh} critical/high · mean P(slip, 2q) {orDash(b.meanPAny2q, (p) => formatProb(p))} · {b.nSignals} news signals
      </div>
      <div className="text-fg-dimmed">
        open in {sourceOf(b)} {orDash(b.earliestFirstSeen, formatDate)} → {orDash(b.lastSeen, formatDate)}
      </div>
    </div>
  )
}

/** small icon + figure pairs under a cluster headline */
function ClusterStats({ b }: { b: Bottleneck }) {
  const item = 'flex items-center gap-1'
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-dimmed">
      <span className={cn(item, b.nCriticalHigh > 0 && 'text-critical')} title="critical or high tier members">
        <ShieldAlert className="size-3.5" /> {b.nCriticalHigh} critical/high
      </span>
      <span className={item} title="mean P(slip, 2q) of the members">
        <Gauge className="size-3.5" /> {orDash(b.meanPAny2q, (p) => formatProb(p))}
      </span>
      <span className={item} title="linked news signals">
        <Newspaper className="size-3.5" /> {b.nSignals}
      </span>
      <span className={item} title={`open in ${sourceOf(b)}`}>
        <CalendarClock className="size-3.5" /> {orDash(b.earliestFirstSeen, formatDate)} → {orDash(b.lastSeen, formatDate)}
      </span>
    </div>
  )
}

function Members({ id }: { id: string }) {
  const [page, setPage] = useState(1)
  const { data, error, isFetching } = useBottleneck(id, page)
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1
  if (error) return <ApiErrorNote error={error} />
  if (!data) return <div className="px-5 py-8 text-center text-sm text-fg-dimmed">loading projects...</div>
  const b = data.bottleneck
  return (
    <>
      <div className="border-b border-border-subtle px-5 py-3">
        <div className="text-sm font-semibold text-fg-base">{headline(b)}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-muted">
          <span className="size-2 rounded-full" style={{ background: colorOf(b.category).color }} />
          {categoryLabel(b.category)} · {place(b)}
        </div>
      </div>
      <div className={cn('divide-y divide-border-subtle transition-opacity', isFetching && 'opacity-60')}>
        {data.members.map((m) => (
          <div key={m.key} className="space-y-1.5 px-5 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <Badge tier={m.tier} />
              <Link to={`/projects/${m.key}`} className="shrink-0 text-xs text-accent hover:underline">
                {m.key}
              </Link>
              <span className="truncate text-sm text-fg-base" title={m.name ?? undefined}>{m.name ?? ''}</span>
            </div>
            <div className="text-xs text-fg-dimmed">
              P(slip, 2q) {orDash(m.pAny2q, (p) => formatProb(p))} · {orDash(m.anticipatedCostCr, formatINR)} ·{' '}
              {m.agency ?? 'agency unknown'}
            </div>
            {m.evidence.map((e, i) => (
              <div key={i} className="rounded-lg bg-surface-elevated/70 px-3 py-2 text-xs leading-snug text-fg-muted">
                <span className="mb-0.5 flex items-center gap-1.5 text-fg-dimmed">
                  <Badge variant={e.kind === 'signal' ? 'accent' : 'muted'}>{e.kind === 'signal' ? 'news' : 'report remark'}</Badge>
                  {orDash(e.firstSeen, formatDate)}
                  {e.lastSeen && e.lastSeen !== e.firstSeen && ` → ${formatDate(e.lastSeen)}`}
                  {e.url && (
                    <a href={e.url} target="_blank" rel="noreferrer" className="ml-auto text-accent hover:underline">
                      source ↗
                    </a>
                  )}
                </span>
                {e.evidence ?? '(no text)'}
                {!e.url && e.sourceDocId && (
                  <span className="mt-0.5 block truncate text-fg-dimmed" title={e.sourceDocId}>
                    {e.sourceDocId.split('/').pop()}
                    {e.sourcePage !== null && ` p.${e.sourcePage}`}
                  </span>
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
    'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors',
    on ? 'bg-fg-base text-fg-inverse shadow-sm' : 'text-fg-muted hover:bg-surface-elevated hover:text-fg-base'
  )

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
        info={
          <>
            <p>Each cluster lists the {CAVEAT}.</p>
            <p>
              Issues come from report remarks, which are free text only through 2023; after that only linked news
              {s?.signals_used !== undefined && ` (${s.signals_used} severe items used)`} can add to a cluster.
            </p>
            <p>A cluster needs {s?.min_projects ?? 3} or more current projects. {s?.note}</p>
          </>
        }
        actions={
          data && (
            <span className="text-xs text-fg-dimmed">
              as of {formatDate(data.asof)}
              {s?.n_bottlenecks !== undefined && ` · ${s.n_bottlenecks} clusters + ${s.n_rollups} state rollups`}
              {s?.n_projects !== undefined && ` · ${s.n_projects} projects`}
              {s?.capital_exposed_cr !== undefined && ` · ${formatINRShort(s.capital_exposed_cr)}`}
              {lastEvidence && ` · latest evidence ${formatDate(lastEvidence)}`}
            </span>
          )
        }
      />

      {error ? (
        <Card>
          <ApiErrorNote error={error} />
        </Card>
      ) : !data ? (
        <div className="h-48 flex items-center justify-center text-sm text-fg-dimmed">loading bottlenecks...</div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-subtle bg-surface-panel px-3 py-2 shadow-card">
            <span className="flex rounded-full bg-surface-elevated p-0.5">
              {(['authority', 'state'] as const).map((l) => (
                <button key={l} onClick={() => { setLevel(l); setSelected(null) }} className={chip(level === l)}>
                  {l === 'authority' ? 'By authority' : 'State rollups'}
                </button>
              ))}
            </span>
            <button onClick={() => setCategory(null)} className={chip(category === null)}>All issues</button>
            {categories.map((c) => (
              <button key={c} onClick={() => setCategory(c)} className={chip(category === c)}>
                <span className="size-2 rounded-full" style={{ background: colorOf(c).color }} />
                {categoryLabel(c)}
              </button>
            ))}
            <span className="ml-auto flex items-center gap-2">
              <Select aria-label="state" value={state ?? ''} onChange={(e) => setState(e.target.value || null)}>
                <option value="">All states</option>
                {states.map((st) => (
                  <option key={st} value={st}>{st}</option>
                ))}
              </Select>
              <Select aria-label="sort" value={sort} onChange={(e) => setSort(e.target.value as 'capital' | 'count')}>
                <option value="capital">Sort by capital</option>
                <option value="count">Sort by projects</option>
              </Select>
            </span>
          </div>

          {shown.length === 0 ? (
            <Card>
              <div className="px-5 py-8 text-center text-sm text-fg-dimmed">
                no cluster matches these filters — not the same as no open issues: remarks stop in 2023
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
              <div className="lg:col-span-2 space-y-5">
                <Card
                  title={`Capital that would be affected · ${shown.length}`}
                  info="Area: capital of the member projects. Colour: issue category. Click a block for its projects."
                >
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
                </Card>

                <Card title="Clusters">
                  <div className="divide-y divide-border-subtle">
                    {shown.map((b) => (
                      <button
                        key={b.bottleneckId}
                        onClick={() => setSelected(b.bottleneckId)}
                        className={cn(
                          'block w-full px-5 py-3 text-left transition-colors hover:bg-surface-elevated',
                          selected === b.bottleneckId && 'bg-accent/10 shadow-[inset_3px_0_0_hsl(var(--color-accent))]'
                        )}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="flex items-center gap-2 text-sm font-semibold text-fg-base">
                            <span className="size-2.5 rounded-full" style={{ background: colorOf(b.category).color }} />
                            {headline(b)}
                          </span>
                          <span className="flex items-center gap-1 text-xs text-fg-muted">
                            <Building2 className="size-3.5 text-fg-dimmed" /> {categoryLabel(b.category)} · {place(b)}
                          </span>
                        </div>
                        <ClusterStats b={b} />
                        {b.evidence[0] && <div className="mt-1.5 text-xs text-fg-muted line-clamp-1">{b.evidence[0]}</div>}
                      </button>
                    ))}
                  </div>
                </Card>
              </div>

              <Card
                title="Projects that would be affected"
                titleRight={
                  selected && (
                    <button onClick={() => setSelected(null)} className="text-fg-dimmed hover:text-fg-base">
                      close ✕
                    </button>
                  )
                }
              >
                {selected ? (
                  <Members key={selected} id={selected} />
                ) : (
                  <div className="px-5 py-8 text-center text-sm text-fg-dimmed">
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
