/**
 * src/views/home/RoleHomes.tsx
 *
 * Home ('/') per role, picked by views/Home.tsx: the public's transparency landing, a ministry official's dashboard
 * and an agency official's scorecard. Each opens with the week's sentences and the portfolio line (WeekBrief), then
 * what the role acts on. Every request is already cut to the viewer's scope by the backend (backend/access.py), so
 * these only choose what to show and how. No model number: tiers, outlook words, agency words, report facts, counts.
 */
import type React from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Building2, FileText, Landmark, Siren } from 'lucide-react'
import { Page, PageHeader } from '@/components/layout/Page'
import { Card } from '@/components/ui/Card'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { OutlookChip } from '@/components/ui/OutlookChip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Meter } from '@/views/command-center/KPIRibbon'
import { WeekBrief } from '@/views/command-center/WeekBrief'
import { IndiaMap } from '@/views/home/IndiaMap'
import { EarlyWarningInbox } from '@/views/home/EarlyWarningInbox'
import { LiveStatus } from '@/views/home/LiveStatus'
import { useAgencyMatrix, useDispatchDrafts, useExternalSummary, usePortfolio, useProjects } from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { outlookOf } from '@/lib/outlook'
import { COST_PHRASE, SCHEDULE_ORDER, SCHEDULE_PHRASE, hasWords, peerClause } from '@/lib/agencyWords'
import { EXTERNAL_FACTORS, TIER_COLOR, TIER_LABEL, tierKey } from '@/lib/riskPalette'
import { cn, formatDate, formatINRShort } from '@/lib/formatters'
import type { AgencyPoint } from '@/contracts/intel'

// ------------------------------------------------------------------ shared pieces

export function LinkButton({ to, primary, children }: { to: string; primary?: boolean; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className={cn(
        'inline-flex h-9 items-center gap-1.5 rounded-lg px-4 text-sm font-medium shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
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
    <Link to={to} className="inline-flex items-center gap-1 rounded font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
      {children} <ArrowRight className="size-3.5" aria-hidden="true" />
    </Link>
  )
}

type Row = { key: string; name: string | null; state: string | null; tier: string | null; override?: boolean | null }

/** A short project list: tier dot, name, state, one thing on the right; a row opens the side panel. */
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
        <div className="space-y-2 px-5 py-3" aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-9 animate-pulse rounded-lg bg-surface-elevated" />)}
        </div>
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-muted">{empty}</div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {rows.map((r) => {
            const t = tierKey(r.tier)
            return (
              <button
                key={r.key}
                type="button"
                onClick={() => panel.open(r.key)}
                className="flex w-full items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
              >
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t] }} title={TIER_LABEL[t]} aria-label={TIER_LABEL[t]} role="img" />
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

/** the riskiest projects in scope with their delay outlook in words */
function MostAtRisk({ n }: { n: number }) {
  const { data: p, error } = usePortfolio()
  const { role } = useSession()
  const numbers = can(role, 'canSeeNumbers')
  return (
    <ProjectList
      title="Most at risk"
      info="The projects the risk model ranks highest in your view, with how likely a delay is over the next two quarters."
      more={<MoreLink to="/command">All projects</MoreLink>}
      rows={p?.top.slice(0, n)}
      error={error}
      empty="No open projects in your view."
      right={(r) => <OutlookChip outlook={outlookOf(r, numbers)} tier={r.tier} />}
    />
  )
}

// ------------------------------------------------------------------ public

const lateBy = (m: number) => (m >= 24 ? `${(m / 12).toFixed(1)} years late` : `${Math.round(m)} months late`)

