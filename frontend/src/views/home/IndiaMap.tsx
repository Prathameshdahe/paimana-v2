import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ComposableMap, Geographies, Geography, ZoomableGroup } from 'react-simple-maps'
import { usePortfolio } from '@/lib/queries'
import { TIER_COLOR } from '@/lib/riskPalette'
import { formatINRShort, orDash } from '@/lib/formatters'
import { Card } from '@/components/ui/Card'
import { InfoTip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import type { GroupStat } from '@/contracts/portfolio'
import { GEO_URL, MAP_CENTER, OFF_MAP, normStateKey } from './indiaGeo'

const MIN_ZOOM = 1
const MAX_ZOOM = 6

/** at-risk = Critical + High; the fill is its share of the largest state count */
function atRisk(s: GroupStat | undefined): number {
  return s ? s.nCritical + s.nHigh : 0
}

function fill(s: GroupStat | undefined, max: number): string {
  if (!s) return '#f2f0ea' // no open projects in the data
  const share = atRisk(s) / Math.max(max, 1)
  return share === 0 ? '#e9e5dc' : `color-mix(in srgb, ${TIER_COLOR.Critical} ${Math.round(15 + share * 75)}%, #f6f3ee)`
}

export function IndiaMap() {
  const navigate = useNavigate()
  const { data, error } = usePortfolio()
  const [hovered, setHovered] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)

  const byKey = useMemo(
    () => new Map((data?.byState ?? []).filter((s) => s.name).map((s) => [normStateKey(s.name ?? ''), s])),
    [data]
  )
  const maxAtRisk = useMemo(() => Math.max(0, ...Array.from(byKey.values()).map(atRisk)), [byKey])
  const hoveredStat = hovered ? byKey.get(normStateKey(hovered)) : undefined

  const topStates = useMemo(
    () =>
      [...(data?.byState ?? [])]
        .sort((a, b) => atRisk(b) - atRisk(a) || b.nCritical - a.nCritical || b.n - a.n)
        .slice(0, 6),
    [data]
  )
  const offMap = (data?.byState ?? []).filter((s) => !s.name || OFF_MAP.has(normStateKey(s.name)))

  const open = (s: GroupStat) => s.name && navigate(`/command?state=${encodeURIComponent(s.name)}`)

  return (
    <Card title="Projects by state" info="Shade: critical + high projects in the state. Click a state to open its projects." className="relative h-full flex flex-col">
      {error ? (
        <ApiErrorNote error={error} />
      ) : (
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
                    const stat = byKey.get(normStateKey(name))
                    return (
                      <Geography
                        key={geo.rsmKey}
                        geography={geo}
                        onMouseEnter={() => setHovered(name)}
                        onMouseLeave={() => setHovered(null)}
                        onClick={() => stat && open(stat)}
                        fill={fill(stat, maxAtRisk)}
                        stroke={hovered === name ? '#1f2937' : '#8a8578'}
                        strokeWidth={(hovered === name ? 1.4 : 0.6) / zoom}
                        style={{ outline: 'none', cursor: stat ? 'pointer' : 'default' }}
                      />
                    )
                  })
                }
              </Geographies>
            </ZoomableGroup>
          </ComposableMap>

          <div className="absolute right-3 top-3 flex flex-col border border-border-default bg-surface-panel rounded-lg shadow-pop overflow-hidden">
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

          {hovered && (
            <div className="pointer-events-none absolute left-3 top-3 border border-border-default bg-surface-panel px-3 py-2 text-xs text-fg-base rounded-lg shadow-pop overflow-hidden">
              <div className="font-semibold">{hoveredStat?.name ?? hovered}</div>
              {hoveredStat ? (
                <>
                  <div className="text-fg-muted">
                    {hoveredStat.n} open projects · {orDash(hoveredStat.capitalCr, formatINRShort)}
                  </div>
                  <div className="text-fg-muted">
                    <span className="text-critical font-semibold">{hoveredStat.nCritical}</span> critical ·{' '}
                    <span className="text-warning font-semibold">{hoveredStat.nHigh}</span> high
                  </div>
                </>
              ) : (
                <div className="text-fg-dimmed">no open projects in the reports</div>
              )}
            </div>
          )}
        </div>
      )}

      {data && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle px-5 py-2.5 text-xs text-fg-dimmed">
          <span className="flex items-center gap-2">
            <span>0</span>
            <span className="h-2 w-16 rounded-full" style={{ background: `linear-gradient(90deg, #e9e5dc, ${TIER_COLOR.Critical})` }} />
            <span>{maxAtRisk} critical + high</span>
          </span>
          {offMap.length > 0 && (
            <span className="flex flex-wrap items-center gap-x-2">
              <span className="flex items-center gap-1">
                not on the map
                <InfoTip label="About the map">The boundary file predates Telangana and Ladakh, so their projects are listed here.</InfoTip>
              </span>
              {offMap.map((s, i) => (
                <button key={s.name ?? i} onClick={() => open(s)} className="rounded-full bg-surface-elevated px-2 py-0.5 hover:text-fg-base">
                  {s.name ?? 'state unknown'} {s.n}
                  {s.nCritical + s.nHigh > 0 && <span className="text-critical"> · {s.nCritical + s.nHigh} at risk</span>}
                </button>
              ))}
            </span>
          )}
        </div>
      )}

      <div className="border-t border-border-subtle px-5 pb-3 pt-3">
        <div className="mb-2 text-xs font-medium text-fg-muted">Top states by projects at risk (critical + high)</div>
        <div className="space-y-1">
          {topStates.map((s) => (
            <button
              key={s.name ?? 'unknown'}
              onClick={() => open(s)}
              className="grid w-full grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-elevated"
            >
              <span className="truncate text-sm font-medium text-fg-base">{s.name ?? 'state unknown'}</span>
              {/* the state's open projects, critical and high as their share */}
              <span className="flex h-2 overflow-hidden rounded-full bg-surface-input" title={`${s.n} projects: ${s.nCritical} critical, ${s.nHigh} high`}>
                <span style={{ width: `${(s.nCritical / Math.max(s.n, 1)) * 100}%`, background: TIER_COLOR.Critical }} />
                <span style={{ width: `${(s.nHigh / Math.max(s.n, 1)) * 100}%`, background: TIER_COLOR.High }} />
              </span>
              <span className="whitespace-nowrap text-xs text-fg-dimmed" title={`${s.nCritical} critical, ${s.nHigh} high`}>
                <span className="font-semibold text-critical">{s.nCritical + s.nHigh} at risk</span> of {s.n} · {orDash(s.capitalCr, formatINRShort)}
              </span>
            </button>
          ))}
        </div>
      </div>
    </Card>
  )
}
