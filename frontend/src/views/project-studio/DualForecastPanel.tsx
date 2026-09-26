import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatINR, formatDate, formatMonths, formatPct } from '@/lib/formatters'
import type { Project } from '@/contracts/project'

interface DualForecastPanelProps {
  project: Project
}

export function DualForecastPanel({ project }: DualForecastPanelProps) {
  const costEscalationPct = project.originalCostCr > 0
    ? ((project.revisedCostCr + project.overrunForecastCr - project.originalCostCr) /
        project.originalCostCr) * 100
    : 0

  const financialProgressPct = (project.currentExpenditureCr / project.revisedCostCr) * 100
  const physicalPct = Math.max(0, financialProgressPct - project.disparityDeltaPct)

  return (
    <div className="border border-border-subtle bg-surface-panel h-full rounded-sm">
      <div className="flex flex-col divide-y divide-border-subtle h-full justify-between">

        {/* Cost Telemetry */}
        <div className="px-4 py-3 space-y-3">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted">
            Cost Forecast · Clause (a)
          </div>

          <div>
            <div className="text-xs font-mono text-fg-muted">ML Forecasted Overrun</div>
            <MonoFigure size="2xl" sentiment="critical">
              +{formatINR(project.overrunForecastCr)}
            </MonoFigure>
            <div className="text-xs font-mono text-fg-muted mt-0.5">
              +{formatPct(costEscalationPct)} total escalation
            </div>
          </div>

          <div className="space-y-1.5 text-xs font-mono border-t border-border-subtle pt-2">
            <div className="flex justify-between">
              <span className="text-fg-muted">Original</span>
              <span className="text-fg-base font-medium">{formatINR(project.originalCostCr)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-fg-muted">Revised</span>
              <span className="text-fg-base font-medium">{formatINR(project.revisedCostCr)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-fg-muted">Spent</span>
              <span className="text-fg-base font-medium">{formatINR(project.currentExpenditureCr)}</span>
            </div>
            <div className="flex justify-between border-t border-border-subtle pt-1">
              <span className="text-fg-muted">Projected Final</span>
              <span className="text-critical font-semibold">
                {formatINR(project.revisedCostCr + project.overrunForecastCr)}
              </span>
            </div>
          </div>
        </div>

        {/* Schedule Telemetry */}
        <div className="px-4 py-3 space-y-3">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted">
            Schedule Forecast · 90% CI
          </div>

          <div>
            <div className="text-xs font-mono text-fg-muted">Predicted Delay</div>
            <MonoFigure size="2xl" sentiment="warning">
              +{formatMonths(project.predictedDelayMonths)}
            </MonoFigure>
            <div className="text-xs font-mono text-fg-muted mt-0.5">
              CI: [{project.delayCI.lowerMonths.toFixed(1)}–{project.delayCI.upperMonths.toFixed(1)}] mo
            </div>
          </div>

          <div className="space-y-1.5 text-xs font-mono border-t border-border-subtle pt-2">
            <div className="flex justify-between">
              <span className="text-fg-muted">Sanctioned DOC</span>
              <span className="text-fg-base font-medium">{formatDate(project.sanctionedDoc)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-fg-muted">Revised DOC</span>
              <span className="text-fg-base font-medium">{formatDate(project.revisedDoc)}</span>
            </div>
            <div className="flex justify-between border-t border-border-subtle pt-1">
              <span className="text-fg-muted">ML Predicted DOC</span>
              <span className="text-warning font-semibold">{formatDate(project.predictedDoc)}</span>
            </div>
          </div>
        </div>

        {/* Disparity Index */}
        <div className="px-4 py-3 space-y-3">
          <div className="text-xs font-mono uppercase tracking-widest text-fg-muted">
            Disparity Index Δ(P-F)
          </div>

          <div>
            <div className="text-xs font-mono text-fg-muted">Physical-Financial Gap</div>
            <MonoFigure
              size="2xl"
              sentiment={project.disparityDeltaPct > 15 ? 'critical' : project.disparityDeltaPct > 5 ? 'warning' : 'stable'}
            >
              {project.disparityDeltaPct > 0 ? '+' : ''}{formatPct(project.disparityDeltaPct)}
            </MonoFigure>
          </div>

          {/* Progress bars — sharp, no rounded corners */}
          <div className="space-y-3 border-t border-border-subtle pt-2">
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-fg-muted">Financial</span>
                <span className="text-fg-base font-medium">{formatPct(financialProgressPct)}</span>
              </div>
              <div className="h-1.5 w-full bg-surface-input">
                <div className="h-full bg-accent" style={{ width: `${Math.min(100, financialProgressPct)}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-fg-muted">Physical</span>
                <span className="text-fg-base font-medium">{formatPct(physicalPct)}</span>
              </div>
              <div className="h-1.5 w-full bg-surface-input">
                <div className="h-full bg-stable" style={{ width: `${Math.min(100, physicalPct)}%` }} />
              </div>
            </div>
          </div>

          <div className="text-xs font-mono text-fg-muted border-t border-border-subtle pt-1.5">
            expenditure {project.disparityDeltaPct >= 0 ? 'outpacing' : 'lagging behind'} civil works by {formatPct(Math.abs(project.disparityDeltaPct))}
          </div>
        </div>
      </div>
    </div>
  )
}
