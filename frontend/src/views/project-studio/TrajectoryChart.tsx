import { useMemo } from 'react'
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from 'recharts'
import { Card } from '@/components/ui/Card'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { ApiError } from '@/lib/api'
import { formatDate, formatINR, formatPct } from '@/lib/formatters'
import type { Forecast, Timeline } from '@/contracts/project'

interface Row {
  t: number
  progress?: number
  spend?: number
  cont?: number
  rec?: number
  agy?: number
  band?: [number, number]
  scurve?: number
}

/** series names: the scenarios in plain sentences; `fact` series are report figures whose values any viewer may read */
const SERIES: Record<string, { name: string; pct: boolean; fact: boolean }> = {
  progress: { name: 'Work done (reported)', pct: true, fact: true },
  spend: { name: 'Spent (reported)', pct: false, fact: true },
  cont: { name: 'If it keeps its own pace', pct: true, fact: false },
  rec: { name: 'If it recovers to the sector’s pace', pct: true, fact: false },
  agy: { name: 'If it follows its agency’s pattern', pct: true, fact: false },
  scurve: { name: 'A typical project in the sector', pct: true, fact: false },
}

/** "Likely completion: 6 to 12 months past Nov 2026" from the words forecast; null without the band */
function bandCaption(f: Forecast | undefined): string | null {
  const b = f?.completion.band
  if (!b || !f?.completion.anticipated) return null
  return `Likely completion: ${b} past ${formatDate(f.completion.anticipated)}, the date the latest report gives.`
}

const ts = (iso: string) => Date.parse(iso)
const monthLabel = (t: number) => formatDate(new Date(t).toISOString())

function buildRows(timeline: Timeline | undefined, forecast: Forecast | undefined): Row[] {
  const rows = new Map<number, Row>()
  const at = (t: number) => {
    const r = rows.get(t) ?? { t }
    rows.set(t, r)
    return r
  }
  const history = timeline?.points ?? []
  for (const p of history) {
    const r = at(ts(p.period))
    if (p.physicalProgressPct !== null) r.progress = p.physicalProgressPct
    if (p.expenditureCr !== null) r.spend = p.expenditureCr
  }
  if (!forecast) return [...rows.values()].sort((a, b) => a.t - b.t)

  // scenarios start from the last reported progress so the fan joins the history
  const last = [...history].reverse().find((p) => p.physicalProgressPct !== null)
  if (last && last.physicalProgressPct !== null) {
    const r = at(ts(last.period))
    const v = last.physicalProgressPct
    r.cont = r.rec = r.agy = v
    r.band = [v, v]
  }
  for (const s of forecast.scenarios) {
    const r = at(ts(s.quarter))
    if (s.continue !== null) r.cont = s.continue
    if (s.recover !== null) r.rec = s.recover
    if (s.agency !== null) r.agy = s.agency
  }
  for (const b of forecast.band ?? []) at(ts(b.quarter)).band = [b.lo, b.hi]

  const end = Math.max(...[...rows.keys()])
  for (const c of forecast.scurve) {
    if (c.date && c.expectedProgress !== null && ts(c.date) <= end) at(ts(c.date)).scurve = c.expectedProgress
  }
  return [...rows.values()].sort((a, b) => a.t - b.t)
}

/**
 * Where it could go from here (guide §5.1): reported progress and spend (facts, with their axes), the three scenario
 * curves with their range as the band, and a typical project in the sector as reference — a picture of the paths,
 * not a number. numbers (the developer's Model detail): the tooltip gives every value and the predicted completion
 * window is shaded; otherwise the tooltip names the month and the lines present, and the window is a sentence.
 */
