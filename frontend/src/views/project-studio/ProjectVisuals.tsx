/**
 * The visual blocks of one project, from /api/projects/{key} and /timeline: risk ring and gauges, time vs work,
 * money, progress trend, timeline strip, risk grid, drivers and external issues. The side panel
 * (command-center/ProjectDetailDrawer) and the public project page lay them out; the public gets what the
 * redacted API sends (no drivers, no intervals), so the same blocks simply show less.
 */
import React from 'react'
import { motion } from 'motion/react'
import { AlertTriangle, ArrowDown, ArrowUp, Newspaper } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { Tooltip, InfoTip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import {
  FLAG_ICON, FLAG_LABEL, RISK_DIMENSION, RISK_STATE_CHIP, TIER_COLOR, TIER_LABEL, TIER_TEXT, tierKey,
} from '@/lib/riskPalette'
import { featureLabel } from '@/lib/featureLabels'
import { cn, formatDate, formatINR, formatProb, orDash } from '@/lib/formatters'
import type { EventRow, Flag, ProjectDetail, RiskRow, RiskState, ShapValue, Timeline } from '@/contracts/project'

const EASE = [0.22, 1, 0.36, 1] as const
const GROW = { duration: 0.7, ease: EASE }
const clamp = (v: number) => Math.min(100, Math.max(0, v))

function Section({ title, info, right, className, children }: {
  title: React.ReactNode
  info?: React.ReactNode
  right?: React.ReactNode
  className?: string
  children: React.ReactNode
}) {
  return (
    <section className={cn('rounded-xl border border-border-subtle bg-surface-panel p-4 shadow-card', className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-fg-base">
          {title}
          {info && <InfoTip>{info}</InfoTip>}
        </h3>
        {right && <div className="shrink-0 text-xs text-fg-muted">{right}</div>}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-3 text-center text-sm text-fg-dimmed">{children}</div>
}

/** Sector, state and agency as small chips (the panel header and the public page). */
export function ProjectChips({ detail }: { detail: ProjectDetail }) {
  const m = detail.master ?? {}
  return (
    <div className="flex flex-wrap gap-1.5">
      {[m.sector, m.state, m.agency].filter(Boolean).map((v) => (
        <span key={String(v)} className="max-w-[260px] truncate rounded-full bg-surface-elevated px-2.5 py-0.5 text-xs text-fg-muted ring-1 ring-inset ring-border-subtle" title={String(v)}>
          {String(v)}
        </span>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ risk ring

/** Half-circle gauge of one probability. */
function Gauge({ label, value }: { label: string; value: number | null }) {
  const tone = value === null ? '' : value >= 0.5 ? 'stroke-critical' : value >= 0.2 ? 'stroke-warning' : 'stroke-accent'
  return (
    <div className="flex w-20 flex-col items-center text-center" role="img" aria-label={`${label}: ${orDash(value, formatProb)}`}>
      <svg viewBox="0 0 64 36" className="w-16" aria-hidden="true">
        <path d="M6 32 A26 26 0 0 1 58 32" fill="none" strokeWidth={6} strokeLinecap="round" className="stroke-surface-input" />
        {value !== null && value > 0 && (
          <motion.path d="M6 32 A26 26 0 0 1 58 32" fill="none" strokeWidth={6} strokeLinecap="round" className={tone}
            initial={{ pathLength: 0 }} animate={{ pathLength: value }} transition={GROW} />
        )}
      </svg>
      <span className="-mt-3 font-mono text-sm font-semibold tabular-nums text-fg-base">{orDash(value, formatProb)}</span>
      <span className="mt-1 text-xs leading-tight text-fg-muted">{label}</span>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-fg-muted">{label}</div>
      <div className="text-base font-semibold tabular-nums text-fg-base">{value}</div>
    </div>
  )
}

/**
 * Donut of P(date push or cost revision, 2q) in the tier colour, tier inside. full: three gauges beside it;
 * the public: work done, cost and completion instead. Watch (no completion date): a grey-violet ring and no
 * date-based gauges.
 */
export function RiskRingCard({ detail, full }: { detail: ProjectDetail; full: boolean }) {
  const s = detail.scores
  const t = tierKey(s?.tier ?? null)
  const untiered = t === 'Watch'
  const p = untiered ? null : (s?.pAny2q ?? null)
  const o = detail.latest ?? {}
  const R = 52
  const center = !s ? 'Not scored' : untiered ? 'Watch · no completion date' : TIER_LABEL[t]

  return (
    <Section
      title={full ? 'Slip risk · next 2 quarters' : 'Delay risk'}
      info={full
        ? 'The ring is the chance of a date push or cost revision within 2 quarters, coloured by tier. Tiers go by rank; the probabilities rank projects and are not calibrated frequencies.'
        : 'How likely the project is to be delayed or cost more in the next six months, compared with other projects.'}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
        <div className="relative size-32 shrink-0" role="img" aria-label={`Risk: ${center}${full && p !== null ? `, ${formatProb(p)}` : ''}`}>
          <svg viewBox="0 0 128 128" className="size-32 -rotate-90" aria-hidden="true">
            <circle cx={64} cy={64} r={R} fill="none" strokeWidth={12} className="stroke-surface-input" />
            {p === null ? (
              <circle cx={64} cy={64} r={R} fill="none" strokeWidth={12} stroke={TIER_COLOR.Watch} strokeOpacity={0.5} />
            ) : (
              <motion.circle cx={64} cy={64} r={R} fill="none" strokeWidth={12} strokeLinecap="round" stroke={TIER_COLOR[t]}
                initial={{ pathLength: 0 }} animate={{ pathLength: p }} transition={{ ...GROW, duration: 0.9 }} />
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center px-5 text-center">
            <span className={cn('font-semibold leading-tight', p === null ? 'text-xs text-fg-muted' : cn('text-lg', TIER_TEXT[t]))}>
              {center}
            </span>
            {full && p !== null && <span className="font-mono text-xs tabular-nums text-fg-muted">{formatProb(p)}</span>}
          </div>
        </div>

        {full && s ? (
          <div className="flex flex-1 flex-col gap-3">
            <div className="flex flex-wrap justify-around gap-3">
              {!untiered && <Gauge label="Date push · 2q" value={s.pDatePush2q} />}
              <Gauge label="Cost revision · 2q" value={s.pCostRev2q} />
              {!untiered && <Gauge label="Any slip · 4q" value={s.pAny4q} />}
            </div>
            {s.stagnationOverride && (
              <span className="self-center rounded-full bg-warning/10 px-2.5 py-0.5 text-xs font-medium text-warning"
                title={`${orDash(s.stagnationQuarters, (v) => v.toFixed(0))} quarters without progress; the tier stays by rank`}>
                Work has stalled
              </span>
            )}
          </div>
        ) : (
          <div className="grid flex-1 grid-cols-2 gap-3">
            <Stat label="Work done" value={orDash(o.physicalProgressPct, (v) => `${v.toFixed(0)}%`)} />
            <Stat label="Cost" value={orDash(o.anticipatedCostCr, formatINR)} />
            <Stat label="Expected completion" value={orDash(o.anticipatedCompletion, formatDate)} />
            <Stat label="Scheduled" value={orDash(o.scheduledCompletion, formatDate)} />
          </div>
        )}
      </div>
      {!s && detail.master?.lastStatus && (
        <div className="mt-3 text-xs text-fg-dimmed">Not in the current portfolio · last status: {detail.master.lastStatus}</div>
      )}
    </Section>
  )
}

// ------------------------------------------------------------------ time vs work, money

function Bar({ pct, className, children }: { pct: number; className: string; children?: React.ReactNode }) {
  return (
    <div className="relative h-2.5 overflow-hidden rounded-full bg-surface-input">
      <motion.div className={cn('h-full rounded-full', className)} initial={{ width: 0 }} animate={{ width: `${clamp(pct)}%` }} transition={GROW} />
      {children}
    </div>
  )
}

/** Share of the sanctioned schedule used up (scores, else sanction -> scheduled completion at asof). */
function elapsedPct(d: ProjectDetail): number | null {
  if (d.scores?.elapsedRatio !== null && d.scores?.elapsedRatio !== undefined) return d.scores.elapsedRatio * 100
  const a = d.master?.sanctionDate
  const b = d.latest?.scheduledCompletion
  if (!a || !b) return null
  const t0 = Date.parse(a)
  const t1 = Date.parse(b)
  return t1 > t0 ? ((Date.parse(d.provenance.asof) - t0) / (t1 - t0)) * 100 : null
}

/** Schedule elapsed against physical progress, the gap between them shaded. */
export function TimeVsWork({ detail }: { detail: ProjectDetail }) {
  const time = elapsedPct(detail)
  const work = detail.latest?.physicalProgressPct ?? null
  const gap = time !== null && work !== null ? Math.min(time, 100) - work : null

  return (
    <Section
      title="Time vs work"
      info="Time: the share of the sanctioned schedule (sanction to scheduled completion) already used. Work: physical progress in the latest report. The shaded part is how far work trails time."
      right={gap !== null && Math.abs(gap) >= 1 && (
        <span className={cn('rounded-full px-2 py-0.5 font-medium', gap > 0 ? 'bg-critical/10 text-critical' : 'bg-stable/10 text-stable')}>
          {gap > 0 ? `${gap.toFixed(0)} pts behind` : `${(-gap).toFixed(0)} pts ahead`}
        </span>
      )}
    >
      <div className="space-y-3">
        {[
          { label: 'Time used', v: time, bar: 'bg-fg-muted/60' },
          { label: 'Work done', v: work, bar: 'bg-stable' },
        ].map(({ label, v, bar }) => (
          <div key={label} className="space-y-1">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-fg-muted">{label}</span>
              <span className="font-mono font-semibold tabular-nums text-fg-base">{orDash(v, (x) => `${x.toFixed(0)}%`)}</span>
            </div>
            <Bar pct={v ?? 0} className={bar}>
              {label === 'Work done' && gap !== null && gap > 0 && work !== null && (
                <div className="absolute inset-y-0 bg-critical/25" style={{ left: `${clamp(work)}%`, width: `${gap}%` }} />
              )}
            </Bar>
          </div>
        ))}
        {time !== null && time > 100 && <div className="text-xs text-warning">Past its scheduled completion</div>}
      </div>
    </Section>
  )
}

/** Spent and remaining of the anticipated cost, with the overrun over the original cost hatched. */
export function MoneyBar({ detail }: { detail: ProjectDetail }) {
  const o = detail.latest ?? {}
  const cost = o.anticipatedCostCr ?? null
  const orig = o.originalCostCr ?? null
  const spent = o.expenditureCr ?? null
  if (cost === null || cost <= 0) {
    return <Section title="Money"><Empty>No cost in the latest report</Empty></Section>
  }
  const total = Math.max(cost, spent ?? 0)
  const pct = (v: number) => (v / total) * 100
  const over = orig !== null && orig > 0 ? cost - orig : null
  const legend = [
    { label: 'Spent', v: spent, dot: 'bg-accent' },
    { label: 'Remaining', v: spent !== null ? Math.max(0, cost - spent) : null, dot: 'bg-accent/25' },
    ...(over !== null && over > 0.5 ? [{ label: `Overrun +${((over / (orig ?? cost)) * 100).toFixed(0)}%`, v: over, dot: 'bg-critical' }] : []),
  ]

  return (
    <Section title="Money" right={<span className="font-mono tabular-nums">{formatINR(cost)}</span>}
      info="Spent and remaining of the anticipated cost from the latest report; the red hatch is what the cost grew past the original sanctioned cost.">
      <div className="relative h-3 overflow-hidden rounded-full bg-accent/20">
        {spent !== null && (
          <motion.div className="absolute inset-y-0 left-0 bg-accent" initial={{ width: 0 }} animate={{ width: `${clamp(pct(spent))}%` }} transition={GROW} />
        )}
        {over !== null && over > 0.5 && orig !== null && (
          <div className="absolute inset-y-0" style={{
            left: `${pct(orig)}%`, width: `${pct(over)}%`,
            background: 'repeating-linear-gradient(135deg, hsl(var(--color-critical) / 0.75) 0 3px, hsl(var(--color-critical) / 0.25) 3px 6px)',
          }} />
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
        {legend.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-1.5 text-fg-muted">
            <span className={cn('size-2.5 rounded-full', l.dot)} />
            {l.label}
            <span className="font-mono font-semibold tabular-nums text-fg-base">{orDash(l.v, formatINR)}</span>
          </span>
        ))}
      </div>
      {orig !== null && (over === null || over <= 0.5) && (
        <div className="mt-1.5 text-xs text-fg-dimmed">Within the original cost of {formatINR(orig)}</div>
      )}
    </Section>
  )
}

// ------------------------------------------------------------------ trend

const PROGRESS = '#0b7249'
const SPEND = '#1946b8'

/** Physical progress and spend (as % of the anticipated cost) over the reports, no axes. */
export function ProgressTrend({ timeline, error, height = 96 }: { timeline: Timeline | undefined; error: unknown; height?: number }) {
  const rows = (timeline?.points ?? []).map((p) => ({
    t: Date.parse(p.period),
    progress: p.physicalProgressPct,
    spent: p.expenditureCr !== null && p.anticipatedCostCr ? (p.expenditureCr / p.anticipatedCostCr) * 100 : null,
  }))
  const first = rows[0]
  const last = rows.at(-1)
  const key = (color: string, label: string, dashed?: boolean) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width="16" height="4" aria-hidden="true"><line x1="0" y1="2" x2="16" y2="2" stroke={color} strokeWidth="2.5" strokeDasharray={dashed ? '4 3' : undefined} /></svg>
      {label}
    </span>
  )

  return (
    <Section title="Progress over time" right={<span className="flex gap-3">{key(PROGRESS, 'Work done')}{key(SPEND, 'Spent', true)}</span>}>
      {error ? (
        <ApiErrorNote error={error} className="py-3" />
      ) : !timeline ? (
        <div className="animate-pulse rounded-lg bg-surface-input/70" style={{ height }} />
      ) : !first || !last || rows.length < 2 ? (
        <Empty>{rows.length === 1 ? 'Only one report so far' : 'No reported progress'}</Empty>
      ) : (
        <>
          <div style={{ height }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} hide />
                <YAxis domain={[0, (max: number) => Math.max(100, max)]} hide />
                <ChartTooltip
                  cursor={{ stroke: '#8a8578', strokeDasharray: '2 3' }}
                  content={({ active, payload, label }) =>
                    active && payload?.length ? (
                      <div className="rounded-lg border border-border-default bg-surface-panel px-3 py-2 text-xs shadow-pop">
                        <div className="mb-1 font-semibold text-fg-base">{formatDate(new Date(Number(label)).toISOString())}</div>
                        {payload.map((i) => (
                          <div key={String(i.dataKey)} className="flex justify-between gap-4">
                            <span style={{ color: i.color }}>{i.dataKey === 'progress' ? 'Work done' : 'Spent'}</span>
                            <span className="font-mono font-semibold tabular-nums">{Number(i.value).toFixed(0)}%</span>
                          </div>
                        ))}
                      </div>
                    ) : null
                  }
                />
                <Line dataKey="spent" stroke={SPEND} strokeWidth={2} strokeDasharray="4 3" dot={false} connectNulls animationDuration={700} />
                <Line dataKey="progress" stroke={PROGRESS} strokeWidth={2.5} dot={false} connectNulls animationDuration={700} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex justify-between text-xs text-fg-dimmed">
            <span>{formatDate(new Date(first.t).toISOString())}</span>
            <span>{rows.length} reports</span>
            <span>{formatDate(new Date(last.t).toISOString())}</span>
          </div>
        </>
      )}
    </Section>
  )
}

// ------------------------------------------------------------------ timeline strip

/** as backend serving._add_months: first of the month, months rounded */
function addMonths(iso: string | null | undefined, months: number | null | undefined): string | null {
  if (!iso || months === null || months === undefined) return null
  const d = new Date(iso)
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + Math.round(months), 1)).toISOString()
}

function monthsBetween(a: string, b: string): number {
  const x = new Date(a)
  const y = new Date(b)
  return (y.getUTCFullYear() - x.getUTCFullYear()) * 12 + y.getUTCMonth() - x.getUTCMonth()
}

/**
 * Sanction -> scheduled -> anticipated -> predicted completion (p50, anticipated + months p50) on one line, the
 * p05-p95 band behind it when the viewer gets intervals, and a today (asof) marker.
 */
export function TimelineStrip({ detail }: { detail: ProjectDetail }) {
  const s = detail.scores
  const ant = detail.latest?.anticipatedCompletion ?? null
  const sched = detail.latest?.scheduledCompletion ?? null
  const band = [addMonths(ant, s?.monthsP05), addMonths(ant, s?.monthsP95)] as const
  const marks = [
    { label: 'Sanctioned', date: detail.master?.sanctionDate ?? null, dot: 'bg-fg-muted' },
    { label: 'Scheduled', date: sched, dot: 'bg-accent' },
    { label: 'Anticipated', date: ant, dot: 'bg-warning' },
    { label: 'Predicted', date: addMonths(ant, s?.monthsP50), dot: 'bg-critical' },
  ].filter((m): m is { label: string; date: string; dot: string } => !!m.date)
  const today = detail.provenance.asof
  const all = [...marks.map((m) => m.date), today, ...band.filter((b): b is string => !!b)].map(Date.parse)
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const x = (iso: string) => (hi > lo ? 3 + ((Date.parse(iso) - lo) / (hi - lo)) * 94 : 50)
  const slip = sched && ant ? monthsBetween(sched, ant) : null

  if (marks.length === 0) return <Section title="Timeline"><Empty>No dates in the reports</Empty></Section>

  return (
    <Section
      title="Timeline"
      info={band[0] && band[1]
        ? 'Predicted: the anticipated completion plus the model’s median slip over the next 2 quarters; the shaded band is its 5th–95th percentile.'
        : 'Predicted: the anticipated completion plus the expected slip over the next 2 quarters.'}
      right={slip !== null && slip > 0 && (
        <span className="rounded-full bg-warning/10 px-2 py-0.5 font-medium text-warning">+{slip} mo vs schedule</span>
      )}
    >
      <div className="relative h-12" aria-hidden="true">
        <div className="absolute inset-x-0 top-8 h-1.5 rounded-full bg-surface-input" />
        {band[0] && band[1] && (
          <div className="absolute top-7 h-3.5 rounded-full bg-critical/15 ring-1 ring-inset ring-critical/25"
            style={{ left: `${x(band[0])}%`, width: `${Math.max(1, x(band[1]) - x(band[0]))}%` }} />
        )}
        <div className="absolute top-0 flex -translate-x-1/2 flex-col items-center" style={{ left: `${x(today)}%` }}>
          <span className="text-xs font-medium leading-4 text-fg-base">Today</span>
          <span className="h-7 w-px bg-fg-base/70" />
        </div>
        {marks.map((m, i) => (
          <motion.span key={m.label}
            className={cn('absolute top-[29px] size-3.5 -translate-x-1/2 rounded-full ring-2 ring-surface-panel', m.dot)}
            style={{ left: `${x(m.date)}%` }}
            initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.1 + i * 0.08, duration: 0.3 }} />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs">
        {marks.map((m) => (
          <div key={m.label} className="flex items-center gap-1.5 whitespace-nowrap">
            <span className={cn('size-2.5 shrink-0 rounded-full', m.dot)} />
            <span className="text-fg-muted">{m.label}</span>
            <span className="font-mono font-semibold tabular-nums text-fg-base">{formatDate(m.date)}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ------------------------------------------------------------------ risk grid

const STATE_WORD: Record<RiskState, string> = { flagged: 'Flagged', clear: 'Clear', unknown: 'No data — not the same as clear' }

/**
 * The 13 checklist dimensions as icon tiles: red flagged, green clear, dashed grey no data; hover shows the
 * evidence line. plain (the public): state only on hover, and the top risks in plain words below.
 */
export function RiskGrid({ detail, plain, className }: { detail: ProjectDetail; plain: boolean; className?: string }) {
  const byDim = new Map<string, RiskRow>(detail.riskProfile.map((r) => [r.dimension, r]))
  const n = (st: RiskState) => detail.riskProfile.filter((r) => r.state === st).length

  return (
    <Section
      className={className}
      title={plain ? 'What could hold it up' : 'Risk checklist'}
      info="Each tile is one risk check on the latest reports. Grey dashed means there is no data for it, which is not the same as clear."
      right={detail.riskProfile.length > 0 && (
        <span><span className="font-semibold text-critical">{n('flagged')} flagged</span> · {n('clear')} clear · {n('unknown')} no data</span>
      )}
    >
      {detail.riskProfile.length === 0 ? (
        <Empty>No risk checks: the project is not in the current portfolio</Empty>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {Object.entries(RISK_DIMENSION).map(([dim, { label, short, icon: Icon }]) => {
            const r = byDim.get(dim)
            const st: RiskState = r?.state ?? 'unknown'
            return (
              <Tooltip key={dim} content={
                <div className="space-y-1">
                  <div className="font-semibold">{label} · {STATE_WORD[st]}</div>
                  {!plain && r?.evidence && <div className="text-fg-muted">{r.evidence}</div>}
                  {!plain && r?.asOfDate && <div className="text-fg-dimmed">as of {formatDate(r.asOfDate)}</div>}
                </div>
              }>
                <button type="button" aria-label={`${label}: ${STATE_WORD[st]}`}
                  className={cn('flex flex-col items-center gap-1 rounded-lg px-1 py-2.5 text-center transition-transform hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40', RISK_STATE_CHIP[st])}>
                  <Icon className="size-5" strokeWidth={2} />
                  <span className="text-xs font-medium leading-tight">{short}</span>
                </button>
              </Tooltip>
            )
          })}
        </div>
      )}
      {plain && detail.topRisksPlain.length > 0 && (
        <ul className="mt-4 space-y-2">
          {detail.topRisksPlain.map((t) => (
            <li key={t} className="flex items-start gap-2 text-sm text-fg-base">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
              {t}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

// ------------------------------------------------------------------ drivers, external

/** The three largest SHAP drivers of P(slip, 2q) as bars: red raises the risk, green lowers it. */
export function TopDrivers({ drivers }: { drivers: ShapValue[] }) {
  const top = [...drivers].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, 3)
  const max = Math.max(...top.map((d) => Math.abs(d.contribution)), 1e-4)
  return (
    <Section title="What drives the score"
      info="The three largest TreeSHAP contributions to P(slip, 2q) of the LightGBM model, in log-odds. The full page lists five with their values.">
      {top.length === 0 ? (
        <Empty>No drivers: the slip model does not score this project</Empty>
      ) : (
        <div className="space-y-3">
          {top.map((d) => {
            const up = d.contribution > 0
            const Arrow = up ? ArrowUp : ArrowDown
            return (
              <div key={d.feature} className="space-y-1" title={`${d.feature} = ${String(d.value ?? 'missing')}`}>
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate text-fg-base">{featureLabel(d.feature)}</span>
                  <Arrow className={cn('size-3.5 shrink-0', up ? 'text-critical' : 'text-stable')} aria-label={up ? 'raises risk' : 'lowers risk'} />
                </div>
                <Bar pct={(Math.abs(d.contribution) / max) * 100} className={up ? 'bg-critical/80' : 'bg-stable/80'} />
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}

const OPEN_CATEGORIES: [string, Flag][] = [['land', 'land'], ['forest_env', 'forest'], ['litigation', 'litigation'], ['contractor', 'contractor']]

/** Open land, forest, court and contractor issues from the report remarks; news: the linked-news count (officials). */
export function ExternalChips({ events, news }: { events: EventRow[]; news?: { n: number; scouted: boolean } }) {
  const open = OPEN_CATEGORIES
    .map(([c, f]) => ({ f, n: events.filter((e) => e.category === c && e.status === 'open').length }))
    .filter((x) => x.n > 0)
  const until = events.find((e) => e.remarksLastSeen)?.remarksLastSeen
  return (
    <Section title="External issues"
      info={`Open issues found in the free-text report remarks${until ? `, read up to ${formatDate(until)}` : ' (through 2023)'}${news ? ', and news the scout linked to this project' : ''}.`}>
      <div className="flex flex-wrap gap-2">
        {open.map(({ f, n }) => {
          const Icon = FLAG_ICON[f]
          return (
            <span key={f} className="inline-flex items-center gap-1.5 rounded-full bg-warning/10 px-2.5 py-1 text-xs font-medium text-warning ring-1 ring-inset ring-warning/20">
              <Icon className="size-3.5" strokeWidth={2} />
              {FLAG_LABEL[f]}{n > 1 && ` ×${n}`}
            </span>
          )
        })}
        {open.length === 0 && (
          <span className="rounded-full bg-fg-dimmed/10 px-2.5 py-1 text-xs text-fg-muted">No open issue in the remarks</span>
        )}
        {news && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent ring-1 ring-inset ring-accent/20">
            <Newspaper className="size-3.5" strokeWidth={2} />
            {news.scouted ? `${news.n} linked news` : 'News not searched yet'}
          </span>
        )}
      </div>
    </Section>
  )
}

/** Placeholder shapes while the project loads. */
export function VisualsSkeleton() {
  return (
    <div className="animate-pulse space-y-4" aria-busy="true" aria-label="Loading project">
      <div className="flex items-center gap-6 rounded-xl border border-border-subtle bg-surface-panel p-4">
        <div className="size-32 rounded-full bg-surface-input" />
        <div className="flex flex-1 justify-around">
          {[0, 1, 2].map((i) => <div key={i} className="h-14 w-16 rounded-lg bg-surface-input" />)}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="h-28 rounded-xl bg-surface-input/70" />
        <div className="h-28 rounded-xl bg-surface-input/70" />
      </div>
      <div className="h-36 rounded-xl bg-surface-input/70" />
      <div className="h-28 rounded-xl bg-surface-input/70" />
    </div>
  )
}
