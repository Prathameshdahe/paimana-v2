import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { Badge } from '@/components/ui/Badge'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { usePortfolio, type ProjectQuery } from '@/lib/queries'
import { FLAG_LABEL, TIER_SENTIMENT, TIERS, tierKey } from '@/lib/riskPalette'
import { formatDate, formatINR, formatPct, formatProb, orDash, cn } from '@/lib/formatters'
import type { Flag, ProjectPage, ProjectSort, TierFilter } from '@/contracts/project'

interface TriageTableProps {
  query: ProjectQuery
  onChange: (patch: Partial<ProjectQuery>) => void
  page: ProjectPage | undefined
  error: unknown
  isFetching: boolean
  selectedKey?: string | null
  onOpenDetail: (key: string) => void
}

const TIER_BUTTONS: Array<TierFilter | 'ALL'> = ['ALL', ...TIERS, 'untiered']
const FLAG_CHIPS: Array<Flag | 'ANY'> = ['ANY', ...(Object.keys(FLAG_LABEL) as Flag[])]
const TIER_BUTTON_ON: Record<TierFilter | 'ALL', string> = {
  ALL: 'bg-fg-base',
  Critical: 'bg-critical',
  High: 'bg-warning',
  Medium: 'bg-accent',
  Low: 'bg-stable',
  untiered: 'bg-fg-dimmed',
}

const selectCls =
  'bg-surface-input border border-border-default px-2 py-0.5 text-[11px] font-sans font-semibold uppercase text-fg-muted focus:outline-none max-w-[180px]'

/**
 * TriageTable — high-density operational queue over /api/projects.
 * Server-paginated: filters, search and sort go to the backend; the browser
 * only ever holds one page. Bloomberg-style tabular layout.
 */
