import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Select } from '@/components/ui/Input'
import { hasFilters, tierAfterClick, usePortfolio, type ProjectQuery } from '@/lib/queries'
import { FLAG_LABEL, TIER_COLOR, TIER_LABEL, TIERS } from '@/lib/riskPalette'
import { cn } from '@/lib/formatters'
import type { Flag, TierFilter } from '@/contracts/project'

const TIER_ON: Record<TierFilter | 'ALL', string> = {
  ALL: 'bg-fg-base',
  Critical: 'bg-critical',
  High: 'bg-warning',
  Medium: 'bg-fg-muted',
  Low: 'bg-stable',
  Watch: 'bg-watch',
}

const WATCH_TITLE = 'No completion date in the reports, so the delay risk is not ranked'

type Chip = TierFilter | 'ALL'

/**
 * The command centre's one set of filters, read by the risk map, the two portfolio visuals and the table: search,
 * the tier chips with their counts (also the map's legend; one choice at a time, a radio group: arrows move and pick,
 * clicking the chip already on goes back to All), then sector, state, ministry (when the viewer sees more than one)
 * and flag. Selects wrap rather than shrink below 160 px; search comes first when the row wraps.
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
  const chips: Chip[] = ['ALL', ...TIERS, 'Watch']
  const chipRefs = useRef<Array<HTMLButtonElement | null>>([])
  const current: Chip = query.tier ?? 'ALL'
  const pick = (i: number) => {
    const t = chips[(i + chips.length) % chips.length] as Chip
    chipRefs.current[chips.indexOf(t)]?.focus()
    if (t !== current) onChange({ tier: t === 'ALL' ? undefined : t })
  }
  const onChipKey = (e: React.KeyboardEvent, i: number) => {
    const to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? i + 1
      : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? i - 1
      : e.key === 'Home' ? 0 : e.key === 'End' ? chips.length - 1 : null
    if (to === null) return
    e.preventDefault()
    pick(to)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-subtle bg-surface-panel px-3 py-2.5 shadow-card" role="search" aria-label="Filter projects">
      <label className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-border-default bg-surface-panel px-2.5 focus-within:ring-2 focus-within:ring-accent lg:max-w-[280px]">
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

      <div className="flex flex-wrap items-center gap-1" role="radiogroup" aria-label="Tier">
        {chips.map((t, i) => {
          const on = current === t
          const n = t === 'ALL' ? p?.kpis.nProjects : count(t)
          return (
            <button
              key={t}
              ref={(el) => { chipRefs.current[i] = el }}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange({ tier: tierAfterClick(query.tier, t) })}
              onKeyDown={(e) => onChipKey(e, i)}
              title={t === 'Watch' ? WATCH_TITLE : undefined}
              className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                on ? `text-white shadow-sm ${TIER_ON[t]}` : 'text-fg-muted hover:bg-surface-elevated hover:text-fg-base'
              )}
            >
              {t !== 'ALL' && !on && <span className="size-2 rounded-full" style={{ background: TIER_COLOR[t] }} aria-hidden="true" />}
              {t === 'ALL' ? 'All' : TIER_LABEL[t]}
              {n !== undefined && <span className={cn('tabular-nums', on ? 'text-white' : 'text-fg-dimmed')}>{n.toLocaleString('en-IN')}</span>}
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
            className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs font-medium text-fg-muted hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <X className="size-3.5" aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>
    </div>
  )
}
