import { useState, useMemo, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useProjects } from '@/mocks'
import { PolicySliders } from './prescriptive-sandbox/PolicySliders'
import { DeltaCard } from './prescriptive-sandbox/DeltaCard'
import { PrintMemo } from './prescriptive-sandbox/PrintMemo'
import type { SandboxControls, SandboxState, SandboxOutcome, SandboxDelta } from '@/contracts/sandbox'

const DEFAULT_CONTROLS: SandboxControls = {
  clearanceAccelerationDays: 30,
  capitalTrancheInjectionCr: 100,
  workforceMobilizationPct: 20,
}

export function PrescriptiveSandbox() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: projects = [], isLoading } = useProjects()

  const requestedId = searchParams.get('project')
  const [selectedId, setSelectedId] = useState<string>('')

  useEffect(() => {
    if (projects.length > 0) {
      if (requestedId && projects.some((p) => p.id === requestedId)) {
        setSelectedId(requestedId)
      } else if (!selectedId) {
        const critical = projects.find((p) => p.riskTier === 'CRITICAL')
        const first = critical ? critical.id : (projects[0]?.id ?? '')
        setSelectedId(first)
      }
    }
  }, [projects, requestedId, selectedId])

  const selectedProject = useMemo(() => {
    return projects.find((p) => p.id === selectedId) ?? projects[0]
  }, [projects, selectedId])

  const [controls, setControls] = useState<SandboxControls>(DEFAULT_CONTROLS)

  const handleReset = () => setControls(DEFAULT_CONTROLS)

  const handleProjectSelect = (id: string) => {
    setSelectedId(id)
    setSearchParams({ project: id })
  }

  // Synchronous surrogate recalculation (<16ms)
  const sandboxState: SandboxState | null = useMemo(() => {
    if (!selectedProject) return null

    const baseline: SandboxOutcome = {
      predictedDocRevised: selectedProject.predictedDoc,
      predictedDelayMonthsRevised: selectedProject.predictedDelayMonths,
      overrunForecastCrRevised: selectedProject.overrunForecastCr,
      compositeRiskScoreRevised: selectedProject.compositeRiskScore,
    }

    const clearanceSavingMonths = controls.clearanceAccelerationDays * 0.06
    const capitalSavingMonths = (controls.capitalTrancheInjectionCr / 100) * 1.2
    const workforceSavingMonths = (controls.workforceMobilizationPct / 10) * 0.8

    const totalMonthsRecovered = Math.min(
      selectedProject.predictedDelayMonths * 0.75,
      clearanceSavingMonths + capitalSavingMonths + workforceSavingMonths
    )

    const overrunReduction = Math.min(
      selectedProject.overrunForecastCr * 0.85,
      Math.round(
        (totalMonthsRecovered / Math.max(1, selectedProject.predictedDelayMonths)) *
          selectedProject.overrunForecastCr * 0.7
      )
    )

    const riskReduction = Math.min(
      selectedProject.compositeRiskScore - 15,
      Math.round(
        (totalMonthsRecovered / Math.max(1, selectedProject.predictedDelayMonths)) * 32
      )
    )

    const revisedDocDate = new Date(selectedProject.predictedDoc)
    revisedDocDate.setDate(revisedDocDate.getDate() - Math.round(totalMonthsRecovered * 30.4))
    const predictedDocRevised = revisedDocDate.toISOString().split('T')[0] ?? ''

    const simulated: SandboxOutcome = {
      predictedDocRevised,
      predictedDelayMonthsRevised: Math.max(0, selectedProject.predictedDelayMonths - totalMonthsRecovered),
      overrunForecastCrRevised: Math.max(0, selectedProject.overrunForecastCr - overrunReduction),
      compositeRiskScoreRevised: Math.max(15, selectedProject.compositeRiskScore - riskReduction),
    }

    const delta: SandboxDelta = {
      monthsRecovered: totalMonthsRecovered,
      capitalSavedCr: overrunReduction,
      riskScoreReduction: riskReduction,
    }

    return { projectId: selectedProject.id, baseline, simulated, delta, controls }
  }, [selectedProject, controls])

  if (isLoading || !selectedProject || !sandboxState) {
    return (
      <div className="mx-auto max-w-[1600px] px-4 py-8">
        <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
          loading simulation sandbox...
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      {/* Header (hidden during print) */}
      <div data-no-print className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-sans text-xl font-semibold tracking-wide text-fg-base uppercase">
            What-If Sandbox
          </h1>
          <span className="font-sans text-xs font-medium tracking-widest text-fg-muted uppercase">PRESCRIBE</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="font-sans text-xs font-medium uppercase text-fg-muted">PROJECT:</span>
          <select
            value={selectedId}
            onChange={(e) => handleProjectSelect(e.target.value)}
            className="bg-surface-input border border-border-default px-2 py-1 text-sm font-sans font-medium text-fg-base focus:outline-none max-w-sm"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} — {p.name} [{p.riskTier}]
              </option>
            ))}
          </select>
        </div>
      </div>

      <div data-no-print className="h-px bg-border-subtle" />

      {/* Grid: Sliders | Delta (hidden during print) */}
      <div data-no-print className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5">
          <PolicySliders controls={controls} onChange={setControls} onReset={handleReset} />
        </div>
        <div className="lg:col-span-7">
          <DeltaCard project={selectedProject} state={sandboxState} />
        </div>
      </div>

      <PrintMemo project={selectedProject} state={sandboxState} />
    </div>
  )
}
