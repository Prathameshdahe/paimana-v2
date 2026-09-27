import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useProjects, type ProjectQuery } from '@/lib/queries'
import { FLAG_LABEL } from '@/lib/riskPalette'
import type { Flag } from '@/contracts/project'
import { Page, PageHeader } from '@/components/layout/Page'
import { KPIRibbon } from './command-center/KPIRibbon'
import { PortfolioUrgencyMatrix } from './command-center/PortfolioUrgencyMatrix'
import { TriageTable } from './command-center/TriageTable'
import { ProjectDetailDrawer } from './command-center/ProjectDetailDrawer'

const PAGE_SIZE = 25

export function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
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
  const [drawerKey, setDrawerKey] = useState<string | null>(null)
  const projects = useProjects(query)

  useEffect(() => {
    if (searchParams.has('state') || searchParams.has('flag')) {
      setSearchParams((prev) => { prev.delete('state'); prev.delete('flag'); return prev }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // any filter or sort change goes back to page 1; a page change keeps the rest
  const changeQuery = (patch: Partial<ProjectQuery>) =>
    setQuery((q) => ({ ...q, ...patch, page: patch.page ?? 1 }))

  return (
    <Page>
      <PageHeader
        title="Command Center"
        subtitle="Every open project, ranked by the chance it slips in the next two quarters"
        actions={
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className={projects.error ? 'size-2 rounded-full bg-critical' : 'size-2 rounded-full bg-stable'} />
            {projects.error ? 'data service unreachable' : 'data service up'}
          </span>
        }
      />

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
    </Page>
  )
}
