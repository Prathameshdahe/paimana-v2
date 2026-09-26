/**
 * src/mocks/index.ts
 *
 * Typed offline mock engine for PAIMANA Early Warning Radar.
 *
 * TanStack Query hooks over the bundled project data, with a simulated
 * 300ms latency. Model scores from the FastAPI backend are overlaid when
 * it is reachable (see below).
 *
 * Debug export: window.__PAIMANA_MOCKS__ is populated in development mode
 * for browser DevTools inspection.
 */

import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { MOCK_PROJECTS } from './projects'
import { MOCK_BENCHMARK_ROWS, MOCK_CUF_AUDIT_ROWS } from './audit'
import type { Project, RiskTier, Sector, ShapDriver } from '@/contracts/project'
import type { ModelBenchmarkRow, CUFFieldAuditRow } from '@/contracts/audit'
import type { PortfolioSummary } from '@/contracts/portfolio'
import { API_BASE } from '@/lib/api'

// ── Live model overlay ──────────────────────────────────────────────────────
// The dashboard's Project objects ship with a heuristic compositeRiskScore/
// shapDrivers (build_real_projects.py, no trained model). The FastAPI backend
// now has a real LightGBM model — this overlays its output onto the SAME
// Project shape at the one place every view already reads from, so no view
// component needs to change. Falls back to the heuristic untouched if the
// backend isn't running.

interface BackendShapItem {
  feature: string
  contribution: number
  direction: 'worsening' | 'improving' | 'neutral'
}

interface ModelScore {
  projectId: string
  slipProbability: number
  modelVersion: string
  shap: BackendShapItem[]
}

// Raw engineered feature name -> human label, for the SHAP waterfall (Clause a
// says drivers must be human-readable CUF-style categories, not code identifiers).
const FEATURE_LABELS: Record<string, string> = {
  physical_progress: 'Physical Progress Shortfall',
  agency: 'Implementing Agency Track Record',
  pct_time_elapsed: 'Schedule Time Elapsed',
  state: 'State-Level Execution Factors',
  delay_months: 'Recorded Delay',
  optimism_gap: 'Optimism Gap (Time vs. Progress)',
  cost_revised: 'Cost Revision History',
  n_prior_revisions: 'Prior Revision Count',
  disparity_index: 'Financial-Physical Disparity',
  months_since_last_revision: 'Time Since Last Revision',
  progress_velocity: 'Progress Velocity',
  spend_velocity: 'Spend Velocity',
  cumulative_expenditure: 'Cumulative Expenditure',
  agency_past_slip_rate: 'Agency Historical Slip Rate',
  sector: 'Sector Risk Profile',
  cost_original: 'Original Sanctioned Cost',
  cost_anticipated: 'Anticipated Cost',
  cost_overrun_pct: 'Cost Overrun %',
  project_type: 'Project Type',
  size_band: 'Project Size Band',
}

function featureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? feature
}

/** Same CRITICAL/WARNING/NORMAL cutoffs the heuristic score and the map/matrix already use. */
function tierFromScore(score: number): RiskTier {
  if (score >= 60) return 'CRITICAL'
  if (score >= 30) return 'WARNING'
  return 'NORMAL'
}

function mapShapDrivers(shap: BackendShapItem[], delayMonths: number): ShapDriver[] {
  const totalAbs = shap.reduce((sum, s) => sum + Math.abs(s.contribution), 0) || 1
  return shap
    .map((s) => {
      const weight = Math.round((Math.abs(s.contribution) / totalAbs) * 1000) / 1000
      return {
        feature: featureLabel(s.feature),
        weight,
        impactMonths: Math.round(weight * Math.max(delayMonths, 1) * 10) / 10,
        direction: s.direction,
      }
    })
    .sort((a, b) => b.weight - a.weight)
}

