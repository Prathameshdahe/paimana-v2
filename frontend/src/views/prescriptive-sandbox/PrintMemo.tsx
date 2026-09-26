import { Button } from '@/components/ui/Button'
import {
  formatINR,
  formatMonths,
  formatDate,
} from '@/lib/formatters'
import type { Project } from '@/contracts/project'
import type { SandboxState } from '@/contracts/sandbox'

interface PrintMemoProps {
  project: Project
  state: SandboxState
}

export function PrintMemo({ project, state }: PrintMemoProps) {
  const { baseline, simulated, delta, controls } = state

  const handlePrint = () => {
    window.print()
  }

  return (
    <>
      {/* On-Screen Print Bar (hidden during print) */}
      <div data-no-print>
        <div className="border border-border-subtle bg-surface-panel px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="font-mono text-[11px]">
            <span className="text-fg-dimmed uppercase tracking-widest">PRAGATI Decision Memo</span>
            <span className="text-fg-muted ml-3">
              export formal CCI briefing with active simulation parameters
            </span>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={handlePrint}
          >
            PRINT MEMO
          </Button>
        </div>
      </div>

      {/* Printable PRAGATI Decision Memo Container (1-Page A4) */}
      <div
        data-print-memo
        className="hidden print:block font-serif text-black bg-white p-6 max-w-4xl mx-auto space-y-4 text-xs leading-normal"
      >
        {/* Memo Header */}
        <div className="border-b-2 border-black pb-3 text-center">
          <p className="text-[10px] font-bold tracking-widest uppercase text-gray-700">
            Government of India • Cabinet Secretariat • IPMD Division
          </p>
          <h1 className="text-base font-extrabold uppercase mt-1 tracking-tight text-black">
            MINISTRY OF STATISTICS & PROGRAMME IMPLEMENTATION — PRAGATI EXECUTIVE BRIEF
          </h1>
          <p className="text-[10px] font-mono mt-0.5 text-gray-600">
            Cabinet Decision Protocol • Ref: MOSPI/IPMD/PRAGATI/2026/POL-{project.code} • Date of Issue: {new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
          </p>
        </div>

        {/* Project Metadata Table */}
        <div className="border border-gray-400 p-2.5 bg-gray-50/50">
          <table className="w-full text-[11px]">
            <tbody>
              <tr>
                <td className="font-bold py-0.5 w-1/4 text-gray-800">Project Code:</td>
                <td className="py-0.5 font-mono font-bold text-black">{project.code}</td>
                <td className="font-bold py-0.5 w-1/4 text-gray-800">Date of Issue:</td>
                <td className="py-0.5 font-mono text-black">{new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</td>
              </tr>
              <tr>
                <td className="font-bold py-0.5 text-gray-800">Project Name:</td>
                <td colSpan={3} className="py-0.5 font-sans font-semibold text-black">{project.name}</td>
              </tr>
              <tr>
                <td className="font-bold py-0.5 text-gray-800">Sponsoring Ministry:</td>
                <td className="py-0.5 text-gray-900">{project.ministry}</td>
                <td className="font-bold py-0.5 text-gray-800">Implementing Agency:</td>
                <td className="py-0.5 text-gray-900">{project.agency} ({project.state})</td>
              </tr>
              <tr>
                <td className="font-bold py-0.5 text-gray-800">Sector Classification:</td>
                <td className="py-0.5 text-gray-900">{project.sector}</td>
                <td className="font-bold py-0.5 text-gray-800">Baseline Triage Status:</td>
                <td className="py-0.5 font-bold text-black">{project.riskTier} ({project.compositeRiskScore}/100)</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Net Public Capital Saved & Months Recovered Highlight Box */}
        <div className="border-2 border-black p-3 bg-gray-100 flex items-center justify-between text-center">
          <div className="flex-1 border-r border-gray-400 px-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-700">Net Public Capital Saved</div>
            <div className="text-xl font-extrabold font-mono text-black mt-0.5">
              {formatINR(delta.capitalSavedCr)}
            </div>
            <div className="text-[9px] text-gray-600 mt-0.5">Preserved public exchequer outlay</div>
          </div>
          <div className="flex-1 border-r border-gray-400 px-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-700">Timeline Months Recovered</div>
            <div className="text-xl font-extrabold font-mono text-black mt-0.5">
              +{delta.monthsRecovered.toFixed(1)} Months
            </div>
            <div className="text-[9px] text-gray-600 mt-0.5">Critical path acceleration</div>
          </div>
          <div className="flex-1 px-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-700">Simulated Target DOC</div>
            <div className="text-base font-bold font-mono text-black mt-0.5">
              {formatDate(simulated.predictedDocRevised)}
            </div>
            <div className="text-[9px] text-gray-600 mt-0.5">Risk reduced to {simulated.compositeRiskScoreRevised}/100</div>
          </div>
        </div>

        {/* Baseline vs. Simulated Comparison Table */}
        <div>
          <h2 className="font-bold uppercase text-[11px] border-b border-black pb-1 mb-1.5 text-gray-900">
            1. Baseline vs. Simulated Intervention Comparison
          </h2>
          <table className="w-full text-[11px] border border-gray-400 border-collapse">
            <thead className="bg-gray-100 border-b border-gray-400">
              <tr>
                <th className="p-1.5 text-left font-bold text-gray-800">Telemetry Parameter</th>
                <th className="p-1.5 text-right font-bold text-gray-800">Unmitigated Baseline</th>
                <th className="p-1.5 text-right font-bold text-gray-800">Simulated Outcome</th>
                <th className="p-1.5 text-right font-bold text-gray-800">Net Variance / Delta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-300 font-mono text-[10.5px]">
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Anticipated Commissioning Date (DOC)</td>
                <td className="p-1.5 text-right text-gray-700">{formatDate(baseline.predictedDocRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">{formatDate(simulated.predictedDocRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">-{delta.monthsRecovered.toFixed(1)} mo</td>
              </tr>
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Schedule Delay Slippage</td>
                <td className="p-1.5 text-right text-gray-700">+{formatMonths(baseline.predictedDelayMonthsRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">+{formatMonths(simulated.predictedDelayMonthsRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">-{delta.monthsRecovered.toFixed(1)} mo</td>
              </tr>
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Overrun Forecast (Escalation)</td>
                <td className="p-1.5 text-right text-gray-700">+{formatINR(baseline.overrunForecastCrRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">+{formatINR(simulated.overrunForecastCrRevised)}</td>
                <td className="p-1.5 text-right font-bold text-black">-{formatINR(delta.capitalSavedCr)}</td>
              </tr>
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Composite Risk Score (0–100)</td>
                <td className="p-1.5 text-right text-gray-700">{baseline.compositeRiskScoreRevised}/100</td>
                <td className="p-1.5 text-right font-bold text-black">{simulated.compositeRiskScoreRevised}/100</td>
                <td className="p-1.5 text-right font-bold text-black">-{delta.riskScoreReduction} pts</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Policy Interventions Applied */}
        <div>
          <h2 className="font-bold uppercase text-[11px] border-b border-black pb-1 mb-1.5 text-gray-900">
            2. Policy Interventions Applied in Active Simulation
          </h2>
          <table className="w-full text-[10.5px] border border-gray-400 border-collapse">
            <thead className="bg-gray-100 border-b border-gray-400">
              <tr>
                <th className="p-1.5 text-left font-bold text-gray-800">Policy Lever</th>
                <th className="p-1.5 text-left font-bold text-gray-800">Simulated Parameter</th>
                <th className="p-1.5 text-left font-bold text-gray-800">Competent Authority</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-300">
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Statutory Clearance Compression</td>
                <td className="p-1.5 font-mono text-black">+{controls.clearanceAccelerationDays} Days Acceleration</td>
                <td className="p-1.5 text-gray-700">MoEFCC / State Revenue Authorities</td>
              </tr>
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Emergency Working Capital Tranche</td>
                <td className="p-1.5 font-mono text-black">{formatINR(controls.capitalTrancheInjectionCr)} Injection</td>
                <td className="p-1.5 text-gray-700">Ministry of Finance / NHAI Escrow</td>
              </tr>
              <tr>
                <td className="p-1.5 font-sans font-medium text-black">Contractor Workforce Mobilization</td>
                <td className="p-1.5 font-mono text-black">+{controls.workforceMobilizationPct}% Labor & Equipment Surge</td>
                <td className="p-1.5 text-gray-700">{project.agency} Executing Engineers</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Sign-off Block */}
        <div className="pt-4 border-t border-gray-400 flex justify-between text-[10px] text-gray-700">
          <div>
            <p className="font-bold text-black">Prepared by:</p>
            <p>Infrastructure Project Monitoring Division (IPMD)</p>
            <p>Ministry of Statistics & Programme Implementation (MoSPI)</p>
          </div>
          <div className="text-right">
            <p className="font-bold text-black">Submitted for Cabinet Review:</p>
            <p>Advisor (Infrastructure & Energy)</p>
            <p>PRAGATI Secretariat • Cabinet Secretariat</p>
          </div>
        </div>
      </div>
    </>
  )
}
