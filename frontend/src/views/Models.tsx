import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useMeta, useModels } from '@/lib/queries'
import { formatDate } from '@/lib/formatters'
import { BenchmarkMatrix } from './models/BenchmarkMatrix'
import { AblationTable } from './models/AblationTable'
import { CalibrationChart, LiveAccuracyCard, RegistryHistory, ShapSummary } from './models/ModelPanels'

const TARGETS: Record<string, string> = {
  y_any_h2: 'Any slip · 2q',
  y_date_push_h2: 'Date push · 2q',
  y_cost_rev_h2: 'Cost revision · 2q',
  y_any_h4: 'Any slip · 4q',
}
const targetKey = (r: { target: string; horizon: number }) => `${r.target}_h${r.horizon}`

/**
 * Models (/models, was /audit) over /api/models: live accuracy of the logged predictions, the
 * champion run's rolling-origin backtest against the baselines (clause b), its feature-group
 * ablation (clause c), calibration and SHAP summary, and the registry's champion decisions, one
 * target at a time. Every figure is a row of model/registry.json or model/runs/<runId>/*.csv.
 */
export function Models() {
  const { data, error, isLoading } = useModels()
  const meta = useMeta().data
  const [picked, setPicked] = useState<string | null>(null)

  const targets = data ? [...new Set(data.backtest.map(targetKey))] : []
  const target = picked && targets.includes(picked) ? picked : targets[0]
  const runId = data?.runId
  // the served scores name their run (meta.models); say so when this page shows a different one
  const served = meta ? Object.values(meta.models) : []
  const otherRun = !!runId && served.length > 0 && !served.some((m) => m.startsWith(`${runId}/`))

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono text-sm font-medium tracking-wider text-fg-base uppercase">Models</h1>
          <span className="font-mono text-[11px] tracking-widest text-fg-muted font-medium">VERIFY</span>
        </div>
        {runId && (
          <div className="font-mono text-[11px] text-fg-dimmed">
            run {runId}
            {meta && ` · scores ${meta.modelVersion} · asof ${formatDate(meta.asof)} · gold ${meta.goldVersion}`}
          </div>
        )}
      </div>

      <div className="h-px bg-border-subtle" />

      {error ? (
        <Card>
          <ApiErrorNote error={error} />
        </Card>
      ) : isLoading || !data ? (
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">loading backtest...</div>
      ) : !runId || !target ? (
        <Card>
          <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">
            no champion run in model/registry.json yet: run python -m pipeline.run train
          </div>
        </Card>
      ) : (
        <>
          {otherRun && (
            <div className="border border-warning/40 bg-warning/10 px-4 py-2 font-mono text-xs text-warning">
              The served scores come from {served[0]}, not from run {runId} shown here: re-run
              python -m pipeline.run score.
            </div>
          )}
          <LiveAccuracyCard live={data.liveAccuracy} />
          <Tabs value={target} onValueChange={setPicked}>
            <TabsList>
              {targets.map((t) => (
                <TabsTrigger key={t} value={t}>
                  {TARGETS[t] ?? t}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <BenchmarkMatrix
            rows={data.backtest.filter((r) => targetKey(r) === target)}
            champion={data.champions[target]?.model}
            runId={runId}
          />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
            <CalibrationChart bins={data.calibration.filter((r) => targetKey(r) === target)} runId={runId} />
            <ShapSummary rows={data.shapSummary} runId={runId} />
          </div>
          <AblationTable rows={data.ablation.filter((r) => targetKey(r) === target)} runId={runId} />
          <RegistryHistory
            decisions={data.decisions.filter((d) => targetKey(d) === target)}
            entries={data.registry.filter((e) => targetKey(e) === target)}
          />
        </>
      )}
    </div>
  )
}
