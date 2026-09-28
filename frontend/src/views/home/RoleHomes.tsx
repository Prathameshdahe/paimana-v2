/**
 * src/views/home/RoleHomes.tsx
 *
 * Home ('/') per role, picked by views/Home.tsx: the public's transparency landing, a ministry official's dashboard
 * and an agency official's scorecard. Every request is already cut to the viewer's scope by the backend
 * (backend/access.py), so these only choose what to show and how.
 */
import type React from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Building2, FileText, Gauge, IndianRupee, Landmark, Siren, TrendingUp } from 'lucide-react'
import { Page, PageHeader } from '@/components/layout/Page'
import { Card } from '@/components/ui/Card'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { InfoTip, Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { KPIRibbon, Meter, Tile, TierBar } from '@/views/command-center/KPIRibbon'
import { IndiaMap } from '@/views/home/IndiaMap'
import { EarlyWarningInbox } from '@/views/home/EarlyWarningInbox'
import { LiveStatus } from '@/views/home/LiveStatus'
import {
  useAgencyMatrix, useDispatchDrafts, useExternalSummary, usePortfolio, useProjects,
} from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { EXTERNAL_FACTORS, TIERS, TIER_COLOR, TIER_LABEL, tierKey } from '@/lib/riskPalette'
import {
  cn, formatBiasCi, formatDate, formatINRShort, formatPct, formatPctDelta, formatProb, formatSignedRatio, orDash,
} from '@/lib/formatters'
import type { AgencyPoint } from '@/contracts/intel'

// ------------------------------------------------------------------ shared pieces

export function LinkButton({ to, primary, children }: { to: string; primary?: boolean; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className={cn(
        'inline-flex h-9 items-center gap-1.5 rounded-lg px-4 text-sm font-medium shadow-sm transition-colors',
        primary
          ? 'bg-fg-base text-fg-inverse hover:bg-fg-base/85'
          : 'border border-border-default bg-surface-panel text-fg-base hover:bg-surface-elevated'
      )}
    >
      {children}
    </Link>
  )
}

function MoreLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
      {children} <ArrowRight className="size-3.5" />
    </Link>
  )
}

type Row = { key: string; name: string | null; state: string | null; tier: string | null; override?: boolean | null }

