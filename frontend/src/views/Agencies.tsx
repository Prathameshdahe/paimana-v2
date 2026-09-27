import { useState } from 'react'
import { Link } from 'react-router-dom'
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
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAgencyMatrix, useAgencyProjects } from '@/lib/queries'
import { cn, formatDate, formatINR, formatINRShort, formatProb, orDash } from '@/lib/formatters'
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

/** ratio -> signed percent: 0.56 -> "+56%" */
const signedPct = (v: number | null) => orDash(v, (x) => `${x > 0 ? '+' : ''}${Math.round(x * 100)}%`)
const ci = (lo: number | null, hi: number | null) =>
  lo === null || hi === null ? '—' : `${signedPct(lo)} … ${signedPct(hi)}`

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

/** ' 90% CI [..]', or for a shrunk median ' raw +x%, 90% CI [..]' (the CI is of the raw median) */
function rawCi(shrunk: boolean, raw: number | null, lo: number | null, hi: number | null): string {
  return `${shrunk ? ` raw ${signedPct(raw)},` : ''} 90% CI ${ci(lo, hi)}`
}

function AgencyTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Plotted }> }) {
  const a = payload?.[0]?.payload
  if (!active || !a) return null
  return (
    <div className="border border-border-default bg-surface-panel px-3 py-2 font-mono text-[11px] text-fg-base shadow-lg space-y-0.5 max-w-[320px]">
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
    fontSize: 10,
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
              tick={{ fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', fill: 'hsl(var(--color-fg-dimmed))' }}
              label={{ value: 'schedule bias: median actual / planned duration − 1', position: 'insideBottom', offset: -16, fontSize: 10, fill: 'hsl(var(--color-fg-muted))' }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[y0, y1]}
              ticks={yTicks}
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', fill: 'hsl(var(--color-fg-dimmed))' }}
              label={{ value: 'cost bias', angle: -90, position: 'insideLeft', fontSize: 10, fill: 'hsl(var(--color-fg-muted))' }}
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
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
        {groups.map((g) => (
          <span key={g.label} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: g.color }} />
            {g.label} ({g.rows.length})
          </span>
        ))}
        <span>· bubble size: capital of current projects · click a bubble for its projects</span>
        {plotted.length < points.length && <span>· {points.length - plotted.length} without a bias not drawn</span>}
      </div>
    </div>
  )
}

function Leaderboard({ points, selected, onPick }: { points: AgencyPoint[]; selected: string | null; onPick: (a: string) => void }) {
  const rows = [...points].sort((a, b) => (b.scheduleBias ?? -Infinity) - (a.scheduleBias ?? -Infinity))
  return (
    <div className="overflow-x-auto max-h-[520px]">
      <table className="w-full text-[12px] font-mono border-collapse">
        <thead className="sticky top-0 bg-surface-base">
          <tr className="border-b border-border-default text-fg-muted">
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
              <td className="py-1.5 px-3 text-fg-base max-w-[260px] truncate" title={a.ministry ?? undefined}>
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
      <div className="px-3 py-2 font-mono text-[10px] text-fg-dimmed">* n &lt; 10: shown median shrunk toward the sector median; the CI is of the raw median</div>
    </div>
  )
}

