import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { FileSearch, Info, Siren } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge, IconChip, StalledBadge } from '@/components/ui/Badge'
import { InfoTip } from '@/components/ui/Tooltip'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Page, PageHeader } from '@/components/layout/Page'
import { EvidenceFeed } from './external-factors/EvidenceFeed'
import { LandMap } from './external-factors/LandMap'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { useExternalSummary } from '@/lib/queries'
import { formatDate, formatINR, formatINRShort, formatProb, orDash, cn } from '@/lib/formatters'
import { EXTERNAL_FACTORS as FACTORS, EVENT_CATEGORY, FLAG_ICON } from '@/lib/riskPalette'
import { details, formatQuarter, fromPrior, verdict } from '@/lib/external'
import type {
  CompositeDistribution, ExternalFactorKey, ExternalProject, ExternalSummary, HiddenDelayPrior, PortalOpen, ProposalCase,
  ProposalStatus,
} from '@/contracts/portfolio'

const FACTOR: Partial<Record<string, (typeof FACTORS)[number]>> = Object.fromEntries(FACTORS.map((f) => [f.key, f]))

// ml/risk_profile.py COMPOSITE_HIGH: the composite flags at this score (fc+la coverage only)
const COMPOSITE_HIGH = 0.6

/** "land: open in reports, mentioned ...: 'quote'" -> ["land", "open in reports, ..."] */
function splitEvidence(line: string): [string, string] {
  const i = line.indexOf(': ')
  return i < 0 ? ['', line] : [line.slice(0, i), line.slice(i + 2)]
}

const pct = (v: number | null) => orDash(v, (x) => formatProb(x))
const times = (v: number | null) => orDash(v, (x) => `×${x.toFixed(2)}`)
const slip = (v: number | null) => orDash(v, (x) => `${x.toFixed(0)}mo`)

/** a rounded bar, `share` of 0-1 filled */
function Bar({ share, className = 'bg-warning' }: { share: number; className?: string }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-surface-input">
      <div className={cn('h-full rounded-full', className)} style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }} />
    </div>
  )
}

/**
 * External Factors (/external) over /api/external/summary: per-factor tiles and their top
 * projects, the early-notice list, coverage and the composite score; the caveats sit in one
 * "About this data" section. Every figure comes from gold/external_summary.json. The news
 * evidence below pages /api/signals/feed (officials only; the public sees the summary).
 */
export function ExternalFactors() {
  const { data, error, isLoading } = useExternalSummary()
  const { role } = useRole()

  return (
    <Page>
      <PageHeader
        title="External Factors"
        subtitle="Issues on the ground that the cost and schedule numbers show only at a later revision"
        actions={
          data && (
            <span className="text-xs text-fg-dimmed">
              as of {formatDate(data.asOfDate)} · {data.nProjects.toLocaleString()} projects
              {can(role, 'canSeeModelVersion') && ` · ${data.modelVersion}`}
            </span>
          )
        }
      />

      {error ? (
        <Card>
          <ApiErrorNote error={error} />
        </Card>
      ) : isLoading || !data ? (
        <div className="h-48 flex items-center justify-center text-sm text-fg-dimmed">loading external factors...</div>
      ) : (
        <>
          <FactorBoard s={data} />
          <EarlyNoticePanel s={data} />
          <PortalPanel s={data} />
          <HiddenDelayPanel s={data} />
          <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
            {data.landCoverage?.by_state && <LandMap states={data.landCoverage.by_state} />}
            <div className="space-y-5">
              <RemarkFlagsPanel s={data} />
              <CoveragePanel s={data} />
            </div>
          </div>
          <CompositePanel s={data} />
          <AboutData s={data} />
        </>
      )}

      {can(role, 'canSeeNews') && <EvidenceFeed />}

      <p className="text-xs text-fg-dimmed">External-factor datasets and rulebook: Garvit</p>
    </Page>
  )
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'critical' | 'warning' }) {
  return (
    <div className="bg-surface-panel px-5 py-4">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={cn('mt-1.5 text-xl font-semibold tabular-nums leading-none', tone === 'critical' ? 'text-critical' : tone === 'warning' ? 'text-warning' : 'text-fg-base')}>
        {value}
      </div>
      {sub && <div className="mt-1.5 text-xs text-fg-dimmed">{sub}</div>}
    </div>
  )
}

