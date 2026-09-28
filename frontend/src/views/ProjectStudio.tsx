import { useParams, Link } from 'react-router-dom'
import { useForecast, useProject, useSignals, useTimeline } from '@/lib/queries'
import { isOffline } from '@/lib/api'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { ProjectIdentityStrip } from './project-studio/ProjectIdentityStrip'
import { PredictionPanel } from './project-studio/PredictionPanel'
import { TrajectoryChart } from './project-studio/TrajectoryChart'
import { RiskChecklist } from './project-studio/RiskChecklist'
import { ShapWaterfall } from './project-studio/ShapWaterfall'
import { AnaloguesTable } from './project-studio/AnaloguesTable'
import { ExternalEvents, LinkedSignals } from './project-studio/EvidencePanels'
import { BriefCard } from './project-studio/BriefCard'
import {
  ExternalChips, MoneyBar, ProgressTrend, ProjectChips, RiskGrid, RiskRingCard, TimelineStrip, TimeVsWork, VisualsSkeleton,
} from './project-studio/ProjectVisuals'
import { Page } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Button } from '@/components/ui/Button'
import { Badge, StalledBadge } from '@/components/ui/Badge'

/**
 * Project page (guide §5): one project from /api/projects/{key} and its timeline, forecast, signals and brief.
 * Without canSeeDrivers (the public) it is the simple page, built from the side panel's visual blocks
 * (project-studio/ProjectVisuals) over the redacted API: no drivers, intervals or model internals.
 */
export function ProjectStudio() {
  const { key = '' } = useParams<{ key: string }>()
  const { role } = useRole()
  const full = can(role, 'canSeeDrivers')
  const { data: detail, isLoading, error } = useProject(key)
  // the canonical key: an old or merged key resolves to the project it now belongs to
  const k = detail?.key ?? null
  const timeline = useTimeline(k)
  const forecast = useForecast(full ? k : null)
  const signals = useSignals(full ? k : null)

  if (isLoading && !full) {
    return <Page narrow><VisualsSkeleton /></Page>
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-[1440px] px-6 py-8">
        <div className="h-48 flex items-center justify-center text-xs text-fg-dimmed">
          fetching project telemetry...
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="mx-auto max-w-[1440px] px-6 py-8 text-center">
        {isOffline(error) ? (
          <ApiErrorNote error={error} />
        ) : (
          <div className="text-sm text-fg-muted mb-2">
            project <span className="text-critical">{key}</span> not found
          </div>
        )}
        <Link to="/command">
          <Button variant="secondary" size="sm">← Command Center</Button>
        </Link>
      </div>
    )
  }

  if (!full) {
    return (
      <Page narrow>
        <div className="space-y-2">
          <Link to="/command" className="text-xs text-fg-dimmed transition-colors hover:text-fg-muted">&larr; All projects</Link>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-fg-dimmed">{detail.key}</span>
            {detail.scores && <Badge tier={detail.scores.tier} />}
            {detail.scores?.stagnationOverride && <StalledBadge quarters={detail.scores.stagnationQuarters} />}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg-base">{detail.master?.projectName ?? detail.key}</h1>
          <ProjectChips detail={detail} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <RiskRingCard detail={detail} full={false} />
          <TimelineStrip detail={detail} />
          <TimeVsWork detail={detail} />
          <MoneyBar detail={detail} />
        </div>
        <ProgressTrend timeline={timeline.data} error={timeline.error} height={200} />
        <div className="grid items-start gap-4 lg:grid-cols-3">
          <RiskGrid detail={detail} plain className="lg:col-span-2" />
          <ExternalChips detail={detail} />
        </div>
      </Page>
    )
  }

  return (
    <Page>
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

        <div className="col-span-1 lg:col-span-3">
          <BriefCard key={detail.key} projectKey={detail.key} />
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

        <div className="col-span-1 lg:col-span-2">
          <ExternalEvents events={detail.external.events} asof={detail.provenance.asof} />
        </div>
        <div className="col-span-1">
          <ExternalChips detail={detail} />
        </div>
      </div>
    </Page>
  )
}
