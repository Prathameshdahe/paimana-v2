import { useState, type ReactNode } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { ArrowDown, ArrowUp, Columns3, X } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Badge, IconChip, StalledBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import type { ProjectQuery } from '@/lib/queries'
import { FLAG_ICON, FLAG_LABEL, tierKey } from '@/lib/riskPalette'
import { TONE_DOT, outlookOf, toneOf } from '@/lib/outlook'
import { dueIn } from '@/lib/headline'
import { cn, formatDate, formatINR, formatPct, orDash } from '@/lib/formatters'
import type { Flag, MapRow, ProjectPage, ProjectRow, ProjectSort } from '@/contracts/project'

/** a list row or a map row (the map's selection lists map rows): the extra columns may be missing */
export type TableRow = MapRow & Partial<Pick<ProjectRow, 'agency' | 'expenditureCr' | 'slipToDateMonths' | 'pDatePush2q' | 'pCostRev2q' | 'monthsP50'>>

interface TriageTableProps {
  query: ProjectQuery
  onChange: (patch: Partial<ProjectQuery>) => void
  page: ProjectPage | undefined
  error: unknown
  isFetching: boolean
  /** the open side panel's project */
  selectedKey?: string | null
  onOpenDetail: (key: string) => void
  asof: string | undefined
  numbers: boolean
  /** projects picked on the risk map: listed instead of the page, client-side */
  selection: { rows: TableRow[]; clear: () => void } | null
}

/** columns off by default (Top reason is on from 1280 px); the viewer's choice is kept in this browser */
const EXTRA = { reason: 'Top reason', agency: 'Agency & state', slip: 'Slip so far' } as const
type Extra = keyof typeof EXTRA
const COLS_KEY = 'paimana.triageColumns'

function readCols(): Extra[] {
  try {
    const v = JSON.parse(localStorage.getItem(COLS_KEY) ?? '[]') as unknown
    return Array.isArray(v) ? v.filter((c): c is Extra => typeof c === 'string' && c in EXTRA) : []
  } catch {
    return []
  }
}

/** the plainest reason when the backend sends none: the first flagged outside issue */
const FLAG_REASON: Record<Flag, string> = {
  land: 'Land acquisition flagged',
  forest: 'Forest clearance flagged',
  litigation: 'A court case flagged',
  contractor: 'Contractor stress flagged',
  early_notice: 'An outside issue, no slip yet',
}

function reasonOf(r: TableRow): string | null {
  return r.topReason ?? (r.flags[0] ? FLAG_REASON[r.flags[0]] : null)
}

const WATCH_NOTE = 'No completion date in the reports, so the delay risk is not ranked'

const TH = 'sticky top-0 z-[1] bg-surface-elevated py-2.5 px-4 text-xs font-medium text-fg-muted whitespace-nowrap'

/** a sortable header: a real button, aria-sort on the cell; off while the map's selection is listed */
function SortTh({ by, query, disabled, onSort, className, children }: {
  by: ProjectSort
  query: ProjectQuery
  disabled: boolean
  onSort: (by: ProjectSort) => void
  className?: string
  children: ReactNode
}) {
  const on = !disabled && query.sort === by
  const Arrow = query.order === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={cn(TH, className)} aria-sort={on ? (query.order === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" disabled={disabled} onClick={() => onSort(by)}
        className="inline-flex items-center gap-1 rounded hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-default disabled:hover:text-fg-muted">
        {children}
        {on && <Arrow className="size-3" aria-hidden="true" />}
      </button>
    </th>
  )
}

/** progress as a thin bar with its figure (a report fact) */
function MiniBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-input">
        <div className="h-full rounded-full bg-fg-muted" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      <span className="w-9 text-right font-mono text-sm tabular-nums text-fg-base">{formatPct(pct, 0)}</span>
    </div>
  )
}

function OutlookCell({ row, numbers }: { row: TableRow; numbers: boolean }) {
  if (tierKey(row.tier) === 'Watch') return <span className="text-xs text-fg-dimmed" title={WATCH_NOTE}>not ranked</span>
  const o = outlookOf(row, numbers)
  if (!o || (!o.delay && !o.cost)) {
    return <span className="text-xs text-fg-dimmed" title="The outlook in words is not available for this project yet">—</span>
  }
  return (
    <div className="space-y-0.5 text-xs">
      {([['Delay', o.delay], ['Cost rise', o.cost]] as const).map(([noun, w]) => w && (
        <div key={noun} className="flex items-center gap-1.5 whitespace-nowrap text-fg-base">
          <span className={cn('size-1.5 shrink-0 rounded-full', TONE_DOT[toneOf(w)])} aria-hidden="true" />
          {noun} {w}
        </div>
      ))}
    </div>
  )
}