function AgencyPanel({ agency, point, onClose }: { agency: string; point: AgencyPoint | undefined; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const { data, error, isFetching } = useAgencyProjects(agency, page)
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1

  return (
    <Card
      title={agency}
      titleRight={
        <button onClick={onClose} className="font-mono text-[11px] text-fg-dimmed hover:text-fg-base" aria-label="Close">
          close ✕
        </button>
      }
    >
      {point && (
        <div className="border-b border-border-subtle px-5 py-3 font-mono text-[11px] text-fg-muted space-y-0.5">
          <div>{point.ministry ?? 'ministry unknown'} · {point.sector ?? 'sector unknown'}</div>
          <div>
            n {point.nProjects} · schedule {signedPct(point.scheduleBias)}
            {rawCi(point.shrunk, point.scheduleBiasRaw, point.scheduleBiasCiLo, point.scheduleBiasCiHi)} · cost{' '}
            {signedPct(point.costBias)}
          </div>
          <div className="text-fg-dimmed">
            sector median: schedule {signedPct(point.sectorScheduleBias)} · cost {signedPct(point.sectorCostBias)}
          </div>
          {point.names && (
            <div className="text-[10px] text-fg-dimmed truncate" title={point.names}>printed as: {point.names}</div>
          )}
        </div>
      )}
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">loading projects...</div>
      ) : data.items.length === 0 ? (
        <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">no current projects: its record is all completed work</div>
      ) : (
        <div className={cn('divide-y divide-border-subtle transition-opacity', isFetching && 'opacity-60')}>
          <div className="px-5 py-2 font-mono text-[10px] uppercase tracking-wider text-fg-dimmed">
            {data.total} current projects · riskiest first
          </div>
          {data.items.map((p) => (
            <Link key={p.key} to={`/projects/${p.key}`} className="block px-5 py-2 hover:bg-surface-elevated">
              <div className="flex items-center gap-2 min-w-0">
                <Badge tier={p.tier} />
                <span className="font-mono text-[11px] text-accent shrink-0">{p.key}</span>
                <span className="truncate text-xs text-fg-base" title={p.name ?? undefined}>{p.name ?? ''}</span>
              </div>
              <div className="font-mono text-[10px] text-fg-dimmed pl-[52px]">
                P(slip, 2q) {orDash(p.pAny2q, (x) => formatProb(x))} · {orDash(p.anticipatedCostCr, formatINR)} · {p.state ?? 'state unknown'}
              </div>
            </Link>
          ))}
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
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

/**
 * Agency Performance Matrix (/agencies, guide §6.3) over /api/agencies/matrix: each canonical
 * agency's median schedule and cost bias on past projects, with n and a 90% CI. n < 10 is shrunk
 * toward the sector median and n < 5 hidden unless asked for.
 */
export function Agencies() {
  const [showSmall, setShowSmall] = useState(false)
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [selected, setSelected] = useState<string | null>(null)
  const { data, error, isFetching } = useAgencyMatrix(showSmall)
  const point = data?.points.find((p) => p.agency === selected)

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2 pt-4 pb-2">
        <div>
          <h1 className="font-sans text-2xl font-black tracking-tight text-fg-base uppercase">Agency Performance</h1>
          <p className="text-sm text-fg-muted mt-1">
            How much longer and costlier each implementing agency's projects have run than first planned.
          </p>
        </div>
        {data && (
          <div className="font-mono text-[11px] text-fg-dimmed">
            asof {formatDate(data.asof)} · {data.nAgencies} agencies · {data.nHidden} with n &lt; 5{' '}
            {showSmall ? 'shown' : 'hidden'}
          </div>
        )}
      </div>

      <div className="h-px bg-border-subtle" />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <Card
          className={selected ? 'lg:col-span-2' : 'lg:col-span-3'}
          title={`Agency matrix${data ? ` · ${data.points.length}` : ''}${isFetching ? ' · loading' : ''}`}
          titleRight={
            <div className="flex items-center gap-3 font-mono text-[11px] text-fg-muted">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={showSmall} onChange={(e) => setShowSmall(e.target.checked)} />
                show agencies with n &lt; 5
              </label>
              <span className="flex">
                {(['chart', 'table'] as const).map((v) => (
                  <button
                    key={v}
                    onClick={() => setView(v)}
                    className={cn(
                      'border border-border-default px-2 py-0.5 uppercase tracking-wider',
                      view === v ? 'bg-fg-base text-fg-inverse' : 'hover:text-fg-base'
                    )}
                  >
                    {v === 'chart' ? 'Matrix' : 'Leaderboard'}
                  </button>
                ))}
              </span>
            </div>
          }
        >
          {error ? (
            <ApiErrorNote error={error} />
          ) : !data ? (
            <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">loading agency matrix...</div>
          ) : data.points.length === 0 ? (
            <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">
              no agency has 5 or more past projects with a known planned duration
            </div>
          ) : view === 'chart' ? (
            <MatrixChart points={data.points} onPick={setSelected} />
          ) : (
            <Leaderboard points={data.points} selected={selected} onPick={setSelected} />
          )}
          <div className="border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-muted">
            Small samples are shrunk toward the sector median; this is a historical pattern, not a verdict.
          </div>
          {data && (
            <details className="border-t border-border-subtle px-5 py-2 font-mono text-[10px] text-fg-dimmed">
              <summary className="cursor-pointer">method</summary>
              <p className="mt-1 leading-relaxed">{data.method}</p>
            </details>
          )}
        </Card>

        {selected && <AgencyPanel key={selected} agency={selected} point={point} onClose={() => setSelected(null)} />}
      </div>
    </div>
  )
}
