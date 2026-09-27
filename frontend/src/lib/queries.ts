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
import type {
  AlertKind,
  Alert,
  AlertPage,
  ExternalSummary,
  JobStarted,
  LiveStatus,
  Meta,
  Portfolio,
  RadarSummary,
  SignalFeed,
} from '@/contracts/portfolio'
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
import type { ModelsOut } from '@/contracts/audit'
import type { AgencyMatrix, BottleneckDetail, BottleneckPage } from '@/contracts/intel'
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
  /** ISO time; created at or after */
  since?: string
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

/** Champion registry + the champion run's backtest and ablation tables (a few dozen rows). */
export function useModels() {
  return useQuery({ queryKey: ['models'], queryFn: () => apiGet<ModelsOut>('/api/models') })
}

/** includeHidden: also the agencies with n < 5 */
export function useAgencyMatrix(includeHidden: boolean) {
  return useQuery({
    queryKey: ['agencies', 'matrix', includeHidden],
    queryFn: () => apiGet<AgencyMatrix>('/api/agencies/matrix', { include_hidden: includeHidden || undefined }),
    placeholderData: keepPreviousData,
  })
}

/** Current projects of one canonical agency, riskiest first. */
export function useAgencyProjects(agency: string | null, page: number, size = 20) {
  return useQuery({
    queryKey: ['agencies', agency, 'projects', page, size],
    queryFn: () => apiGet<ProjectPage>(`/api/agencies/${enc(agency ?? '')}/projects`, { page, size }),
    placeholderData: keepPreviousData,
    enabled: !!agency,
  })
}

/** Every bottleneck in one page (13 today); the page filters and sorts them itself. */
export function useBottlenecks() {
  // ponytail: one page of 100, server-side filters and paging if clusters ever pass that
  return useQuery({
    queryKey: ['bottlenecks'],
    queryFn: () => apiGet<BottleneckPage>('/api/bottlenecks', { size: 100 }),
  })
}

export function useBottleneck(id: string | null, page: number, size = 20) {
  return useQuery({
    queryKey: ['bottlenecks', id, page, size],
    queryFn: () => apiGet<BottleneckDetail>(`/api/bottlenecks/${enc(id ?? '')}`, { page, size }),
    placeholderData: keepPreviousData,
    enabled: !!id,
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
    // no polling: useAlertStream refetches every alert query when /api/stream pushes one
  })
}

/** roles that may acknowledge an alert (the backend records whoever does) */
export const ACK_ROLES: Role[] = ['ipmd_analyst', 'ministry_official']

export function useAckAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (vars: { id: number; role: Role }) =>
      apiPost<Alert>(`/api/alerts/${vars.id}/ack`, { role: vars.role }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['alerts'] }),
  })
}

export function useLiveStatus() {
  return useQuery({
    queryKey: ['live', 'status'],
    queryFn: () => apiGet<LiveStatus>('/api/live/status'),
    // every 5 s while a job runs, so its progress and end show without a reload
    refetchInterval: (q) => (q.state.data?.scout.running || q.state.data?.watch.running ? 5_000 : 30_000),
  })
}

/** Runs the inbox watcher now (in the background on the server); its result shows in the status and the alerts. */
export function useWatchNow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (role: Role) => apiPost<JobStarted>('/api/jobs/watch', undefined, { role }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['live'] }),
  })
}

export type FeedFilters = {
  category?: string
  state?: string
  /** at least */
  severity?: number
  linked?: boolean
}

export function useSignalFeed(page: number, size = 20, filters: FeedFilters = {}) {
  return useQuery({
    queryKey: ['signals', 'feed', page, size, filters],
    queryFn: () => apiGet<SignalFeed>('/api/signals/feed', { page, size, ...filters }),
    placeholderData: keepPreviousData,
  })
}

/** under ['signals'], so the alert stream refreshes it with the feed */
export function useRadarSummary() {
  return useQuery({
    queryKey: ['signals', 'radar-summary'],
    queryFn: () => apiGet<RadarSummary>('/api/radar/summary'),
  })
}

/** Starts a scout batch in the background; its progress shows in the live status (scout.running). */
export function useScoutNow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (role: Role) => apiPost<JobStarted>('/api/jobs/scout', undefined, { role }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['live'] }),
  })
}
