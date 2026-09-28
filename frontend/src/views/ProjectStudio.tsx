import { useParams, useSearchParams, Link } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import { useForecast, useProject, useSignals, useTimeline } from '@/lib/queries'
import { isOffline } from '@/lib/api'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { detailHeadline } from '@/lib/headline'
import { TIER_PLAIN, driversOf, outlookOf } from '@/lib/outlook'
import { tierKey } from '@/lib/riskPalette'
import { ProjectIdentityStrip, ProvenanceLine } from './project-studio/ProjectIdentityStrip'
import { PredictionPanel } from './project-studio/PredictionPanel'
import { TrajectoryChart } from './project-studio/TrajectoryChart'
import { RiskChecklist } from './project-studio/RiskChecklist'
import { ShapWaterfall } from './project-studio/ShapWaterfall'
import { AnaloguesTable } from './project-studio/AnaloguesTable'
import { AnaloguesLine } from './project-studio/AnaloguesLine'
import { ExternalEvents, LinkedSignals } from './project-studio/EvidencePanels'
import { BriefCard } from './project-studio/BriefCard'
import { ResearchNews } from './project-studio/ResearchNews'
import { SecondOpinionCard } from './project-studio/SecondOpinionCard'
import { OutlookTiles, TierRing } from './project-studio/Outlook'
import { WhyBlock } from './project-studio/WhyBlock'
import { ExternalChips, GaugeRow, MoneyBar, ProgressTrend, TimelineStrip, TimeVsWork } from './project-studio/ProjectVisuals'
import { Page } from '@/components/layout/Page'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Button } from '@/components/ui/Button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import type { Forecast, ProjectDetail, ProjectSignals, Timeline } from '@/contracts/project'

interface Loaded {
  detail: ProjectDetail
  timeline: { data: Timeline | undefined; error: unknown }
  forecast: { data: Forecast | undefined; error: unknown }
  signals: { data: ProjectSignals | undefined; error: unknown } | null
}

/** what the page says to everyone: the sentence, tier and outlook, why, the AI's reading, the facts and the outside */
function Briefing({ detail, timeline, forecast, signals, insights, opinion, numbers }: Loaded & {
  /** officials: the forecast, the AI brief, linked news */
  insights: boolean
  opinion: boolean
  /** the developer: words may come from the numbers, and the brief's footer counts the figures checked */
  numbers: boolean
}) {
  const s = detail.scores
  const tier = s?.tier ?? null
  const outlook = outlookOf(s, numbers)
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <section className="space-y-5 rounded-xl border border-border-subtle bg-surface-panel p-6 shadow-card animate-card-in" aria-label="Where it stands">
            <p className="text-lg leading-relaxed text-fg-base">{detailHeadline(detail, numbers)}</p>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
              <TierRing tier={tier} />
              <div className="min-w-[14rem] flex-1 space-y-3">
                <p className="text-sm leading-relaxed text-fg-muted">
                  {s ? TIER_PLAIN[tierKey(tier)] : `Not in the current scored portfolio${detail.master?.lastStatus ? `; last status: ${detail.master.lastStatus}` : ''}.`}
                </p>
              </div>
            </div>
            <OutlookTiles outlook={outlook} tier={tier} />
          </section>
          <WhyBlock drivers={driversOf(s, numbers)} checks={detail.riskProfile} />
        </div>
        <div className="space-y-4">
          {insights ? (
            <>
              <BriefCard key={detail.key} projectKey={detail.key} numbers={numbers} />
              {opinion && <SecondOpinionCard key={`o-${detail.key}`} projectKey={detail.key} variant="page" tier={tier} numbers={numbers} />}
            </>
          ) : (
            <ExternalChips detail={detail} research={detail.research} />
          )}
        </div>
      </div>

      <section className="space-y-4" aria-labelledby="facts-h">
        <h2 id="facts-h" className="text-base font-semibold text-fg-base">What the reports show</h2>
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
          <TimeVsWork detail={detail} />
          <MoneyBar detail={detail} />
          <TimelineStrip detail={detail} />
        </div>
        <ProgressTrend timeline={timeline.data} error={timeline.error} height={160} />
      </section>

      {insights && (
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <TrajectoryChart timeline={timeline.data} forecast={forecast.data} forecastError={forecast.error ?? timeline.error} asof={detail.provenance.asof} />
          </div>
          <AnaloguesLine forecast={forecast.data} error={forecast.error} />
        </div>
      )}

      <section className="space-y-4" aria-labelledby="outside-h">
        <h2 id="outside-h" className="text-base font-semibold text-fg-base">What is happening around it</h2>
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <ExternalEvents events={detail.external.events} asof={detail.provenance.asof} />
          </div>
          <div className="space-y-4">
            {insights && <ExternalChips detail={detail} research={detail.research} news={signals?.data && { n: signals.data.items.length, scouted: !!signals.data.lastScoutAt }} />}
            {signals && <LinkedSignals data={signals.data} error={signals.error} />}
          </div>
        </div>
        <ResearchNews projectKey={detail.key} variant="page" />
      </section>
    </div>
  )
}

