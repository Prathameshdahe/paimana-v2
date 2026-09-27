import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useProjects, type ProjectQuery } from '@/lib/queries'
import { KPIRibbon } from './command-center/KPIRibbon'
import { PortfolioUrgencyMatrix } from './command-center/PortfolioUrgencyMatrix'
import { TriageTable } from './command-center/TriageTable'
import { ProjectDetailDrawer } from './command-center/ProjectDetailDrawer'

const PAGE_SIZE = 25

export function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  // ?state= comes from the India map click-through; read once, then dropped from the URL
  const [query, setQuery] = useState<ProjectQuery>(() => ({
    sort: 'risk',
    order: 'desc',
    page: 1,
    size: PAGE_SIZE,
    state: searchParams.get('state') ?? undefined,
  }))
  const [drawerKey, setDrawerKey] = useState<string | null>(null)
  const projects = useProjects(query)

  useEffect(() => {
    if (searchParams.has('state')) {
      setSearchParams((prev) => { prev.delete('state'); return prev }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // any filter or sort change goes back to page 1; a page change keeps the rest
  const changeQuery = (patch: Partial<ProjectQuery>) =>
    setQuery((q) => ({ ...q, ...patch, page: patch.page ?? 1 }))

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      {/* Page header — pronounced, distinct from content */}
      <div className="flex items-end justify-between pt-4 pb-2">
        <div className="flex items-center gap-4">
          <h1 className="font-sans text-2xl font-black tracking-tight text-fg-base uppercase">
            Executive Command Center
          </h1>
        </div>
        <div className="font-mono text-[11px] text-fg-muted uppercase tracking-widest flex items-center gap-2">
          telemetry pipeline{' '}
          {projects.error ? (
            <span className="text-critical font-bold">unreachable</span>
          ) : (
            <span className="text-stable font-bold">operational</span>
          )}
        </div>
      </div>

      <div className="h-px bg-border-subtle" />

      <KPIRibbon />
      <PortfolioUrgencyMatrix
        page={projects.data}
        selectedKey={drawerKey}
        onOpenDetail={setDrawerKey}
      />
      <TriageTable
        query={query}
        onChange={changeQuery}
        page={projects.data}
        error={projects.error}
        isFetching={projects.isFetching}
        selectedKey={drawerKey}
        onOpenDetail={setDrawerKey}
      />
      <ProjectDetailDrawer projectKey={drawerKey} onClose={() => setDrawerKey(null)} />
    </div>
  )
}
