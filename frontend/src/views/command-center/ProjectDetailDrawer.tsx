import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { DualForecastPanel } from '@/views/project-studio/DualForecastPanel'
import { SCurveChart } from '@/views/project-studio/SCurveChart'

import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/formatters'
import type { Project } from '@/contracts/project'

interface ProjectDetailDrawerProps {
  project: Project | null
  isOpen: boolean
  onClose: () => void
}

export function ProjectDetailDrawer({ project, isOpen, onClose }: ProjectDetailDrawerProps) {
  // ESC key listener to dismiss drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  if (!isOpen || !project) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-fg-base/40 backdrop-blur-xs transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over Drawer Panel */}
      <aside
        data-lenis-prevent
        className="relative z-50 flex h-full w-full max-w-[85vw] flex-col border-l border-border-default bg-surface-base shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={`Project diagnostics for ${project.code}`}
      >
        {/* Drawer Header */}
        <div className="flex items-center justify-between border-b border-border-default bg-surface-panel px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-fg-base">
                {project.code}
              </span>
              <span
                className={cn(
                  'border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider',
                  project.riskTier === 'CRITICAL'
                    ? 'border-critical/30 bg-critical/10 text-critical'
                    : project.riskTier === 'WARNING'
                    ? 'border-warning/30 bg-warning/10 text-warning'
                    : 'border-stable/30 bg-stable/10 text-stable'
                )}
              >
                [{project.riskTier.slice(0, 4)}] {project.compositeRiskScore}/100
              </span>
              <span className="font-mono text-[10px] text-fg-dimmed">
                {project.sector} · {project.agency} · {project.state}
              </span>
            </div>
            <h2 className="mt-0.5 truncate font-sans text-xs text-fg-muted font-medium">
              {project.name}
            </h2>
          </div>

          <div className="ml-4 flex items-center gap-2">
            <Link to={`/projects/${project.id}`} onClick={onClose}>
              <Button variant="ghost" size="sm" className="font-mono text-[10px]">
                FULL STUDIO ↗
              </Button>
            </Link>
            <button
              onClick={onClose}
              className="rounded-xs border border-border-subtle p-1 font-mono text-xs text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base"
              aria-label="Close project drawer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Diagnostic Studio Body - Bento Grid */}
        <div className="flex-1 overflow-y-auto p-5 bg-surface-panel/30">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            
            {/* Top Left: Main Metric Chart (S-Curve) */}
            <div className="col-span-1 lg:col-span-2">
              <SCurveChart data={project.sCurve} />
            </div>

            {/* Top Right: Quick Metrics (Cost/Schedule/Disparity) */}
            <div className="col-span-1 flex flex-col h-full">
              <DualForecastPanel project={project} />
            </div>


          </div>
        </div>
      </aside>
    </div>
  )
}