/**
 * The project list over /api/projects (server-paged: filters, search and sort go to the backend; the browser holds
 * one page), or the projects picked on the risk map. Project, tier, the outlook in words, progress, when it is due,
 * cost and the top reason; agency and slip so far on request. The server orders "risk" by its own rank: an order is
 * shown where a number is not, and the outlook and top reason say why one row sits above another. Rows take focus;
 * Enter opens the side panel.
 */
export function TriageTable({ query, onChange, page, error, isFetching, selectedKey, onOpenDetail, asof, numbers, selection }: TriageTableProps) {
  const [cols, setCols] = useState<Extra[]>(readCols)

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

  const rows: TableRow[] | undefined = selection ? selection.rows : page?.items
  const total = selection ? selection.rows.length : (page?.total ?? 0)
  const size = query.size ?? 25
  const pageNo = query.page ?? 1
  const totalPages = Math.max(1, Math.ceil((page?.total ?? 0) / size))

  const handleSort = (sort: ProjectSort) => {
    if (query.sort === sort) onChange({ order: query.order === 'asc' ? 'desc' : 'asc' })
    else onChange({ sort, order: sort === 'name' ? 'asc' : 'desc' })
  }
  const th = TH
  const reasonCls = show('reason') ? '' : 'hidden xl:table-cell'
  const nCols = 7 + (show('agency') ? 1 : 0) + (show('slip') ? 1 : 0)

  const sortProps = { query, disabled: !!selection, onSort: handleSort }

  return (
    <Card
      id="project-list"
      tabIndex={-1}
      className="scroll-mt-20 focus:outline-none"
      title={<>Projects <span className="font-normal text-fg-dimmed">{total.toLocaleString('en-IN')}</span></>}
      titleRight={
        <span className="flex items-center gap-3">
          {selection && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 py-0.5 pl-2.5 pr-1 text-xs font-medium text-fg-base ring-1 ring-inset ring-accent/25">
              {selection.rows.length.toLocaleString('en-IN')} selected on the map
              <button type="button" onClick={selection.clear} aria-label="Clear the map selection"
                className="inline-flex size-5 items-center justify-center rounded-full hover:bg-accent/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                <X className="size-3" aria-hidden="true" />
              </button>
            </span>
          )}
          {isFetching && !selection && <span className="text-fg-dimmed">Updating…</span>}
          <Popover.Root>
            <Popover.Trigger asChild>
              <Button size="sm" variant="ghost">
                <Columns3 className="size-4" aria-hidden="true" /> Columns{cols.length ? ` +${cols.length}` : ''}
              </Button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content align="end" sideOffset={6} className="z-50 w-52 rounded-xl border border-border-default bg-surface-panel p-2 shadow-pop">
                <div className="px-2 pb-1.5 pt-1 text-xs text-fg-dimmed">More columns</div>
                {(Object.keys(EXTRA) as Extra[]).map((c) => (
                  <label key={c} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-fg-base hover:bg-surface-elevated">
                    <input type="checkbox" checked={show(c)} onChange={() => toggleCol(c)} className="accent-[hsl(var(--color-accent))]" />
                    {EXTRA[c]}
                    {c === 'reason' && <span className="ml-auto text-xs text-fg-dimmed">wide screens</span>}
                  </label>
                ))}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </span>
      }
    >
      {error && !selection ? (
        <ApiErrorNote error={error} />
      ) : (
        <div className={cn('max-h-[720px] overflow-auto transition-opacity', isFetching && !selection && 'opacity-60')} data-lenis-prevent>
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border-subtle">
                <SortTh {...sortProps} by="name" className="pl-5">Project</SortTh>
                <SortTh {...sortProps} by="risk">Tier</SortTh>
                <th className={th}>Outlook</th>
                <SortTh {...sortProps} by="progress">Progress</SortTh>
                <th className={th}>Due</th>
                <SortTh {...sortProps} by="cost" className="text-right">Cost</SortTh>
                <th className={cn(th, reasonCls)}>Top reason</th>
                {show('agency') && <th className={th}>Agency</th>}
                {show('slip') && <SortTh {...sortProps} by="slip" className="text-right">Slip so far</SortTh>}
                <th className={cn(th, 'pr-5')}>Flags</th>
              </tr>
            </thead>
            <tbody>
              {!rows ? (
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i} className="border-b border-border-subtle/70">
                    <td colSpan={nCols} className="px-5 py-3"><div className="h-8 animate-pulse rounded bg-surface-input/60" /></td>
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={nCols} className="py-10 text-center text-sm text-fg-muted">
                    {selection ? 'Nothing is selected on the map.' : 'No project matches these filters. Clear a filter to see more.'}
                  </td>
                </tr>
              ) : (
                rows.map((p) => {
                  const due = dueIn(p.anticipatedCompletion, asof)
                  const reason = reasonOf(p)
                  return (
                    <tr
                      key={p.key}
                      tabIndex={0}
                      onClick={() => onOpenDetail(p.key)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onOpenDetail(p.key) } }}
                      aria-label={`${p.name ?? p.key}, ${p.tier ?? 'not scored'}`}
                      className={cn(
                        'cursor-pointer border-b border-border-subtle/70 align-top transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40',
                        p.key === selectedKey ? 'bg-accent/10 shadow-[inset_3px_0_0_hsl(var(--color-accent))]' : 'hover:bg-surface-elevated'
                      )}
                    >
                      <td className="py-3 pl-5 pr-4">
                        <div className="max-w-[280px] truncate font-medium text-fg-base xl:max-w-[380px]" title={p.name ?? undefined}>
                          {p.name ?? p.key}
                        </div>
                        <div className="mt-0.5 max-w-[280px] truncate text-xs text-fg-dimmed xl:max-w-[380px]">
                          {[p.key, p.sector, p.state].filter(Boolean).join(' · ')}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1"><Badge tier={p.tier} />{p.override && <StalledBadge />}</div>
                      </td>
                      <td className="px-4 py-3"><OutlookCell row={p} numbers={numbers} /></td>
                      <td className="px-4 py-3">
                        {p.physicalProgressPct === null ? <span className="text-xs text-fg-dimmed">not reported</span> : <MiniBar pct={p.physicalProgressPct} />}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {p.anticipatedCompletion ? (
                          <>
                            <div className="text-fg-base">{formatDate(p.anticipatedCompletion)}</div>
                            {due && <div className={cn('mt-0.5 text-xs', due.overdue ? 'font-medium text-critical' : 'text-fg-dimmed')}>{due.short}</div>}
                          </>
                        ) : (
                          <span className="text-xs text-fg-dimmed" title={WATCH_NOTE}>no date</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <div className="font-mono tabular-nums text-fg-base">{orDash(p.anticipatedCostCr, formatINR)}</div>
                        {p.expenditureCr !== undefined && <div className="mt-0.5 text-xs text-fg-dimmed">spent {orDash(p.expenditureCr, formatINR)}</div>}
                      </td>
                      <td className={cn('max-w-[220px] px-4 py-3 text-xs text-fg-muted', reasonCls)}>
                        <span className="line-clamp-2" title={reason ?? undefined}>{reason ?? <span className="text-fg-dimmed">none on record</span>}</span>
                      </td>
                      {show('agency') && (
                        <td className="max-w-[200px] px-4 py-3">
                          <div className="truncate text-fg-muted">{p.agency ?? '—'}</div>
                          <div className="mt-0.5 truncate text-xs text-fg-dimmed">{p.state ?? '—'}</div>
                        </td>
                      )}
                      {show('slip') && (
                        <td className="whitespace-nowrap px-4 py-3 text-right">
                          <span className={cn('font-mono tabular-nums', (p.slipToDateMonths ?? 0) > 12 ? 'font-semibold text-critical' : 'text-fg-base')}>
                            {orDash(p.slipToDateMonths, (v) => `${v.toFixed(0)} mo`)}
                          </span>
                        </td>
                      )}
                      <td className="py-3 pl-4 pr-5">
                        <div className="flex gap-1">
                          {p.flags.map((f) => (
                            <Tooltip key={f} content={f === 'early_notice' ? 'Early notice: an outside issue on record, no slip in the numbers yet' : FLAG_LABEL[f]}>
                              <span tabIndex={-1}>
                                <IconChip icon={FLAG_ICON[f]} size="sm" variant={f === 'early_notice' ? 'critical' : 'warning'} aria-label={FLAG_LABEL[f]} role="img" />
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

      {!selection && totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-subtle px-5 py-3">
          <div className="text-xs text-fg-dimmed">
            Page <span className="font-medium text-fg-base">{pageNo}</span> of <span className="font-medium text-fg-base">{totalPages}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={pageNo <= 1} onClick={() => onChange({ page: pageNo - 1 })}>Previous</Button>
            <Button size="sm" disabled={pageNo >= totalPages} onClick={() => onChange({ page: pageNo + 1 })}>Next</Button>
          </div>
        </div>
      )}
    </Card>
  )
}
