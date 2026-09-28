import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import type React from 'react'
import { Hourglass, Link2, Radio, Search, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { IconChip } from '@/components/ui/Badge'
import { Select } from '@/components/ui/Input'
import { InfoTip } from '@/components/ui/Tooltip'
import { Button } from '@/components/ui/Button'
import { Page, PageHeader } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { SignalCard } from './external-factors/EvidenceFeed'
import { GEO_URL, MAP_CENTER, OFF_MAP, normStateKey } from './home/indiaGeo'
import { useLiveStatus, usePortfolio, useRadarSummary, useScoutNow, useSignalFeed, type FeedFilters } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { EVENT_CATEGORY, TIER_COLOR, categoryLabel } from '@/lib/riskPalette'
import { cn, formatDateTime } from '@/lib/formatters'
import type { RadarSummary, SignalFeed } from '@/contracts/portfolio'

function Tile({ icon, label, value, sub, info, tone }: {
  icon: LucideIcon
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  info?: React.ReactNode
  tone?: 'critical' | 'accent' | 'warning' | 'stable' | 'muted'
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border-subtle bg-surface-panel p-4 shadow-card animate-card-in">
      <div className="flex items-center gap-2">
        <IconChip icon={icon} size="sm" variant={tone ?? 'muted'} />
        <span className="truncate text-xs text-fg-muted">{label}</span>
        {info && <InfoTip label={`About ${label}`}>{info}</InfoTip>}
      </div>
      <div className="mt-2.5 text-xl font-semibold tabular-nums leading-none text-fg-base">{value}</div>
      {sub && <div className="mt-1.5 text-xs text-fg-dimmed">{sub}</div>}
    </div>
  )
}

function SummaryStrip({ s }: { s: RadarSummary }) {
  const severe = s.bySeverity.filter((r) => Number(r.name) >= 2).reduce((a, r) => a + r.n, 0)
  const cats = s.byCategory.filter((r) => r.name !== 'none').slice(0, 4)
  const catMax = Math.max(1, ...cats.map((c) => c.n))
  const lt = s.leadTime
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile icon={Radio} tone="accent" label={`Last ${s.windowDays} days`} value={s.nWindow} sub={`signals of ${s.nSignalsTotal} stored`} />
      <Tile
        icon={Link2}
        label="Linked · unlinked"
        value={<>{s.nLinked} <span className="text-fg-dimmed">· {s.nUnlinked}</span></>}
        info="Unlinked: an ambiguous or weak match to a project."
      />
      <Tile
        icon={TriangleAlert}
        tone={severe > 0 ? 'critical' : 'muted'}
        label="Severity ≥ 2"
        value={<span className={cn(severe > 0 && 'text-critical')}>{severe}</span>}
        sub={`in the last ${s.windowDays} days`}
      />
      <div className="min-w-0 rounded-xl border border-border-subtle bg-surface-panel p-4 shadow-card animate-card-in">
        <div className="text-xs text-fg-muted">Top categories</div>
        {cats.length === 0 ? (
          <div className="mt-2 text-xs text-fg-dimmed">none tagged</div>
        ) : (
          <div className="mt-2 space-y-1">
            {cats.map((c) => (
              <div key={String(c.name)} className="grid grid-cols-[1fr_2rem] items-center gap-2 text-xs" title={categoryLabel(String(c.name))}>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface-input">
                  <div className="h-full rounded-full" style={{ width: `${(c.n / catMax) * 100}%`, background: EVENT_CATEGORY[String(c.name)]?.color ?? '#9a968c' }} />
                </div>
                <span className="text-right tabular-nums text-fg-base">{c.n}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <Tile icon={Search} label="Projects scouted" value={s.nProjectsScouted} />
      <Tile
        icon={Hourglass}
        tone="warning"
        label="Lead time"
        value={lt.medianLeadDays === null ? '—' : `${lt.medianLeadDays} d`}
        sub={`median · ${lt.nWithLaterChange} of ${lt.nLinkedPairs} linked saw a later change`}
        info={<>Lead time: {lt.basis}. Search results can be years old, so a long gap is weak evidence of an early warning.</>}
      />
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
    <Card title="Severe signals by state" info="Severity 2 or more, last 90 days, by the state of the linked project. Click a state to filter the feed.">
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
      <div className="border-t border-border-subtle px-5 py-2.5 text-xs text-fg-dimmed space-y-1">
        <div className="flex items-center gap-2">
          <span>0</span>
          <span className="h-2 w-16 rounded-full" style={{ background: `linear-gradient(90deg, #eeebe4, ${TIER_COLOR.Critical})` }} />
          <span>{heat.length ? max : 0} severe signals</span>
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
  const { role } = useSession()
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
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-subtle bg-surface-panel px-3 py-2 shadow-card">
        <Select aria-label="category" value={filters.category ?? ''} onChange={(e) => set({ category: e.target.value || undefined })}>
          <option value="">All categories</option>
          {Object.keys(EVENT_CATEGORY).map((c) => (
            <option key={c} value={c}>{categoryLabel(c)}</option>
          ))}
        </Select>
        <Select aria-label="state" value={filters.state ?? ''} onChange={(e) => set({ state: e.target.value || undefined })}>
          <option value="">All states</option>
          {states.map((st) => (
            <option key={st} value={st}>{st}</option>
          ))}
        </Select>
        <Select
          aria-label="severity"
          value={filters.severity ?? ''}
          onChange={(e) => set({ severity: e.target.value ? Number(e.target.value) : undefined })}
        >
          <option value="">Any severity</option>
          <option value="2">severity ≥ 2</option>
          <option value="3">severity 3</option>
        </Select>
        <Select
          aria-label="linked"
          value={filters.linked === undefined ? '' : String(filters.linked)}
          onChange={(e) => set({ linked: e.target.value === '' ? undefined : e.target.value === 'true' })}
        >
          <option value="">Linked and unlinked</option>
          <option value="true">linked to a project</option>
          <option value="false">unlinked</option>
        </Select>
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
            <div className="space-y-2 px-4 py-4" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-surface-input/60" />)}</div>
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
