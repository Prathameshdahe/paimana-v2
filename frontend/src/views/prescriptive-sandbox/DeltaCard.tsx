import { MonoFigure } from '@/components/ui/MonoFigure'
import { formatINR, formatMonths, formatDate } from '@/lib/formatters'
import type { SandboxState } from '@/contracts/sandbox'
import type { Project } from '@/contracts/project'

interface DeltaCardProps {
  project?: Project
  state: SandboxState
}

export function DeltaCard({ project: _project, state }: DeltaCardProps) {
  const { baseline, simulated, delta, controls } = state

  const fiscalROI =
    controls.capitalTrancheInjectionCr > 0
      ? (delta.capitalSavedCr / controls.capitalTrancheInjectionCr).toFixed(1)
      : null

  return (
    <div className="space-y-4">
      {/* Delta Summary — 3-cell grid */}
      <div className="border border-border-subtle bg-surface-panel grid grid-cols-3 divide-x divide-border-subtle">
        <div className="px-4 py-3 flex flex-col items-center text-center">
          <div className="text-xs font-sans font-semibold uppercase tracking-wider text-fg-muted mb-1">
            Capital Saved
          </div>
          <MonoFigure size="xl" sentiment="stable">
            {delta.capitalSavedCr > 0 ? `+${formatINR(delta.capitalSavedCr)}` : '—'}
          </MonoFigure>
        </div>
        <div className="px-4 py-3 flex flex-col items-center text-center">
          <div className="text-xs font-sans font-semibold uppercase tracking-wider text-fg-muted mb-1">
            Schedule Recovered
          </div>
          <MonoFigure size="xl" sentiment="stable">
            {delta.monthsRecovered > 0 ? `+${delta.monthsRecovered.toFixed(1)}mo` : '—'}
          </MonoFigure>
        </div>
        <div className="px-4 py-3 flex flex-col items-center text-center">
          <div className="text-xs font-sans font-semibold uppercase tracking-wider text-fg-muted mb-1">
            Risk Reduced
          </div>
          <MonoFigure size="xl" sentiment="stable">
            {delta.riskScoreReduction > 0 ? `-${delta.riskScoreReduction}pts` : '—'}
          </MonoFigure>
          <div className="text-[10px] font-mono text-fg-dimmed mt-0.5">
            → {simulated.compositeRiskScoreRevised}/100
          </div>
        </div>
      </div>

      {/* Comparison Table */}
      <div className="border border-border-subtle bg-surface-panel">
        <div className="border-b border-border-subtle px-3 py-2">
          <span className="text-xs font-sans font-semibold uppercase tracking-wider text-fg-muted">
            Baseline vs. Simulated Outcome
          </span>
        </div>

        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border-default text-fg-dimmed font-sans">
              <th className="py-2 px-3 text-left font-medium">Metric</th>
              <th className="py-2 px-3 text-right font-medium">Baseline</th>
              <th className="py-2 px-3 text-right font-medium">Simulated</th>
              <th className="py-2 px-3 text-right font-medium">Δ Benefit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle/60">
            <tr className="h-8">
              <td className="px-3 text-fg-muted font-sans">Cost Overrun</td>
              <td className="px-3 text-right text-critical font-mono">+{formatINR(baseline.overrunForecastCrRevised)}</td>
              <td className="px-3 text-right text-fg-base font-mono">+{formatINR(simulated.overrunForecastCrRevised)}</td>
              <td className="px-3 text-right text-stable font-mono">
                {delta.capitalSavedCr > 0 ? `-${formatINR(delta.capitalSavedCr)}` : '—'}
              </td>
            </tr>
            <tr className="h-8">
              <td className="px-3 text-fg-muted font-sans">Completion (DOC)</td>
              <td className="px-3 text-right text-warning font-mono">{formatDate(baseline.predictedDocRevised)}</td>
              <td className="px-3 text-right text-fg-base font-mono">{formatDate(simulated.predictedDocRevised)}</td>
              <td className="px-3 text-right text-stable font-mono">
                {delta.monthsRecovered > 0 ? `${delta.monthsRecovered.toFixed(1)}mo earlier` : '—'}
              </td>
            </tr>
            <tr className="h-8">
              <td className="px-3 text-fg-muted font-sans">Delay vs Revised DOC</td>
              <td className="px-3 text-right text-fg-muted font-mono">+{formatMonths(baseline.predictedDelayMonthsRevised)}</td>
              <td className="px-3 text-right text-fg-base font-mono">+{formatMonths(simulated.predictedDelayMonthsRevised)}</td>
              <td className="px-3 text-right text-stable font-mono">
                {delta.monthsRecovered > 0 ? `-${delta.monthsRecovered.toFixed(1)}mo` : '—'}
              </td>
            </tr>
            <tr className="h-8">
              <td className="px-3 text-fg-muted font-sans">Composite Risk</td>
              <td className="px-3 text-right text-critical font-mono">{baseline.compositeRiskScoreRevised}/100</td>
              <td className="px-3 text-right text-fg-base font-mono">{simulated.compositeRiskScoreRevised}/100</td>
              <td className="px-3 text-right text-stable font-mono">
                {delta.riskScoreReduction > 0 ? `-${delta.riskScoreReduction}pts` : '—'}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Fiscal ROI */}
        {fiscalROI && (
          <div className="border-t border-border-subtle px-3 py-2 flex items-center justify-between text-xs font-sans">
            <span className="text-fg-dimmed">
              Fiscal efficiency: ₹1 Cr injected prevents ₹<span className="font-mono">{fiscalROI}</span> Cr escalation
            </span>
            <span className="text-accent font-semibold"><span className="font-mono">{fiscalROI}</span>× return</span>
          </div>
        )}
      </div>
    </div>
  )
}
