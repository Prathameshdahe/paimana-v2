import { Link, useNavigate } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useExternalSummary } from '@/lib/queries'
import { formatDate, formatINR, formatINRShort, formatProb, orDash, cn } from '@/lib/formatters'
import type { Flag } from '@/contracts/project'
import type {
  CompositeDistribution,
  ExternalFactorKey,
  ExternalProject,
  ExternalSummary,
} from '@/contracts/portfolio'

const FACTORS: Array<{ key: ExternalFactorKey; label: string; short: string; flag?: Flag }> = [
  { key: 'land', label: 'Land acquisition', short: 'land', flag: 'land' },
  { key: 'forest_clearance', label: 'Forest clearance', short: 'forest', flag: 'forest' },
  { key: 'litigation', label: 'Litigation', short: 'litigation', flag: 'litigation' },
  { key: 'contractor', label: 'Contractor stress', short: 'contractor', flag: 'contractor' },
  { key: 'utility_shifting', label: 'Utility shifting', short: 'utility' },
  { key: 'inter_agency', label: 'Inter-agency', short: 'inter-agency' },
]
const FACTOR_LABEL: Record<string, string> = Object.fromEntries(FACTORS.map((f) => [f.key, f.label]))

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

/**
 * External Factors (/external) over /api/external/summary: per-factor rollups,
 * the early-notice list, coverage and caveats, and the composite score. Every
 * figure comes from gold/external_summary.json (one aggregate response).
 */
export function ExternalFactors() {
  const { data, error, isLoading } = useExternalSummary()

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2 pt-4 pb-2">
        <div>
          <h1 className="font-sans text-2xl font-black tracking-tight text-fg-base uppercase">External Factors</h1>
          <p className="text-sm text-fg-muted mt-1">
            Hidden factors (land acquisition, forest clearance, litigation, contractor stress, utility shifting,
            inter-agency) that the CUF numbers only show at the next revision.
          </p>
        </div>
        {data && (
          <div className="font-mono text-[11px] text-fg-dimmed">
            asof {formatDate(data.asOfDate)} · {data.nProjects.toLocaleString()} projects · {data.modelVersion}
          </div>
        )}
      </div>

      <div className="h-px bg-border-subtle" />

      {error ? (
        <Card>
          <ApiErrorNote error={error} />
        </Card>
      ) : isLoading || !data ? (
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
          loading external factors...
        </div>
      ) : (
        <>
          <FactorCards s={data} />
          <EarlyNoticePanel s={data} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
            <CoveragePanel s={data} />
            <CompositePanel s={data} />
          </div>
        </>
      )}

      <p className="font-mono text-[11px] text-fg-dimmed">External-factor datasets and rulebook: Garvit</p>
    </div>
  )
}

function Stat({ label, value, sub, sentiment = 'default' }: {
  label: string
  value: string
  sub?: string
  sentiment?: 'critical' | 'warning' | 'default'
}) {
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed">{label}</div>
      <MonoFigure size="xl" sentiment={sentiment} className="block mt-1.5">
        {value}
      </MonoFigure>
      {sub && <div className="font-mono text-[10px] text-fg-dimmed mt-1">{sub}</div>}
    </div>
  )
}

/** One project from a summary top list, linking to its project page. */
function ProjectLine({ p, factor }: { p: ExternalProject; factor: ExternalFactorKey }) {
  const lines = p.evidence.map(splitEvidence).filter(([f]) => f === factor)

  return (
    <Link to={`/projects/${p.project_key}`} className="block px-4 py-2.5 hover:bg-surface-elevated transition-colors">
      <div className="flex items-center gap-2">
        <Badge tier={p.tier} className="w-[60px] shrink-0" />
        <span className="truncate text-xs font-semibold text-fg-base" title={p.project_name ?? undefined}>
          {p.project_name ?? p.project_key}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-fg-muted tabular-nums">
          {orDash(p.anticipated_cost_cr, formatINR)}
        </span>
      </div>
      <div className="font-mono text-[10px] text-fg-dimmed mt-0.5 pl-[68px]">
        {p.project_key} · {p.state ?? 'state unknown'} · slip to date {slip(p.slip_to_date_months)}
      </div>
      {lines.map(([, text], i) => (
        <div key={i} className="mt-1 pl-[68px] text-[11px] leading-snug text-fg-muted line-clamp-2" title={text}>
          {text}
        </div>
      ))}
    </Link>
  )
}

