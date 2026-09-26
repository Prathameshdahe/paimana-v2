import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ComposableMap, Geographies, Geography, Marker, ZoomableGroup } from 'react-simple-maps'
import { computeStateAggregates, normStateKey } from '@/lib/stateAggregate'
import { RISK_COLOR, RISK_FILL } from '@/lib/riskPalette'
import { formatINRShort } from '@/lib/formatters'
import { Card } from '@/components/ui/Card'
import stateDots from '@/data/state-dots.json'

const GEO_URL = '/india-states-simplified.geojson'

interface Dot { lon: number; lat: number; tier: 'CRITICAL' | 'WARNING' | 'NORMAL'; id: string }
const DOTS: Record<string, Dot[]> = stateDots as Record<string, Dot[]>
// dot placement is approximate for Telangana/Ladakh — the reference geography
// predates their split from Andhra Pradesh/J&K, so their dots scatter inside
// the pre-split parent polygon rather than the exact sub-state boundary.

const DOT_COLOR = RISK_COLOR
function hoverFill(avgRiskScore: number | undefined): string {
  if (avgRiskScore === undefined) return '#f2f0ea'
  if (avgRiskScore >= 60) return RISK_FILL.CRITICAL
  if (avgRiskScore >= 30) return RISK_FILL.WARNING
  return RISK_FILL.NORMAL
}

/** all dots flattened, keyed by normalized state so they render regardless of hover */
const ALL_DOTS: Dot[] = Object.values(DOTS).flat()

const MAP_CENTER: [number, number] = [83, 21]
const MIN_ZOOM = 1
const MAX_ZOOM = 6

export function IndiaMap() {
  const navigate = useNavigate()
  const aggregates = useMemo(() => computeStateAggregates(), [])
  const [hovered, setHovered] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)

  const hoveredAgg = hovered ? aggregates.get(normStateKey(hovered)) : undefined

  const topStates = useMemo(
    () =>
      Array.from(aggregates.values())
        .sort((a, b) => b.criticalCount - a.criticalCount || b.avgRiskScore - a.avgRiskScore)
        .slice(0, 6),
    [aggregates]
  )

  return (
    <Card title="Portfolio by State" className="relative h-full flex flex-col">
      <div className="relative bg-white">
        <ComposableMap
          projection="geoMercator"
          projectionConfig={{ center: MAP_CENTER, scale: 780 }}
          width={440}
          height={560}
          style={{ width: '100%', height: 'auto' }}
        >
          {/* filterZoomEvent blocks all mouse/touch drag+wheel — map is static,
              zoom only changes via the +/- buttons (controlled `zoom` state) */}
          <ZoomableGroup center={MAP_CENTER} zoom={zoom} minZoom={MIN_ZOOM} maxZoom={MAX_ZOOM} filterZoomEvent={() => false}>
            <Geographies geography={GEO_URL}>
              {({ geographies }) =>
                geographies.map((geo) => {
                  const name: string = geo.properties?.name ?? ''
                  const agg = aggregates.get(normStateKey(name))
                  const isHovered = hovered === name
                  return (
                    <Geography
                      key={geo.rsmKey}
                      geography={geo}
                      onMouseEnter={() => setHovered(name)}
                      onMouseLeave={() => setHovered(null)}
                      onClick={() => agg && navigate(`/command?state=${encodeURIComponent(agg.state)}`)}
                      fill={isHovered ? hoverFill(agg?.avgRiskScore) : 'transparent'}
                      stroke="#8a8578"
                      strokeWidth={0.6 / zoom}
                      style={{ outline: 'none', cursor: agg ? 'pointer' : 'default', transition: 'fill 150ms' }}
                    />
                  )
                })
              }
            </Geographies>

            {ALL_DOTS.map((d) => (
              <Marker key={d.id} coordinates={[d.lon, d.lat]}>
                <circle r={1.8 / zoom} fill={DOT_COLOR[d.tier]} stroke="#fff" strokeWidth={0.4 / zoom} />
              </Marker>
            ))}
          </ZoomableGroup>
        </ComposableMap>

        <div className="absolute right-3 top-3 flex flex-col border border-border-default bg-surface-panel shadow">
          <button
            onClick={() => setZoom((z) => Math.min(MAX_ZOOM, +(z * 1.4).toFixed(2)))}
            disabled={zoom >= MAX_ZOOM}
            className="flex h-7 w-7 items-center justify-center text-sm font-mono text-fg-base hover:bg-surface-elevated disabled:opacity-30 disabled:cursor-not-allowed border-b border-border-subtle"
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            onClick={() => setZoom((z) => Math.max(MIN_ZOOM, +(z / 1.4).toFixed(2)))}
            disabled={zoom <= MIN_ZOOM}
            className="flex h-7 w-7 items-center justify-center text-sm font-mono text-fg-base hover:bg-surface-elevated disabled:opacity-30 disabled:cursor-not-allowed"
            aria-label="Zoom out"
          >
            −
          </button>
        </div>

        {hoveredAgg && (
          <div className="pointer-events-none absolute left-3 top-3 border border-border-default bg-surface-panel px-3 py-2 text-[11px] font-mono shadow-lg text-fg-base">
            <div className="font-semibold">{hoveredAgg.state}</div>
            <div className="text-fg-muted">{hoveredAgg.projectCount} projects · {hoveredAgg.criticalCount} critical</div>
            <div className="text-fg-muted">avg risk {hoveredAgg.avgRiskScore}/100 · {formatINRShort(hoveredAgg.totalOverrunCr)} overrun</div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-4 border-t border-border-subtle px-5 py-2 text-[10px] font-mono uppercase tracking-wider text-fg-dimmed">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: DOT_COLOR.CRITICAL }} />Critical project</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: DOT_COLOR.WARNING }} />Warning project</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: DOT_COLOR.NORMAL }} />Normal project</span>
        <span className="text-fg-dimmed/70">hover state to see risk fill</span>
      </div>

      <div className="border-t border-border-subtle">
        <div className="px-5 py-2 text-[10px] font-mono uppercase tracking-wider text-fg-dimmed">
          Top states by critical count
        </div>
        <div className="divide-y divide-border-subtle">
          {topStates.map((s) => (
            <button
              key={s.state}
              onClick={() => navigate(`/command?state=${encodeURIComponent(s.state)}`)}
              className="flex w-full items-center justify-between px-5 py-2 text-left hover:bg-surface-elevated transition-colors"
            >
              <span className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ background: s.avgRiskScore >= 60 ? DOT_COLOR.CRITICAL : s.avgRiskScore >= 30 ? DOT_COLOR.WARNING : DOT_COLOR.NORMAL }}
                />
                <span className="text-sm font-medium text-fg-base">{s.state}</span>
              </span>
              <span className="font-mono text-[11px] text-fg-dimmed">
                {s.projectCount} projects · <span className="text-critical font-semibold">{s.criticalCount} crit</span> · risk {s.avgRiskScore}
              </span>
            </button>
          ))}
        </div>
      </div>
    </Card>
  )
}
