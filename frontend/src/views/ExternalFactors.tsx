import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { Info, Siren } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge, IconChip } from '@/components/ui/Badge'
import { InfoTip } from '@/components/ui/Tooltip'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Page, PageHeader } from '@/components/layout/Page'
import { EvidenceFeed } from './external-factors/EvidenceFeed'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { useExternalSummary } from '@/lib/queries'
import { formatDate, formatINR, formatINRShort, formatProb, orDash, cn } from '@/lib/formatters'
import { EXTERNAL_FACTORS as FACTORS } from '@/lib/riskPalette'
import type { CompositeDistribution, ExternalFactorKey, ExternalProject, ExternalSummary } from '@/contracts/portfolio'

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
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-stretch">
            <CoveragePanel s={data} />
            <CompositePanel s={data} />
          </div>
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
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-y border-border-subtle bg-surface-elevated/60">
            <th className={cn(th, 'pl-5')}>Project</th>
            <th className={th}>Factor</th>
            <th className={th}>Evidence</th>
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
                    {lines.map(([f], i) => {
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
                <td className="min-w-[240px] px-4 py-3">
                  {lines.map(([, text], i) => (
                    <div key={i} className="text-xs leading-snug text-fg-muted line-clamp-2" title={text}>
                      {text}
                    </div>
                  ))}
                </td>
                <td className="px-4 py-3">
                  <Badge tier={p.tier} />
                  <div className="mt-1 text-xs text-fg-dimmed">P(slip) {pct(p.p_any_2q)}</div>
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

  const caveats = [
    'Report remarks are free text only through 2023; later reports print templates. So "open" means open when last mentioned — the last known state, not a confirmed state today.',
    `Land records come from the Bhoomi Rashi highway register (29 states). A road project is rated only when the km range in its name places it on notified stretches of its NH (${of(c.land_linked)} current projects; 84% right on a hand-checked sample). ${c.land_possible.toLocaleString()} more have a possible link on the NH or district alone, shown but not rated. Everything else is unknown, not clear.`,
    `Forest-clearance complexity comes from the Parivesh rulebook. Forest area is known for ${of(c.forest_area_known)} projects; for the rest the complexity is the rulebook's expected value — an estimate, not a measurement.`,
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
