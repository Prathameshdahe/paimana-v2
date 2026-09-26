import { useState } from 'react'
import { useProjects } from '@/mocks'
import { KPIRibbon } from './command-center/KPIRibbon'
import { PortfolioUrgencyMatrix } from './command-center/PortfolioUrgencyMatrix'
import { TriageTable } from './command-center/TriageTable'
import { ProjectDetailDrawer } from './command-center/ProjectDetailDrawer'
import type { Project } from '@/contracts/project'

export function CommandCenter() {
  const { data: projects = [], isLoading } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [drawerProject, setDrawerProject] = useState<Project | null>(null)

  const handleSelectFromMatrix = (projectId: string) => {
    setSelectedProjectId(projectId)
  }

  const handleOpenDetail = (projectId: string) => {
    const project = projects.find((p) => p.id === projectId) ?? null
    setSelectedProjectId(projectId)
    setDrawerProject(project)
  }

  const handleCloseDrawer = () => {
    setDrawerProject(null)
  }

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
          telemetry pipeline <span className="text-stable font-bold">operational</span>
        </div>
      </div>

      <div className="h-px bg-border-subtle" />

      {isLoading ? (
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
          loading telemetry stream...
        </div>
      ) : (
        <>
          <KPIRibbon />
          <PortfolioUrgencyMatrix
            projects={projects}
            selectedProjectId={selectedProjectId}
            onSelectProject={handleSelectFromMatrix}
          />
          <TriageTable
            projects={projects}
            selectedProjectId={selectedProjectId}
            onSelectProject={setSelectedProjectId}
            onOpenDetail={handleOpenDetail}
          />
          <ProjectDetailDrawer
            project={drawerProject}
            isOpen={drawerProject !== null}
            onClose={handleCloseDrawer}
          />
        </>
      )}
    </div>
  )
}
