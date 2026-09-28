import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useProjectPanel } from '@/lib/useProjectPanel'
import {
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { Info } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { OutlookChip } from '@/components/ui/OutlookChip'
import { Page, PageHeader } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAgencyMatrix, useAgencyProjects } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { outlookOf } from '@/lib/outlook'
import { COST_PHRASE, SCHEDULE_PHRASE, peerClause } from '@/lib/agencyWords'
import { RankedAgencies } from './agencies/RankedAgencies'
import { AgencyDotPlot } from './agencies/AgencyDotPlot'
import {
  cn, formatBiasCi as rawCi, formatDate, formatINR, formatINRShort, formatProb, formatRatioRange as ci,
  formatSignedRatio as signedPct, orDash,
} from '@/lib/formatters'
import type { AgencyPoint } from '@/contracts/intel'

/**
 * Colour = ministry: three fixed slots and "other" (a scatter validates only three
 * categorical hues against each other; the rest fold into grey). Fixed by name, so a
 * toggle never repaints an agency.
 */
const MINISTRY_COLOR: Array<[string, string, string]> = [
  ['Ministry of Road Transport & Highways', 'Road Transport', '#2a78d6'],
  ['Ministry of Railways', 'Railways', '#eb6834'],
  ['Ministry of Power', 'Power', '#1baf7a'],
]
const OTHER = { label: 'Other / unknown', color: '#9a968c' }

type Plotted = AgencyPoint & { x: number; y: number }

/** [lo, hi, ticks] in percent: a round step, 0 always inside with room on both sides */
function axis(values: number[]): [number, number, number[]] {
  const lo = Math.min(-10, ...values)
  const hi = Math.max(10, ...values)
  const step = [10, 20, 25, 50, 100, 200].find((s) => (hi - lo) / s <= 8) ?? 500
  const a = Math.floor(lo / step) * step
  const b = Math.ceil(hi / step) * step
  return [a, b, Array.from({ length: (b - a) / step + 1 }, (_, i) => a + i * step)]
}

function AgencyTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Plotted }> }) {
  const a = payload?.[0]?.payload
  if (!active || !a) return null
  return (
    <div className="border border-border-default bg-surface-panel px-3 py-2 text-xs text-fg-base space-y-0.5 max-w-[320px] rounded-lg shadow-pop overflow-hidden">
      <div className="font-semibold">{a.agency}</div>
      <div className="text-fg-dimmed">{a.ministry ?? 'ministry unknown'} · {a.sector ?? 'sector unknown'}</div>
      <div className="text-fg-muted">
        n {a.nProjects} projects · {a.nOpen} open · {formatINRShort(a.capitalCr)}
      </div>
      {/* the CI is of the raw median: when the shown one is shrunk, the raw value goes next to its CI */}
      <div>
        schedule median <span className="font-semibold">{signedPct(a.scheduleBias)}</span>
        <span className="text-fg-dimmed">{rawCi(a.shrunk, a.scheduleBiasRaw, a.scheduleBiasCiLo, a.scheduleBiasCiHi)}</span>
      </div>
      <div>
        cost median <span className="font-semibold">{signedPct(a.costBias)}</span>
        <span className="text-fg-dimmed">{rawCi(a.shrunk, a.costBiasRaw, a.costBiasCiLo, a.costBiasCiHi)} · n {a.nCost}</span>
      </div>
      {a.shrunk && (
        <div className="text-fg-muted">
          n &lt; 10: shown median shrunk toward the sector (weight {orDash(a.shrinkWeight, (w) => w.toFixed(2))})
        </div>
      )}
      <div className="text-fg-muted">
        trend {orDash(a.trend, (t) => `${t > 0 ? '+' : ''}${Math.round(t * 100)} pp`)} (recent n {a.nRecent})
      </div>
    </div>
  )
}

