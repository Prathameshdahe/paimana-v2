import { useMemo } from 'react'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts'
import { Card } from '@/components/ui/Card'
import { useMeta } from '@/lib/queries'
import { TIER_COLOR, TIERS, tierKey } from '@/lib/riskPalette'
import { formatINR, formatProb, orDash } from '@/lib/formatters'
import type { ProjectPage, ProjectRow } from '@/contracts/project'

interface PortfolioUrgencyMatrixProps {
  /** the Triage Register's current page — the matrix never asks for more */
  page: ProjectPage | undefined
  selectedKey?: string | null
  onOpenDetail?: (key: string) => void
}

interface Point {
  row: ProjectRow
  x: number
  y: number
  z: number
}

function monthsBetween(fromIso: string, toIso: string): number {
  const a = new Date(fromIso)
  const b = new Date(toIso)
  return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth())
}

/**
 * Urgency scatter over the current page: how soon each project is due
 * (months from asof to its anticipated completion) against P(date push or
 * cost revision, 2q). Top-left = due soon and likely to slip. Untiered rows
 * have no completion date and are counted, not plotted.
 */
export function PortfolioUrgencyMatrix({ page, selectedKey, onOpenDetail }: PortfolioUrgencyMatrixProps) {
  const { data: meta } = useMeta()

  const points = useMemo<Point[]>(() => {
    if (!page || !meta) return []
    return page.items
      .filter((r) => r.pAny2q !== null && r.anticipatedCompletion)
      .map((r) => ({
        row: r,
        x: monthsBetween(meta.asof, r.anticipatedCompletion ?? meta.asof),
        y: Math.round((r.pAny2q ?? 0) * 1000) / 10,
        z: r.anticipatedCostCr ?? 0,
      }))
  }, [page, meta])
  const notPlotted = (page?.items.length ?? 0) - points.length

  return (
    <Card
      title={`Portfolio Urgency Matrix · this page (${points.length} of ${page?.items.length ?? 0})`}
      titleRight={
        <div className="flex items-center gap-4 font-sans font-semibold text-xs text-fg-dimmed">
          {TIERS.map((t) => (
            <span key={t}>
              <span className="inline-block h-1.5 w-1.5 mr-1" style={{ background: TIER_COLOR[t] }} />
              {t.toUpperCase()}
            </span>
          ))}
        </div>
      }
    >
      <div className="h-[320px] w-full p-2">
        {points.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-fg-dimmed">
            {page ? 'no scored projects with a completion date on this page' : 'waiting for the register page...'}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 16, right: 20, left: 10, bottom: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ccd1da" />
              <XAxis
                type="number"
                dataKey="x"
                stroke="#707987"
                fontSize={12}
                fontFamily="IBM Plex Mono"
                tickLine={false}
                tickFormatter={(v: number) => `${v}mo`}
                label={{ value: 'Months to anticipated completion (from asof) →', position: 'insideBottom', offset: -12, fontSize: 12, fill: '#4d5563', fontFamily: 'IBM Plex Sans' }}
              />
              <YAxis
                type="number"
                dataKey="y"
                stroke="#707987"
                fontSize={12}
                fontFamily="IBM Plex Mono"
                tickLine={false}
                domain={[0, 100]}
                tickFormatter={(v: number) => `${v}%`}
                width={44}
                label={{ value: 'P(slip, 2q)', angle: -90, position: 'insideLeft', offset: 10, fontSize: 12, fill: '#4d5563', fontFamily: 'IBM Plex Sans' }}
              />
              <ZAxis type="number" dataKey="z" range={[30, 320]} />
              <ReferenceLine x={0} stroke="#ba1b2b" strokeDasharray="4 4" opacity={0.5} label={{ value: 'due at asof', fontSize: 12, fill: '#ba1b2b', position: 'insideTopRight' }} />
              <Tooltip
                cursor={{ strokeDasharray: '3 3' }}
                content={({ active, payload }) => {
                  const p = active ? (payload?.[0]?.payload as Point | undefined) : undefined
                  if (!p) return null
                  return (
                    <div className="border border-border-default bg-surface-panel px-3 py-2 text-xs max-w-[280px] rounded-lg shadow-pop overflow-hidden">
                      <div className="font-semibold text-fg-base border-b border-border-subtle pb-1 mb-1.5">
                        {p.row.key} · {p.row.tier}
                      </div>
                      <div className="text-fg-muted truncate">{p.row.name}</div>
                      <div style={{ color: TIER_COLOR[tierKey(p.row.tier)] }} className="font-semibold">
                        P(slip, 2q) {orDash(p.row.pAny2q, formatProb)}
                      </div>
                      <div className="text-fg-dimmed">due in {p.x} months · {orDash(p.row.anticipatedCostCr, formatINR)}</div>
                    </div>
                  )
                }}
              />
              <Scatter
                data={points}
                onClick={(d: { payload?: Point }) => d.payload && onOpenDetail?.(d.payload.row.key)}
                style={{ cursor: 'pointer' }}
                isAnimationActive={false}
              >
                {points.map((p) => (
                  <Cell
                    key={p.row.key}
                    fill={TIER_COLOR[tierKey(p.row.tier)]}
                    fillOpacity={0.75}
                    stroke={p.row.key === selectedKey ? '#1f2937' : '#fff'}
                    strokeWidth={p.row.key === selectedKey ? 2 : 1}
                  />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="px-5 pb-2 -mt-1 text-xs text-fg-dimmed">
        dot size = anticipated cost · click a dot for its detail
        {notPlotted > 0 && ` · ${notPlotted} on this page not plotted (no completion date, schedule not scored)`}
      </div>
    </Card>
  )
}
