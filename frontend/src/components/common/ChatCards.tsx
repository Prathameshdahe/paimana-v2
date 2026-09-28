/**
 * The assistant's cards (contracts/assistant.ts): the data an answer is built from, drawn from the card itself so
 * they read the same whatever the narrative says. Project names open the side panel; the sources list carries the
 * [n] anchors the narrative's chips scroll to; external links open in a new tab without a referrer.
 */
import React, { useId, useState } from 'react'
import { AlertTriangle, ArrowDown, ArrowUp, Check, ChevronDown, ExternalLink, Loader2, RotateCcw, X } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { webUrl } from '@/lib/citations'
import { CONCERN, FLAG_ICON, FLAG_LABEL, RISK_DIMENSION, TIER_COLOR, TIER_LABEL, tierKey } from '@/lib/riskPalette'
import {
  cn, formatDate, formatDateTime, formatINR, formatINRShort, formatLooseDate, formatProb, orDash,
} from '@/lib/formatters'
import type {
  ChatCard, ChatProjectRow, ChatSource, ChatStage, ChatTool, CompareCard, ExplainCard, HistoryCard, OpinionCard,
  ProjectCard, ProjectFacts, ProjectsCard, StatsCard,
} from '@/contracts/assistant'
import type { Flag } from '@/contracts/project'

const pct = (v: number) => `${v.toFixed(0)}%`

/** the chance the list and project cards show, in the words the public page uses */
const P_ANY = 'Delay or cost rise, next 6 months'

function Shell({ title, right, children, className }: {
  title: React.ReactNode
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('animate-card-in rounded-xl border border-border-subtle bg-surface-panel p-3 shadow-card', className)}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h4 className="min-w-0 text-sm font-semibold leading-snug text-fg-base">{title}</h4>
        {right && <span className="shrink-0 text-xs text-fg-dimmed">{right}</span>}
      </div>
      {children}
    </section>
  )
}

function OpenProject({ projectKey, children, className }: { projectKey: string; children: React.ReactNode; className?: string }) {
  const panel = useProjectPanel()
  return (
    <button
      type="button"
      onClick={() => panel.open(projectKey)}
      className={cn('rounded text-left font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40', className)}
    >
      {children}
    </button>
  )
}

function FlagIcons({ flags }: { flags: Flag[] }) {
  const known = flags.filter((f) => f in FLAG_ICON)
  if (!known.length) return null
  return (
    <span className="inline-flex items-center gap-1 text-warning">
      {known.map((f) => {
        const Icon = FLAG_ICON[f]
        return <Icon key={f} className="size-3.5" strokeWidth={2} aria-label={FLAG_LABEL[f]} role="img" />
      })}
    </span>
  )
}

// ------------------------------------------------------------------ projects, stats

function ProjectLine({ p }: { p: ChatProjectRow }) {
  const panel = useProjectPanel()
  const t = tierKey(p.tier)
  return (
    <button
      type="button"
      onClick={() => panel.open(p.key)}
      className="flex w-full items-center gap-2.5 rounded-lg px-1.5 py-2 text-left transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
    >
      <span className="size-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t] }} title={TIER_LABEL[t]} aria-label={TIER_LABEL[t]} role="img" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-accent" title={p.name ?? undefined}>{p.name ?? p.key}</span>
        <span className="flex items-center gap-1.5 text-xs text-fg-dimmed">
          <span className="truncate">
            {p.state ?? 'state unknown'} · {orDash(p.anticipatedCostCr, formatINRShort)}
            {p.physicalProgressPct !== null && ` · ${pct(p.physicalProgressPct)} done`}
          </span>
          <FlagIcons flags={p.flags} />
        </span>
      </span>
      <span className="shrink-0 font-mono text-xs font-semibold tabular-nums text-fg-base" title={P_ANY}>
        {orDash(p.pAny2q, formatProb)}
      </span>
    </button>
  )
}

function ProjectsCardView({ card }: { card: ProjectsCard }) {
  const more = card.total > card.items.length
  return (
    <Shell title={card.title} right={more ? `${card.items.length} of ${card.total}, riskiest first` : `${card.total} found`}>
      {card.items.length === 0 ? (
        <p className="py-2 text-center text-sm text-fg-dimmed">No project matches in your view</p>
      ) : (
        <ul className="-mx-1.5 divide-y divide-border-subtle">
          {card.items.map((p) => <li key={p.key}><ProjectLine p={p} /></li>)}
        </ul>
      )}
    </Shell>
  )
}