/** the developer's tab: every model number the page had before the numbers policy */
function ModelDetail({ detail, timeline, forecast, signals }: Loaded) {
  return (
    <div className="space-y-4">
      <ProvenanceLine detail={detail} />
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
        <PredictionPanel detail={detail} />
        <div className="lg:col-span-2">
          <TrajectoryChart timeline={timeline.data} forecast={forecast.data} forecastError={forecast.error ?? timeline.error} asof={detail.provenance.asof} numbers />
        </div>
        {detail.scores && <GaugeRow scores={detail.scores} />}
        <div className="lg:col-span-2"><TimelineStrip detail={detail} numbers /></div>
        <div className="lg:col-span-2"><RiskChecklist rows={detail.riskProfile} /></div>
        <ShapWaterfall drivers={detail.scores?.shapTop5 ?? []} />
        <div className="lg:col-span-2"><AnaloguesTable forecast={forecast.data} /></div>
        {signals && <LinkedSignals data={signals.data} error={signals.error} numbers />}
        <div className="lg:col-span-3"><ExternalChips detail={detail} research={detail.research} numbers /></div>
      </div>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="animate-pulse space-y-8" aria-busy="true" aria-label="Loading the project">
      <div className="space-y-2">
        <div className="h-3 w-24 rounded bg-surface-input" />
        <div className="h-7 w-2/3 rounded bg-surface-input" />
        <div className="h-4 w-1/2 rounded bg-surface-input/80" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <div className="h-72 rounded-xl bg-surface-input/70" />
          <div className="h-52 rounded-xl bg-surface-input/70" />
        </div>
        <div className="h-80 rounded-xl bg-surface-input/70" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-32 rounded-xl bg-surface-input/70" />)}
      </div>
    </div>
  )
}

/**
 * Project page (guide §5): one project from /api/projects/{key} with its timeline, and for officials the forecast,
 * linked news, the AI brief and second opinion. Every viewer gets the same briefing, laid out as a story: where it
 * stands in a sentence, the tier and the outlook in words, why, what the reports show, where it could go, and what
 * is happening around it. The API already cuts what a viewer may not see. The developer gets a second tab, Model
 * detail (?tab=model), with every model number the page used to show.
 */
export function ProjectStudio() {
  const { key = '' } = useParams<{ key: string }>()
  const [params, setParams] = useSearchParams()
  const { role } = useSession()
  const insights = can(role, 'canSeeDrivers')
  const numbers = can(role, 'canSeeNumbers')
  const { data: detail, isLoading, error } = useProject(key)
  // the canonical key: an old or merged key resolves to the project it now belongs to
  const k = detail?.key ?? null
  const timeline = useTimeline(k)
  const forecast = useForecast(insights ? k : null)
  const signals = useSignals(can(role, 'canSeeNews') ? k : null)

  if (isLoading) return <Page><PageSkeleton /></Page>

  if (error || !detail) {
    return (
      <Page narrow>
        <div className="space-y-4 py-10 text-center">
          {isOffline(error) ? (
            <ApiErrorNote error={error} />
          ) : (
            <p className="text-sm text-fg-muted">
              Project <span className="font-mono text-fg-base">{key}</span> was not found, or it is not in your view.
            </p>
          )}
          <Link to="/command"><Button variant="secondary" size="sm">Back to all projects</Button></Link>
        </div>
      </Page>
    )
  }

  const loaded: Loaded = {
    detail,
    timeline: { data: timeline.data, error: timeline.error },
    forecast: { data: forecast.data, error: forecast.error },
    signals: can(role, 'canSeeNews') ? { data: signals.data, error: signals.error } : null,
  }
  const briefing = <Briefing {...loaded} insights={insights} opinion={can(role, 'canSeeSecondOpinion')} numbers={numbers} />
  const tab = params.get('tab') === 'model' ? 'model' : 'briefing'

  return (
    <MotionConfig reducedMotion="user">
      <Page>
        <ProjectIdentityStrip detail={detail} />
        {numbers ? (
          <Tabs
            value={tab}
            onValueChange={(v) => setParams((p) => { if (v === 'model') p.set('tab', 'model'); else p.delete('tab'); return p }, { replace: true })}
          >
            <TabsList aria-label="Project views">
              <TabsTrigger value="briefing">Briefing</TabsTrigger>
              <TabsTrigger value="model">Model detail</TabsTrigger>
            </TabsList>
            <TabsContent value="briefing" className="mt-6">{briefing}</TabsContent>
            <TabsContent value="model" className="mt-6"><ModelDetail {...loaded} /></TabsContent>
          </Tabs>
        ) : briefing}
      </Page>
    </MotionConfig>
  )
}
