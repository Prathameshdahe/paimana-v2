import { useParams, Link } from 'react-router-dom'
import { useProject } from '@/mocks'
import { ProjectIdentityStrip } from './project-studio/ProjectIdentityStrip'
import { DualForecastPanel } from './project-studio/DualForecastPanel'
import { SCurveChart } from './project-studio/SCurveChart'
import { ShapWaterfall } from './project-studio/ShapWaterfall'
import { SandboxCTA } from './project-studio/SandboxCTA'
import { Button } from '@/components/ui/Button'

export function ProjectStudio() {
  const { id = '' } = useParams<{ id: string }>()
  const { data: project, isLoading, isError } = useProject(id)

  if (isLoading) {
    return (
      <div className="mx-auto max-w-[1600px] px-4 py-8">
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
          fetching project telemetry...
        </div>
      </div>
    )
  }

  if (isError || !project) {
    return (
      <div className="mx-auto max-w-[1600px] px-4 py-8 text-center">
        <div className="font-mono text-sm text-fg-muted mb-2">
          project <span className="text-critical">{id}</span> not found
        </div>
        <Link to="/command">
          <Button variant="secondary" size="sm">← COMMAND CENTER</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <ProjectIdentityStrip project={project} />
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Top Left: Main Metric Chart (S-Curve) */}
        <div className="col-span-1 lg:col-span-2">
          <SCurveChart data={project.sCurve} />
        </div>

        {/* Top Right: Quick Metrics (Cost/Schedule/Disparity) */}
        <div className="col-span-1 flex flex-col h-full">
          <DualForecastPanel project={project} />
        </div>

        {/* Bottom Section: Waterfall List + Sandbox */}
        <div className="col-span-1 lg:col-span-3 h-full">
          <ShapWaterfall
            drivers={project.shapDrivers}
            delayRemarks={project.delayRemarks}
            topBottleneck={project.topBottleneck}
            sandboxAction={
              <SandboxCTA projectId={project.id} projectName={project.name} />
            }
          />
        </div>
      </div>
    </div>
  )
}
