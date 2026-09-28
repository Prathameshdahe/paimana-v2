import { Card } from '@/components/ui/Card'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { usePortfolio, type PortfolioFilters } from '@/lib/queries'
import { fractionWord } from '@/lib/headline'
import { cn, formatINRShort } from '@/lib/formatters'
import type { GroupStat } from '@/contracts/portfolio'

const ROWS = 8

/** "Roads carries about half of the Critical projects here." — from the counts, in fraction words */
function sectorTakeaway(rows: GroupStat[]): string | null {
  const total = rows.reduce((s, r) => s + r.nCritical, 0)
  const top = [...rows].sort((a, b) => b.nCritical - a.nCritical)[0]
  if (!top || total === 0 || !top.name) return rows.length ? 'No project here is rated Critical.' : null
  const share = fractionWord(top.nCritical, total)
  return share === 'all'
    ? `All the Critical projects here are in ${top.name}.`
    : `${top.name} carries ${share} of the Critical projects here.`
}

/**
 * Where the risk sits, by sector: one bar per sector, Critical then High then the rest in grey, sorted by Critical and
 * High together; hover for the counts and capital, click to filter the page by that sector. Counts only; it reads the
 * page's state and ministry filters (a sector filter would leave one bar, so it is not applied here).
 */
export function SectorRisk({ filters, selected, onPick, ignored, className }: {
  filters: PortfolioFilters
  selected: string | undefined
  onPick: (sector: string | undefined) => void
  /** a search, tier or flag filter is on: the counts cannot follow it, and the card says so */
  ignored?: boolean
  className?: string
}) {
  const { data, error } = usePortfolio({ state: filters.state, ministry: filters.ministry })
  const rows = [...(data?.bySector ?? [])]
    .filter((r) => r.name)
    .sort((a, b) => b.nCritical + b.nHigh - (a.nCritical + a.nHigh) || b.n - a.n)
  const shown = rows.slice(0, ROWS)
  const max = Math.max(1, ...shown.map((r) => r.n))
  const takeaway = sectorTakeaway(rows)

  return (
    <Card title="Where the risk sits" className={className}>
      <div className="space-y-3 px-5 py-4">
        {error ? (
          <ApiErrorNote error={error} className="py-2" />
        ) : !data ? (
          <div className="space-y-2" aria-busy="true">
            {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-5 animate-pulse rounded bg-surface-input/70" />)}
          </div>
        ) : rows.length === 0 ? (
          <p className="py-4 text-center text-sm text-fg-muted">No project matches these filters.</p>
        ) : (
          <>
            {takeaway && <p className="text-base text-fg-base">{takeaway}</p>}
            <ul className="space-y-1.5">
              {shown.map((r) => {
                const rest = Math.max(0, r.n - r.nCritical - r.nHigh)
                const on = selected === r.name
                return (
                  <li key={r.name}>
                    <Tooltip content={
                      <div className="space-y-0.5">
                        <div className="font-semibold">{r.name}</div>
                        <div>{r.nCritical} Critical · {r.nHigh} High · {rest} other</div>
                        <div className="text-fg-muted">{r.n.toLocaleString('en-IN')} projects{r.capitalCr !== null && ` · ${formatINRShort(r.capitalCr)}`}</div>
                      </div>
                    }>
                      <button
                        type="button"
                        aria-pressed={on}
                        onClick={() => onPick(on ? undefined : (r.name ?? undefined))}
                        aria-label={`${r.name}: ${r.nCritical} Critical, ${r.nHigh} High of ${r.n} projects${on ? ', filtering the page' : ''}`}
                        className={cn(
                          'grid w-full grid-cols-[minmax(0,7.5rem)_1fr_3rem] items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                          on && 'bg-accent/10 ring-1 ring-inset ring-accent/30'
                        )}
                      >
                        <span className="truncate text-fg-base">{r.name}</span>
                        <span className="flex h-2.5 overflow-hidden rounded-full bg-surface-input" style={{ width: `${Math.max(4, (r.n / max) * 100)}%` }}>
                          <span className="h-full bg-critical" style={{ width: `${(r.nCritical / Math.max(r.n, 1)) * 100}%` }} />
                          <span className="h-full bg-warning" style={{ width: `${(r.nHigh / Math.max(r.n, 1)) * 100}%` }} />
                          <span className="h-full bg-fg-dimmed/35" style={{ width: `${(rest / Math.max(r.n, 1)) * 100}%` }} />
                        </span>
                        <span className="text-right tabular-nums text-fg-muted">{r.n.toLocaleString('en-IN')}</span>
                      </button>
                    </Tooltip>
                  </li>
                )
              })}
            </ul>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-dimmed">
              <span className="inline-flex items-center gap-1"><span className="size-2 rounded-full bg-critical" />Critical</span>
              <span className="inline-flex items-center gap-1"><span className="size-2 rounded-full bg-warning" />High</span>
              <span className="inline-flex items-center gap-1"><span className="size-2 rounded-full bg-fg-dimmed/35" />the rest</span>
              {rows.length > ROWS && <span>· the {ROWS} with the most Critical and High of {rows.length} sectors</span>}
            </div>
            {ignored && (
              <p className="text-xs text-fg-muted">The search, tier and flag filters above do not apply to these bars.</p>
            )}
          </>
        )}
      </div>
    </Card>
  )
}
