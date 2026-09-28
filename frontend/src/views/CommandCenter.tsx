import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  changesFilters, hasFilters, useMeta, usePortfolio, useProjectMap, useProjects, type ProjectQuery,
} from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { FLAG_LABEL } from '@/lib/riskPalette'
import { formatDate } from '@/lib/formatters'
import type { Flag } from '@/contracts/project'
import { Page, PageHeader } from '@/components/layout/Page'
import { WeekBrief } from './command-center/WeekBrief'
import { FilterBar } from './command-center/FilterBar'
import { RiskMap } from './command-center/RiskMap'
import { SectorRisk } from './command-center/SectorRisk'
import { DelaySources } from './command-center/DelaySources'
import { TriageTable, type TableRow } from './command-center/TriageTable'
import { useProjectPanel } from '@/lib/useProjectPanel'

const PAGE_SIZE = 25

/**
 * Command Center (/command): what needs attention this week in a few sentences, the portfolio in one line, then one
 * set of filters shared by the risk map (every project by due date and delay outlook), the two portfolio visuals
 * (where the risk sits by sector, where the delays come from) and the project list. Dots picked on the map list in
 * the table until cleared. No model number is shown: tiers, outlook words, report facts and counts.
 */
export function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { role } = useSession()
  const numbers = can(role, 'canSeeNumbers')
  // ?state= (India map) and ?flag= (External Factors) are read once, then dropped from the URL
  const [query, setQuery] = useState<ProjectQuery>(() => {
    const flag = searchParams.get('flag')
    return {
      sort: 'risk',
      order: 'desc',
      page: 1,
      size: PAGE_SIZE,
      state: searchParams.get('state') ?? undefined,
      flag: flag && Object.keys(FLAG_LABEL).includes(flag) ? (flag as Flag) : undefined,
    }
  })
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const panel = useProjectPanel()
  const projects = useProjects(query)
  const map = useProjectMap(query)
  const meta = useMeta()
  const portfolio = usePortfolio()
  const asof = meta.data?.asof ?? portfolio.data?.asof
  // the map's tier counts (collapsed lanes, the no-date strip) follow the sector, state and ministry filters; GET
  // /api/portfolio cannot follow a search or a flag, so with either the counts are unknown and the map gives no number
  const scoped = usePortfolio({ sector: query.sector, state: query.state, ministry: query.ministry })
  const tierCounts = query.q || query.flag ? undefined : scoped.data?.tiers

  useEffect(() => {
    if (searchParams.has('state') || searchParams.has('flag')) {
      setSearchParams((prev) => { prev.delete('state'); prev.delete('flag'); return prev }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // a filter change goes back to page 1 and clears the map's selection; a sort or page change, or a patch that changes
  // nothing (the chip already on), keeps the selection
  const changeQuery = useCallback((patch: Partial<ProjectQuery>) => {
    if (changesFilters(query, patch)) setSelected(new Set())
    setQuery((q) => ({ ...q, ...patch, page: patch.page ?? 1 }))
  }, [query])

  const clearSelection = useCallback(() => setSelected(new Set()), [])
  const onSelect = useCallback((keys: string[], add: boolean) => {
    setSelected((cur) => new Set(add ? [...cur, ...keys] : keys))
  }, [])
  const onToggle = useCallback((key: string) => {
    setSelected((cur) => {
      const next = new Set(cur)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  // Escape anywhere on the page clears the map's selection (the side panel handles its own Escape first)
  useEffect(() => {
    if (selected.size === 0) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !panel.key) setSelected(new Set()) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected.size, panel.key])

  const selectedRows = useMemo<TableRow[] | null>(() => {
    if (selected.size === 0) return null
    return (map.rows ?? []).filter((r) => selected.has(r.key))
  }, [selected, map.rows])

  const clearFilters = () => changeQuery({ q: undefined, tier: undefined, sector: undefined, state: undefined, ministry: undefined, flag: undefined })

  return (
    <Page>
      <PageHeader
        title="Command Center"
        actions={
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className={projects.error ? 'size-2 rounded-full bg-critical' : 'size-2 rounded-full bg-stable'} aria-hidden="true" />
            {asof && <>as of {formatDate(asof)} · </>}
            {projects.error ? 'the data service is not answering' : 'data up to date'}
          </span>
        }
      />

      <WeekBrief />

      <section className="space-y-4" aria-label="Portfolio">
        <FilterBar query={query} onChange={changeQuery} />
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
          <RiskMap
            className="xl:col-span-2"
            rows={map.rows}
            partial={map.partial}
            isLoading={map.isLoading}
            error={map.error}
            asof={asof}
            numbers={numbers}
            tierFilter={query.tier}
            tierCounts={tierCounts}
            openKey={panel.key}
            onOpen={panel.open}
            selection={selected}
            onSelect={onSelect}
            onToggle={onToggle}
            onClearSelection={clearSelection}
            onListNoDate={() => changeQuery({ tier: 'Watch' })}
            filtersActive={hasFilters(query)}
            onClearFilters={clearFilters}
          />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-1">
            <SectorRisk filters={query} selected={query.sector} onPick={(sector) => changeQuery({ sector })}
              ignored={!!(query.q || query.tier || query.flag)} />
            <DelaySources selected={query.flag} onPick={(flag) => changeQuery({ flag })} filtersActive={hasFilters(query)} />
          </div>
        </div>
      </section>

      <TriageTable
        query={query}
        onChange={changeQuery}
        page={projects.data}
        error={projects.error}
        isFetching={projects.isFetching}
        selectedKey={panel.key}
        onOpenDetail={panel.open}
        asof={asof}
        numbers={numbers}
        selection={selectedRows && { rows: selectedRows, clear: clearSelection }}
      />
    </Page>
  )
}