/** an unmapped kind or group in sentence case, so a newer backend's word still reads as a label */
const asLabel = (w: string) => w.charAt(0).toUpperCase() + w.slice(1).replace(/_/g, ' ')

/** the first column's header per stats groupBy (llm/tools.py: portfolio, outside factors, agencies, bottlenecks) */
const GROUP_LABEL: Record<string, string> = {
  state: 'State', sector: 'Sector', ministry: 'Ministry', agency: 'Agency', tier: 'Tier', factor: 'Outside factor',
  bottleneck: 'Bottleneck',
}

/** a tier count: a number as itself, null as "unknown" (the count is not known for the row; not the same as 0) */
function Count({ v, cls }: { v: number | null; cls: string }) {
  if (v === null) return <span className="text-fg-dimmed" title="The count is not known for this row">unknown</span>
  return <span className={v ? `font-semibold ${cls}` : 'text-fg-dimmed'}>{v}</span>
}

function StatsCardView({ card }: { card: StatsCard }) {
  const th = 'py-1.5 px-2 font-medium'
  return (
    <Shell title={card.title}>
      <div className="-mx-1 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-border-subtle text-fg-muted">
              <th scope="col" className={cn(th, 'pl-1')}>{GROUP_LABEL[card.groupBy] ?? asLabel(card.groupBy)}</th>
              <th scope="col" className={cn(th, 'text-right')}>Projects</th>
              <th scope="col" className={cn(th, 'text-right')}>Capital</th>
              <th scope="col" className={cn(th, 'text-right text-critical')}>Critical</th>
              <th scope="col" className={cn(th, 'pr-1 text-right text-warning')}>High</th>
            </tr>
          </thead>
          <tbody>
            {card.rows.map((r, i) => (
              <tr key={`${r.name}-${i}`} className="border-b border-border-subtle/60 last:border-0">
                <th scope="row" className="max-w-[10rem] truncate py-1.5 pl-1 pr-2 text-left font-normal text-fg-base" title={r.name ?? undefined}>
                  {r.name ?? 'unknown'}
                </th>
                <td className="px-2 py-1.5 text-right tabular-nums text-fg-base">{r.n.toLocaleString('en-IN')}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums text-fg-muted">{orDash(r.capitalCr, formatINRShort)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums"><Count v={r.nCritical} cls="text-critical" /></td>
                <td className="py-1.5 pl-2 pr-1 text-right tabular-nums"><Count v={r.nHigh} cls="text-warning" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  )
}

// ------------------------------------------------------------------ one project, compare

/** the tier ring in small: the chance of a slip as the arc, in the tier colour */
function MiniRing({ tier, p }: { tier: string | null; p: number | null }) {
  const t = tierKey(tier)
  const R = 16
  const C = 2 * Math.PI * R
  return (
    <div className="relative size-12 shrink-0" role="img" aria-label={`${TIER_LABEL[t]}${p !== null ? `, ${formatProb(p)} chance of a delay or cost rise in the next 6 months` : ''}`}>
      <svg viewBox="0 0 40 40" className="size-12 -rotate-90" aria-hidden="true">
        <circle cx={20} cy={20} r={R} fill="none" strokeWidth={5} className="stroke-surface-input" />
        {p === null ? (
          <circle cx={20} cy={20} r={R} fill="none" strokeWidth={5} stroke={TIER_COLOR.Watch} strokeOpacity={0.5} />
        ) : (
          <circle cx={20} cy={20} r={R} fill="none" strokeWidth={5} strokeLinecap="round" stroke={TIER_COLOR[t]}
            strokeDasharray={`${(C * Math.min(1, Math.max(0, p))).toFixed(1)} ${C.toFixed(1)}`} />
        )}
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-xs font-semibold tabular-nums text-fg-base">
        {p === null ? '—' : formatProb(p)}
      </span>
    </div>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-xs text-fg-muted" title={label}>{label}</div>
      <div className="font-mono text-sm font-semibold tabular-nums text-fg-base">{value}</div>
    </div>
  )
}

function ProjectCardView({ card }: { card: ProjectCard }) {
  const slip = card.monthsP50 !== null && card.monthsP50 >= 0.5 ? `+${Math.round(card.monthsP50)} mo` : card.monthsP50 !== null ? 'none' : '—'
  return (
    <Shell title={<OpenProject projectKey={card.key}>{card.name ?? card.key}</OpenProject>} right={<span className="font-mono">{card.key}</span>}>
      <div className="flex items-center gap-3">
        <MiniRing tier={card.tier} p={card.pAny2q} />
        <div className="min-w-0 space-y-1">
          <Badge tier={card.tier} />
          <div className="text-xs leading-snug text-fg-muted">
            {card.pAny2q !== null ? `${formatProb(card.pAny2q)} chance of a delay or cost rise in the next 6 months` : 'No completion date, so the delay risk is not ranked'}
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
        <Figure label="Work done" value={orDash(card.progressPct, pct)} />
        <Figure label="Anticipated cost" value={orDash(card.costCr, formatINR)} />
        <Figure label="Expected completion" value={orDash(card.anticipatedCompletion, formatDate)} />
        <Figure label="Likely further delay" value={slip} />
      </div>
      {(card.pDatePush2q !== null || card.pCostRev2q !== null) && (
        <div className="mt-2 text-xs text-fg-dimmed">
          Date push {orDash(card.pDatePush2q, formatProb)} · cost revision {orDash(card.pCostRev2q, formatProb)}, next 6 months
        </div>
      )}
      {card.topRisksPlain.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-border-subtle pt-2.5">
          {card.topRisksPlain.map((r) => (
            <li key={r} className="flex items-start gap-2 text-sm leading-snug text-fg-base">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
              {r}
            </li>
          ))}
        </ul>
      )}
    </Shell>
  )
}

function CompareCardView({ card }: { card: CompareCard }) {
  const rows: Array<[string, (p: ProjectFacts) => React.ReactNode]> = [
    ['Tier', (p) => <Badge tier={p.tier} />],
    [P_ANY, (p) => <span className="font-mono tabular-nums">{orDash(p.pAny2q, formatProb)}</span>],
    ['Work done', (p) => <span className="font-mono tabular-nums">{orDash(p.progressPct, pct)}</span>],
    ['Anticipated cost', (p) => <span className="whitespace-nowrap font-mono tabular-nums">{orDash(p.costCr, formatINRShort)}</span>],
    ['Expected completion', (p) => orDash(p.anticipatedCompletion, formatDate)],
    ['Top risk', (p) => p.topRisksPlain[0] ?? <span className="text-fg-dimmed">none flagged</span>],
  ]
  return (
    <Shell title={`Comparing ${card.items.length} projects`}>
      <div className="-mx-1 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-border-subtle align-bottom">
              <td className="py-1.5 pl-1" />
              {card.items.map((p) => (
                <th key={p.key} scope="col" className="min-w-[7.5rem] px-2 py-1.5 text-left">
                  <OpenProject projectKey={p.key} className="line-clamp-2 text-xs">{p.name ?? p.key}</OpenProject>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, cell]) => (
              <tr key={label} className="border-b border-border-subtle/60 align-top last:border-0">
                <th scope="row" className="py-1.5 pl-1 pr-2 text-left font-normal text-fg-muted">{label}</th>
                {card.items.map((p) => <td key={p.key} className="px-2 py-1.5 text-fg-base">{cell(p)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  )
}

// ------------------------------------------------------------------ explain, history

function ExplainCardView({ card }: { card: ExplainCard }) {
  const drivers = [...card.drivers].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
  const max = Math.max(...drivers.map((d) => Math.abs(d.contribution)), 1e-4)
  return (
    <Shell title={<>Why {card.name ?? card.key} is <span className="whitespace-nowrap">{TIER_LABEL[tierKey(card.tier)]}</span></>} right={<Badge tier={card.tier} />}>
      {drivers.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-fg-muted">What moves the model&rsquo;s score most</div>
          {drivers.map((d) => {
            const up = d.contribution > 0
            const Arrow = up ? ArrowUp : ArrowDown
            return (
              <div key={d.feature} className="space-y-1">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="min-w-0 truncate text-fg-base" title={d.label}>{d.label}</span>
                  <span className={cn('flex shrink-0 items-center gap-0.5', up ? 'text-critical' : 'text-stable')}>
                    <Arrow className="size-3.5" aria-hidden="true" />
                    {up ? 'raises risk' : 'lowers risk'}
                  </span>
                </div>
                <div className="h-2 overflow-hidden bg-surface-input">
                  <div className={cn('h-full', up ? 'bg-critical/80' : 'bg-stable/80')} style={{ width: `${(Math.abs(d.contribution) / max) * 100}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      )}
      {card.flagged.length > 0 && (
        <div className={cn('space-y-2', drivers.length > 0 && 'mt-3 border-t border-border-subtle pt-2.5')}>
          <div className="text-xs text-fg-muted">Flagged checks</div>
          {card.flagged.map((f) => {
            const Icon = RISK_DIMENSION[f.dimension]?.icon ?? AlertTriangle
            return (
              <div key={f.dimension} className="flex items-start gap-2">
                <Icon className="mt-0.5 size-4 shrink-0 text-critical" strokeWidth={2} aria-hidden="true" />
                <div className="min-w-0">
                  <div className="text-sm font-medium leading-snug text-fg-base">{f.label}</div>
                  {f.evidence && <div className="line-clamp-3 text-xs leading-snug text-fg-muted" title={f.evidence}>{f.evidence}</div>}
                </div>
              </div>
            )
          })}
        </div>
      )}
      {drivers.length === 0 && card.flagged.length === 0 && (
        <p className="py-2 text-center text-sm text-fg-dimmed">No drivers or flagged checks for this project</p>
      )}
    </Shell>
  )
}

/** physical progress over the reports as a small line (0-100%), segments broken where a report has no figure */
function Sparkline({ values, label }: { values: Array<number | null>; label: string }) {
  const W = 240
  const H = 48
  const pad = 4
  const n = values.length
  const max = Math.max(100, ...values.filter((v): v is number => v !== null))
  const x = (i: number) => (n > 1 ? pad + (i / (n - 1)) * (W - 2 * pad) : W / 2)
  const y = (v: number) => H - pad - (v / max) * (H - 2 * pad)
  const segments: string[] = []
  let run: string[] = []
  values.forEach((v, i) => {
    if (v === null) {
      if (run.length) segments.push(run.join(' '))
      run = []
    } else run.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`)
  })
  if (run.length) segments.push(run.join(' '))
  let last = n - 1
  while (last >= 0 && values[last] === null) last--
  const lastV = values[last]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={label}>
      <line x1={pad} x2={W - pad} y1={y(100)} y2={y(100)} className="stroke-border-default" strokeDasharray="3 3" strokeWidth={1} />
      <line x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} className="stroke-border-subtle" strokeWidth={1} />
      {segments.map((pts) => (
        <polyline key={pts} points={pts} fill="none" className="stroke-stable" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {lastV !== undefined && lastV !== null && <circle cx={x(last)} cy={y(lastV)} r={3.5} className="fill-stable" />}
    </svg>
  )
}

function HistoryCardView({ card }: { card: HistoryCard }) {
  const pts = card.points
  const first = pts[0]
  const last = pts.at(-1)
  const progress = pts.map((p) => p.progressPct)
  const lastProgress = [...progress].reverse().find((v): v is number => v !== null)
  return (
    <Shell title={<>What changed · <OpenProject projectKey={card.key}>{card.name ?? card.key}</OpenProject></>}>
      {pts.length >= 2 && first && last ? (
        <div>
          <div className="flex items-baseline justify-between text-xs text-fg-muted">
            <span>Work done over {pts.length} reports</span>
            {lastProgress !== undefined && <span className="font-mono font-semibold tabular-nums text-fg-base">{pct(lastProgress)}</span>}
          </div>
          <Sparkline values={progress} label={`Work done from ${formatDate(first.period)} to ${formatDate(last.period)}${lastProgress !== undefined ? `, now ${pct(lastProgress)}` : ''}`} />
          <div className="flex justify-between text-xs text-fg-dimmed">
            <span>{formatDate(first.period)}</span>
            <span>{formatDate(last.period)}</span>
          </div>
        </div>
      ) : (
        <p className="text-xs text-fg-dimmed">{pts.length === 1 ? 'Only one report so far' : 'No reports with figures'}</p>
      )}
      {card.changes.length > 0 && (
        <ul className="mt-2.5 list-disc space-y-1 pl-5 text-sm leading-snug text-fg-base marker:text-fg-dimmed">
          {card.changes.map((c) => <li key={c}>{c}</li>)}
        </ul>
      )}
    </Shell>
  )
}

// ------------------------------------------------------------------ opinion

function OpinionCardView({ card }: { card: OpinionCard }) {
  const c = CONCERN[card.concern] ?? CONCERN.watch
  return (
    <Shell title="AI second opinion" right={card.generatedAt && formatDateTime(card.generatedAt)}>
      <div className="space-y-1.5">
        <Badge variant={c.variant}>{c.label}</Badge>
        <p className="text-sm font-medium leading-snug text-fg-base">{card.headline}</p>
        <p className="text-xs text-fg-dimmed">An AI reading of the evidence; it does not change the tier.</p>
        <OpenProject projectKey={card.key} className="text-xs">Open the project for the full opinion</OpenProject>
      </div>
    </Shell>
  )
}

function CardBody({ card }: { card: ChatCard }) {
  switch (card.type) {
    case 'projects': return <ProjectsCardView card={card} />
    case 'stats': return <StatsCardView card={card} />
    case 'project': return <ProjectCardView card={card} />
    case 'compare': return <CompareCardView card={card} />
    case 'explain': return <ExplainCardView card={card} />
    case 'history': return <HistoryCardView card={card} />
    case 'opinion': return <OpinionCardView card={card} />
    default: return null
  }
}

/** one data card; sources are drawn by SourcesList under the narrative. A card that fails to draw says so alone. */
export function ChatCardView({ card }: { card: ChatCard }) {
  return (
    <ErrorBoundary fallback={<p className="rounded-xl border border-dashed border-border-default px-3 py-2 text-xs text-fg-dimmed">This card could not be shown.</p>}>
      <CardBody card={card} />
    </ErrorBoundary>
  )
}

// ------------------------------------------------------------------ sources

/** a source's kind in words: llm/tools.py's own sources, then the knowledge search's document kinds (llm/rag.py) */
const KIND_LABEL: Record<string, string> = {
  project: 'Project data', portfolio: 'Portfolio figures', model: 'Risk model', checklist: 'Risk checks',
  agency: 'Agency figures', bottleneck: 'Bottlenecks', research: 'Web research', news: 'News', event: 'Report remark',
  external: 'External data', help: 'Help page', doc: 'Documentation', glossary: 'Glossary', opinion: 'AI second opinion',
}

/** the numbered sources the narrative cites; each item is the target of its [n] chips */
export function SourcesList({ items, anchor, flashed }: {
  items: ChatSource[]
  /** the element id of source n */
  anchor: (n: number) => string
  flashed: number | null
}) {
  const panel = useProjectPanel()
  return (
    <section aria-label="Sources" className="rounded-xl border border-border-subtle bg-surface-panel/70 p-2.5">
      <h4 className="mb-1.5 px-1 text-xs font-semibold text-fg-muted">Sources</h4>
      <ol className="space-y-0.5">
        {items.map((s) => {
          const href = webUrl(s.url)
          return (
            <li
              key={s.n}
              id={anchor(s.n)}
              tabIndex={-1}
              className={cn(
                // a chip moves the focus here: keyboard viewers keep a ring after the highlight fades
                'flex scroll-mt-4 gap-2 rounded-lg px-1.5 py-1.5 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                flashed === s.n ? 'bg-accent/10 ring-1 ring-inset ring-accent/30' : ''
              )}
            >
              <span className="mt-px inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded bg-accent/15 px-1 font-semibold leading-none text-accent">
                {s.n}
              </span>
              <div className="min-w-0 flex-1 space-y-0.5">
                {href ? (
                  <a href={href} target="_blank" rel="noreferrer" className="inline font-medium leading-snug text-fg-base hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                    {s.title}
                    <ExternalLink className="ml-1 inline size-3 align-baseline text-fg-dimmed" aria-label="opens in a new tab" />
                  </a>
                ) : (
                  <span className="font-medium leading-snug text-fg-base">{s.title}</span>
                )}
                <div className="flex flex-wrap items-center gap-x-1.5 text-fg-dimmed">
                  <span>{KIND_LABEL[s.kind] ?? asLabel(s.kind)}</span>
                  {s.source && <span className="truncate">· {s.source}</span>}
                  {s.date && <span>· {formatLooseDate(s.date, s.datePrecision)}</span>}
                  {s.projectKey && (
                    <span>
                      ·{' '}
                      <button type="button" onClick={() => panel.open(s.projectKey ?? '')}
                        className="font-mono text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                        {s.projectKey}
                      </button>
                    </span>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// ------------------------------------------------------------------ progress

const STAGE_LABEL: Record<ChatStage, string> = {
  routing: 'Reading the question',
  planning: 'Choosing what to look up',
  tools: 'Looking up the data',
  writing: 'Writing the answer',
  checking: 'Checking the numbers against the data',
}

/** what B3 sends as the reason when the local model drops mid-answer (llm/agent.py): not a failed check */
const DROPPED = /stopped answering/i

/**
 * Each retry in words. B3 sends one when a draft fails the check against the data (a second attempt follows, and
 * after a second failure the answer is built from the data), or when the local model stops mid-answer (the answer
 * is built from the data at once).
 */
function retryLines(retries: string[][]): Array<{ text: string; reasons: string[] }> {
  let failed = 0
  return retries.map((reasons) => {
    if (reasons.some((r) => DROPPED.test(r))) {
      return { reasons, text: 'The local AI stopped answering, so the answer is built from the data instead' }
    }
    failed += 1
    return {
      reasons,
      text: failed === 1 ? 'The first draft did not pass the check against the data, so it is being written again'
        : 'The second draft did not pass either, so the answer is built from the data instead',
    }
  })
}

/**
 * The tool calls of one answer as a compact list: open on the newest answer, folded to one line on older ones (so it
 * folds when the next question is asked, never under the viewer's eyes as an answer ends); the viewer can open or
 * fold it. While it streams, the stage, the newest step and a set-aside draft are announced politely from a hidden
 * region of their own, so a folded list (display none) does not silence them.
 */
export function ToolSteps({ steps, stage, detail, retries, streaming, latest }: {
  steps: ChatTool[]
  stage: ChatStage | null
  detail: string | null
  retries: string[][]
  streaming: boolean
  /** the newest answer */
  latest: boolean
}) {
  const [open, setOpen] = useState<boolean | null>(null)
  const listId = useId()
  const expanded = open ?? (streaming || latest)
  const now = streaming ? (detail || (stage ? STAGE_LABEL[stage] : 'Sending the question')) : null
  const summary = `${steps.length} step${steps.length === 1 ? '' : 's'}`
    + (retries.length ? ` · ${retries.length} draft${retries.length === 1 ? '' : 's'} set aside` : '')
  const lines = retryLines(retries)
  const newest = steps.at(-1)
  const lastRetry = lines.at(-1)
  if (!streaming && steps.length === 0 && retries.length === 0) return null

  return (
    <div className="text-xs">
      <div className="sr-only" aria-live="polite">
        {streaming && (
          <>
            <div>{now}</div>
            {newest && <div>{newest.label}{newest.status === 'done' ? ', done' : newest.status === 'error' ? ', failed' : ''}</div>}
            {lastRetry && <div>{lastRetry.text}</div>}
          </>
        )}
      </div>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setOpen(!expanded)}
        className="flex max-w-full items-center gap-1.5 rounded-md py-0.5 pr-1 text-fg-muted transition-colors hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', !expanded && '-rotate-90')} aria-hidden="true" />
        {streaming && <Loader2 className="size-3.5 shrink-0 animate-spin text-accent" aria-hidden="true" />}
        <span className="truncate">{now ?? summary}</span>
      </button>
      <ol id={listId} className={cn('mt-1 space-y-1 border-l border-border-default pl-3 ml-1.5', !expanded && 'hidden')}>
        {steps.map((s) => (
          <li key={s.id} className="flex items-start gap-1.5">
            {s.status === 'running' ? (
              <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-accent" aria-label="running" />
            ) : s.status === 'done' ? (
              <Check className="mt-0.5 size-3.5 shrink-0 text-stable" aria-label="done" />
            ) : (
              <X className="mt-0.5 size-3.5 shrink-0 text-critical" aria-label="failed" />
            )}
            <span className="min-w-0">
              <span className="text-fg-base">{s.label}</span>
              {s.summary && <span className="text-fg-dimmed"> · {s.summary}</span>}
            </span>
          </li>
        ))}
        {lines.map(({ text, reasons }, i) => (
          <li key={`retry-${i}`} className="flex items-start gap-1.5 text-warning" title={reasons.join('; ') || undefined}>
            <RotateCcw className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>{text}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