/** Overlays real model output onto the heuristic Project list. Pure — never mutates MOCK_PROJECTS. */
function applyModelScores(projects: Project[], scores: Map<string, ModelScore>): Project[] {
  if (scores.size === 0) return projects
  return projects.map((p) => {
    const score = scores.get(p.id)
    if (!score) return p
    const compositeRiskScore = Math.round(score.slipProbability * 100)
    const shapDrivers = mapShapDrivers(score.shap, p.predictedDelayMonths)
    return {
      ...p,
      compositeRiskScore,
      riskTier: tierFromScore(compositeRiskScore),
      shapDrivers: shapDrivers.length > 0 ? shapDrivers : p.shapDrivers,
      topBottleneck: shapDrivers[0]?.feature ?? p.topBottleneck,
    }
  })
}

// Fetched once per page session (the model doesn't retrain on the fly), a
// short timeout so the app never feels slow just because the backend isn't
// up — same offline-first spirit as the rest of this mock layer.
let scoresPromise: Promise<Map<string, ModelScore>> | null = null

async function loadModelScores(): Promise<Map<string, ModelScore>> {
  if (!scoresPromise) {
    scoresPromise = (async () => {
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 1500)
        const res = await fetch(`${API_BASE}/api/model-scores`, { signal: controller.signal })
        clearTimeout(timeout)
        if (!res.ok) return new Map()
        const rows: ModelScore[] = await res.json()
        return new Map(rows.map((r) => [r.projectId, r]))
      } catch {
        return new Map() // backend not running — heuristic data stays as-is
      }
    })()
  }
  return scoresPromise
}

async function getLiveProjects(): Promise<Project[]> {
  const scores = await loadModelScores()
  return applyModelScores(MOCK_PROJECTS, scores)
}

// ── Simulated Latency ─────────────────────────────────────────────────────────
const MOCK_LATENCY_MS = 300

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ── Query Key Factory ─────────────────────────────────────────────────────────
export const queryKeys = {
  projects: {
    all: ['projects'] as const,
    filtered: (filters: ProjectFilters) => ['projects', 'filtered', filters] as const,
    detail: (id: string) => ['projects', id] as const,
  },
  portfolio: ['portfolio', 'summary'] as const,
  audit: {
    benchmark: ['audit', 'benchmark'] as const,
    cuf: ['audit', 'cuf'] as const,
  },
} as const

// ── Filter Types ──────────────────────────────────────────────────────────────

export interface ProjectFilters {
  ministry?: string
  sector?: Sector
  riskTier?: RiskTier
  searchQuery?: string
}

// ── Mock Query Functions ──────────────────────────────────────────────────────

async function fetchProjects(filters?: ProjectFilters): Promise<Project[]> {
  await delay(MOCK_LATENCY_MS)

  let results = await getLiveProjects()

  if (filters?.riskTier !== undefined) {
    const tier = filters.riskTier
    results = results.filter((p) => p.riskTier === tier)
  }

  if (filters?.sector !== undefined) {
    const sector = filters.sector
    results = results.filter((p) => p.sector === sector)
  }

  if (filters?.ministry !== undefined && filters.ministry !== '') {
    const ministry = filters.ministry.toLowerCase()
    results = results.filter((p) => p.ministry.toLowerCase().includes(ministry))
  }

  if (filters?.searchQuery !== undefined && filters.searchQuery.trim() !== '') {
    const q = filters.searchQuery.toLowerCase()
    results = results.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.code.toLowerCase().includes(q) ||
        p.agency.toLowerCase().includes(q) ||
        p.state.toLowerCase().includes(q)
    )
  }

  return results
}

async function fetchProject(id: string): Promise<Project | undefined> {
  await delay(MOCK_LATENCY_MS)
  const projects = await getLiveProjects()
  return projects.find((p) => p.id === id)
}

