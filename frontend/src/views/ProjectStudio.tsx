import { useParams, Link } from 'react-router-dom'
import { useProject } from '@/lib/queries'
import { isOffline } from '@/lib/api'
import { ProjectIdentityStrip } from './project-studio/ProjectIdentityStrip'
import { PredictionPanel } from './project-studio/PredictionPanel'
import { ShapWaterfall } from './project-studio/ShapWaterfall'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Button } from '@/components/ui/Button'

export function ProjectStudio() {
  const { key = '' } = useParams<{ key: string }>()
  const { data: detail, isLoading, error } = useProject(key)

  if (isLoading) {
    return (
      <div className="mx-auto max-w-[1600px] px-4 py-8">
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
          fetching project telemetry...
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="mx-auto max-w-[1600px] px-4 py-8 text-center">
        {isOffline(error) ? (
          <ApiErrorNote error={error} />
        ) : (
          <div className="font-mono text-sm text-fg-muted mb-2">
            project <span className="text-critical">{key}</span> not found
          </div>
        )}
        <Link to="/command">
          <Button variant="secondary" size="sm">← COMMAND CENTER</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <ProjectIdentityStrip detail={detail} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="col-span-1">
          <PredictionPanel detail={detail} />
        </div>
        <div className="col-span-1 lg:col-span-2">
          <ShapWaterfall drivers={detail.scores?.shapTop5 ?? []} />
        </div>
      </div>
    </div>
  )
}
