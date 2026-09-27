import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Page, PageHeader } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { SignalCard } from './external-factors/EvidenceFeed'
import { GEO_URL, MAP_CENTER, OFF_MAP, normStateKey } from './home/indiaGeo'
import { useLiveStatus, usePortfolio, useRadarSummary, useScoutNow, useSignalFeed, type FeedFilters } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { EVENT_CATEGORY, TIER_COLOR, categoryLabel } from '@/lib/riskPalette'
import { cn, formatDateTime } from '@/lib/formatters'
import type { RadarSummary, SignalFeed } from '@/contracts/portfolio'

const selectCls =
  'bg-surface-input border border-border-default px-2 py-0.5 text-xs font-sans font-semibold text-fg-muted focus:outline-none max-w-[200px]'

function SummaryStrip({ s }: { s: RadarSummary }) {
  const severe = s.bySeverity.filter((r) => Number(r.name) >= 2).reduce((a, r) => a + r.n, 0)
  const cats = s.byCategory.filter((r) => r.name !== 'none').slice(0, 4)
  const lt = s.leadTime
  const cell = 'bg-surface-panel px-4 py-3 min-w-0'
  const label = 'text-xs text-fg-dimmed'
  const value = 'font-mono text-lg font-semibold text-fg-base tabular-nums'
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-px bg-border-subtle border border-border-subtle">
      <div className={cell}>
        <div className={label}>last {s.windowDays} days</div>
        <div className={value}>{s.nWindow}</div>
        <div className="text-xs text-fg-dimmed">signals of {s.nSignalsTotal} stored</div>
      </div>
      <div className={cell}>
        <div className={label}>linked · unlinked</div>
        <div className={value}>
          {s.nLinked} · <span className="text-fg-muted">{s.nUnlinked}</span>
        </div>
        <div className="text-xs text-fg-dimmed">unlinked: ambiguous or weak match</div>
      </div>
      <div className={cell}>
        <div className={label}>severity ≥ 2</div>
        <div className={cn(value, severe > 0 && 'text-critical')}>{severe}</div>
        <div className="text-xs text-fg-dimmed">in the last {s.windowDays} days</div>
      </div>
      <div className={cell}>
        <div className={label}>categories</div>
        <div className="text-xs text-fg-muted leading-snug">
          {cats.length === 0 ? 'none tagged' : cats.map((c) => `${categoryLabel(String(c.name))} ${c.n}`).join(' · ')}
        </div>
      </div>
      <div className={cell}>
        <div className={label}>projects scouted</div>
        <div className={value}>{s.nProjectsScouted}</div>
      </div>
      <div className={cell} title={lt.basis}>
        <div className={label}>lead time (median)</div>
        <div className={value}>{lt.medianLeadDays === null ? '—' : `${lt.medianLeadDays} d`}</div>
        <div className="text-xs text-fg-dimmed">
          {lt.nWithLaterChange} of {lt.nLinkedPairs} linked pairs saw a later CUF change
        </div>
      </div>
    </div>
  )
}

/** severity >= 2 signals of the last 90 days per state of their linked projects; click filters the feed */
function HeatMap({ feed, state, onState }: { feed: SignalFeed | undefined; state: string | null; onState: (s: string | null) => void }) {
  const [hovered, setHovered] = useState<string | null>(null)
  const heat = feed?.stateHeat ?? []
  const byKey = new Map(heat.filter((h) => h.state).map((h) => [normStateKey(h.state ?? ''), h]))
  const max = Math.max(1, ...heat.map((h) => h.n))
  const offMap = heat.filter((h) => !h.state || OFF_MAP.has(normStateKey(h.state)))
  const hot = hovered ? byKey.get(normStateKey(hovered)) : undefined

  return (
    <Card title="Severe signals by state · 90 days">
      <div className="relative bg-white">
        <ComposableMap
          projection="geoMercator"
          projectionConfig={{ center: MAP_CENTER, scale: 780 }}
          width={440}
          height={520}
          style={{ width: '100%', height: 'auto' }}
        >
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => {
                const name: string = geo.properties?.name ?? ''
                const h = byKey.get(normStateKey(name))
                const on = !!state && normStateKey(state) === normStateKey(name)
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    onMouseEnter={() => setHovered(name)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => h?.state && onState(on ? null : h.state)}
                    fill={
                      h
                        ? `color-mix(in srgb, ${TIER_COLOR.Critical} ${Math.round(20 + (h.n / max) * 70)}%, #f6f3ee)`
                        : '#eeebe4'
                    }
                    stroke={on || hovered === name ? '#1f2937' : '#8a8578'}
                    strokeWidth={on ? 1.6 : hovered === name ? 1.2 : 0.6}
                    style={{ outline: 'none', cursor: h ? 'pointer' : 'default' }}
                  />
                )
              })
            }
          </Geographies>
        </ComposableMap>
        {hovered && (
          <div className="pointer-events-none absolute left-3 top-3 border border-border-default bg-surface-panel px-3 py-2 text-xs text-fg-base rounded-lg shadow-pop overflow-hidden">
            <div className="font-semibold">{hovered}</div>
            <div className="text-fg-muted">{hot ? `${hot.n} severe signals` : 'no severe signal linked here'}</div>
          </div>
        )}
      </div>
      <div className="border-t border-border-subtle px-5 py-2 text-xs text-fg-dimmed space-y-1">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-8" style={{ background: `linear-gradient(90deg, #eeebe4, ${TIER_COLOR.Critical})` }} />
          fill: severity ≥ 2 signals linked to the state's projects (max {heat.length ? max : 0}) · click to filter
        </div>
        {heat.length === 0 && <div>no severe signal in the last 90 days — or the scout has not searched those projects</div>}
        {offMap.length > 0 && (
          <div>
            not drawn: {offMap.map((h) => `${h.state ?? 'state unknown'} ${h.n}`).join(' · ')}
          </div>
        )}
      </div>
    </Card>
  )
}