/** A short project list: tier dot, name, state, one visual on the right; a row opens the side panel. */
function ProjectList<T extends Row>({ title, info, more, rows, error, right, empty }: {
  title: React.ReactNode
  info?: React.ReactNode
  more?: React.ReactNode
  rows: T[] | undefined
  error: unknown
  right: (r: T) => React.ReactNode
  empty: string
}) {
  const panel = useProjectPanel()
  return (
    <Card title={title} info={info} titleRight={more}>
      {error ? (
        <ApiErrorNote error={error} />
      ) : !rows ? (
        <div className="space-y-2 px-5 py-3">
          {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-9 animate-pulse rounded-lg bg-surface-elevated" />)}
        </div>
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-dimmed">{empty}</div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {rows.map((r) => {
            const t = tierKey(r.tier)
            return (
              <button
                key={r.key}
                onClick={() => panel.open(r.key)}
                className="flex w-full items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-surface-elevated"
              >
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t] }} title={TIER_LABEL[t]} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-fg-base" title={r.name ?? undefined}>{r.name ?? r.key}</span>
                  <span className="flex items-center gap-1.5 truncate text-xs text-fg-dimmed">
                    {r.state ?? 'state unknown'}
                    {r.override && <StalledBadge className="py-0" />}
                  </span>
                </span>
                {right(r)}
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}

/** chance of a new delay or cost revision within two quarters, as a bar */
function RiskCell({ p }: { p: number | null }) {
  const tone = p === null ? 'bg-fg-dimmed' : p >= 0.5 ? 'bg-critical' : p >= 0.2 ? 'bg-warning' : 'bg-accent'
  return (
    <span className="flex w-28 shrink-0 items-center gap-2" title="chance of a new delay or cost revision within two quarters">
      <span className="flex-1"><Meter pct={(p ?? 0) * 100} className={tone} /></span>
      <span className="w-9 text-right text-xs font-semibold tabular-nums text-fg-base">{orDash(p, formatProb)}</span>
    </span>
  )
}

/** a bar from a centre zero line: overrun to the right (red), under to the left (green) */
function SignedBar({ value, scale }: { value: number | null; scale: number }) {
  return (
    <div className="relative h-2 rounded-full bg-surface-input">
      <div className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
      {value !== null && (
        <div
          className={cn('absolute inset-y-0 rounded-full transition-[width] duration-700', value > 0 ? 'bg-critical/75' : 'bg-stable/75')}
          style={value >= 0
            ? { left: '50%', width: `${Math.min(1, value / scale) * 50}%` }
            : { right: '50%', width: `${Math.min(1, -value / scale) * 50}%` }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ public

const lateBy = (m: number) => (m >= 24 ? `${(m / 12).toFixed(1)} years late` : `${Math.round(m)} months late`)

/** The transparency landing: headline figures, the risk mix, the map and two short lists; no alerts. */
export function PublicHome() {
  const { data: p, error } = usePortfolio()
  const near = useProjects({ sort: 'progress', size: 5, near_complete: true })
  const late = useProjects({ sort: 'slip', size: 5 })
  const k = p?.kpis
  const nStates = p?.byState.filter((s) => s.name).length

  return (
    <Page>
      <section className="rounded-2xl border border-border-subtle bg-gradient-to-br from-accent/10 via-surface-panel to-surface-panel px-6 py-8 shadow-card animate-card-in sm:px-8">
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-fg-base sm:text-4xl">
          Where India&rsquo;s central infrastructure projects stand
        </h1>
        <p className="mt-3 max-w-2xl text-base text-fg-muted">
          Cost, progress and the risk of delay for every open central-sector project{p && <>, as of {formatDate(p.asof)}</>}.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <LinkButton to="/command" primary>Browse all projects <ArrowRight className="size-4" /></LinkButton>
          <LinkButton to="/external">External factors</LinkButton>
        </div>
      </section>

      {error ? (
        <Card><ApiErrorNote error={error} /></Card>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Tile icon={Building2} tone="accent" label="Open projects" value={k ? k.nProjects.toLocaleString() : '…'}>
            <div className="mt-2 text-xs text-fg-dimmed">{nStates ?? '…'} states · {p?.bySector.length ?? '…'} sectors</div>
          </Tile>
          <Tile icon={IndianRupee} tone="accent" label="Anticipated cost" value={orDash(k?.anticipatedCostCr, formatINRShort)}>
            <div className="mt-2 text-xs text-fg-dimmed">originally {orDash(k?.originalCostCr, formatINRShort)}</div>
          </Tile>
          <Tile icon={TrendingUp} tone="critical" label="Cost overrun" value={<span className="text-critical">{orDash(k?.overrunPct, formatPctDelta)}</span>}>
            <div className="mt-2 text-xs text-fg-dimmed">{orDash(k?.overrunCr, formatINRShort)} above the original cost</div>
          </Tile>
          <Tile icon={Gauge} tone="stable" label="Average progress" value={orDash(k?.avgProgressPct, (v) => formatPct(v, 0))}>
            <div className="mt-3"><Meter pct={k?.avgProgressPct ?? 0} className="bg-stable" /></div>
          </Tile>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
        <IndiaMap />
        <div className="space-y-5">
          {p && (
            <Card
              title="Risk of delay"
              info="Open projects are ranked by the chance of a new delay or cost revision in the next six months. Projects with no completion date on record are not ranked."
            >
              <div className="space-y-4 px-5 py-4">
                <TierBar tiers={p.tiers} total={p.kpis.nProjects} className="h-3" />
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-5">
                  {[...TIERS, 'Watch' as const].map((t) => {
                    const n = p.tiers.find((x) => x.tier === t)?.n ?? 0
                    return (
                      <div key={t} className="flex items-start gap-2">
                        <span className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t] }} />
                        <span>
                          <span className="block text-lg font-semibold leading-tight tabular-nums text-fg-base">{n.toLocaleString()}</span>
                          <span className="block text-xs text-fg-dimmed">{TIER_LABEL[t]}</span>
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </Card>
          )}
          <ProjectList
            title="Closest to completion"
            info="Open projects 80-99% done whose expected completion date has not passed yet."
            more={<MoreLink to="/command">All projects</MoreLink>}
            rows={near.data?.items}
            error={near.error}
            empty="No open project is 80-99% done and still on its expected date."
            right={(r) => (
              <span className="flex w-32 shrink-0 items-center gap-2">
                <span className="flex-1"><Meter pct={r.physicalProgressPct ?? 0} className="bg-stable" /></span>
                {/* floored: 99.6% done is not "100%" */}
                <span className="w-10 text-right text-xs font-semibold tabular-nums text-fg-base">{orDash(r.physicalProgressPct, (v) => `${Math.floor(v)}%`)}</span>
              </span>
            )}
          />
          <ProjectList
            title="Longest delays"
            info="How far the expected completion date has moved past the original schedule."
            rows={late.data?.items}
            error={late.error}
            empty="No open project is behind its original schedule."
            right={(r) => r.slipToDateMonths !== null && <Badge variant="critical">{lateBy(r.slipToDateMonths)}</Badge>}
          />
        </div>
      </div>
    </Page>
  )
}

// ------------------------------------------------------------------ ministry

/** The ministry's agencies ranked by schedule overrun on past projects, worst first, as signed bars. */
function AgenciesRanked() {
  const { data, error } = useAgencyMatrix(false)
  const rows = [...(data?.points ?? [])]
    .filter((a) => a.scheduleBias !== null)
    .sort((a, b) => (b.scheduleBias ?? 0) - (a.scheduleBias ?? 0))
  const scale = Math.max(0.1, ...rows.map((a) => Math.abs(a.scheduleBias ?? 0)))
  return (
    <Card
      title="Agencies by schedule overrun"
      info="How much longer each agency's past projects took than first planned (median). Agencies with fewer than 5 past projects are left out; fewer than 10 are pulled toward the sector median."
      titleRight={<MoreLink to="/agencies">Matrix</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="h-48 animate-pulse" />
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-dimmed">No agency has 5 or more past projects to compare.</div>
      ) : (
        <div className="max-h-[360px] divide-y divide-border-subtle overflow-y-auto" data-lenis-prevent>
          {rows.map((a) => (
            <Link key={a.agency} to={`/agencies?agency=${encodeURIComponent(a.agency)}`} className="grid grid-cols-[minmax(0,1fr)_6rem_3rem] items-center gap-3 px-5 py-2 transition-colors hover:bg-surface-elevated">
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-fg-base" title={a.names ?? undefined}>{a.agency}</span>
                <span className="block text-xs text-fg-dimmed">{a.nOpen} open</span>
              </span>
              <SignedBar value={a.scheduleBias} scale={scale} />
              <span className="text-right text-xs font-semibold tabular-nums text-fg-base">{formatSignedRatio(a.scheduleBias)}</span>
            </Link>
          ))}
        </div>
      )}
    </Card>
  )
}

/** Early-notice projects in scope: the count, their capital and a bar per external factor. */
function EarlyNoticeCard() {
  const { data, error } = useExternalSummary()
  const en = data?.earlyNotice
  const max = Math.max(1, ...EXTERNAL_FACTORS.map(({ key }) => en?.by_factor[key] ?? 0))
  return (
    <Card
      title={<><Siren className="size-4 text-critical" /> Early notice</>}
      info="Projects with a land, forest, litigation or contractor issue on record while their numbers show no slip yet (or rank Low or Medium): a reason to ask the agency, not a forecast."
      titleRight={<MoreLink to="/external">External factors</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !en ? (
        <div className="h-48 animate-pulse" />
      ) : (
        <div className="space-y-4 px-5 py-4">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold leading-none tabular-nums text-critical">{en.n_projects.toLocaleString()}</span>
            <span className="text-sm text-fg-muted">projects · {formatINRShort(en.capital_exposed_cr)}</span>
          </div>
          <div className="space-y-2">
            {EXTERNAL_FACTORS.map(({ key, label, icon: Icon }) => {
              const n = en.by_factor[key] ?? 0
              return (
                <div key={key} className="grid grid-cols-[1rem_7.5rem_1fr_2rem] items-center gap-2 text-xs">
                  <Icon className="size-3.5 text-fg-dimmed" />
                  <span className="truncate text-fg-muted">{label}</span>
                  <Meter pct={(n / max) * 100} className="bg-critical/70" />
                  <span className="text-right font-semibold tabular-nums text-fg-base">{n}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </Card>
  )
}

/** A ministry official's dashboard: the ministry's figures, riskiest projects, agencies, early notice, map, alerts. */
export function MinistryHome({ ministry }: { ministry: string }) {
  const { data: p, error } = usePortfolio()
  return (
    <Page>
      <PageHeader
        title={<><Landmark className="size-6 text-accent" /> {ministry}</>}
        subtitle="Your ministry's projects, alerts and agencies"
        actions={<LinkButton to="/command">Open Command Center <ArrowRight className="size-4" /></LinkButton>}
      />
      <KPIRibbon />
      <LiveStatus />
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-3">
        <ProjectList
          title="Most at risk"
          more={<MoreLink to="/command">All projects</MoreLink>}
          rows={p?.top.slice(0, 7)}
          error={error}
          empty="No open projects."
          right={(r) => <RiskCell p={r.pAny2q} />}
        />
        <AgenciesRanked />
        <EarlyNoticeCard />
      </div>
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-2">
        <IndiaMap />
        <EarlyWarningInbox />
      </div>
    </Page>
  )
}

// ------------------------------------------------------------------ agency

/** 90th percentile, so one extreme peer does not squash the scale */
function p90(values: number[]): number {
  const s = [...values].sort((a, b) => a - b)
  return s[Math.floor(0.9 * (s.length - 1))] ?? 0
}

/**
 * One bullet bar: the agency's bias as a bar from zero, the sector median as a tick, every peer agency as a faint
 * dot on the same scale (a peer past the scale sits at its edge).
 */
function BiasBullet({ label, self, sector, peers, note, rank }: {
  label: string
  self: number | null
  sector: number | null
  peers: number[]
  note: string
  rank: { rank: number; of: number } | null
}) {
  const known = [self, sector].filter((v): v is number => v !== null)
  const lo = Math.min(0, ...known, ...peers)
  const hi = Math.max(0.1, ...known, p90(peers))
  const pos = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`
  const worse = self !== null && sector !== null && self > sector
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 text-sm font-medium text-fg-base">
          {label}
          <InfoTip label={`About ${label.toLowerCase()}`}>{note}</InfoTip>
        </span>
        <span className="flex items-baseline gap-2">
          <span className={cn('text-2xl font-semibold tabular-nums leading-none', worse ? 'text-critical' : 'text-stable')}>{formatSignedRatio(self)}</span>
          {rank && <Badge variant={rankTone(rank)}>#{rank.rank} of {rank.of}</Badge>}
        </span>
      </div>
      <div className="relative h-6">
        <div className="absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-surface-input" />
        {peers.map((v, i) => (
          <span key={i} className="absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg-dimmed/50" style={{ left: pos(v) }} />
        ))}
        {self !== null && (
          <div
            className={cn('absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full transition-all duration-700', worse ? 'bg-critical/80' : 'bg-stable/80')}
            style={{ left: pos(Math.min(0, self)), width: `calc(${pos(Math.max(0, self))} - ${pos(Math.min(0, self))})` }}
          />
        )}
        <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: pos(0) }} />
        {self !== null && (
          <span
            className={cn('absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface-panel', worse ? 'bg-critical' : 'bg-stable')}
            style={{ left: pos(self) }}
          />
        )}
        {sector !== null && (
          <Tooltip content={`sector median ${formatSignedRatio(sector)}`}>
            <div className="absolute inset-y-0 w-1 -translate-x-1/2 rounded-full bg-fg-base" style={{ left: pos(sector) }} />
          </Tooltip>
        )}
      </div>
      <div className="flex justify-between text-xs text-fg-dimmed">
        <span>sector median {formatSignedRatio(sector)}</span>
        <span>{peers.length} peer agencies</span>
      </div>
    </div>
  )
}

/** the rank badge's colour by position (rank 1 = smallest overrun): top third green, bottom third red, amber between */
function rankTone({ rank, of }: { rank: number; of: number }): 'stable' | 'warning' | 'critical' {
  const pos = rank / Math.max(of, 1)
  return pos <= 1 / 3 ? 'stable' : pos > 2 / 3 ? 'critical' : 'warning'
}

/** rank 1 = the smallest overrun among the peers that have the value; ties share a rank */
function rankOf(self: AgencyPoint, peers: AgencyPoint[], get: (a: AgencyPoint) => number | null) {
  const v = get(self)
  if (v === null) return null
  const known = peers.map(get).filter((x): x is number => x !== null)
  return { rank: known.filter((x) => x < v).length + 1, of: known.length }
}

/** The agency against the other agencies of its sector on the Agency matrix, schedule and cost. */
function AgencyScorecard({ self, peers, error, loading }: { self: AgencyPoint | undefined; peers: AgencyPoint[]; error: unknown; loading: boolean }) {
  const others = peers.filter((a) => a !== self)
  return (
    <Card
      title="Your agency against its sector"
      info="Median of how much longer and costlier your agency's past projects ran than first planned, against the other agencies of its sector (dots) and the sector median (tick). Rank 1 is the smallest overrun. Agencies with fewer than 5 past projects are not ranked; fewer than 10 are pulled toward the sector median."
      titleRight={<MoreLink to="/agencies">Open the matrix</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : loading ? (
        <div className="h-48 animate-pulse" />
      ) : !self ? (
        <div className="px-5 py-8 text-center text-sm text-fg-dimmed">
          No past projects with a known planned duration yet, so there is nothing to compare.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 px-5 py-5 md:grid-cols-2">
          <BiasBullet
            label="Schedule"
            self={self.scheduleBias}
            sector={self.sectorScheduleBias}
            peers={others.map((a) => a.scheduleBias).filter((v): v is number => v !== null)}
            rank={rankOf(self, peers, (a) => a.scheduleBias)}
            note={`How much longer than planned (median of ${self.nProjects} past projects).${formatBiasCi(self.shrunk, self.scheduleBiasRaw, self.scheduleBiasCiLo, self.scheduleBiasCiHi)}`}
          />
          <BiasBullet
            label="Cost"
            self={self.costBias}
            sector={self.sectorCostBias}
            peers={others.map((a) => a.costBias).filter((v): v is number => v !== null)}
            rank={rankOf(self, peers, (a) => a.costBias)}
            note={`How much costlier than planned (median of ${self.nCost} past projects with costs).${formatBiasCi(self.shrunk, self.costBiasRaw, self.costBiasCiLo, self.costBiasCiHi)}`}
          />
        </div>
      )}
    </Card>
  )
}

/** Memos from the worker cell waiting for this agency's decision. */
function ApprovalsCard() {
  const { data, error } = useDispatchDrafts()
  const pending = (data ?? []).filter((d) => d.status === 'pending')
  return (
    <Card title="Approvals waiting" titleRight={<MoreLink to="/approvals">Inbox</MoreLink>} className="flex flex-col">
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="h-32 animate-pulse" />
      ) : (
        <div className="space-y-3 px-5 py-4">
          <div className="flex items-baseline gap-2">
            <span className={cn('text-3xl font-semibold leading-none tabular-nums', pending.length ? 'text-warning' : 'text-fg-base')}>{pending.length}</span>
            <span className="text-sm text-fg-muted">{pending.length === 1 ? 'memo needs' : 'memos need'} your decision</span>
          </div>
          {pending.slice(0, 3).map((d) => (
            <Link key={d.id} to="/approvals" className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-surface-elevated">
              <FileText className="size-4 shrink-0 text-fg-dimmed" />
              <span className="min-w-0 flex-1 truncate text-sm text-fg-base">{d.projectName}</span>
              <span className="shrink-0 text-xs text-fg-dimmed">{formatDate(d.createdAt)}</span>
            </Link>
          ))}
        </div>
      )}
    </Card>
  )
}

/** An agency official's scorecard: against its peers, its own figures, riskiest projects, approvals and alerts. */
export function AgencyHome({ agency }: { agency: string }) {
  const { data: p, error } = usePortfolio()
  // every agency (n < 5 too), so a small agency still finds itself; its peers are the ranked ones of its sector
  const matrix = useAgencyMatrix(true)
  const self = matrix.data?.points.find((a) => a.isSelf)
  const peers = self ? (matrix.data?.points ?? []).filter((a) => a.sector === self.sector && (!a.hidden || a === self)) : []

  return (
    <Page>
      <PageHeader
        title={<><Building2 className="size-6 text-accent" /> {agency}</>}
        subtitle={self ? [self.ministry, self.sector].filter(Boolean).join(' · ') : "Your agency's scorecard"}
        actions={<LinkButton to="/command">Your projects <ArrowRight className="size-4" /></LinkButton>}
      />
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AgencyScorecard self={self} peers={peers} error={matrix.error} loading={!matrix.data} />
        </div>
        <ApprovalsCard />
      </div>
      <KPIRibbon />
      <LiveStatus />
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-2">
        <ProjectList
          title="Most at risk"
          more={<MoreLink to="/command">All projects</MoreLink>}
          rows={p?.top.slice(0, 8)}
          error={error}
          empty="No open projects."
          right={(r) => <RiskCell p={r.pAny2q} />}
        />
        <EarlyWarningInbox />
      </div>
    </Page>
  )
}
