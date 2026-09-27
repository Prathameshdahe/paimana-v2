/**
 * src/lib/queries.ts
 *
 * TanStack Query hooks over the FastAPI backend. Every hook asks for an
 * aggregate, one page, or one project; nothing fetches a full table. When the
 * backend is down the hooks error with ApiError status 0 (see lib/api.ts) and
 * the views say so; there is no bundled fallback data.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api'
import type { AlertKind, Alert, AlertPage, ExternalSummary, Meta, Portfolio } from '@/contracts/portfolio'
import type {
  Flag,
  Forecast,
  ProjectDetail,
  ProjectPage,
  ProjectSignals,
  ProjectSort,
  TierFilter,
  Timeline,
} from '@/contracts/project'
import type { Role } from '@/lib/auth/RoleContext'

export type PortfolioFilters = {
  ministry?: string
  sector?: string
  state?: string
  tier?: TierFilter
}

export type ProjectQuery = PortfolioFilters & {
  q?: string
  flag?: Flag
  sort?: ProjectSort
  order?: 'asc' | 'desc'
  page?: number
  size?: number
}

export type AlertQuery = {
  kind?: AlertKind
  acked?: boolean
  page?: number
  size?: number
}

const enc = encodeURIComponent

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => apiGet<Meta>('/api/meta') })
}

export function usePortfolio(filters: PortfolioFilters = {}) {
  return useQuery({
    queryKey: ['portfolio', filters],
    queryFn: () => apiGet<Portfolio>('/api/portfolio', filters),
  })
}

export function useProjects(query: ProjectQuery, enabled = true) {
  return useQuery({
    queryKey: ['projects', query],
    queryFn: () => apiGet<ProjectPage>('/api/projects', query),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useProject(key: string | null) {
  return useQuery({
    queryKey: ['project', key],
    queryFn: () => apiGet<ProjectDetail>(`/api/projects/${enc(key ?? '')}`),
    enabled: !!key,
  })
}

export function useTimeline(key: string | null) {
  return useQuery({
    queryKey: ['project', key, 'timeline'],
    queryFn: () => apiGet<Timeline>(`/api/projects/${enc(key ?? '')}/timeline`),
    enabled: !!key,
  })
}

/** 404 when the project is not in the current scored portfolio. */
export function useForecast(key: string | null) {
  return useQuery({
    queryKey: ['project', key, 'forecast'],
    queryFn: () => apiGet<Forecast>(`/api/projects/${enc(key ?? '')}/forecast`),
    enabled: !!key,
  })
}

export function useSignals(key: string | null) {
  return useQuery({
    queryKey: ['project', key, 'signals'],
    queryFn: () => apiGet<ProjectSignals>(`/api/projects/${enc(key ?? '')}/signals`),
    enabled: !!key,
  })
}

export function useExternalSummary() {
  return useQuery({
    queryKey: ['external', 'summary'],
    queryFn: () => apiGet<ExternalSummary>('/api/external/summary'),
  })
}

export function useAlerts(query: AlertQuery = {}) {
  return useQuery({
    queryKey: ['alerts', query],
    queryFn: () => apiGet<AlertPage>('/api/alerts', query),
    placeholderData: keepPreviousData,
    // ponytail: polling; the backend also has an SSE stream (/api/stream) if a minute is too slow
    refetchInterval: 60_000,
  })
}

export function useAckAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (vars: { id: number; role: Role }) =>
      apiPost<Alert>(`/api/alerts/${vars.id}/ack`, { role: vars.role }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['alerts'] }),
  })
}