function MatrixChart({ points, onPick }: { points: AgencyPoint[]; onPick: (a: string) => void }) {
  const plotted: Plotted[] = points
    .filter((p) => p.scheduleBias !== null && p.costBias !== null)
    .map((p) => ({ ...p, x: (p.scheduleBias ?? 0) * 100, y: (p.costBias ?? 0) * 100 }))
  // both zero lines always inside the plot, so all four quadrants show
  const [x0, x1, xTicks] = axis(plotted.map((p) => p.x))
  const [y0, y1, yTicks] = axis(plotted.map((p) => p.y))
  const groups = [
    ...MINISTRY_COLOR.map(([m, label, color]) => ({ label, color, rows: plotted.filter((p) => p.ministry === m) })),
    { ...OTHER, rows: plotted.filter((p) => !MINISTRY_COLOR.some(([m]) => m === p.ministry)) },
  ]
  const quadrant = (value: string, position: 'insideTopLeft' | 'insideTopRight' | 'insideBottomLeft' | 'insideBottomRight') => ({
    value,
    position,
    fill: 'hsl(var(--color-fg-dimmed))',
    fontSize: 12,
    fontFamily: 'IBM Plex Mono, monospace',
  })

  return (
    <div>
      <div className="h-[460px] px-2 pt-3">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid stroke="hsl(var(--color-border-subtle))" strokeDasharray="2 4" />
            <ReferenceArea x1={0} x2={x1} y1={0} y2={y1} fillOpacity={0} label={quadrant('late & over budget', 'insideTopRight')} />
            <ReferenceArea x1={x0} x2={0} y1={0} y2={y1} fillOpacity={0} label={quadrant('over budget', 'insideTopLeft')} />
            <ReferenceArea x1={0} x2={x1} y1={y0} y2={0} fillOpacity={0} label={quadrant('late', 'insideBottomRight')} />
            <ReferenceArea x1={x0} x2={0} y1={y0} y2={0} fillOpacity={0} label={quadrant('on time & on budget', 'insideBottomLeft')} />
            <ReferenceLine x={0} stroke="hsl(var(--color-border-strong))" />
            <ReferenceLine y={0} stroke="hsl(var(--color-border-strong))" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[x0, x1]}
              ticks={xTicks}
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fontSize: 12, fontFamily: 'IBM Plex Mono, monospace', fill: 'hsl(var(--color-fg-dimmed))' }}
              label={{ value: 'schedule bias: median actual / planned duration − 1', position: 'insideBottom', offset: -16, fontSize: 12, fill: 'hsl(var(--color-fg-muted))' }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[y0, y1]}
              ticks={yTicks}
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fontSize: 12, fontFamily: 'IBM Plex Mono, monospace', fill: 'hsl(var(--color-fg-dimmed))' }}
              label={{ value: 'cost bias', angle: -90, position: 'insideLeft', fontSize: 12, fill: 'hsl(var(--color-fg-muted))' }}
            />
            <ZAxis type="number" dataKey="capitalCr" range={[30, 900]} />
            <Tooltip content={<AgencyTooltip />} cursor={{ strokeDasharray: '2 2' }} />
            {groups.map((g) => (
              <Scatter
                key={g.label}
                name={g.label}
                data={g.rows}
                fill={g.color}
                fillOpacity={0.7}
                stroke="hsl(var(--color-surface-panel))"
                strokeWidth={2}
                cursor="pointer"
                onClick={(d: { payload?: Plotted }) => d.payload && onPick(d.payload.agency)}
              />
            ))}
            {/* the signed-in agency official's own agency, ringed over its bubble */}
            <Scatter
              name="your agency"
              data={plotted.filter((p) => p.isSelf)}
              fill="none"
              stroke="hsl(var(--color-fg-base))"
              strokeWidth={3}
              isAnimationActive={false}
              onClick={(d: { payload?: Plotted }) => d.payload && onPick(d.payload.agency)}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle px-5 py-2.5 text-xs text-fg-muted">
        {groups.map((g) => (
          <span key={g.label} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: g.color }} />
            {g.label} <span className="text-fg-dimmed">{g.rows.length}</span>
          </span>
        ))}
        {plotted.some((p) => p.isSelf) && (
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full ring-2 ring-fg-base" /> your agency
          </span>
        )}
        <span className="ml-auto text-fg-dimmed">
          size = capital
          {plotted.length < points.length && ` · ${points.length - plotted.length} without a bias not drawn`}
        </span>
      </div>
    </div>
  )
}

