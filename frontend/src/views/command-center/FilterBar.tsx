import { useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Select } from '@/components/ui/Input'
import { hasFilters, usePortfolio, type ProjectQuery } from '@/lib/queries'
import { FLAG_LABEL, TIER_COLOR, TIER_LABEL, TIERS } from '@/lib/riskPalette'
import { cn } from '@/lib/formatters'
import type { Flag, TierFilter } from '@/contracts/project'

const TIER_ON: Record<TierFilter | 'ALL', string> = {
  ALL: 'bg-fg-base',
  Critical: 'bg-critical',
  High: 'bg-warning',
  Medium: 'bg-accent',
  Low: 'bg-stable',
  Watch: 'bg-watch',
}

const WATCH_TITLE = 'No completion date in the reports, so the delay risk is not ranked'

/**
 * The command centre's one set of filters, read by the risk map, the two portfolio visuals and the table: search,
 * the tier chips with their counts (also the map's legend), then sector, state, ministry (when the viewer sees more
 * than one) and flag. Selects wrap rather than shrink below 160 px; search comes first when the row wraps.
 */
export function FilterBar({ query, onChange }: { query: ProjectQuery; onChange: (patch: Partial<ProjectQuery>) => void }) {
  const { data: p } = usePortfolio()
  const [text, setText] = useState(query.q ?? '')

  // the box empties when something else clears the search (Clear filters, a chip)
  useEffect(() => { if (!query.q) setText('') }, [query.q])

  // debounce the search box into the query
  useEffect(() => {
    const t = setTimeout(() => {
      const q = text.trim() || undefined
      if (q !== query.q) onChange({ q })
    }, 300)
    return () => clearTimeout(t)
  }, [text, query.q, onChange])

  const names = (rows: Array<{ name: string | null }> | undefined) =>
    (rows ?? []).map((r) => r.name).filter((n): n is string => !!n).sort()
  const sectors = names(p?.bySector)
  const states = names(p?.byState)
  const ministries = names(p?.byMinistry)
  const count = (t: TierFilter) => p?.tiers.find((x) => x.tier === t)?.n
  const chips: Array<TierFilter | 'ALL'> = ['ALL', ...TIERS, 'Watch']

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-subtle bg-surface-panel px-3 py-2.5 shadow-card" role="search" aria-label="Filter projects">
      <label className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-border-default bg-surface-panel px-2.5 focus-within:ring-2 focus-within:ring-accent/30 lg:max-w-[280px]">
        <Search className="size-4 shrink-0 text-fg-dimmed" aria-hidden="true" />
        <span className="sr-only">Search projects</span>
        <input
          type="search"
          placeholder="Search a name or PRJ key"
          value={text}
          maxLength={100}
          onChange={(e) => setText(e.target.value)}
          className="w-full bg-transparent text-sm text-fg-base placeholder:text-fg-dimmed focus:outline-none"
        />
      </label>

      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Tier">
        {chips.map((t) => {
          const on = (query.tier ?? 'ALL') === t
          const n = t === 'ALL' ? p?.kpis.nProjects : count(t)
          return (
            <button
              key={t}
              type="button"
              aria-pressed={on}
              onClick={() => onChange({ tier: t === 'ALL' ? undefined : t })}
              title={t === 'Watch' ? WATCH_TITLE : undefined}
              className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                on ? `text-white shadow-sm ${TIER_ON[t]}` : 'text-fg-muted hover:bg-surface-elevated hover:text-fg-base'
              )}
            >
              {t !== 'ALL' && !on && <span className="size-2 rounded-full" style={{ background: TIER_COLOR[t] }} aria-hidden="true" />}
              {t === 'ALL' ? 'All' : TIER_LABEL[t]}
              {n !== undefined && <span className={cn('tabular-nums', on ? 'text-white/80' : 'text-fg-dimmed')}>{n.toLocaleString('en-IN')}</span>}
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2 xl:ml-auto [&>select]:min-w-[160px]">
        <Select aria-label="Sector" value={query.sector ?? ''} onChange={(e) => onChange({ sector: e.target.value || undefined })}>
          <option value="">All sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          {query.sector && !sectors.includes(query.sector) && <option value={query.sector}>{query.sector}</option>}
        </Select>
        <Select aria-label="State" value={query.state ?? ''} onChange={(e) => onChange({ state: e.target.value || undefined })}>
          <option value="">All states</option>
          {states.map((s) => <option key={s} value={s}>{s}</option>)}
          {query.state && !states.includes(query.state) && <option value={query.state}>{query.state}</option>}
        </Select>
        {ministries.length > 1 && (
          <Select aria-label="Ministry" value={query.ministry ?? ''} onChange={(e) => onChange({ ministry: e.target.value || undefined })}>
            <option value="">All ministries</option>
            {ministries.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        )}
        <Select
          aria-label="Flag"
          value={query.flag ?? ''}
          onChange={(e) => onChange({ flag: (e.target.value || undefined) as Flag | undefined })}
          title="A flagged outside issue; early notice: flagged while the reports show no slip yet"
        >
          <option value="">Any flag</option>
          {(Object.keys(FLAG_LABEL) as Flag[]).map((f) => <option key={f} value={f}>{FLAG_LABEL[f]}</option>)}
        </Select>
        {hasFilters(query) && (
          <button
            type="button"
            onClick={() => { setText(''); onChange({ q: undefined, tier: undefined, sector: undefined, state: undefined, ministry: undefined, flag: undefined }) }}
            className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs font-medium text-fg-muted hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <X className="size-3.5" aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>
    </div>
  )
}