/** The transparency landing: a flat hero, the portfolio in sentences and one line, the map and two short lists. */
export function PublicHome() {
  const { data: p } = usePortfolio()
  const near = useProjects({ sort: 'progress', size: 5, near_complete: true })
  const late = useProjects({ sort: 'slip', size: 5 })

  return (
    <Page>
      <section className="rounded-2xl border border-border-subtle bg-surface-panel px-6 py-8 shadow-card animate-card-in sm:px-8">
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-fg-base sm:text-4xl">
          Where India&rsquo;s central infrastructure projects stand
        </h1>
        <p className="mt-3 max-w-2xl text-base text-fg-muted">
          Cost, progress and the risk of delay for every open central-sector project{p && <>, as of {formatDate(p.asof)}</>}.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <LinkButton to="/command" primary>Browse all projects <ArrowRight className="size-4" aria-hidden="true" /></LinkButton>
          <LinkButton to="/external">What holds projects up</LinkButton>
        </div>
      </section>

      <WeekBrief title="Where the projects stand" />

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <IndiaMap />
        <div className="space-y-4">
          <ProjectList
            title="Closest to completion"
            info="Open projects 80–99% done whose expected completion date has not passed yet."
            more={<MoreLink to="/command">All projects</MoreLink>}
            rows={near.data?.items}
            error={near.error}
            empty="No open project is 80–99% done and still on its expected date."
            right={(r) => (
              <span className="flex w-32 shrink-0 items-center gap-2">
                <span className="flex-1"><Meter pct={r.physicalProgressPct ?? 0} className="bg-stable" /></span>
                {/* floored: 99.6% done is not "100%" */}
                <span className="w-10 text-right text-xs font-semibold tabular-nums text-fg-base">{r.physicalProgressPct === null ? '—' : `${Math.floor(r.physicalProgressPct)}%`}</span>
              </span>
            )}
          />
          <ProjectList
            title="Longest delays so far"
            info="How far the expected completion date has moved past the original schedule, from the reports."
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

/** The ministry's agencies grouped by their past schedule in words, with how many past and open projects each has. */
function AgenciesRanked() {
  const { data, error } = useAgencyMatrix(false)
  const points = data?.points ?? []
  const words = hasWords(points)
  const groups = SCHEDULE_ORDER
    .map((w) => ({ w, rows: points.filter((a) => a.scheduleWord === w).sort((a, b) => b.nProjects - a.nProjects) }))
    .filter((g) => g.rows.length > 0)
  const row = (a: AgencyPoint) => (
    <Link key={a.agency} to={`/agencies?agency=${encodeURIComponent(a.agency)}`}
      className="flex items-center justify-between gap-3 px-5 py-2 transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40">
      <span className="min-w-0 truncate text-sm font-medium text-fg-base" title={a.names ?? undefined}>{a.agency}</span>
      <span className="shrink-0 text-xs tabular-nums text-fg-dimmed">{a.nProjects} past · {a.nOpen} open</span>
    </Link>
  )
  return (
    <Card
      title="How its agencies usually finish"
      info="Each agency's past projects against their first plan, in words. Agencies with fewer than 5 past projects are left out; a pattern, not a verdict."
      titleRight={<MoreLink to="/agencies">All agencies</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !data ? (
        <div className="h-48 animate-pulse" aria-busy="true" />
      ) : points.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-muted">No agency has 5 or more past projects to compare.</div>
      ) : !words ? (
        <div className="max-h-[360px] overflow-y-auto" data-lenis-prevent>
          <p className="px-5 pt-3 text-xs text-fg-dimmed">The past pattern in words is not available yet; agencies by past projects.</p>
          <div className="divide-y divide-border-subtle">{[...points].sort((a, b) => b.nProjects - a.nProjects).map(row)}</div>
        </div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto" data-lenis-prevent>
          {groups.map(({ w, rows }) => (
            <div key={w}>
              <div className="sticky top-0 bg-surface-elevated px-5 py-1.5 text-xs font-medium text-fg-muted">{SCHEDULE_PHRASE[w]} · {rows.length}</div>
              <div className="divide-y divide-border-subtle">{rows.map(row)}</div>
            </div>
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
      title={<><Siren className="size-4 text-critical" aria-hidden="true" /> Early notice</>}
      info="Projects with a land, forest, court or contractor issue on record while their reports show no slip yet: a reason to ask the agency, not a forecast."
      titleRight={<MoreLink to="/external">What holds projects up</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : !en ? (
        <div className="h-48 animate-pulse" aria-busy="true" />
      ) : (
        <div className="space-y-4 px-5 py-4">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold leading-none tabular-nums text-critical">{en.n_projects.toLocaleString('en-IN')}</span>
            <span className="text-sm text-fg-muted">projects · {formatINRShort(en.capital_exposed_cr)}</span>
          </div>
          <div className="space-y-2">
            {EXTERNAL_FACTORS.map(({ key, label, icon: Icon }) => {
              const n = en.by_factor[key] ?? 0
              return (
                <div key={key} className="grid grid-cols-[1rem_7.5rem_1fr_2rem] items-center gap-2 text-xs">
                  <Icon className="size-3.5 text-fg-dimmed" aria-hidden="true" />
                  <span className="truncate text-fg-muted">{label}</span>
                  <Meter pct={(n / max) * 100} className="bg-fg-muted" />
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

/** A ministry official's dashboard: the week, the riskiest projects, how its agencies finish, early notice, map, alerts. */
export function MinistryHome({ ministry }: { ministry: string }) {
  return (
    <Page>
      <PageHeader
        title={<><Landmark className="size-6 text-accent" aria-hidden="true" /> {ministry}</>}
        actions={<LinkButton to="/command">Open Command Center <ArrowRight className="size-4" aria-hidden="true" /></LinkButton>}
      />
      <WeekBrief />
      <LiveStatus />
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
        <MostAtRisk n={7} />
        <AgenciesRanked />
        <EarlyNoticeCard />
      </div>
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
        <IndiaMap />
        <EarlyWarningInbox />
      </div>
    </Page>
  )
}

// ------------------------------------------------------------------ agency

/**
 * The agency against the other agencies of its sector, in two sentences: its past schedule and cost in words on its
 * past projects, and what most of its peers do (agencies counted by their word).
 */
function AgencyScorecard({ self, peers, error, loading }: { self: AgencyPoint | undefined; peers: AgencyPoint[]; error: unknown; loading: boolean }) {
  const words = self?.scheduleWord
  const peer = self ? peerClause(peers.filter((a) => a !== self), self.sector) : null
  return (
    <Card
      title="How your agency's projects usually finish"
      info="Your agency's past projects against their first plan, in words, beside the other agencies of its sector. Fewer than 5 past projects is too few to say."
      titleRight={<MoreLink to="/agencies">All agencies</MoreLink>}
    >
      {error ? (
        <ApiErrorNote error={error} />
      ) : loading ? (
        <div className="h-40 animate-pulse" aria-busy="true" />
      ) : !self ? (
        <div className="px-5 py-8 text-center text-sm text-fg-muted">
          No past projects with a known planned duration yet, so there is nothing to compare.
        </div>
      ) : !words ? (
        <div className="px-5 py-6 text-sm text-fg-muted">
          Your agency&rsquo;s past pattern in words is not available yet. It has {self.nProjects} past projects and {self.nOpen} open.
        </div>
      ) : (
        <div className="space-y-3 px-5 py-5">
          <p className="text-lg leading-relaxed text-fg-base">
            <span className="font-semibold">Schedule:</span> {SCHEDULE_PHRASE[words].toLowerCase()}, on {self.nProjects} past project{self.nProjects === 1 ? '' : 's'}
            {peer && words !== 'too few projects' ? `; ${peer}.` : '.'}
          </p>
          {self.costWord && (
            <p className="text-lg leading-relaxed text-fg-base">
              <span className="font-semibold">Cost:</span> {COST_PHRASE[self.costWord].toLowerCase()}, on {self.nCost} past project{self.nCost === 1 ? '' : 's'} with costs.
            </p>
          )}
          <p className="text-xs text-fg-dimmed">{self.nOpen} open projects now · {formatINRShort(self.capitalCr)}</p>
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
        <div className="h-32 animate-pulse" aria-busy="true" />
      ) : (
        <div className="space-y-3 px-5 py-4">
          <div className="flex items-baseline gap-2">
            <span className={cn('text-3xl font-semibold leading-none tabular-nums', pending.length ? 'text-warning' : 'text-fg-base')}>{pending.length}</span>
            <span className="text-sm text-fg-muted">{pending.length === 1 ? 'memo needs' : 'memos need'} your decision</span>
          </div>
          {pending.length === 0 && <p className="text-xs text-fg-dimmed">Nothing is waiting for you.</p>}
          {pending.slice(0, 3).map((d) => (
            <Link key={d.id} to="/approvals" className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
              <FileText className="size-4 shrink-0 text-fg-dimmed" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-sm text-fg-base">{d.projectName}</span>
              <span className="shrink-0 text-xs text-fg-dimmed">{formatDate(d.createdAt)}</span>
            </Link>
          ))}
        </div>
      )}
    </Card>
  )
}

/** An agency official's scorecard: the week, how its projects usually finish, approvals, riskiest projects and alerts. */
export function AgencyHome({ agency }: { agency: string }) {
  // every agency (n < 5 too), so a small agency still finds itself; its peers are the others of its sector
  const matrix = useAgencyMatrix(true)
  const self = matrix.data?.points.find((a) => a.isSelf)
  const peers = self ? (matrix.data?.points ?? []).filter((a) => a.sector === self.sector && (!a.hidden || a === self)) : []

  return (
    <Page>
      <PageHeader
        title={<><Building2 className="size-6 text-accent" aria-hidden="true" /> {agency}</>}
        subtitle={self ? [self.ministry, self.sector].filter(Boolean).join(' · ') : undefined}
        actions={<LinkButton to="/command">Your projects <ArrowRight className="size-4" aria-hidden="true" /></LinkButton>}
      />
      <WeekBrief />
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AgencyScorecard self={self} peers={peers} error={matrix.error} loading={!matrix.data} />
        </div>
        <ApprovalsCard />
      </div>
      <LiveStatus />
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
        <MostAtRisk n={8} />
        <EarlyWarningInbox />
      </div>
    </Page>
  )
}