/**
 * External Evidence Radar (/radar, guide §6.2): the news the scout stored (/api/signals/feed)
 * with filters, a state heat map and the /api/radar/summary rollup. IPMD analysts can start a
 * scout batch; its progress shows through the live status.
 */
export function Radar() {
  const { role } = useRole()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<FeedFilters>({})
  const feed = useSignalFeed(page, 20, filters)
  const summary = useRadarSummary()
  const live = useLiveStatus().data
  const scoutNow = useScoutNow()
  const states = (usePortfolio().data?.byState ?? []).map((s) => s.name).filter((n): n is string => !!n).sort()
  const running = !!live?.scout.running
  const pages = feed.data ? Math.max(1, Math.ceil(feed.data.total / feed.data.size)) : 1
  const filtered = Object.values(filters).some((v) => v !== undefined)

  // a scout run that ends without raising an alert sends nothing on the stream: refetch here
  const wasRunning = useRef(running)
  useEffect(() => {
    if (wasRunning.current && !running) client.invalidateQueries({ queryKey: ['signals'] })
    wasRunning.current = running
  }, [running, client])

  const set = (patch: FeedFilters) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }
  const lastRun = live?.scout.lastRun

  return (
    <Page>
      <PageHeader
        title="Evidence Radar"
        subtitle="News matched to current projects, often ahead of the next report revision"
        info="From Google News and PIB. A news item is linked to a project only on a strong match; the rest stay unlinked."
        actions={
        <div className="flex items-center gap-3 text-xs text-fg-dimmed">
          <span>
            {running
              ? 'scout running now…'
              : lastRun?.finishedAt
                ? `scout last ran ${formatDateTime(lastRun.finishedAt)} (${lastRun.status ?? 'unknown'})`
                : 'scout has not run on this server'}
          </span>
          {can(role, 'canRunJobs') && (
            <Button size="sm" disabled={!live || running || scoutNow.isPending} onClick={() => scoutNow.mutate()}>
              {running || scoutNow.isPending ? 'Scouting…' : 'Run scout now'}
            </Button>
          )}
        </div>
        }
      />
      {scoutNow.data && <div className="text-xs text-fg-dimmed">{scoutNow.data.detail}</div>}
      {scoutNow.isError && <div className="text-xs text-critical">scout failed to start: {String(scoutNow.error)}</div>}
      {live?.scout.lastError && <div className="text-xs text-critical">scout: {live.scout.lastError}</div>}

      {summary.error ? (
        <Card>
          <ApiErrorNote error={summary.error} />
        </Card>
      ) : (
        summary.data && <SummaryStrip s={summary.data} />
      )}
      <p className="text-xs text-fg-dimmed">
        Lead time: {summary.data?.leadTime.basis ?? 'news date to the first later CUF change'}. Search results can be
        years old, so a long gap is weak evidence of an early warning.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <select className={selectCls} value={filters.category ?? ''} onChange={(e) => set({ category: e.target.value || undefined })}>
          <option value="">all categories</option>
          {Object.keys(EVENT_CATEGORY).map((c) => (
            <option key={c} value={c}>{categoryLabel(c)}</option>
          ))}
        </select>
        <select className={selectCls} value={filters.state ?? ''} onChange={(e) => set({ state: e.target.value || undefined })}>
          <option value="">all states</option>
          {states.map((st) => (
            <option key={st} value={st}>{st}</option>
          ))}
        </select>
        <select
          className={selectCls}
          value={filters.severity ?? ''}
          onChange={(e) => set({ severity: e.target.value ? Number(e.target.value) : undefined })}
        >
          <option value="">any severity</option>
          <option value="2">severity ≥ 2</option>
          <option value="3">severity 3</option>
        </select>
        <select
          className={selectCls}
          value={filters.linked === undefined ? '' : String(filters.linked)}
          onChange={(e) => set({ linked: e.target.value === '' ? undefined : e.target.value === 'true' })}
        >
          <option value="">linked and unlinked</option>
          <option value="true">linked to a project</option>
          <option value="false">unlinked</option>
        </select>
        {filtered && (
          <Button size="sm" variant="ghost" onClick={() => { setFilters({}); setPage(1) }}>
            clear filters
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <Card className="lg:col-span-2" title={`Signals${feed.data ? ` · ${feed.data.total}` : ''}`}>
          {feed.error ? (
            <ApiErrorNote error={feed.error} />
          ) : !feed.data ? (
            <div className="px-5 py-8 text-center text-xs text-fg-dimmed">loading signals...</div>
          ) : feed.data.items.length === 0 ? (
            <div className="px-5 py-8 text-center text-xs text-fg-dimmed space-y-1">
              {filtered ? (
                <div>no stored signal matches these filters — not the same as no external trouble</div>
              ) : (
                <>
                  <div>no news evidence stored yet — not the same as no external trouble</div>
                  <div className="text-xs">
                    {lastRun ? 'the scout ran but stored nothing it could match' : 'the scout has not run on this server'}
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className={cn('grid grid-cols-1 md:grid-cols-2 gap-px bg-border-subtle transition-opacity', feed.isFetching && 'opacity-60')}>
              {feed.data.items.map((s) => (
                <SignalCard key={s.id} s={s} />
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

        <HeatMap feed={feed.data} state={filters.state ?? null} onState={(st) => set({ state: st ?? undefined })} />
      </div>
    </Page>
  )
}
