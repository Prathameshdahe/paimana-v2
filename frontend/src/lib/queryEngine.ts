/**
 * src/lib/queryEngine.ts
 *
 * Local rule-based "ask your data" engine for the chat widget. Filters/
 * aggregates the real project dataset directly — no network round trip.
 *
 * No LLM here. This is a keyword+regex query parser over
 * MOCK_PROJECTS, not RAG. It answers "which X projects in Y have Z" style
 * questions quickly. Could later be swapped for an LLM call through the
 * backend with the same signature (askQuestion(text) -> string).
 */
import { MOCK_PROJECTS } from '@/mocks/projects'
import type { Project, RiskTier } from '@/contracts/project'
import { formatINRShort } from '@/lib/formatters'

const SECTORS = Array.from(new Set(MOCK_PROJECTS.map((p) => p.sector)))
const STATES = Array.from(new Set(MOCK_PROJECTS.map((p) => p.state)))

function findKeyword(q: string, options: string[]): string | undefined {
  const lower = q.toLowerCase()
  return options.find((o) => lower.includes(o.toLowerCase()))
}

function findTier(q: string): RiskTier | undefined {
  const lower = q.toLowerCase()
  if (/\bcritical\b/.test(lower)) return 'CRITICAL'
  if (/\bwarning\b/.test(lower)) return 'WARNING'
  if (/\bnormal|stable\b/.test(lower)) return 'NORMAL'
  return undefined
}

function findPctThreshold(q: string): number | undefined {
  const m = q.match(/(?:over|above|more than|greater than|>\s*)\s*(\d+)\s*%/i)
  return m ? Number(m[1]) : undefined
}

function findMonthThreshold(q: string): number | undefined {
  const m = q.match(/(\d+)\s*months?/i)
  return m ? Number(m[1]) : undefined
}

function findTopN(q: string): number | undefined {
  const m = q.match(/top\s*(\d+)/i)
  return m ? Number(m[1]) : undefined
}

function fmtProject(p: Project): string {
  return `${p.code} — ${p.name} (${p.state}) — risk ${p.compositeRiskScore}/100, overrun ${formatINRShort(p.overrunForecastCr)}, delay ${p.predictedDelayMonths}mo`
}

export interface QueryResult {
  answer: string
  projects: Project[]
}

export function askQuestion(raw: string): QueryResult {
  const q = raw.trim()
  if (!q) return { answer: 'Ask about a sector, state, risk tier, overrun %, or delay — e.g. "critical railway projects in Maharashtra".', projects: [] }

  const sector = findKeyword(q, SECTORS)
  const state = findKeyword(q, STATES)
  const tier = findTier(q)
  const pctThreshold = findPctThreshold(q)
  const monthThreshold = findMonthThreshold(q)
  const topN = findTopN(q)
  const isCount = /\bhow many\b|\bcount\b|\bnumber of\b/i.test(q)
  const isAvg = /\baverage\b|\bavg\b/i.test(q)

  let results = MOCK_PROJECTS
  if (sector) results = results.filter((p) => p.sector === sector)
  if (state) results = results.filter((p) => p.state === state)
  if (tier) results = results.filter((p) => p.riskTier === tier)
  if (pctThreshold !== undefined) {
    results = results.filter((p) => (p.originalCostCr > 0 ? (p.overrunForecastCr / p.originalCostCr) * 100 : 0) > pctThreshold)
  }
  if (monthThreshold !== undefined) {
    results = results.filter((p) => p.predictedDelayMonths > monthThreshold)
  }

  const scope = [tier?.toLowerCase(), sector, state && `in ${state}`].filter(Boolean).join(' ') || 'matching'

  if (isCount) {
    return { answer: `${results.length} ${scope} project${results.length === 1 ? '' : 's'}.`, projects: [] }
  }

  if (isAvg) {
    const n = results.length || 1
    const avgRisk = Math.round(results.reduce((a, p) => a + p.compositeRiskScore, 0) / n)
    const avgDelay = Math.round((results.reduce((a, p) => a + p.predictedDelayMonths, 0) / n) * 10) / 10
    return { answer: `${results.length} ${scope} projects — average risk score ${avgRisk}/100, average predicted delay ${avgDelay} months.`, projects: [] }
  }

  results = [...results].sort((a, b) => b.compositeRiskScore - a.compositeRiskScore)
  const limit = topN ?? 8
  const shown = results.slice(0, limit)

  if (results.length === 0) {
    return { answer: `No ${scope} projects found in the current dataset (top 300 by cost, FY2024-25).`, projects: [] }
  }

  const more = results.length > shown.length ? ` (showing top ${shown.length} of ${results.length}, by risk score)` : ''
  return {
    answer: `${results.length} ${scope} project${results.length === 1 ? '' : 's'}${more}:\n` + shown.map(fmtProject).join('\n'),
    projects: shown,
  }
}