function FactorCards({ s }: { s: ExternalSummary }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {FACTORS.map(({ key, label, flag }) => {
        const f = s.factors[key]
        return (
          <Card
            key={key}
            title={label}
            titleRight={
              <span className="font-mono text-[11px] text-fg-dimmed">
                {f ? `${f.n_flagged} flagged` : 'not in summary'}
              </span>
            }
            className="flex flex-col"
          >
            {!f ? (
              <div className="px-5 py-6 text-center font-mono text-xs text-fg-dimmed">
                no rollup for this factor in external_summary.json — unknown, not clear
              </div>
            ) : (
              <>
                <div className="grid grid-cols-3 divide-x divide-border-subtle border-b border-border-subtle">
                  <Stat label="Flagged" value={f.n_flagged.toLocaleString()} sentiment={f.n_flagged ? 'warning' : 'default'} />
                  <Stat label="Capital exposed" value={formatINRShort(f.capital_exposed_cr)} />
                  <Stat
                    label="Early notice"
                    value={String(s.earlyNotice.by_factor[key] ?? 0)}
                    sentiment={s.earlyNotice.by_factor[key] ? 'critical' : 'default'}
                  />
                </div>
                {f.top.length === 0 ? (
                  <div className="px-5 py-6 text-center font-mono text-xs text-fg-dimmed">
                    no current project flagged for this factor
                  </div>
                ) : (
                  <div className="flex-1 divide-y divide-border-subtle/60 max-h-[360px] overflow-y-auto" data-lenis-prevent>
                    {f.top.map((p) => (
                      <ProjectLine key={p.project_key} p={p} factor={key} />
                    ))}
                  </div>
                )}
                <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-fg-dimmed flex justify-between gap-2">
                  <span>
                    top {f.top.length} of {f.n_flagged} by capital
                  </span>
                  {flag && (
                    <Link to={`/command?flag=${flag}`} className="hover:text-fg-base hover:underline">
                      all in Command Center &rarr;
                    </Link>
                  )}
                </div>
              </>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function NoticeTable({ rows }: { rows: ExternalProject[] }) {
  const navigate = useNavigate()

  if (rows.length === 0) {
    return <div className="px-5 py-6 text-center font-mono text-xs text-fg-dimmed">no project in this list</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left font-mono text-[12px]">
        <thead>
          <tr className="border-y border-border-default text-fg-dimmed font-sans text-[11px] uppercase tracking-wider">
            <th className="py-2.5 px-4 font-semibold">Project</th>
            <th className="py-2.5 px-4 font-semibold">Factor</th>
            <th className="py-2.5 px-4 font-semibold">Evidence</th>
            <th className="py-2.5 px-4 font-semibold">Tier</th>
            <th className="py-2.5 px-4 font-semibold text-right whitespace-nowrap">Slip to date</th>
            <th className="py-2.5 px-4 font-semibold text-right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const lines = p.evidence.map(splitEvidence)
            return (
              <tr
                key={p.project_key}
                onClick={() => navigate(`/projects/${p.project_key}`)}
                className="border-b border-border-subtle/60 hover:bg-surface-elevated/50 cursor-pointer align-top"
              >
                <td className="py-2.5 px-4 max-w-[280px]">
                  <Link
                    to={`/projects/${p.project_key}`}
                    onClick={(e) => e.stopPropagation()}
                    className="block truncate font-sans text-[13px] font-semibold text-fg-base hover:underline"
                    title={p.project_name ?? undefined}
                  >
                    {p.project_name ?? p.project_key}
                  </Link>
                  <div className="text-[11px] text-fg-dimmed mt-0.5">
                    {p.project_key} · {p.sector ?? 'sector unknown'} · {p.state ?? 'state unknown'}
                  </div>
                </td>
                <td className="py-2.5 px-4 whitespace-nowrap">
                  {lines.map(([f], i) => (
                    <div key={i} className="text-warning uppercase text-[10px] tracking-wider leading-5">
                      {FACTOR_LABEL[f] ?? f}
                    </div>
                  ))}
                </td>
                <td className="py-2.5 px-4 min-w-[320px]">
                  {lines.map(([, text], i) => (
                    <div key={i} className="font-sans text-[12px] leading-snug text-fg-muted line-clamp-2" title={text}>
                      {text}
                    </div>
                  ))}
                </td>
                <td className="py-2.5 px-4">
                  <Badge tier={p.tier} />
                  <div className="text-[10px] text-fg-dimmed mt-1">P(slip) {pct(p.p_any_2q)}</div>
                </td>
                <td className="py-2.5 px-4 text-right text-fg-base">{slip(p.slip_to_date_months)}</td>
                <td className="py-2.5 px-4 text-right text-fg-base tabular-nums whitespace-nowrap">
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

  return (
    <Card
      title={`Early Notice · ${en.n_projects} projects`}
      titleRight={
        <Link to="/command?flag=early_notice" className="font-mono text-[11px] text-fg-dimmed hover:text-fg-base hover:underline">
          all {en.n_projects} in Command Center &rarr;
        </Link>
      }
    >
      <div className="px-5 py-3 text-xs text-fg-muted border-b border-border-subtle">
        A flagged external factor while the CUF numbers do not show a slip yet. Two readings of &ldquo;no slip
        yet&rdquo;: strictly, slip to date of 0 months or less; broadly, that or a Low/Medium tier (which includes
        projects that already slipped but rank low on the model).
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-border-subtle border-b border-border-subtle">
        <Stat
          label="No slip or tier Low/Medium"
          value={en.n_projects.toLocaleString()}
          sub={`${formatINRShort(en.capital_exposed_cr)} capital`}
          sentiment="critical"
        />
        <Stat
          label="Strict: no slip to date"
          value={en.no_slip_to_date.n_projects.toLocaleString()}
          sub={`${formatINRShort(en.no_slip_to_date.capital_exposed_cr)} capital`}
          sentiment="critical"
        />
        <Stat
          label="Any external factor flagged"
          value={en.n_flagged_any.toLocaleString()}
          sub={`${formatINRShort(en.capital_flagged_any_cr)} capital`}
        />
        <div className="px-4 py-3">
          <div className="text-[10px] font-sans font-semibold uppercase tracking-widest text-fg-dimmed">
            Early notice by factor
          </div>
          <div className="mt-1.5 grid grid-cols-2 gap-x-3 font-mono text-[11px] text-fg-muted">
            {FACTORS.map(({ key, label, short }) => (
              <span key={key} className="flex justify-between gap-2" title={label}>
                <span className="truncate">{short}</span>
                <span className="text-fg-base tabular-nums">{en.by_factor[key] ?? 0}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      <Tabs defaultValue="broad" className="pt-3">
        <div className="px-5 flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="broad">No slip or Low/Medium · {en.top.length}</TabsTrigger>
            <TabsTrigger value="strict">Strict: no slip to date · {strictTop.length}</TabsTrigger>
          </TabsList>
          <span className="font-mono text-[10px] text-fg-dimmed">
            the {en.top.length} largest by anticipated cost; the strict tab filters those
          </span>
        </div>
        <TabsContent value="broad" className="mt-3">
          <NoticeTable rows={en.top} />
        </TabsContent>
        <TabsContent value="strict" className="mt-3">
          <NoticeTable rows={strictTop} />
          {strictTop.length < en.no_slip_to_date.n_projects && (
            <div className="px-5 py-2 font-mono text-[10px] text-fg-dimmed">
              {strictTop.length} of the {en.no_slip_to_date.n_projects} strict cases are among the {en.top.length} largest;
              the rest are in the Command Center early-notice list.
            </div>
          )}
        </TabsContent>
      </Tabs>
    </Card>
  )
}

function CoveragePanel({ s }: { s: ExternalSummary }) {
  const c = s.coverage
  const lf = s.noticeBacktest.land_or_forest
  const sectors = lf ? Object.entries(lf.by_sector) : []
  const holds = sectors.filter(([, r]) => (r.lift ?? 0) > 1)
  const fails = sectors.filter(([, r]) => (r.lift ?? 0) <= 1)
  const list = (rows: typeof sectors) => rows.map(([name, r]) => `${name} ${times(r.lift)}`).join(', ')
  const of = (n: number) => `${n.toLocaleString()} of ${c.n_current.toLocaleString()}`

  const caveats = [
    'Report remarks are free text only through 2023; later reports print templates. So "open" means open when last mentioned — the last known state, not a confirmed state today.',
    `Land records come from Bhoomi Rashi and cover Maharashtra national-highway projects only (${of(c.land_linked)} current projects). Land in every other state is unknown, not clear.`,
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
    <Card title="Coverage & Caveats" className="h-full">
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-border-subtle border-b border-border-subtle">
        <Stat label="Land linked" value={c.land_linked.toLocaleString()} sub={`of ${c.n_current.toLocaleString()} · MH NH only`} />
        <Stat label="Forest area known" value={c.forest_area_known.toLocaleString()} sub={`of ${c.n_current.toLocaleString()}`} />
        <Stat label="Composite fc+la" value={c.composite_fc_la.toLocaleString()} sub="forest + land" />
        <Stat label="Composite fc only" value={c.composite_fc_only.toLocaleString()} sub="land missing" />
      </div>
      <ul className="list-disc pl-9 pr-5 py-3 space-y-2.5 text-xs leading-relaxed text-fg-muted">
        {caveats.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </Card>
  )
}

/** min-max whisker, 25-75% box, median tick and the flag line on a 0-1 track */
function BoxPlot({ d }: { d: CompositeDistribution }) {
  const x = (v: number) => `${Math.min(100, Math.max(0, v * 100))}%`
  return (
    <div className="relative h-6 bg-surface-input border border-border-subtle" role="img"
      aria-label={`min ${d.min.toFixed(2)}, quartiles ${d['25%'].toFixed(2)} / ${d['50%'].toFixed(2)} / ${d['75%'].toFixed(2)}, max ${d.max.toFixed(2)}`}>
      <div className="absolute top-1/2 h-px bg-fg-dimmed" style={{ left: x(d.min), width: x(d.max - d.min) }} />
      <div
        className="absolute top-1 bottom-1 min-w-[3px] bg-accent/30 border border-accent"
        style={{ left: x(d['25%']), width: x(d['75%'] - d['25%']) }}
      />
      <div className="absolute top-0 bottom-0 w-0.5 bg-fg-base" style={{ left: x(d['50%']) }} />
      <div className="absolute top-0 bottom-0 border-l border-dashed border-critical" style={{ left: x(COMPOSITE_HIGH) }} />
    </div>
  )
}

function CompositePanel({ s }: { s: ExternalSummary }) {
  const rows = [
    { key: 'fc+la' as const, label: 'Forest + land (fc+la)', note: `rated: flagged at ${COMPOSITE_HIGH} or above` },
    { key: 'fc_only' as const, label: 'Forest only (fc_only)', note: 'not rated: the land half is missing, so unknown' },
  ]

  return (
    <Card title="External-Factor Score by Coverage" className="h-full">
      <div className="px-5 py-3 space-y-4">
        {rows.map(({ key, label, note }) => {
          const d = s.externalComposite.by_coverage[key]
          return (
            <div key={key} className="space-y-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-xs font-semibold text-fg-base">{label}</span>
                <span className="font-mono text-[11px] text-fg-dimmed">
                  {d
                    ? `${d.n_projects.toLocaleString()} projects · ${d.n_score_ge_high} at ≥ ${COMPOSITE_HIGH} · mean ${d.mean.toFixed(2)} · median ${d['50%'].toFixed(2)}`
                    : 'no projects'}
                </span>
              </div>
              {d && <BoxPlot d={d} />}
              <div className={cn('font-mono text-[10px]', key === 'fc+la' ? 'text-fg-muted' : 'text-fg-dimmed')}>{note}</div>
            </div>
          )
        })}
        <div className="flex justify-between font-mono text-[10px] text-fg-dimmed">
          <span>0</span>
          <span>score (dashed: {COMPOSITE_HIGH})</span>
          <span>1</span>
        </div>
        <p className="text-[11px] leading-relaxed text-fg-dimmed border-t border-border-subtle pt-3">
          {s.externalComposite.rule}
        </p>
      </div>
    </Card>
  )
}