function Leaderboard({ points, selected, onPick }: { points: AgencyPoint[]; selected: string | null; onPick: (a: string) => void }) {
  const rows = [...points].sort((a, b) => (b.scheduleBias ?? -Infinity) - (a.scheduleBias ?? -Infinity))
  return (
    <div className="overflow-x-auto max-h-[520px]">
      <table className="w-full whitespace-nowrap text-xs font-mono border-collapse">
        <thead className="sticky top-0 bg-surface-elevated font-sans">
          <tr className="border-b border-border-subtle text-fg-muted">
            <th className="py-2 px-3 text-left font-medium">Agency</th>
            <th className="py-2 px-3 text-right font-medium">n</th>
            <th className="py-2 px-3 text-right font-medium">Open</th>
            <th className="py-2 px-3 text-right font-medium">Capital</th>
            <th className="py-2 px-3 text-right font-medium">Schedule bias ▼</th>
            <th className="py-2 px-3 text-right font-medium">90% CI</th>
            <th className="py-2 px-3 text-right font-medium">Cost bias</th>
            <th className="py-2 px-3 text-right font-medium">90% CI</th>
            <th className="py-2 px-3 text-right font-medium">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr
              key={a.agency}
              onClick={() => onPick(a.agency)}
              className={cn(
                'border-b border-border-subtle cursor-pointer hover:bg-surface-elevated',
                selected === a.agency && 'bg-surface-elevated',
                a.isSelf && 'bg-accent/10 font-semibold'
              )}
            >
              <td className="py-2 px-3 font-sans text-sm text-fg-base max-w-[260px] truncate" title={a.ministry ?? undefined}>
                {a.agency}
                {a.shrunk && <span className="ml-1 text-fg-dimmed" title="n < 10: shrunk toward the sector median">*</span>}
              </td>
              <td className="py-1.5 px-3 text-right tabular-nums">{a.nProjects}</td>
              <td className="py-1.5 px-3 text-right tabular-nums text-fg-muted">{a.nOpen}</td>
              <td className="py-1.5 px-3 text-right tabular-nums text-fg-muted">{formatINRShort(a.capitalCr)}</td>
              <td className="py-1.5 px-3 text-right tabular-nums font-semibold">{signedPct(a.scheduleBias)}</td>
              <td className="py-1.5 px-3 text-right tabular-nums text-fg-dimmed">{ci(a.scheduleBiasCiLo, a.scheduleBiasCiHi)}</td>
              <td className="py-1.5 px-3 text-right tabular-nums">{signedPct(a.costBias)}</td>
              <td className="py-1.5 px-3 text-right tabular-nums text-fg-dimmed">{ci(a.costBiasCiLo, a.costBiasCiHi)}</td>
              <td className="py-1.5 px-3 text-right tabular-nums text-fg-muted">
                {orDash(a.trend, (t) => `${t > 0 ? '+' : ''}${Math.round(t * 100)} pp`)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 py-2 text-xs text-fg-dimmed">* n &lt; 10: the shown median is shrunk toward the sector; its 90% CI is of the raw median</div>
    </div>
  )
}

/** this agency against its sector: two bars from zero (overrun right, under left) and the CI note */
function BiasCompare({ label, value, sector, note }: { label: string; value: number | null; sector: number | null; note: string }) {
  const scale = Math.max(0.1, Math.abs(value ?? 0), Math.abs(sector ?? 0))
  const bar = (v: number | null, cls: string) => (
    <div className="relative h-2 rounded-full bg-surface-input">
      <div className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
      {v !== null && (
        <div
          className={cn('absolute inset-y-0 rounded-full', cls)}
          style={v >= 0 ? { left: '50%', width: `${(v / scale) * 50}%` } : { right: '50%', width: `${(-v / scale) * 50}%` }}
        />
      )}
    </div>
  )
  return (
    <div className="space-y-1.5" title={note}>
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium text-fg-base">{label}</span>
        <span className="text-fg-dimmed">{note}</span>
      </div>
      <div className="grid grid-cols-[4.5rem_1fr_3rem] items-center gap-2 text-xs">
        <span className="text-fg-muted">this agency</span>
        {bar(value, (value ?? 0) > 0 ? 'bg-critical/80' : 'bg-stable/80')}
        <span className="text-right font-semibold tabular-nums text-fg-base">{signedPct(value)}</span>
        <span className="text-fg-muted">sector</span>
        {bar(sector, 'bg-fg-dimmed/50')}
        <span className="text-right tabular-nums text-fg-muted">{signedPct(sector)}</span>
      </div>
    </div>
  )
}

/** the agency's pattern in two sentences: its schedule and cost words on its past projects, and what its peers do */
function AgencySentences({ point, peers }: { point: AgencyPoint; peers: AgencyPoint[] }) {
  if (!point.scheduleWord) {
    return <p className="text-sm text-fg-muted">How this agency&rsquo;s projects usually finish is not available in words yet.</p>
  }
  const peer = peerClause(peers.filter((a) => a !== point && a.sector === point.sector), point.sector)
  return (
    <div className="space-y-1.5 text-sm leading-relaxed text-fg-base">
      <p>
        <span className="font-semibold">Schedule:</span> {SCHEDULE_PHRASE[point.scheduleWord].toLowerCase()}, on {point.nProjects} past project{point.nProjects === 1 ? '' : 's'}
        {peer && point.scheduleWord !== 'too few projects' ? `; ${peer}.` : '.'}
      </p>
      {point.costWord && (
        <p><span className="font-semibold">Cost:</span> {COST_PHRASE[point.costWord].toLowerCase()}, on {point.nCost} past project{point.nCost === 1 ? '' : 's'} with costs.</p>
      )}
    </div>
  )
}

function AgencyPanel({ agency, point, peers, numbers, onClose }: {
  agency: string
  point: AgencyPoint | undefined
  peers: AgencyPoint[]
  /** the developer: the bias bars and each project's probability too */
  numbers: boolean
  onClose: () => void
}) {
  const [page, setPage] = useState(1)
  const panel = useProjectPanel()
  const { data, error, isFetching } = useAgencyProjects(agency, page)
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1

  return (
    <Card
      title={agency}
      titleRight={
        <button type="button" onClick={onClose} className="rounded text-fg-dimmed hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-label="Close the agency">
          Close ✕
        </button>
      }
    >
      {point && (
        <div className="space-y-3 border-b border-border-subtle px-5 py-4">
          <div className="text-xs text-fg-muted">
            {point.ministry ?? 'ministry unknown'} · {point.sector ?? 'sector unknown'} · {point.nProjects} past projects · {point.nOpen} open
          </div>
          <AgencySentences point={point} peers={peers} />
          {numbers && (
            <>
              <BiasCompare
                label="Schedule"
                value={point.scheduleBias}
                sector={point.sectorScheduleBias}
                note={rawCi(point.shrunk, point.scheduleBiasRaw, point.scheduleBiasCiLo, point.scheduleBiasCiHi).trim()}
              />
              <BiasCompare
                label="Cost"
                value={point.costBias}
                sector={point.sectorCostBias}
                note={rawCi(point.shrunk, point.costBiasRaw, point.costBiasCiLo, point.costBiasCiHi).trim()}
              />
            </>
          )}
          {point.names && (
            <div className="truncate text-xs text-fg-dimmed" title={point.names}>printed as: {point.names}</div>
          )}
        </div>
      )}
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="space-y-2 px-5 py-4" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded bg-surface-input/60" />)}</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-muted">No open projects: its record is all completed work.</div>
      ) : (
        <div className={cn('divide-y divide-border-subtle transition-opacity', isFetching && 'opacity-60')}>
          <div className="px-5 py-2 text-xs text-fg-dimmed">
            {data.total} open projects · the riskiest first
          </div>
          {data.items.map((p) => (
            <button key={p.key} type="button" onClick={() => panel.open(p.key)} className="block w-full px-5 py-2.5 text-left transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm text-fg-base" title={p.name ?? undefined}>{p.name ?? p.key}</span>
                <OutlookChip outlook={outlookOf(p, numbers)} tier={p.tier} />
              </div>
              <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-fg-dimmed">
                <Badge tier={p.tier} />
                {p.override && <StalledBadge />}
                <span className="truncate">
                  {p.key}{numbers && ` · P(slip, 2q) ${orDash(p.pAny2q, (x) => formatProb(x))}`} · {orDash(p.anticipatedCostCr, formatINR)} · {p.state ?? 'state unknown'}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed">
          <span>page {page} of {pages}</span>
          <span className="flex gap-2">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </span>
        </div>
      )}
    </Card>
  )
}

type View = 'words' | 'chart' | 'table'
const VIEW_LABEL: Record<View, string> = { words: 'In words', chart: 'Matrix', table: 'Leaderboard' }

/**
 * Agencies (/agencies, guide §6.3) over /api/agencies/matrix: how each canonical agency's past projects usually
 * finished against the first plan, in words — a list grouped by schedule word with counts, capital and a cost word,
 * and a dot plot of agencies by sector and word. n < 5 is too few to say (hidden unless asked for). The developer
 * also gets the numeric matrix and leaderboard (medians, 90% CIs, shrinkage); nobody else sees a bias statistic.
 */
export function Agencies() {
  const { role } = useSession()
  const numbers = can(role, 'canSeeNumbers')
  const [showSmall, setShowSmall] = useState(false)
  const [picked, setView] = useState<View>('words')
  const view: View = numbers ? picked : 'words'
  // the picked agency lives in the URL (?agency=), so a link can open the page with it selected
  const [params, setParams] = useSearchParams()
  const selected = params.get('agency')
  const setSelected = (a: string | null) => setParams((p) => {
    const next = new URLSearchParams(p)
    if (a) next.set('agency', a)
    else next.delete('agency')
    return next
  }, { replace: true })
  const { data, error, isFetching } = useAgencyMatrix(showSmall)
  const point = data?.points.find((p) => p.agency === selected)

  return (
    <Page>
      <PageHeader
        title="Agencies"
        subtitle="How each agency's projects usually finish against the first plan"
        actions={
          data && (
            <span className="text-xs text-fg-dimmed">
              as of {formatDate(data.asof)} · {data.nAgencies} agencies · {data.nHidden} with fewer than 5 past projects{' '}
              {showSmall ? 'shown' : 'hidden'}
            </span>
          )
        }
      />

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
        <Card
          className={selected ? 'xl:col-span-2' : 'xl:col-span-3'}
          title={<>Which agencies usually finish late <span className="font-normal text-fg-dimmed">{data ? data.points.length : ''}{isFetching ? ' · updating' : ''}</span></>}
          info="Each agency's past projects against their first plan, in words. A pattern from history, not a verdict on a project. Pick an agency for its open projects."
          titleRight={
            <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
              <label className="flex cursor-pointer items-center gap-1.5">
                <input type="checkbox" checked={showSmall} onChange={(e) => setShowSmall(e.target.checked)} className="accent-[hsl(var(--color-accent))]" />
                include agencies with fewer than 5 past projects
              </label>
              {numbers && (
                <span className="flex rounded-full bg-surface-elevated p-0.5" role="group" aria-label="View">
                  {(['words', 'chart', 'table'] as const).map((v) => (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={view === v}
                      onClick={() => setView(v)}
                      className={cn(
                        'h-7 rounded-full px-3 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                        view === v ? 'bg-surface-panel text-fg-base shadow-sm' : 'hover:text-fg-base'
                      )}
                    >
                      {VIEW_LABEL[v]}
                    </button>
                  ))}
                </span>
              )}
            </div>
          }
        >
          {error ? (
            <ApiErrorNote error={error} />
          ) : !data ? (
            <div className="grid animate-pulse gap-2 p-5 lg:grid-cols-2" aria-busy="true">
              <div className="h-64 rounded-lg bg-surface-input/60" />
              <div className="h-64 rounded-lg bg-surface-input/60" />
            </div>
          ) : data.points.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-fg-muted">
              No agency has 5 or more past projects with a known planned duration yet.
            </div>
          ) : view === 'words' ? (
            <div className={cn('grid grid-cols-1', !selected && 'lg:grid-cols-2')}>
              <div className={cn('max-h-[640px] overflow-y-auto border-border-subtle', selected ? 'border-b' : 'border-b lg:border-b-0 lg:border-r')} data-lenis-prevent>
                <RankedAgencies points={data.points} selected={selected} onPick={setSelected} />
              </div>
              <AgencyDotPlot points={data.points} selected={selected} onPick={setSelected} />
            </div>
          ) : view === 'chart' ? (
            <MatrixChart points={data.points} onPick={setSelected} />
          ) : (
            <Leaderboard points={data.points} selected={selected} onPick={setSelected} />
          )}
          {data && numbers && (
            <details className="group border-t border-border-subtle px-5 py-2.5 text-xs text-fg-dimmed">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-fg-muted">
                <Info className="size-3.5" /> About this data
              </summary>
              <p className="mt-2 leading-relaxed">{data.method}</p>
            </details>
          )}
        </Card>

        {selected && (
          <AgencyPanel key={selected} agency={selected} point={point} peers={data?.points ?? []} numbers={numbers} onClose={() => setSelected(null)} />
        )}
      </div>
    </Page>
  )
}
