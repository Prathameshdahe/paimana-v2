import { useEffect, useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Columns3, Search } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge, IconChip, StalledBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Input'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { usePortfolio, type ProjectQuery } from '@/lib/queries'
import { FLAG_ICON, FLAG_LABEL, TIER_COLOR, TIERS, tierKey } from '@/lib/riskPalette'
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

const TIER_BUTTONS: Array<TierFilter | 'ALL'> = ['ALL', ...TIERS, 'Watch']
const TIER_BUTTON_ON: Record<TierFilter | 'ALL', string> = {
  ALL: 'bg-fg-base',
  Critical: 'bg-critical',
  High: 'bg-warning',
  Medium: 'bg-accent',
  Low: 'bg-stable',
  Watch: 'bg-watch',
}

/** columns off by default; the viewer's choice is kept in this browser */
const EXTRA = { agency: 'Agency & state', expSlip: 'Expected slip', slip: 'Slip so far' } as const
type Extra = keyof typeof EXTRA
const COLS_KEY = 'paimana.triageColumns'

function readCols(): Extra[] {
  try {
    const v = JSON.parse(localStorage.getItem(COLS_KEY) ?? '[]') as unknown
    return Array.isArray(v) ? v.filter((c): c is Extra => c in EXTRA) : []
  } catch {
    return []
  }
}

/** a value bar with its figure: P(slip) coloured by tier, progress in accent */
function MiniBar({ pct, color, label }: { pct: number; color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden bg-surface-input">
        <div className="h-full" style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }} />
      </div>
      <span className="w-10 text-right font-mono text-sm tabular-nums text-fg-base">{label}</span>
    </div>
  )
}

/**
 * The project register over /api/projects. Server-paginated: filters, search and sort go to the
 * backend; the browser only ever holds one page. Six columns by default, three more on request.
 */
