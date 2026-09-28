import { Card } from '@/components/ui/Card'
import { Tooltip } from '@/components/ui/Tooltip'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useExternalSummary } from '@/lib/queries'
import { EXTERNAL_FACTORS } from '@/lib/riskPalette'
import { cn, formatINRShort } from '@/lib/formatters'
import type { Flag } from '@/contracts/project'

/**
 * Where the delays come from: the six outside factors ranked by how many current projects have them on record, a
 * grey bar with the early-notice share (flagged while the reports show no slip yet) as a darker inner part; hover
 * for the counts and capital, click to filter the page by the factor's flag where it has one. Counts over every
 * project in view (gold/external_summary.json), not the page's other filters: with a filter on, the card says so.
 */
export function DelaySources({ selected, onPick, filtersActive, className }: {
  selected: Flag | undefined
  onPick: (flag: Flag | undefined) => void
  filtersActive?: boolean
  className?: string
}) {
  const { data, error } = useExternalSummary()
  const rows = EXTERNAL_FACTORS
    .map((f) => ({ ...f, x: data?.factors[f.key], notice: data?.earlyNotice.by_factor[f.key] ?? 0 }))
    .filter((r) => r.x)
    .sort((a, b) => (b.x?.n_flagged ?? 0) - (a.x?.n_flagged ?? 0))
  const max = Math.max(1, ...rows.map((r) => r.x?.n_flagged ?? 0))
  const top = rows[0]
  const takeaway = top?.x && top.x.n_flagged > 0
    ? `${top.label} is on record for ${top.x.n_flagged.toLocaleString('en-IN')} projects worth ${formatINRShort(top.x.capital_exposed_cr)}`
      + (top.notice > 0 ? `; ${top.notice.toLocaleString('en-IN')} of them show no slip in the reports yet.` : '.')
    : null

  return (
    <Card title="Where the delays come from" className={className}>
      <div className="space-y-3 px-5 py-4">
        {error ? (
          <ApiErrorNote error={error} className="py-2" />
        ) : !data ? (
          <div className="space-y-2" aria-busy="true">
            {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-5 animate-pulse rounded bg-surface-input/70" />)}
          </div>
        ) : rows.length === 0 ? (
          <p className="py-4 text-center text-sm text-fg-muted">No outside factor is in the summary: unknown, not clear.</p>
        ) : (
          <>
            {takeaway && <p className="text-base text-fg-base">{takeaway}</p>}
            <ul className="space-y-1.5">
              {rows.map(({ key, label, icon: Icon, flag, x, notice }) => {
                const n = x?.n_flagged ?? 0
                const on = !!flag && selected === flag
                const bar = (
                  <span className="relative flex h-2.5 overflow-hidden rounded-full bg-surface-input">
                    <span className="h-full rounded-full bg-fg-dimmed/40" style={{ width: `${(n / max) * 100}%` }} />
                    <span className="absolute inset-y-0 left-0 rounded-full bg-fg-muted" style={{ width: `${(notice / max) * 100}%` }} />
                  </span>
                )
                const inner = (
                  <>
                    <Icon className="size-3.5 text-fg-dimmed" aria-hidden="true" />
                    <span className="truncate text-fg-base">{label}</span>
                    {bar}
                    <span className="text-right tabular-nums text-fg-muted">{n.toLocaleString('en-IN')}</span>
                  </>
                )
                const cls = 'grid w-full grid-cols-[1rem_minmax(0,7.5rem)_1fr_3rem] items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs'
                return (
                  <li key={key}>
                    <Tooltip content={
                      <div className="space-y-0.5">
                        <div className="font-semibold">{label}</div>
                        <div>{n.toLocaleString('en-IN')} projects on record · {x && formatINRShort(x.capital_exposed_cr)}</div>
                        <div className="text-fg-muted">{notice.toLocaleString('en-IN')} with no slip in the reports yet (early notice)</div>
                        {!flag && <div className="text-fg-dimmed">No list filter for this factor</div>}
                      </div>
                    }>
                      {flag ? (
                        <button type="button" aria-pressed={on} onClick={() => onPick(on ? undefined : flag)}
                          aria-label={`${label}: ${n} projects, ${notice} early notice${on ? ', filtering the page' : ''}`}
                          className={cn(cls, 'transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40', on && 'bg-accent/10 ring-1 ring-inset ring-accent/30')}>
                          {inner}
                        </button>
                      ) : (
                        <span tabIndex={0} className={cn(cls, 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40')}
                          aria-label={`${label}: ${n} projects, ${notice} early notice`}>
                          {inner}
                        </span>
                      )}
                    </Tooltip>
                  </li>
                )
              })}
            </ul>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-dimmed">
              <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-full bg-fg-dimmed/40" />on record</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-full bg-fg-muted" />no slip in the reports yet</span>
            </div>
            {filtersActive && (
              <p className="text-xs text-fg-muted">Across every project in your view: the filters above do not apply here.</p>
            )}
          </>
        )}
      </div>
    </Card>
  )
}
