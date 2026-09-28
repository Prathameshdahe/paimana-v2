import { useMemo, useState } from 'react'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { Card } from '@/components/ui/Card'
import { formatDate, orDash } from '@/lib/formatters'
import type { LandState } from '@/contracts/portfolio'
import { GEO_URL, MAP_CENTER, OFF_MAP, normStateKey } from '../home/indiaGeo'

const INK = '#2a78d6' // the land category colour (riskPalette EVENT_CATEGORY.land)
const NO_DATA = '#eeebe4'

function fill(s: LandState | undefined, max: number): string {
  if (!s?.has_data || !s.area_ha) return NO_DATA
  return `color-mix(in srgb, ${INK} ${Math.round(18 + Math.sqrt(s.area_ha / max) * 70)}%, #f6f3ee)`
}

const n = (v: number | null) => orDash(v, (x) => x.toLocaleString('en-IN'))

/** one state's register and its current road projects, as the hover card and the off-map chips show them */
function StateCard({ s }: { s: LandState }) {
  return (
    <>
      <div className="font-semibold">{s.state}</div>
      {s.has_data ? (
        <div className="text-fg-muted">
          {n(s.stretches)} NH stretches · {n(s.parcels)} parcels · {n(s.area_ha)} ha
          <div className="text-fg-dimmed">latest notification {orDash(s.last_notif, formatDate)}</div>
        </div>
      ) : (
        <div className="text-fg-dimmed">no Bhoomi Rashi data for this state</div>
      )}
      {s.n_road > 0 && (
        <div className="mt-1 text-fg-muted">
          {s.n_road} current road projects: <span className="font-semibold text-fg-base">{s.n_rated} rated</span>
          {s.n_flagged > 0 && <span className="text-critical"> ({s.n_flagged} flagged)</span>}
          {s.n_possible > 0 && `, ${s.n_possible} possible link`}
        </div>
      )}
    </>
  )
}

/** India map of the Bhoomi Rashi highway register: shade = hectares notified; grey = no data for the state. */
export function LandMap({ states, className }: { states: LandState[]; className?: string }) {
  const [hovered, setHovered] = useState<string | null>(null)
  const byKey = useMemo(() => new Map(states.map((s) => [normStateKey(s.state), s])), [states])
  const max = Math.max(1, ...states.map((s) => s.area_ha ?? 0))
  const withData = states.filter((s) => s.has_data)
  const hoveredStat = hovered ? byKey.get(normStateKey(hovered)) : undefined
  const offMap = states.filter((s) => OFF_MAP.has(normStateKey(s.state)))
  const total = (k: 'stretches' | 'n_road' | 'n_rated') => withData.reduce((a, s) => a + (s[k] ?? 0), 0)

  return (
    <Card
      className={className}
      title="Land records by state"
      info="Bhoomi Rashi highway land register, every state that has data (pulled 27 Sep 2026; most states last notified in May 2025). Shade: hectares on notified stretches. A road project is rated only when the km range in its name falls on a notified stretch of its NH; an NH or district match alone is shown as possible, never flagged."
      titleRight={<span>{withData.length} states · {total('stretches').toLocaleString('en-IN')} stretches</span>}
    >
      <div className="relative mx-auto max-w-[420px]">
        <ComposableMap projection="geoMercator" projectionConfig={{ center: MAP_CENTER, scale: 780 }} width={440} height={520}
          style={{ width: '100%', height: 'auto' }}>
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => {
                const name: string = geo.properties?.name ?? ''
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    onMouseEnter={() => setHovered(name)}
                    onMouseLeave={() => setHovered(null)}
                    fill={fill(byKey.get(normStateKey(name)), max)}
                    stroke={hovered === name ? '#1f2937' : '#8a8578'}
                    strokeWidth={hovered === name ? 1.2 : 0.5}
                    style={{ outline: 'none' }}
                  />
                )
              })
            }
          </Geographies>
        </ComposableMap>
        {hovered && (
          <div className="pointer-events-none absolute left-2 top-2 max-w-[240px] rounded-lg border border-border-default bg-surface-panel px-3 py-2 text-xs shadow-pop">
            {hoveredStat ? <StateCard s={hoveredStat} /> : <><div className="font-semibold">{hovered}</div><div className="text-fg-dimmed">no Bhoomi Rashi data, no current road project</div></>}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border-subtle px-5 py-2.5 text-xs text-fg-dimmed">
        <span className="flex items-center gap-2">
          <span className="size-2.5 rounded-sm" style={{ background: NO_DATA }} /> no data
          <span className="h-2 w-14" style={{ background: `linear-gradient(90deg, color-mix(in srgb, ${INK} 18%, #f6f3ee), ${INK})` }} />
          {Math.round(max).toLocaleString('en-IN')} ha
        </span>
        <span>{total('n_rated')} of {total('n_road')} current road projects in these states rated</span>
        {offMap.length > 0 && (
          <span className="flex flex-wrap gap-1.5">
            {offMap.map((s) => (
              <span key={s.state} className=" bg-surface-elevated px-2 py-0.5" title={`${s.n_rated} rated of ${s.n_road} road projects`}>
                {s.state}{s.has_data ? ` ${n(s.stretches)} stretches` : ' · no data'}
              </span>
            ))}
          </span>
        )}
      </div>
    </Card>
  )
}