export function TriageTable({ query, onChange, page, error, isFetching, selectedKey, onOpenDetail }: TriageTableProps) {
  const { data: portfolio } = usePortfolio()
  const [text, setText] = useState(query.q ?? '')
  const [cols, setCols] = useState<Extra[]>(readCols)

  // debounce the search box into the query
  useEffect(() => {
    const t = setTimeout(() => {
      const q = text.trim() || undefined
      if (q !== query.q) onChange({ q })
    }, 300)
    return () => clearTimeout(t)
  }, [text, query.q, onChange])

  const toggleCol = (c: Extra) => {
    const next = cols.includes(c) ? cols.filter((x) => x !== c) : [...cols, c]
    setCols(next)
    try {
      localStorage.setItem(COLS_KEY, JSON.stringify(next))
    } catch {
      // storage disabled: the choice lasts this visit
    }
  }
  const show = (c: Extra) => cols.includes(c)
  const nCols = 6 + cols.length

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
  const th = 'py-2.5 px-4 text-xs font-medium text-fg-muted whitespace-nowrap'
  const sortable = 'cursor-pointer hover:text-fg-base'

  return (
    <Card
      title={<>Projects <span className="font-normal text-fg-dimmed">{total.toLocaleString()}</span></>}
      titleRight={
        <span className="flex items-center gap-3">
          {isFetching && <span className="text-fg-dimmed">loading…</span>}
          <Popover.Root>
            <Popover.Trigger asChild>
              <Button size="sm" variant="ghost">
                <Columns3 className="size-4" /> Columns{cols.length ? ` +${cols.length}` : ''}
              </Button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content align="end" sideOffset={6} className="z-50 w-52 rounded-xl border border-border-default bg-surface-panel p-2 shadow-pop">
                <div className="px-2 pb-1.5 pt-1 text-xs text-fg-dimmed">More columns</div>
                {(Object.keys(EXTRA) as Extra[]).map((c) => (
                  <label key={c} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-fg-base hover:bg-surface-elevated">
                    <input type="checkbox" checked={show(c)} onChange={() => toggleCol(c)} className="accent-[hsl(var(--color-accent))]" />
                    {EXTRA[c]}
                  </label>
                ))}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </span>
      }
    >
      {/* One filter row: search, tier chips, then dropdowns */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-5 py-3">
        <label className="flex h-8 min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-border-default bg-surface-panel px-2.5 shadow-sm focus-within:ring-2 focus-within:ring-accent/30 lg:max-w-[260px]">
          <Search className="size-4 shrink-0 text-fg-dimmed" />
          <input
            type="text"
            placeholder="Search name or PRJ key"
            value={text}
            maxLength={100}
            onChange={(e) => setText(e.target.value)}
            className="w-full bg-transparent text-sm text-fg-base placeholder:text-fg-dimmed focus:outline-none"
          />
        </label>

        <div className="flex flex-wrap items-center gap-1">
          {TIER_BUTTONS.map((t) => {
            const on = (query.tier ?? 'ALL') === t
            return (
              <button
                key={t}
                aria-pressed={on}
                onClick={() => onChange({ tier: t === 'ALL' ? undefined : t })}
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 px-3 text-xs font-medium transition-colors',
                  on ? `text-white shadow-sm ${TIER_BUTTON_ON[t]}` : 'text-fg-muted hover:bg-surface-elevated hover:text-fg-base'
                )}
                title={t === 'Watch' ? 'no anticipated completion date in the reports — schedule not scored; listed by flagged checklist rows, then P(cost revision), an order no backtest has checked' : undefined}
              >
                {t !== 'ALL' && !on && <span className="size-2 rounded-full" style={{ background: TIER_COLOR[t] }} />}
                {t === 'ALL' ? 'All' : t}
              </button>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 xl:ml-auto [&>select]:max-w-[160px]">
          <Select
            aria-label="flag"
            value={query.flag ?? ''}
            onChange={(e) => onChange({ flag: (e.target.value || undefined) as Flag | undefined })}
            title="a flagged external factor; early notice: flagged while the reports show no slip yet"
          >
            <option value="">Any flag</option>
            {(Object.keys(FLAG_LABEL) as Flag[]).map((f) => <option key={f} value={f}>{FLAG_LABEL[f]}</option>)}
          </Select>
          <Select aria-label="sector" value={query.sector ?? ''} onChange={(e) => onChange({ sector: e.target.value || undefined })}>
            <option value="">All sectors</option>
            {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select aria-label="state" value={query.state ?? ''} onChange={(e) => onChange({ state: e.target.value || undefined })}>
            <option value="">All states</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
            {query.state && !states.includes(query.state) && <option value={query.state}>{query.state}</option>}
          </Select>
        </div>
      </div>

      {error ? (
        <ApiErrorNote error={error} />
      ) : (
        <div className={cn('overflow-x-auto transition-opacity', isFetching && 'opacity-60')}>
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border-subtle bg-surface-elevated/60">
                <th className={cn(th, sortable, 'pl-5')} onClick={() => handleSort('name')}>Project{sortIcon('name')}</th>
                <th className={th}>Tier</th>
                <th className={cn(th, sortable)} onClick={() => handleSort('risk')} title="chance of a date push or cost revision within 2 quarters">
                  P(slip, 2q){sortIcon('risk')}
                </th>
                <th className={th}>Progress</th>
                <th className={cn(th, sortable, 'text-right')} onClick={() => handleSort('cost')}>Cost{sortIcon('cost')}</th>
                {show('agency') && <th className={th}>Agency</th>}
                {show('expSlip') && <th className={cn(th, 'text-right')} title="predicted slip over the next 2 quarters, p50 (p95)">Expected slip</th>}
                {show('slip') && (
                  <th className={cn(th, sortable, 'text-right')} onClick={() => handleSort('slip')}>Slip so far{sortIcon('slip')}</th>
                )}
                <th className={cn(th, 'pr-5')}>Flags</th>
              </tr>
            </thead>
            <tbody>
              {!page ? (
                <tr>
                  <td colSpan={nCols} className="py-8 text-center text-sm text-fg-dimmed">loading...</td>
                </tr>
              ) : page.items.length === 0 ? (
                <tr>
                  <td colSpan={nCols} className="py-8 text-center text-sm text-fg-dimmed">No projects match these filters.</td>
                </tr>
              ) : (
                page.items.map((p) => {
                  const t = tierKey(p.tier)
                  return (
                    <tr
                      key={p.key}
                      onClick={() => onOpenDetail(p.key)}
                      className={cn(
                        'cursor-pointer border-b border-border-subtle/70 transition-colors',
                        p.key === selectedKey ? 'bg-accent/10 shadow-[inset_3px_0_0_hsl(var(--color-accent))]' : 'hover:bg-surface-elevated/70'
                      )}
                    >
                      <td className="py-3 pl-5 pr-4">
                        <div className="max-w-[280px] truncate font-medium text-fg-base xl:max-w-[440px]" title={p.name ?? undefined}>
                          {p.name ?? p.key}
                        </div>
                        <div className="mt-0.5 max-w-[280px] truncate text-xs text-fg-dimmed xl:max-w-[440px]">
                          {p.key} · {p.sector ?? 'sector unknown'}
                        </div>
                      </td>

                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1"><Badge tier={p.tier} />{p.override && <StalledBadge />}</div>
                      </td>

                      <td className="px-4 py-3">
                        {p.pAny2q === null ? (
                          <span className="text-xs text-fg-dimmed" title="no anticipated completion date — schedule not scored">not scored</span>
                        ) : (
                          <Tooltip content={`date push ${orDash(p.pDatePush2q, formatProb)} · cost revision ${orDash(p.pCostRev2q, formatProb)}`}>
                            <div><MiniBar pct={p.pAny2q * 100} color={TIER_COLOR[t]} label={formatProb(p.pAny2q)} /></div>
                          </Tooltip>
                        )}
                      </td>

                      <td className="px-4 py-3">
                        {p.physicalProgressPct === null ? (
                          <span className="text-xs text-fg-dimmed">—</span>
                        ) : (
                          <MiniBar pct={p.physicalProgressPct} color="hsl(var(--color-accent))" label={formatPct(p.physicalProgressPct, 0)} />
                        )}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <div className="font-mono tabular-nums text-fg-base">{orDash(p.anticipatedCostCr, formatINR)}</div>
                        <div className="mt-0.5 text-xs text-fg-dimmed">spent {orDash(p.expenditureCr, formatINR)}</div>
                      </td>

                      {show('agency') && (
                        <td className="max-w-[200px] px-4 py-3">
                          <div className="truncate text-fg-muted">{p.agency ?? '—'}</div>
                          <div className="mt-0.5 truncate text-xs text-fg-dimmed">{p.state ?? '—'}</div>
                        </td>
                      )}
                      {show('expSlip') && (
                        <td className="whitespace-nowrap px-4 py-3 text-right font-mono tabular-nums text-fg-base">
                          {orDash(p.monthsP50, (v) => `${v.toFixed(0)}mo`)}
                          {p.monthsP95 !== null && <span className="text-xs text-fg-dimmed"> ({p.monthsP95.toFixed(0)})</span>}
                        </td>
                      )}
                      {show('slip') && (
                        <td className="whitespace-nowrap px-4 py-3 text-right">
                          <span className={cn('font-mono tabular-nums', (p.slipToDateMonths ?? 0) > 12 ? 'font-semibold text-critical' : 'text-fg-base')}>
                            {orDash(p.slipToDateMonths, (v) => `${v.toFixed(0)}mo`)}
                          </span>
                          <div className="mt-0.5 text-xs text-fg-dimmed">
                            {p.anticipatedCompletion ? `due ${formatDate(p.anticipatedCompletion)}` : 'no date'}
                          </div>
                        </td>
                      )}

                      <td className="py-3 pl-4 pr-5">
                        <div className="flex gap-1">
                          {p.flags.map((f) => (
                            <Tooltip key={f} content={f === 'early_notice' ? 'Early notice: flagged external factor, no slip in the numbers yet' : FLAG_LABEL[f]}>
                              <span>
                                <IconChip icon={FLAG_ICON[f]} size="sm" variant={f === 'early_notice' ? 'critical' : 'warning'} aria-label={FLAG_LABEL[f]} />
                              </span>
                            </Tooltip>
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

      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-3">
          <div className="text-xs text-fg-dimmed">
            Page <span className="font-medium text-fg-base">{pageNo}</span> of <span className="font-medium text-fg-base">{totalPages}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={pageNo <= 1} onClick={() => onChange({ page: pageNo - 1 })}>Prev</Button>
            <Button size="sm" disabled={pageNo >= totalPages} onClick={() => onChange({ page: pageNo + 1 })}>Next</Button>
          </div>
        </div>
      )}
    </Card>
  )
}
