import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { DataConfidenceBadge } from '@/components/common/DataConfidenceBadge'
import { formatRunwayDays } from '@/lib/formatters'
import type { Project } from '@/contracts/project'

interface ProjectIdentityStripProps {
  project: Project
}

export function ProjectIdentityStrip({ project }: ProjectIdentityStripProps) {
  const isCritical = project.actionableRunwayDays <= 30

  return (
    <div className="space-y-2">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 font-mono text-[10px] text-fg-dimmed">
        <Link to="/command" className="hover:text-fg-muted transition-colors">
          COMMAND
        </Link>
        <span>/</span>
        <span className="text-fg-muted">{project.code}</span>
      </div>

      {/* Identity bar — single horizontal strip */}
      <div className="border border-border-subtle bg-surface-panel">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between px-4 py-3">
          <div className="space-y-1">
            <div className="flex items-center gap-3 font-mono text-[11px]">
              <span className="text-fg-base font-medium">{project.code}</span>
              <Badge tier={project.riskTier} />
              <span className="text-fg-dimmed">{project.sector}</span>
            </div>

            <h1 className="text-base font-medium text-fg-base">
              {project.name}
            </h1>

            <div className="flex items-center gap-4 font-mono text-[10px] text-fg-dimmed">
              <span>{project.ministry}</span>
              <span className="text-border-strong">│</span>
              <span>{project.agency}</span>
              <span className="text-border-strong">│</span>
              <span>{project.state}</span>
            </div>

            <DataConfidenceBadge project={project} />
          </div>

          {/* Key metrics — inline, right-aligned */}
          <div className="flex items-center gap-6 mt-3 lg:mt-0 font-mono text-[11px]">
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-widest text-fg-dimmed">Risk</div>
              <MonoFigure
                size="lg"
                sentiment={
                  project.riskTier === 'CRITICAL' ? 'critical' :
                  project.riskTier === 'WARNING' ? 'warning' : 'stable'
                }
              >
                {project.compositeRiskScore}/100
              </MonoFigure>
            </div>
            <div className="w-px h-8 bg-border-subtle" />
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-widest text-fg-dimmed">Runway</div>
              <MonoFigure size="lg" sentiment={isCritical ? 'critical' : 'default'}>
                {formatRunwayDays(project.actionableRunwayDays)}
              </MonoFigure>
            </div>
          </div>
        </div>

        {/* Critical alert bar */}
        {isCritical && (
          <div className="border-t border-critical/30 bg-critical/5 px-4 py-1.5 font-mono text-[10px] text-critical">
            ADMINISTRATIVE BUFFER EXHAUSTED — intervention window closing. Initiate sandbox simulation.
          </div>
        )}
      </div>
    </div>
  )
}
