import { useParams, Link } from 'react-router-dom'
import { useForecast, useProject, useSignals, useTimeline } from '@/lib/queries'
import { isOffline } from '@/lib/api'
import { ProjectIdentityStrip } from './project-studio/ProjectIdentityStrip'
import { PredictionPanel } from './project-studio/PredictionPanel'
import { TrajectoryChart } from './project-studio/TrajectoryChart'
import { RiskChecklist } from './project-studio/RiskChecklist'
import { ShapWaterfall } from './project-studio/ShapWaterfall'
import { AnaloguesTable } from './project-studio/AnaloguesTable'
import { ExternalEvents, LinkedSignals } from './project-studio/EvidencePanels'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Button } from '@/components/ui/Button'

/** Project page (guide §5): one project from /api/projects/{key} and its timeline, forecast and signals. */
export function ProjectStudio() {
  const { key = '' } = useParams<{ key: string }>()
  const { data: detail, isLoading, error } = useProject(key)
  // the canonical key: an old or merged key resolves to the project it now belongs to
  const k = detail?.key ?? null
  const timeline = useTimeline(k)
  const forecast = useForecast(k)
  const signals = useSignals(k)

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
          <TrajectoryChart
            timeline={timeline.data}
            forecast={forecast.data}
            forecastError={forecast.error ?? timeline.error}
            asof={detail.provenance.asof}
          />
        </div>

        <div className="col-span-1 lg:col-span-2">
          <RiskChecklist rows={detail.riskProfile} />
        </div>
        <div className="col-span-1">
          <ShapWaterfall drivers={detail.scores?.shapTop5 ?? []} />
        </div>

        <div className="col-span-1 lg:col-span-2">
          <AnaloguesTable forecast={forecast.data} />
        </div>
        <div className="col-span-1">
          <LinkedSignals data={signals.data} error={signals.error} />
        </div>

        <div className="col-span-1 lg:col-span-3">
          <ExternalEvents events={detail.external.events} />
        </div>
      </div>
    </div>
  )
}
