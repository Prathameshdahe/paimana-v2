/**
 * src/lib/stateAggregate.ts
 * Per-state rollup for the India choropleth map. Handles the old/new state
 * name mismatch between our data (modern names) and the boundary file
 * (Orissa/Uttaranchal, pre-2011 GADM naming).
 */
import { MOCK_PROJECTS } from '@/mocks/projects'
import type { Project } from '@/contracts/project'

/** normalize a state name to one canonical key so both spellings match */
export function normStateKey(name: string): string {
  const n = name.trim().toLowerCase()
  const alias: Record<string, string> = {
    orissa: 'odisha',
    uttaranchal: 'uttarakhand',
  }
  return alias[n] ?? n
}

export interface StateAggregate {
  state: string
  projectCount: number
  criticalCount: number
  warningCount: number
  avgRiskScore: number
  totalOverrunCr: number
}

export function computeStateAggregates(): Map<string, StateAggregate> {
  const byState = new Map<string, Project[]>()
  for (const p of MOCK_PROJECTS) {
    const key = normStateKey(p.state)
    const list = byState.get(key) ?? []
    list.push(p)
    byState.set(key, list)
  }

  const out = new Map<string, StateAggregate>()
  for (const [key, projects] of byState) {
    const first = projects[0]
    if (!first) continue
    const n = projects.length
    out.set(key, {
      state: first.state,
      projectCount: n,
      criticalCount: projects.filter((p) => p.riskTier === 'CRITICAL').length,
      warningCount: projects.filter((p) => p.riskTier === 'WARNING').length,
      avgRiskScore: Math.round(projects.reduce((a, p) => a + p.compositeRiskScore, 0) / n),
      totalOverrunCr: Math.round(projects.reduce((a, p) => a + p.overrunForecastCr, 0)),
    })
  }
  return out
}

// matches --color-critical/--color-warning/--color-stable in styles/globals.css
export function riskColor(avgRiskScore: number | undefined): string {
  if (avgRiskScore === undefined) return '#e8e4dc' // no data — neutral
  if (avgRiskScore >= 60) return '#ba1b2b' // critical
  if (avgRiskScore >= 30) return '#9c4d04' // warning
  return '#0b7249' // stable
}