export function TriageTable({ query, onChange, page, error, isFetching, selectedKey, onOpenDetail }: TriageTableProps) {
  const { data: portfolio } = usePortfolio()
  const [text, setText] = useState(query.q ?? '')

  // debounce the search box into the query
  useEffect(() => {
    const t = setTimeout(() => {
      const q = text.trim() || undefined
      if (q !== query.q) onChange({ q })
    }, 300)
    return () => clearTimeout(t)
  }, [text, query.q, onChange])

  const sectors = (portfolio?.bySector ?? []).map((s) => s.name).filter((n): n is string => !!n).sort()
  const states = (portfolio?.byState ?? []).map((s) => s.name).filter((n): n is string => !!n).sort()
  const total = page?.total ?? 0
  const size = query.size ?? 25
  const pageNo = query.page ?? 1
  const totalPages = Math.max(1, Math.ceil(total / size))

  const handleSort = (sort: ProjectSort) => {
    if (query.sort === sort) onChange({ order: query.order === 'asc' ? 'desc' : 'asc' })
    else onChange({ sort, order: sort === 'name' ? 'asc' : 'desc' })
  }
  const sortIcon = (sort: ProjectSort) => (query.sort === sort ? (query.order === 'asc' ? ' ▲' : ' ▼') : '')

  return (
    <Card
      title={`Triage Register · ${total.toLocaleString()}${isFetching ? ' · loading' : ''}`}
      titleRight={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/* Tier filters */}
          {TIER_BUTTONS.map((t) => {
            const on = (query.tier ?? 'ALL') === t
            return (
              <button
                key={t}
                onClick={() => onChange({ tier: t === 'ALL' ? undefined : t })}
                className={cn(
                  'font-sans text-[11px] font-bold tracking-wider px-2.5 py-1 rounded-sm transition-all uppercase',
                  on
                    ? `text-white shadow-sm ${TIER_BUTTON_ON[t]}`
                    : 'text-fg-dimmed hover:text-fg-base bg-surface-elevated/50 hover:bg-surface-elevated'
                )}
                title={t === 'untiered' ? 'no anticipated completion date in the reports — schedule not scored' : undefined}
              >
                {t === 'untiered' ? 'no date' : t}
              </button>
            )
          })}

          <select
            value={query.sector ?? ''}
            onChange={(e) => onChange({ sector: e.target.value || undefined })}
            className={selectCls}
          >
            <option value="">ALL SECTORS</option>
            {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          <select
            value={query.state ?? ''}
            onChange={(e) => onChange({ state: e.target.value || undefined })}
            className={selectCls}
          >
            <option value="">ALL STATES</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
            {query.state && !states.includes(query.state) && <option value={query.state}>{query.state}</option>}
          </select>
        </div>
      }
    >
      {/* Search bar */}
      <div className="border-b border-border-subtle px-5 py-4 bg-surface-panel/50">
        <div className="flex items-center gap-2.5 bg-surface-input px-3.5 py-2.5 rounded-md border border-border-default focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/20 transition-all shadow-inner">
          <Search className="w-4 h-4 text-fg-dimmed" />
          <input
            type="text"
            placeholder="Search by project name or PRJ key..."
            value={text}
            maxLength={100}
            onChange={(e) => setText(e.target.value)}
            className="w-full bg-transparent text-sm font-sans font-medium text-fg-base placeholder:text-fg-dimmed focus:outline-none"
          />
        </div>

        {/* Flag chips: a flagged risk-profile dimension, or early notice */}
        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          <span className="font-sans text-[11px] font-semibold uppercase tracking-wider text-fg-dimmed mr-1">Flag</span>
          {FLAG_CHIPS.map((f) => {
            const on = (query.flag ?? 'ANY') === f
            return (
              <button
                key={f}
                aria-pressed={on}
                onClick={() => onChange({ flag: f === 'ANY' ? undefined : f })}
                title={f === 'early_notice' ? 'flagged external factor while the CUF numbers show no slip yet' : undefined}
                className={cn(
                  'border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider transition-colors',
                  on
                    ? f === 'early_notice'
                      ? 'border-critical bg-critical text-white'
                      : f === 'ANY'
                        ? 'border-fg-base bg-fg-base text-fg-inverse'
                        : 'border-warning bg-warning text-white'
                    : 'border-border-default text-fg-dimmed hover:text-fg-base hover:border-border-strong'
                )}
              >
                {f === 'ANY' ? 'any' : FLAG_LABEL[f]}
              </button>
            )
          })}
        </div>
      </div>

      {error ? (
        <ApiErrorNote error={error} />
      ) : (
        <div className={cn('overflow-x-auto transition-opacity', isFetching && 'opacity-60')}>
          <table className="w-full border-collapse text-left font-mono text-[13px]">
            <thead>
              <tr className="border-b border-border-default text-fg-dimmed font-sans text-xs uppercase tracking-wider">
                <th className="py-3 px-5 font-semibold w-[300px] cursor-pointer hover:text-fg-muted" onClick={() => handleSort('name')}>
                  PROJECT{sortIcon('name')}
                </th>
                <th className="py-3 px-5 font-semibold">AGENCY</th>
                <th className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right" onClick={() => handleSort('risk')}>
                  P(SLIP, 2Q){sortIcon('risk')}
                </th>
                <th className="py-3 px-5 font-semibold text-right">EXP. SLIP</th>
                <th className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right" onClick={() => handleSort('slip')}>
                  SLIP SO FAR{sortIcon('slip')}
                </th>
                <th className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right" onClick={() => handleSort('cost')}>
                  COST{sortIcon('cost')}
                </th>
                <th className="py-3 px-5 font-semibold text-right">PROGRESS</th>
                <th className="py-3 px-5 font-semibold">FLAGS</th>
              </tr>
            </thead>
            <tbody>
              {!page ? (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-fg-dimmed text-xs">loading...</td>
                </tr>
              ) : page.items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-fg-dimmed text-xs">
                    No projects match filter criteria.
                  </td>
                </tr>
              ) : (
                page.items.map((p) => {
                  const t = tierKey(p.tier)
                  return (
                    <tr
                      key={p.key}
                      onClick={() => onOpenDetail(p.key)}
                      className={cn(
                        'border-b transition-all h-14 cursor-pointer',
                        p.key === selectedKey
                          ? 'bg-accent/15 border-l-4 border-l-accent border-b-border-default shadow-sm'
                          : 'border-border-subtle/60 hover:bg-surface-elevated/50'
                      )}
                    >
                      {/* Project */}
                      <td className="py-3 px-5">
                        <div className="flex items-center gap-2">
                          <Badge tier={p.tier} className="w-[64px] shrink-0 text-[11px]" />
                          <span className="text-fg-base font-sans truncate max-w-[240px] text-sm font-semibold" title={p.name ?? undefined}>
                            {p.name ?? p.key}
                          </span>
                        </div>
                        <div className="text-[12px] font-sans text-fg-dimmed pl-[72px] mt-1 font-medium">
                          <span className="font-mono">{p.key}</span> · {p.sector ?? 'sector unknown'}
                          {p.override && <span className="text-warning"> · stagnation override</span>}
                        </div>
                      </td>

                      {/* Agency */}
                      <td className="py-3 px-5 font-sans text-fg-muted truncate max-w-[180px]">
                        <span className="text-[13px] font-semibold">{p.agency ?? '—'}</span>
                        <div className="text-[12px] font-medium text-fg-dimmed mt-1">{p.state ?? '—'}</div>
                      </td>

                      {/* P(any, 2q) */}
                      <td className="py-3 px-5 text-right">
                        {p.pAny2q === null ? (
                          <span className="text-[11px] text-fg-dimmed" title="no anticipated completion date — schedule not scored">
                            not scored
                          </span>
                        ) : (
                          <>
                            <MonoFigure size="base" sentiment={TIER_SENTIMENT[t]}>
                              {formatProb(p.pAny2q)}
                            </MonoFigure>
                            <div className="text-[11px] text-fg-dimmed mt-1" title="P(date push, 2q) · P(cost revision, 2q)">
                              date {orDash(p.pDatePush2q, formatProb)} · cost {orDash(p.pCostRev2q, formatProb)}
                            </div>
                          </>
                        )}
                      </td>

                      {/* Expected slip next 2q */}
                      <td className="py-3 px-5 text-right text-fg-base" title="predicted slip over the next 2 quarters, p50 (p95)">
                        {orDash(p.monthsP50, (v) => `${v.toFixed(0)}mo`)}
                        <span className="text-fg-dimmed text-[11px]"> {orDash(p.monthsP95, (v) => `(${v.toFixed(0)})`)}</span>
                      </td>

                      {/* Slip to date */}
                      <td className="py-3 px-5 text-right">
                        <span className={cn((p.slipToDateMonths ?? 0) > 12 ? 'text-critical font-semibold' : 'text-fg-base')}>
                          {orDash(p.slipToDateMonths, (v) => `${v.toFixed(0)}mo`)}
                        </span>
                        <div className="text-[11px] text-fg-dimmed mt-1">
                          {p.anticipatedCompletion ? `due ${formatDate(p.anticipatedCompletion)}` : 'no date'}
                        </div>
                      </td>

                      {/* Cost */}
                      <td className="py-3 px-5 text-right tabular-nums">
                        <span className="text-fg-base">{orDash(p.anticipatedCostCr, formatINR)}</span>
                        <div className="text-[11px] text-fg-dimmed mt-1">spent {orDash(p.expenditureCr, formatINR)}</div>
                      </td>

                      {/* Progress */}
                      <td className="py-3 px-5 text-right text-fg-muted">
                        {orDash(p.physicalProgressPct, (v) => formatPct(v, 0))}
                      </td>

                      {/* Flags */}
                      <td className="py-3 px-5">
                        <div className="flex flex-wrap gap-1 max-w-[160px]">
                          {p.flags.map((f) => (
                            <span
                              key={f}
                              className={cn(
                                'border px-1 py-0.5 text-[10px] uppercase tracking-wider',
                                f === 'early_notice' ? 'border-critical/40 text-critical' : 'border-warning/40 text-warning'
                              )}
                            >
                              {FLAG_LABEL[f]}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-default px-5 py-3 bg-surface-panel/50">
          <div className="font-sans text-[11px] text-fg-dimmed font-semibold tracking-wider">
            PAGE <span className="text-fg-base">{pageNo}</span> OF <span className="text-fg-base">{totalPages}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={pageNo <= 1}
              onClick={() => onChange({ page: pageNo - 1 })}
              className="px-3 py-1.5 bg-surface-input text-[11px] font-sans font-bold uppercase text-fg-base rounded border border-border-default disabled:opacity-30 disabled:cursor-not-allowed hover:not-disabled:bg-surface-elevated transition-colors shadow-sm"
            >
              Prev
            </button>
            <button
              disabled={pageNo >= totalPages}
              onClick={() => onChange({ page: pageNo + 1 })}
              className="px-3 py-1.5 bg-surface-input text-[11px] font-sans font-bold uppercase text-fg-base rounded border border-border-default disabled:opacity-30 disabled:cursor-not-allowed hover:not-disabled:bg-surface-elevated transition-colors shadow-sm"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}