async function fetchPortfolioSummary(): Promise<PortfolioSummary> {
  await delay(MOCK_LATENCY_MS)
  const projects = await getLiveProjects()
  const originalCost = projects.reduce((acc, p) => acc + p.originalCostCr, 0)
  const revisedCost = projects.reduce((acc, p) => acc + p.revisedCostCr, 0)
  const actualSpend = projects.reduce((acc, p) => acc + p.currentExpenditureCr, 0)
  const totalOverrun = projects.reduce((acc, p) => acc + p.overrunForecastCr, 0)
  const totalDisparity = projects.reduce((acc, p) => acc + p.disparityDeltaPct, 0)

  return {
    totalProjects: projects.length,
    criticalCount: projects.filter((p) => p.riskTier === 'CRITICAL').length,
    warningCount: projects.filter((p) => p.riskTier === 'WARNING').length,
    normalCount: projects.filter((p) => p.riskTier === 'NORMAL').length,
    originalPortfolioCostCr: Math.round(originalCost),
    revisedPortfolioCostCr: Math.round(revisedCost),
    cumulativeExpenditureCr: Math.round(actualSpend),
    cumulativeOverrunCr: Math.round(totalOverrun),
    reportingCycle: 'Apr 2026 Snapshot (Top 300 Real Projects)',
    avgDisparityDeltaPct: Math.round((totalDisparity / (projects.length || 1)) * 10) / 10,
  }
}

async function fetchBenchmarkData(): Promise<ModelBenchmarkRow[]> {
  await delay(MOCK_LATENCY_MS)
  return MOCK_BENCHMARK_ROWS
}

async function fetchCUFAuditData(): Promise<CUFFieldAuditRow[]> {
  await delay(MOCK_LATENCY_MS)
  return MOCK_CUF_AUDIT_ROWS
}

// ── TanStack Query Hooks ──────────────────────────────────────────────────────

/**
 * Returns the full project list, optionally filtered.
 * Simulates 300ms backend latency.
 */
export function useProjects(filters?: ProjectFilters): UseQueryResult<Project[], Error> {
  return useQuery({
    queryKey: filters ? queryKeys.projects.filtered(filters) : queryKeys.projects.all,
    queryFn: () => fetchProjects(filters),
  })
}

/**
 * Returns a single project by ID.
 * Returns undefined if not found (not an error — component should handle gracefully).
 */
export function useProject(id: string): UseQueryResult<Project | undefined, Error> {
  return useQuery({
    queryKey: queryKeys.projects.detail(id),
    queryFn: () => fetchProject(id),
    enabled: id.trim() !== '',
  })
}

/**
 * Returns the portfolio-level macro KPI summary.
 * Figures are authoritative per PROJECT_CONTEXT.md (1,981 projects, ₹42.78L Cr, etc.)
 */
export function usePortfolioSummary(): UseQueryResult<PortfolioSummary, Error> {
  return useQuery({
    queryKey: queryKeys.portfolio,
    queryFn: fetchPortfolioSummary,
    staleTime: Infinity, // Static data — never refetch within a session
  })
}

/**
 * Returns the AI/ML vs. Statistical model benchmark rows (Clause b).
 */
export function useBenchmarkData(): UseQueryResult<ModelBenchmarkRow[], Error> {
  return useQuery({
    queryKey: queryKeys.audit.benchmark,
    queryFn: fetchBenchmarkData,
    staleTime: Infinity,
  })
}

/**
 * Returns the CUF field utility audit rows (Clause c).
 */
export function useCUFAuditData(): UseQueryResult<CUFFieldAuditRow[], Error> {
  return useQuery({
    queryKey: queryKeys.audit.cuf,
    queryFn: fetchCUFAuditData,
    staleTime: Infinity,
  })
}

// ── Development Debug Export ──────────────────────────────────────────────────
// Exposes raw mock data via window.__PAIMANA_MOCKS__ for DevTools inspection.
// Verify: window.__PAIMANA_MOCKS__.projects.length === 10
//         window.__PAIMANA_MOCKS__.portfolio.totalProjects === 1981

if (import.meta.env.DEV) {
  window.__PAIMANA_MOCKS__ = {
    projects: MOCK_PROJECTS,
  }
  console.info('[PAIMANA] Mock engine active. Debug data available at window.__PAIMANA_MOCKS__')
  console.info(`[PAIMANA] ${MOCK_PROJECTS.length} projects loaded (heuristic baseline — live model overlay applied per-query if backend is up)`)
}
