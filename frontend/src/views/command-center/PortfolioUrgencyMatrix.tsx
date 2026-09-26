import { useMemo, useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { Card } from '@/components/ui/Card'
import { formatINR, formatRunwayDays } from '@/lib/formatters'
import { RISK_COLOR } from '@/lib/riskPalette'
import type { Project, RiskTier } from '@/contracts/project'

interface PortfolioUrgencyMatrixProps {
  projects: Project[]
  selectedProjectId?: string | null
  onSelectProject?: (projectId: string) => void
}

/**
 * Smooth gradient-area chart — 300 points read as a shape/trend, not 300
 * individual marks. Segment color still tracks risk tier via a hard-stop
 * SVG gradient (two stops at the same offset = instant color cutover, no
 * blur between tiers), same technique used for threshold-colored area
 * charts. Reuses the map's palette so the whole dashboard reads as one
 * visual language.
 */
export function PortfolioUrgencyMatrix({
  projects,
  selectedProjectId,
  onSelectProject,
}: PortfolioUrgencyMatrixProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)

  const data = useMemo(
    () =>
      [...projects]
        .sort((a, b) => a.actionableRunwayDays - b.actionableRunwayDays)
        .map((p, index) => ({ ...p, index })),
    [projects]
  )
  const n = Math.max(data.length - 1, 1)

  const gradientStops = useMemo(() => {
    const stops: { offset: number; color: string }[] = []
    data.forEach((p, i) => {
      const offset = i / n
      const color = RISK_COLOR[p.riskTier as RiskTier] ?? RISK_COLOR.NORMAL
      const prev = stops[stops.length - 1]
      if (!prev || prev.color !== color) {
        if (prev) stops.push({ offset, color: prev.color }) // hard cutover, no blend
        stops.push({ offset, color })
      }
    })
    return stops.length ? stops : [{ offset: 0, color: RISK_COLOR.NORMAL }]
  }, [data, n])

  // first index where runway crosses the 30-day critical threshold
  const criticalBoundaryIndex = data.findIndex((p) => p.actionableRunwayDays > 30)

  return (
    <Card
      title="Portfolio Urgency Matrix"
      titleRight={
        <div className="flex items-center gap-4 font-sans font-semibold text-[11px] text-fg-dimmed">
          <span><span className="inline-block h-1.5 w-1.5 mr-1" style={{ background: RISK_COLOR.CRITICAL }} />CRIT &le;30d</span>
          <span><span className="inline-block h-1.5 w-1.5 mr-1" style={{ background: RISK_COLOR.WARNING }} />WARN 30-90d</span>
          <span><span className="inline-block h-1.5 w-1.5 mr-1" style={{ background: RISK_COLOR.NORMAL }} />STBL &gt;90d</span>
        </div>
      }
    >
      <div className="h-[340px] w-full p-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 16, right: 20, left: 10, bottom: 20 }}
            onMouseMove={(s) => setActiveIndex(typeof s.activeTooltipIndex === 'number' ? s.activeTooltipIndex : null)}
            onMouseLeave={() => setActiveIndex(null)}
          >
            <defs>
              <linearGradient id="urgencyStroke" x1="0" y1="0" x2="1" y2="0">
                {gradientStops.map((s, i) => (
                  <stop key={i} offset={s.offset} stopColor={s.color} />
                ))}
              </linearGradient>
              <linearGradient id="urgencyFill" x1="0" y1="0" x2="1" y2="0">
                {gradientStops.map((s, i) => (
                  <stop key={i} offset={s.offset} stopColor={s.color} stopOpacity={0.22} />
                ))}
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#ccd1da" vertical={false} />
            <XAxis
              dataKey="index"
              tick={false}
              axisLine={false}
              label={{ value: 'Actionable Runway Days →', position: 'insideBottom', offset: -6, fontSize: 11, fill: '#4d5563', fontFamily: 'IBM Plex Sans' }}
            />
            <YAxis
              stroke="#707987"
              fontSize={11}
              fontFamily="IBM Plex Mono"
              tickLine={false}
              domain={[0, 100]}
              tickFormatter={(v) => `${v}`}
              width={40}
              label={{ value: 'Risk Score', angle: -90, position: 'insideLeft', offset: 10, fontSize: 10, fill: '#4d5563', fontFamily: 'IBM Plex Sans' }}
            />

            {criticalBoundaryIndex > 0 && (
              <ReferenceLine x={criticalBoundaryIndex} stroke={RISK_COLOR.CRITICAL} strokeDasharray="4 4" opacity={0.5} />
            )}

            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const p = payload[0]?.payload as (typeof data)[number] | undefined
                if (!p) return null
                return (
                  <div className="border border-border-default bg-surface-panel px-3 py-2 font-mono text-xs shadow-lg">
                    <div className="font-semibold text-fg-base border-b border-border-subtle pb-1 mb-1.5">{p.code}</div>
                    <div className="text-fg-muted">{formatRunwayDays(p.actionableRunwayDays)} runway</div>
                    <div style={{ color: RISK_COLOR[p.riskTier as RiskTier] }} className="font-semibold">
                      risk {p.compositeRiskScore}/100
                    </div>
                    <div className="text-fg-dimmed">+{formatINR(p.overrunForecastCr)} overrun</div>
                  </div>
                )
              }}
            />

            <Area
              type="monotone"
              dataKey="compositeRiskScore"
              stroke="url(#urgencyStroke)"
              strokeWidth={2}
              fill="url(#urgencyFill)"
              dot={false}
              activeDot={{
                r: 5,
                stroke: '#fff',
                strokeWidth: 1.5,
                fill: activeIndex !== null ? RISK_COLOR[data[activeIndex]?.riskTier as RiskTier] ?? RISK_COLOR.NORMAL : RISK_COLOR.NORMAL,
                // recharts wraps this handler twice: at runtime the second argument
                // is the dot's props (which carry `index`), not the mouse event its
                // types describe.
                onClick: (_props: unknown, dot: unknown) => {
                  const index = (dot as { index?: number } | undefined)?.index
                  const p = typeof index === 'number' ? data[index] : undefined
                  if (p) onSelectProject?.(p.id)
                },
                style: { cursor: 'pointer' },
              }}
              isAnimationActive
              animationDuration={600}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {selectedProjectId && (
        <div className="px-5 pb-2 -mt-1 text-[10px] font-mono text-fg-dimmed">
          selected: {selectedProjectId} — click a point on the curve to change selection
        </div>
      )}
    </Card>
  )
}