/** One project from a summary top list, linking to its project page. */
function ProjectLine({ p, factor }: { p: ExternalProject; factor: ExternalFactorKey }) {
  const panel = useProjectPanel()
  const lines = p.evidence.map(splitEvidence).filter(([f]) => f === factor)

  return (
    <button onClick={() => panel.open(p.project_key)} className="block w-full bg-surface-panel px-5 py-3 text-left transition-colors hover:bg-surface-elevated">
      <div className="flex items-start justify-between gap-3">
        <span className="truncate text-sm font-medium text-fg-base" title={p.project_name ?? undefined}>
          {p.project_name ?? p.project_key}
        </span>
        <span className="shrink-0 font-mono text-sm tabular-nums text-fg-base">{orDash(p.anticipated_cost_cr, formatINR)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs text-fg-dimmed">
        <Badge tier={p.tier} />
        {p.stalled && <StalledBadge />}
        <span className="truncate">{p.project_key} · {p.state ?? 'state unknown'} · slip so far {slip(p.slip_to_date_months)}</span>
      </div>
      {lines.map(([, text], i) => (
        <div key={i} className="mt-1.5 text-xs leading-snug text-fg-muted line-clamp-2" title={text}>
          {text}
        </div>
      ))}
    </button>
  )
}

/** six factor tiles (count, capital bar, early notice); the picked one lists its top projects */
function FactorBoard({ s }: { s: ExternalSummary }) {
  const first = FACTORS.find(({ key }) => (s.factors[key]?.n_flagged ?? 0) > 0)?.key ?? 'land'
  const [picked, setPicked] = useState<ExternalFactorKey>(first)
  const maxCap = Math.max(1, ...FACTORS.map(({ key }) => s.factors[key]?.capital_exposed_cr ?? 0))
  const f = s.factors[picked]
  const meta = FACTOR[picked]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {FACTORS.map(({ key, label, icon }) => {
          const x = s.factors[key]
          const en = s.earlyNotice.by_factor[key] ?? 0
          const on = key === picked
          return (
            <button
              key={key}
              aria-pressed={on}
              disabled={!x}
              onClick={() => setPicked(key)}
              className={cn(
                'rounded-xl border bg-surface-panel p-4 text-left shadow-card transition-all animate-card-in disabled:opacity-60',
                on ? 'border-accent ring-2 ring-accent/20' : 'border-border-subtle hover:border-border-strong'
              )}
            >
              <div className="flex items-center gap-2">
                <IconChip icon={icon} size="sm" variant={x?.n_flagged ? 'warning' : 'muted'} />
                <span className="truncate text-sm font-medium text-fg-base">{label}</span>
              </div>
              {!x ? (
                <div className="mt-3 text-xs text-fg-dimmed">not in the summary — unknown, not clear</div>
              ) : (
                <>
                  <div className="mt-3 flex items-baseline gap-1.5">
                    <span className="text-2xl font-semibold tabular-nums leading-none text-fg-base">{x.n_flagged.toLocaleString()}</span>
                    <span className="text-xs text-fg-dimmed">flagged</span>
                  </div>
                  <div className="mt-3"><Bar share={x.capital_exposed_cr / maxCap} /></div>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
                    <span className="text-fg-muted">{formatINRShort(x.capital_exposed_cr)}</span>
                    {en > 0 && (
                      <span className="flex items-center gap-1 font-medium text-critical" title="early notice: flagged while the numbers show no slip yet">
                        <Siren className="size-3" /> {en}
                      </span>
                    )}
                  </div>
                </>
              )}
            </button>
          )
        })}
      </div>

      {f && meta && (
        <Card
          title={<>{meta.label} <span className="font-normal text-fg-dimmed">· top {f.top.length} of {f.n_flagged} by capital</span></>}
          titleRight={
            meta.flag && (
              <Link to={`/command?flag=${meta.flag}`} className="text-accent hover:underline">
                All in Command Center &rarr;
              </Link>
            )
          }
        >
          {f.top.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-fg-dimmed">no current project flagged for this factor</div>
          ) : (
            <div className="grid grid-cols-1 gap-px bg-border-subtle lg:grid-cols-2">
              {f.top.map((p) => (
                <ProjectLine key={p.project_key} p={p} factor={picked} />
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function NoticeTable({ rows }: { rows: ExternalProject[] }) {
  const panel = useProjectPanel()

  if (rows.length === 0) {
    return <div className="px-5 py-6 text-center text-sm text-fg-dimmed">no project in this list</div>
  }
  const th = 'py-2.5 px-4 text-xs font-medium text-fg-muted'
  // the public gets no evidence lines (as on its project page): no Evidence column then
  const withEvidence = rows.some((p) => p.evidence.length > 0)
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-y border-border-subtle bg-surface-elevated/60">
            <th className={cn(th, 'pl-5')}>Project</th>
            <th className={th}>Factor</th>
            {withEvidence && <th className={th}>Evidence</th>}
            <th className={th}>Tier</th>
            <th className={cn(th, 'text-right whitespace-nowrap')}>Slip so far</th>
            <th className={cn(th, 'pr-5 text-right')}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const lines = p.evidence.map(splitEvidence)
            return (
              <tr
                key={p.project_key}
                onClick={() => panel.open(p.project_key)}
                className="cursor-pointer border-b border-border-subtle/70 align-top transition-colors hover:bg-surface-elevated/70"
              >
                <td className="max-w-[280px] py-3 pl-5 pr-4">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); panel.open(p.project_key) }}
                    className="block max-w-full truncate text-left font-medium text-fg-base hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                    title={p.project_name ?? undefined}
                  >
                    {p.project_name ?? p.project_key}
                  </button>
                  <div className="mt-0.5 truncate text-xs text-fg-dimmed">
                    {p.project_key} · {p.sector ?? 'sector unknown'} · {p.state ?? 'state unknown'}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-1">
                    {(p.factors ?? lines.map(([f]) => f)).map((f, i) => {
                      const m = FACTOR[f]
                      return (
                        <span key={i} className="flex items-center gap-1.5 whitespace-nowrap text-xs text-warning">
                          {m && <m.icon className="size-3.5" />}
                          {m?.label ?? f}
                        </span>
                      )
                    })}
                  </div>
                </td>
                {withEvidence && (
                  <td className="min-w-[220px] px-4 py-3">
                    {lines.map(([, text], i) => (
                      <div key={i} className="text-xs leading-snug text-fg-muted line-clamp-2" title={text}>
                        {text}
                      </div>
                    ))}
                  </td>
                )}
                <td className="px-4 py-3">
                  <div className="flex flex-col items-start gap-1"><Badge tier={p.tier} />{p.stalled && <StalledBadge />}</div>
                  <div className="mt-1 whitespace-nowrap text-xs text-fg-dimmed">P(slip) {pct(p.p_any_2q)}</div>
                </td>
                <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-base">{slip(p.slip_to_date_months)}</td>
                <td className="whitespace-nowrap py-3 pl-4 pr-5 text-right font-mono tabular-nums text-fg-base">
                  {orDash(p.anticipated_cost_cr, formatINR)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EarlyNoticePanel({ s }: { s: ExternalSummary }) {
  const en = s.earlyNotice
  const strictTop = en.top.filter((p) => p.slip_to_date_months !== null && p.slip_to_date_months <= 0)
  const maxBy = Math.max(1, ...FACTORS.map(({ key }) => en.by_factor[key] ?? 0))

  return (
    <Card
      title={<><Siren className="size-4 text-critical" /> Early notice</>}
      info={
        <>
          A flagged external factor while the CUF numbers do not show a slip yet. Two readings of &ldquo;no slip yet&rdquo;:
          strictly, slip to date of 0 months or less; broadly, that or a Low/Medium tier (which includes projects that
          already slipped but rank low on the model).
        </>
      }
      titleRight={
        <Link to="/command?flag=early_notice" className="text-accent hover:underline">
          All {en.n_projects} in Command Center &rarr;
        </Link>
      }
    >
      <div className="grid grid-cols-2 gap-px border-b border-border-subtle bg-border-subtle lg:grid-cols-4">
        <Stat
          label="Broad: no slip or tier Low/Medium"
          value={en.n_projects.toLocaleString()}
          sub={`${formatINRShort(en.capital_exposed_cr)} capital`}
          tone="critical"
        />
        <Stat
          label="Strict: no slip to date"
          value={en.no_slip_to_date.n_projects.toLocaleString()}
          sub={`${formatINRShort(en.no_slip_to_date.capital_exposed_cr)} capital`}
          tone="critical"
        />
        <Stat
          label="Any external factor flagged"
          value={en.n_flagged_any.toLocaleString()}
          sub={`${formatINRShort(en.capital_flagged_any_cr)} capital`}
        />
        <div className="bg-surface-panel px-5 py-4">
          <div className="text-xs text-fg-muted">Early notice by factor</div>
          <div className="mt-2 space-y-1">
            {FACTORS.map(({ key, label, icon: Icon }) => (
              <div key={key} className="grid grid-cols-[1rem_1fr_2rem] items-center gap-2 text-xs" title={label}>
                <Icon className="size-3.5 text-fg-dimmed" />
                <Bar share={(en.by_factor[key] ?? 0) / maxBy} className="bg-critical/70" />
                <span className="text-right tabular-nums text-fg-base">{en.by_factor[key] ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <Tabs defaultValue="broad" className="pt-3">
        <div className="flex flex-wrap items-center gap-2 px-5">
          <TabsList>
            <TabsTrigger value="broad">Broad · {en.top.length}</TabsTrigger>
            <TabsTrigger value="strict">Strict · {strictTop.length}</TabsTrigger>
          </TabsList>
          <InfoTip label="About these lists">
            The {en.top.length} largest by anticipated cost; the strict tab filters those.
            {strictTop.length < en.no_slip_to_date.n_projects &&
              ` ${strictTop.length} of the ${en.no_slip_to_date.n_projects} strict cases are among them; the rest are in the Command Center early-notice list.`}
          </InfoTip>
        </div>
        <TabsContent value="broad" className="mt-3">
          <NoticeTable rows={en.top} />
        </TabsContent>
        <TabsContent value="strict" className="mt-3">
          <NoticeTable rows={strictTop} />
        </TabsContent>
      </Tabs>
    </Card>
  )
}

function CoveragePanel({ s }: { s: ExternalSummary }) {
  const c = s.coverage
  const lf = s.noticeBacktest.land_or_forest
  const n = Math.max(c.n_current, 1)
  const rows = [
    { label: 'Land rated', v: c.land_linked, note: 'km range on a Bhoomi Rashi NH stretch, 29 states' },
    { label: 'Land: possible link', v: c.land_possible, note: 'NH or district only, not rated' },
    ...(s.portal ? [{ label: 'PARIVESH proposal linked', v: s.portal.n_linked, note: `${s.portal.n_open} still open` }] : []),
    { label: 'Forest area known', v: c.forest_area_known },
    { label: 'Composite: forest + land', v: c.composite_fc_la },
    { label: 'Composite: forest only', v: c.composite_fc_only, note: 'land missing' },
  ]
  const maxRate = Math.max(lf?.slip_rate_with ?? 0, lf?.slip_rate_without ?? 0, 0.0001)

  return (
    <Card title="Coverage" info="How many current projects each external data source reaches. Outside it a factor is unknown, not clear." className="h-full">
      <div className="space-y-3 px-5 py-4">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
              <span className="text-fg-base">{r.label}{r.note && <span className="text-fg-dimmed"> · {r.note}</span>}</span>
              <span className="tabular-nums text-fg-muted">{r.v.toLocaleString()} of {c.n_current.toLocaleString()}</span>
            </div>
            <Bar share={r.v / n} className="bg-accent" />
          </div>
        ))}
      </div>

      {lf && (
        <div className="border-t border-border-subtle px-5 py-4">
          <div className="mb-2 flex items-center gap-1.5 text-sm font-medium text-fg-base">
            Did an open land or forest remark come before a slip?
            <InfoTip label="About this backtest">
              Past reports with no slip yet: share whose completion was pushed 3+ months within 4 quarters. Within the same
              sector and year the lift is {times(lf.lift_within_sector_year)}. It does not hold in every sector (see About this
              data), so an early notice is a reason to ask the agency, not a forecast.
            </InfoTip>
          </div>
          {[
            { label: 'with a remark', v: lf.slip_rate_with, cls: 'bg-critical/80' },
            { label: 'without', v: lf.slip_rate_without, cls: 'bg-fg-dimmed/50' },
          ].map((r) => (
            <div key={r.label} className="grid grid-cols-[7rem_1fr_3rem] items-center gap-3 py-0.5 text-xs">
              <span className="text-fg-muted">{r.label}</span>
              <Bar share={(r.v ?? 0) / maxRate} className={r.cls} />
              <span className="text-right tabular-nums text-fg-base">{pct(r.v)}</span>
            </div>
          ))}
          <div className="mt-1.5 text-xs text-fg-dimmed">lift {times(lf.lift)}</div>
        </div>
      )}
    </Card>
  )
}

const FACTOR_TITLE: Record<HiddenDelayPrior['factor'], string> = {
  forest_clearance: 'Forest-clearance stage in the report remarks',
  land_progress: 'Land acquired, share in the report remarks',
  land_complexity: 'Land complexity on the km-matched NH stretch (the links the checklist rates)',
  land_complexity_nh: 'Land complexity on an NH or district link only (not rated)',
}

const TONE_TEXT = { warning: 'text-warning', stable: 'text-stable', muted: 'text-fg-dimmed' } as const

/** one measured prior: the verdict, how many current projects it applies to; n, CI and Garvit's band in the tip */
function DelayTile({ r, min }: { r: HiddenDelayPrior; min: number }) {
  const e = fromPrior(r)
  const v = verdict(e)
  return (
    <div className={cn('rounded-lg border bg-surface-panel p-3', v.tone === 'muted' ? 'border-border-subtle' : 'border-border-default')}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs leading-snug text-fg-muted">{r.label}</span>
        <InfoTip label={`About ${r.label}`}>
          {details(e, min).map((line) => <p key={line}>{line}</p>)}
          <p className="text-fg-dimmed">Garvit&rsquo;s guessed band ({r.garvit_status}): {r.garvit_band} months. Matched on {r.strata}; {r.as_of_note}.</p>
        </InfoTip>
      </div>
      <div className={cn('mt-2 font-semibold leading-none tabular-nums', v.tone === 'muted' ? 'text-sm' : 'text-lg', TONE_TEXT[v.tone])}>{v.text}</div>
      {v.also && <div className="mt-1 text-xs font-medium text-fg-muted">{v.also}</div>}
      <div className="mt-1.5 text-xs text-fg-dimmed">
        {r.n_current !== undefined && r.n_current !== null ? `${r.n_current} current · ` : ''}n = {r.n_projects}
      </div>
    </div>
  )
}

/** measured extra slip per forest stage, land share and land complexity against matched projects, as tiles */
function HiddenDelayPanel({ s }: { s: ExternalSummary }) {
  const h = s.hiddenDelayPriors
  if (!h) return null
  const groups = (Object.keys(FACTOR_TITLE) as HiddenDelayPrior['factor'][])
    .map((f) => [f, h.rows.filter((r) => r.factor === f)] as const)
    .filter(([, rows]) => rows.length > 0)
  return (
    <Card
      title="Measured hidden delay"
      info={<>{h.note} Each tile: the extra completion push over the next 4 quarters where its 95% interval excludes zero (else the extra chance of a 3+ month push, else none measurable). &ldquo;Current&rdquo;: projects in view whose status is current today. A remark stage or share counts only within {s.remarkFlags?.live_window_quarters ?? 4} quarters of its report, and remark free text ends in {s.remarkFlags?.last_remark_quarter ?? '2023'}, so the remark groups count none now; a forest stage PARIVESH shows as finally approved does not count either.</>}
      titleRight={<span>measured on real projects · replaces the guessed bands</span>}
    >
      <div className="divide-y divide-border-subtle">
        {groups.map(([f, rows]) => (
          <div key={f} className="space-y-2.5 px-5 py-4">
            <div className="text-xs font-medium text-fg-muted">
              {FACTOR_TITLE[f]} <span className="font-normal text-fg-dimmed">· {rows[0]?.as_of_note}</span>
            </div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 xl:grid-cols-8">
              {rows.map((r) => <DelayTile key={r.group} r={r} min={h.min_projects} />)}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------ PARIVESH

const day = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const mo = (v: number | null) => orDash(v, (x) => `${Math.round(x)} mo`)

/** a proposal's state in one line and its tone: stuck past its limit, open, final, dropped */
function proposalLine(p: ProposalStatus): { text: string; tone: string } {
  if (p.open_at_asof) {
    const next = p.stage1 ? 'Stage-II' : 'Stage-I'
    return p.overdue
      ? { text: `No ${next} after ${mo(p.months_in_stage)}; rule limit about ${mo(p.norm_months)}`, tone: 'text-critical' }
      : { text: `${p.stage_at_asof} for ${mo(p.months_in_stage)}`, tone: 'text-warning' }
  }
  if (p.stage2 && p.received) {
    const m = Math.round((Date.parse(p.stage2) - Date.parse(p.received)) / (30.44 * 864e5))
    return { text: `Final approval ${m} months after filing`, tone: 'text-stable' }
  }
  const q = p.last_query_on && p.last_query_replied === false
    ? ` after a ${p.last_query_by ?? 'portal'} query of ${day(p.last_query_on)} went unanswered` : ''
  return { text: `Dropped without approval${q}`, tone: 'text-critical' }
}

/** filed, Stage-I, Stage-II as three dots on a line */
function Milestones({ p }: { p: ProposalStatus }) {
  const steps = [['Filed', p.received], ['Stage-I', p.stage1], ['Stage-II', p.stage2]] as const
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      {steps.map(([label, d], i) => (
        <span key={label} className="flex items-center gap-1">
          {i > 0 && <span className={cn('h-px w-4', d ? 'bg-stable' : 'bg-border-strong')} />}
          <span className={cn('size-2 rounded-full', d ? 'bg-stable' : 'border border-fg-dimmed')} />
          <span className={d ? 'text-fg-base' : 'text-fg-dimmed'}>{label} {d ? formatDate(d) : '—'}</span>
        </span>
      ))}
    </div>
  )
}

/** the proposals the report remarks name, as the portal shows them: the blocker the report numbers did not */
function CaseCallout({ c }: { c: ProposalCase }) {
  const panel = useProjectPanel()
  return (
    <div className="rounded-xl border border-border-default bg-surface-elevated/40 p-4">
      <button type="button" onClick={() => panel.open(c.project_key)} className="text-left text-sm font-semibold text-fg-base hover:underline">
        {c.project_name ?? c.project_key}
      </button>
      <div className="mt-0.5 text-xs text-fg-dimmed">{c.project_key}{c.current ? '' : ' · past project'}</div>
      <div className="mt-3 space-y-3">
        {c.proposals.map((p) => {
          const line = proposalLine(p)
          return (
            <div key={p.proposal_no} className="space-y-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="font-mono text-xs text-fg-base">{p.proposal_no}</span>
                <span className="text-xs text-fg-dimmed">{p.category} · {orDash(p.area_ha, (v) => `${v.toFixed(1)} ha`)}</span>
              </div>
              <Milestones p={p} />
              <div className={cn('text-xs font-medium', line.tone)}>{line.text}</div>
              {p.status_retrieved && p.retrieved && (
                <div className="text-xs text-fg-dimmed">
                  portal on {day(p.retrieved)}: {p.status_retrieved}
                  {p.open_at_asof && p.last_query_on && ` · last entry ${day(p.last_query_on)}${p.last_query_by ? ` (${p.last_query_by})` : ''}`}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function OpenList({ rows }: { rows: PortalOpen[] }) {
  const panel = useProjectPanel()
  const [all, setAll] = useState(false)
  const shown = all ? rows : rows.slice(0, 8)
  const th = 'py-2.5 px-4 text-xs font-medium text-fg-muted'
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-elevated/60">
            <th className={cn(th, 'pl-5')}>Project</th>
            <th className={th}>PARIVESH stage</th>
            <th className={cn(th, 'text-right whitespace-nowrap')}>In stage</th>
            <th className={th}>Filed</th>
            <th className={th}>Tier</th>
            <th className={cn(th, 'pr-5 text-right')}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.project_key} onClick={() => panel.open(p.project_key)}
              className="cursor-pointer border-b border-border-subtle/70 transition-colors hover:bg-surface-elevated/70">
              <td className="max-w-[320px] py-2.5 pl-5 pr-4">
                <button type="button" onClick={(e) => { e.stopPropagation(); panel.open(p.project_key) }}
                  className="block max-w-full truncate text-left font-medium text-fg-base hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                  title={p.project_name ?? undefined}>
                  {p.project_name ?? p.project_key}
                </button>
                <div className="truncate text-xs text-fg-dimmed" title={p.proposals.replace(/;/g, ', ')}>
                  {p.project_key} · {p.state ?? 'state unknown'} · {p.n_open} open proposal{p.n_open === 1 ? '' : 's'}
                </div>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 text-xs text-fg-base">{p.stage_at_asof}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-right text-xs tabular-nums">
                <span className={p.overdue ? 'font-semibold text-critical' : 'text-fg-base'}>{mo(p.months_in_stage)}</span>
                <div className="text-fg-dimmed">limit {mo(p.norm_months)}</div>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 text-xs text-fg-muted">{orDash(p.oldest_open_received, formatDate)}</td>
              <td className="px-4 py-2.5"><div className="flex flex-wrap gap-1"><Badge tier={p.tier} />{p.stalled && <StalledBadge />}</div></td>
              <td className="whitespace-nowrap py-2.5 pl-4 pr-5 text-right font-mono tabular-nums text-fg-base">{orDash(p.anticipated_cost_cr, formatINR)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 8 && (
        <button type="button" onClick={() => setAll((v) => !v)} className="w-full px-5 py-2.5 text-center text-xs font-medium text-accent hover:bg-surface-elevated">
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  )
}

/** forest-clearance proposals open on PARIVESH that the reports never mention: counts, the named cases, the list */
function PortalPanel({ s }: { s: ExternalSummary }) {
  const po = s.portal
  if (!po) return null
  const cases = po.cases ?? []
  const open = po.open_list ?? []
  return (
    <Card
      title={<><FileSearch className="size-4 text-critical" /> Open on PARIVESH, not in the report</>}
      info={`${po.source}. Open: no Stage-II (final) approval at ${formatDate(s.asOfDate)}. The rule limit for the stage comes from the forest-clearance rules; in 2014-22 real times ran 2-3x the rules. Early notice from outside the reports, not a model input.`}
      titleRight={<span>{po.n_linked} current projects linked</span>}
    >
      <div className="grid grid-cols-2 gap-px border-b border-border-subtle bg-border-subtle lg:grid-cols-4">
        <Stat label="Proposal still open" value={po.n_open.toLocaleString()} sub={`${formatINRShort(po.capital_open_cr)} capital`} tone="warning" />
        <Stat label="Past the rule limit" value={po.n_overdue.toLocaleString()} sub="flags the forest row" tone="critical" />
        <Stat label="Open, silent in the report" value={po.n_open_not_in_report.toLocaleString()} sub="no forest issue in the remarks" tone="critical" />
        <div className="bg-surface-panel px-5 py-4">
          <div className="text-xs text-fg-muted">Linked projects by stage</div>
          <div className="mt-2 space-y-1">
            {Object.entries(po.by_stage).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 text-xs"><span className="truncate text-fg-muted">{k}</span><span className="tabular-nums text-fg-base">{v}</span></div>
            ))}
          </div>
        </div>
      </div>
      {cases.length > 0 && (
        <div className="space-y-3 border-b border-border-subtle px-5 py-4">
          <div className="flex items-center gap-1.5 text-sm font-medium text-fg-base">
            The portal shows the blocker; the report numbers did not
            <InfoTip label="About these cases">The only proposal numbers the report remarks name, looked up on the public PARIVESH pages. The remarks went quiet in 2023; the portal still records each step.</InfoTip>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">{cases.map((c) => <CaseCallout key={c.project_key} c={c} />)}</div>
        </div>
      )}
      {open.length > 0 && <OpenList rows={open} />}
    </Card>
  )
}

// ------------------------------------------------------------------ remark flags

const REMARK_ROWS: Array<[string, keyof typeof FLAG_ICON]> = [['land', 'land'], ['forest_env', 'forest'], ['litigation', 'litigation'], ['contractor', 'contractor']]

/** report-remark flags live today against stale ones, with the quarter a stale one was last known */
function RemarkFlagsPanel({ s }: { s: ExternalSummary }) {
  const rf = s.remarkFlags
  if (!rf?.by_category) return null
  const max = Math.max(1, ...Object.values(rf.by_category).map((c) => c.open))
  return (
    <Card
      title="Report flags: live or stale"
      info={`Report remarks are free text only through ${rf.last_remark_quarter}; later reports print templates. A remark flag counts as open today only within ${rf.live_window_quarters} quarters of its last mention; an older one is stale and shown with the quarter it was last known, never as today's state.`}
      titleRight={<span>{rf.n_projects_live} live · {rf.n_projects_stale} stale</span>}
    >
      <div className="space-y-2.5 px-5 py-4">
        {REMARK_ROWS.map(([cat, flag]) => {
          const c = rf.by_category?.[cat]
          const Icon = FLAG_ICON[flag]
          if (!c) return null
          const stale = c.open - c.live
          return (
            <div key={cat} className="grid grid-cols-[1rem_7rem_1fr_auto] items-center gap-2.5 text-xs">
              <Icon className="size-3.5 text-fg-dimmed" />
              <span className="truncate text-fg-base">{EVENT_CATEGORY[cat]?.label ?? cat}</span>
              <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-input">
                <div className="bg-warning" style={{ width: `${(c.live / max) * 100}%` }} />
                <div className="bg-fg-dimmed/40" style={{ width: `${(stale / max) * 100}%` }} />
              </div>
              <span className="whitespace-nowrap tabular-nums text-fg-muted">
                <span className={c.live ? 'font-semibold text-warning' : ''}>{c.live} live</span> · {stale} stale
                {c.last_known && <span className="text-fg-dimmed"> · last known {formatQuarter(c.last_known)}</span>}
              </span>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/** min-max whisker, 25-75% box, median tick and the flag line on a 0-1 track */
function BoxPlot({ d }: { d: CompositeDistribution }) {
  const x = (v: number) => `${Math.min(100, Math.max(0, v * 100))}%`
  return (
    <div className="relative h-6 rounded-md bg-surface-input" role="img"
      aria-label={`min ${d.min.toFixed(2)}, quartiles ${d['25%'].toFixed(2)} / ${d['50%'].toFixed(2)} / ${d['75%'].toFixed(2)}, max ${d.max.toFixed(2)}`}>
      <div className="absolute top-1/2 h-px bg-fg-dimmed" style={{ left: x(d.min), width: x(d.max - d.min) }} />
      <div
        className="absolute top-1 bottom-1 min-w-[3px] rounded-sm bg-accent/30 border border-accent"
        style={{ left: x(d['25%']), width: x(d['75%'] - d['25%']) }}
      />
      <div className="absolute top-0 bottom-0 w-0.5 bg-fg-base" style={{ left: x(d['50%']) }} />
      <div className="absolute top-0 bottom-0 border-l border-dashed border-critical" style={{ left: x(COMPOSITE_HIGH) }} />
    </div>
  )
}

function CompositePanel({ s }: { s: ExternalSummary }) {
  const rows = [
    { key: 'fc+la' as const, label: 'Forest + land', note: `rated: flagged at ${COMPOSITE_HIGH} or above` },
    { key: 'fc_only' as const, label: 'Forest only', note: 'not rated: the land half is missing, so unknown' },
  ]

  return (
    <Card title="External-factor score" info="Distribution of the land + forest composite by data coverage. Box: middle half; bar: median; dashed line: the flag threshold." className="h-full">
      <div className="space-y-5 px-5 py-4">
        {rows.map(({ key, label, note }) => {
          const d = s.externalComposite.by_coverage[key]
          return (
            <div key={key} className="space-y-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-medium text-fg-base">
                  {label}
                  <InfoTip label={`About ${label}`}>{note}</InfoTip>
                </span>
                <span className="text-xs text-fg-dimmed">
                  {d
                    ? `${d.n_projects.toLocaleString()} projects · ${d.n_score_ge_high} at ≥ ${COMPOSITE_HIGH} · median ${d['50%'].toFixed(2)} · mean ${d.mean.toFixed(2)}`
                    : 'no projects'}
                </span>
              </div>
              {d && <BoxPlot d={d} />}
            </div>
          )
        })}
        <div className="flex justify-between text-xs text-fg-dimmed">
          <span>0</span>
          <span>score · dashed at {COMPOSITE_HIGH}</span>
          <span>1</span>
        </div>
      </div>
    </Card>
  )
}

/** every caveat and method note of this page, folded into one section */
function AboutData({ s }: { s: ExternalSummary }) {
  const c = s.coverage
  const lf = s.noticeBacktest.land_or_forest
  const sectors = lf ? Object.entries(lf.by_sector) : []
  const holds = sectors.filter(([, r]) => (r.lift ?? 0) > 1)
  const fails = sectors.filter(([, r]) => (r.lift ?? 0) <= 1)
  const list = (rows: typeof sectors) => rows.map(([name, r]) => `${name} ${times(r.lift)}`).join(', ')
  const of = (n: number) => `${n.toLocaleString()} of ${c.n_current.toLocaleString()}`

  const rf = s.remarkFlags
  const caveats = [
    rf
      ? `Report remarks are free text only through ${rf.last_remark_quarter}; later reports print templates. ${rf.n_projects_stale.toLocaleString()} current projects still had a land, forest, court or contractor issue open when the remarks ended; ${rf.n_projects_live} of them are recent enough (within ${rf.live_window_quarters} quarters) to count as open today, so remark flags describe the last known state, not today's.`
      : 'Report remarks are free text only through 2023; later reports print templates. So "open" means open when last mentioned — the last known state, not a confirmed state today.',
    `Land records come from the Bhoomi Rashi highway register (29 states). A road project is rated only when the km range in its name places it on notified stretches of its NH (${of(c.land_linked)} current projects; 84% right on a hand-checked sample). ${c.land_possible.toLocaleString()} more have a possible link on the NH or district alone, shown but not rated. Everything else is unknown, not clear.`,
    `Forest-clearance complexity comes from the Parivesh rulebook. Forest area is known for ${of(c.forest_area_known)} projects; for the rest the complexity is the rulebook's expected value — an estimate, not a measurement.`,
    ...(s.portal
      ? [`PARIVESH: ${s.portal.n_linked.toLocaleString()} current projects have a hand-reviewed link to a forest-clearance proposal in the PARIVESH 1.0 list (proposals filed 2014 to mid-2022; the list is not a census). ${s.portal.n_open} were still open in ${formatDate(s.asOfDate)} and ${s.portal.n_overdue} of those were past the rule limit, which flags the forest row; none of the ${s.portal.n_open} is mentioned in the report remarks.`]
      : []),
  ]
  if (lf) {
    caveats.push(
      `On history, of past reports with no slip yet, those with an open land or forest remark had their completion pushed 3+ months within 4 quarters ${pct(lf.slip_rate_with)} of the time against ${pct(lf.slip_rate_without)} without (${times(lf.lift)}; ${times(lf.lift_within_sector_year)} within the same sector and year). ` +
        (holds.length
          ? `The lift holds in ${list(holds)}${fails.length ? `, not in ${list(fails)}` : ''} and not portfolio-wide, so an early notice is a reason to ask the agency, not a forecast.`
          : 'It does not hold in any sector with enough rows, so an early notice is a reason to ask the agency, not a forecast.')
    )
  }

  return (
    <details className="group rounded-xl border border-border-subtle bg-surface-panel shadow-card">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 text-sm font-semibold text-fg-base">
        <Info className="size-4 text-fg-dimmed" />
        About this data
        <span className="ml-auto text-xs font-normal text-fg-dimmed group-open:hidden">show</span>
        <span className="ml-auto hidden text-xs font-normal text-fg-dimmed group-open:inline">hide</span>
      </summary>
      <div className="space-y-3 border-t border-border-subtle px-5 py-4 text-sm leading-relaxed text-fg-muted">
        <ul className="list-disc space-y-2 pl-5">
          {caveats.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="text-xs text-fg-dimmed">Composite score: {s.externalComposite.rule}</p>
      </div>
    </details>
  )
}