export function TrajectoryChart({
  timeline,
  forecast,
  forecastError,
  asof,
  numbers = false,
}: {
  timeline: Timeline | undefined
  forecast: Forecast | undefined
  forecastError: unknown
  asof: string
  numbers?: boolean
}) {
  const rows = useMemo(() => buildRows(timeline, forecast), [timeline, forecast])
  const c = forecast?.completion
  const caption = bandCaption(forecast)

  return (
    <Card
      variant="section"
      title={numbers ? 'Trajectory and scenarios' : 'Where it could go from here'}
      info={
        forecast && (
          <>
            <p>
              The dashed lines are three paths from the last report: keeping the project&apos;s own recent pace,
              recovering to the sector&apos;s typical pace, and following how its agency&apos;s projects usually went. The
              dotted line is a typical {forecast.sector ?? 'sector'} project at the same share of its schedule
              {numbers && forecast.scurveFitYear ? ` (fit ${forecast.scurveFitYear})` : ''}.
            </p>
            {numbers && forecast.bandMethod && <p>{forecast.bandMethod}</p>}
          </>
        )
      }
      titleRight={
        <span className="text-fg-dimmed hidden sm:inline text-xs">
          {timeline ? `${timeline.points.length} reports` : ''}
          {numbers && c?.p50 && ` · completion p50 ${formatDate(c.p50)}`}
        </span>
      }
      className="h-full flex flex-col"
    >
      {rows.length === 0 ? (
        <div className="h-[320px] flex items-center justify-center text-sm text-fg-muted">
          No reported progress for this project yet.
        </div>
      ) : (
        <div className="flex-1 w-full p-2 min-h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ccd1da" />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                tickFormatter={monthLabel}
                minTickGap={28}
                stroke="#707987"
                fontSize={12}
                fontFamily="IBM Plex Mono"
                tickLine={false}
              />
              <YAxis
                yAxisId="pct"
                domain={[0, 100]}
                tickFormatter={(v: number) => `${v}%`}
                stroke="#0b7249"
                fontSize={12}
                fontFamily="IBM Plex Mono"
                tickLine={false}
                width={44}
              />
              <YAxis
                yAxisId="cr"
                orientation="right"
                tickFormatter={(v: number) => `₹${Math.round(v)}Cr`}
                stroke="#1946b8"
                fontSize={12}
                fontFamily="IBM Plex Mono"
                tickLine={false}
                width={78}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  return (
                    <div className="border border-border-default bg-surface-panel p-3 text-xs rounded-lg shadow-pop overflow-hidden">
                      <div className="font-bold text-fg-base border-b border-border-subtle pb-1.5 mb-2">
                        {monthLabel(Number(label))}
                      </div>
                      {payload.map((item) => {
                        const key = String(item.dataKey)
                        const v = item.value
                        // a scenario's value is a model output: the four roles see the line's name, not its value
                        const shown = numbers || SERIES[key]?.fact
                        const text = !shown ? null : Array.isArray(v)
                          ? `${formatPct(Number(v[0]), 0)} – ${formatPct(Number(v[1]), 0)}`
                          : SERIES[key]?.pct
                            ? formatPct(Number(v), 1)
                            : formatINR(Number(v))
                        return (
                          <div key={key} className="flex items-center justify-between gap-4">
                            <span style={{ color: item.color }}>{item.name}</span>
                            {text && <span className="font-semibold text-fg-base">{text}</span>}
                          </div>
                        )
                      })}
                    </div>
                  )
                }}
              />
              <Legend verticalAlign="top" height={30} wrapperStyle={{ fontSize: '12px', fontFamily: 'IBM Plex Sans' }} />

              {numbers && c?.p05 && c.p95 && (
                <ReferenceArea
                  yAxisId="pct"
                  x1={ts(c.p05)}
                  x2={ts(c.p95)}
                  fill="#9c4d04"
                  fillOpacity={0.07}
                  ifOverflow="extendDomain"
                  label={{ value: 'completion p05–p95', position: 'insideBottom', fontSize: 12, fill: '#9c4d04' }}
                />
              )}
              {c?.anticipated && (
                <ReferenceLine yAxisId="pct" x={ts(c.anticipated)} stroke="#707987" strokeDasharray="2 3"
                  ifOverflow="extendDomain" label={{ value: 'reported completion', position: 'insideTopLeft', fontSize: 12, fill: '#707987' }} />
              )}
              <ReferenceLine yAxisId="pct" x={ts(asof)} stroke="#1f2937" strokeDasharray="4 4"
                label={{ value: 'today', position: 'insideBottomRight', fontSize: 12, fill: '#1f2937' }} />

              <Area yAxisId="pct" dataKey="band" name="Range of the three paths" stroke="none" fill="#5b7299" fillOpacity={0.18}
                connectNulls isAnimationActive={false} legendType="square" />
              <Line yAxisId="pct" dataKey="scurve" name={SERIES.scurve?.name} stroke="#8a8578" strokeWidth={1.5}
                strokeDasharray="1 3" dot={false} connectNulls isAnimationActive={false} />
              <Line yAxisId="cr" dataKey="spend" name={SERIES.spend?.name} stroke="#1946b8" strokeWidth={1.5}
                dot={{ r: 2 }} connectNulls isAnimationActive={false} />
              <Line yAxisId="pct" dataKey="progress" name={SERIES.progress?.name} stroke="#0b7249" strokeWidth={2.5}
                dot={{ r: 3, fill: '#0b7249' }} connectNulls isAnimationActive={false} />
              <Line yAxisId="pct" dataKey="cont" name={SERIES.cont?.name} stroke="#0b7249" strokeWidth={2}
                strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
              <Line yAxisId="pct" dataKey="rec" name={SERIES.rec?.name} stroke="#1946b8" strokeWidth={1.5}
                strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
              <Line yAxisId="pct" dataKey="agy" name={SERIES.agy?.name} stroke="#ba1b2b" strokeWidth={1.5}
                strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {caption && !numbers && (
        <div className="border-t border-border-subtle px-5 py-2.5 text-sm text-fg-base">{caption}</div>
      )}

      {!forecast && (
        <div className="border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed leading-relaxed">
          {forecastError instanceof ApiError && forecastError.status === 404 ? (
            <div>No paths ahead: the project is not in the current scored portfolio, so the history is shown alone.</div>
          ) : forecastError ? (
            <ApiErrorNote error={forecastError} className="py-2 text-left" />
          ) : (
            <div>Loading the paths ahead…</div>
          )}
        </div>
      )}
    </Card>
  )
}
