/**
 * src/lib/queries.ts
 *
 * TanStack Query hooks over the FastAPI backend. Every hook asks for an
 * aggregate, one page, or one project; nothing fetches a full table. When the
 * backend is down the hooks error with ApiError status 0 (see lib/api.ts) and
 * the views say so; there is no bundled fallback data.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiGet, apiPost } from '@/lib/api'
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
  ResearchSummary,
  Scopes,
  SignalFeed,
} from '@/contracts/portfolio'
import type {
  BriefOut,
  Flag,
  Forecast,
  MapRow,
  ProjectDetail,
  ProjectMap,
  ProjectPage,
  ProjectResearch,
  ProjectSignals,
  ProjectSort,
  SecondOpinionNone,
  SecondOpinionOut,
  TierFilter,
  Timeline,
} from '@/contracts/project'
import type { ModelsOut } from '@/contracts/audit'
import type { AgencyMatrix, BottleneckDetail, BottleneckPage } from '@/contracts/intel'
import type { DispatchDraft } from '@/contracts/workers'
import type {
  ApproveSignup, AuditPage, AuditQuery, RejectSignup, ResetToken, SignupRow, SignupStatus, User, UserPage, UserUpdate,
} from '@/contracts/auth'
import { useScopeKey } from '@/lib/auth/SessionContext'

export type PortfolioFilters = {
  ministry?: string
  sector?: string
  state?: string
  tier?: TierFilter
}

export type ProjectQuery = PortfolioFilters & {
  q?: string
  flag?: Flag
  /** 80-99% done and not past the anticipated completion */
  near_complete?: boolean
  sort?: ProjectSort
  order?: 'asc' | 'desc'
  page?: number
  size?: number
}

/** does the patch change a filter of the query (not the sort or the page, not a value it already has)? */
export function changesFilters(q: ProjectQuery, patch: Partial<ProjectQuery>): boolean {
  return (Object.keys(patch) as Array<keyof ProjectQuery>)
    .some((k) => k !== 'page' && k !== 'sort' && k !== 'order' && patch[k] !== q[k])
}

/** the tier a filter chip's click asks for: the chip's own, or All again (undefined) when that chip is already on */
export function tierAfterClick(current: TierFilter | undefined, chip: TierFilter | 'ALL'): TierFilter | undefined {
  return chip === 'ALL' || chip === current ? undefined : chip
}

/** does the query carry a filter (not just a sort or a page)? */
export function hasFilters(q: ProjectQuery): boolean {
  return !!(q.q || q.tier || q.sector || q.state || q.ministry || q.flag || q.near_complete)
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

/** Ministries and agencies an account can be scoped to (the same for every viewer): the request-access and admin pickers. */
export function useScopes() {
  return useQuery({ queryKey: ['scopes'], queryFn: () => apiGet<Scopes>('/api/scopes'), staleTime: Infinity })
}

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => apiGet<Meta>('/api/meta') })  // the same for every viewer
}

export function usePortfolio(filters: PortfolioFilters = {}) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['portfolio', filters, scope],
    queryFn: () => apiGet<Portfolio>('/api/portfolio', filters),
  })
}

export function useProjects(query: ProjectQuery, enabled = true) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['projects', query, scope],
    queryFn: () => apiGet<ProjectPage>('/api/projects', query),
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** the list's filters without its sort and paging: what the map is asked for */
function mapFilters(q: ProjectQuery): ProjectQuery {
  const { q: text, tier, sector, state, ministry, flag, near_complete } = q
  return { q: text, tier, sector, state, ministry, flag, near_complete }
}

/** the fallback's size: the list's cap per request (backend/routes.py le=100); nothing asks for more */
export const MAP_FALLBACK_SIZE = 100

/** a backend without GET /api/projects/map answers 400 (the key rule) or 404: remembered, so it is asked once */
let mapMissing = false

export interface ProjectMapResult {
  rows: MapRow[] | undefined
  /** rows in scope for these filters */
  total: number | undefined
  /** set when rows are only the riskiest MAP_FALLBACK_SIZE (no map endpoint): the caption says so */
  partial: { shown: number; total: number } | null
  isLoading: boolean
  isFetching: boolean
  error: unknown
}

/**
 * Every row in scope for the command centre's risk map (GET /api/projects/map, the list's filters, no paging). A
 * backend without that endpoint gets one ask, then the list's first page of the MAP_FALLBACK_SIZE riskiest instead,
 * and `partial` tells the caption. enabled false: nothing is asked.
 */
export function useProjectMap(query: ProjectQuery, enabled = true): ProjectMapResult {
  const scope = useScopeKey()
  const filters = mapFilters(query)
  const map = useQuery({
    queryKey: ['projects', 'map', filters, scope],
    queryFn: async (): Promise<ProjectMap | null> => {
      try {
        const r = await apiGet<ProjectMap | MapRow[]>('/api/projects/map', filters)
        return Array.isArray(r) ? { total: r.length, items: r } : r
      } catch (e) {
        if (e instanceof ApiError && (e.status === 400 || e.status === 404 || e.status === 405)) {
          mapMissing = true
          return null
        }
        throw e
      }
    },
    enabled: enabled && !mapMissing,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const fallback = mapMissing || map.data === null
  const list = useProjects({ ...filters, sort: 'risk', order: 'desc', page: 1, size: MAP_FALLBACK_SIZE }, enabled && fallback)
  if (fallback) {
    const page = list.data
    return {
      rows: page?.items,
      total: page?.total,
      partial: page && page.total > page.items.length ? { shown: page.items.length, total: page.total } : null,
      isLoading: list.isLoading,
      isFetching: list.isFetching,
      error: list.error,
    }
  }
  return {
    rows: map.data?.items,
    total: map.data?.total,
    partial: null,
    isLoading: map.isLoading,
    isFetching: map.isFetching,
    error: map.error,
  }
}

export function useProject(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, scope],
    queryFn: () => apiGet<ProjectDetail>(`/api/projects/${enc(key ?? '')}`),
    enabled: !!key,
  })
}

export function useTimeline(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'timeline', scope],
    queryFn: () => apiGet<Timeline>(`/api/projects/${enc(key ?? '')}/timeline`),
    enabled: !!key,
  })
}

/** 404 when the project is not in the current scored portfolio. */
export function useForecast(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'forecast', scope],
    queryFn: () => apiGet<Forecast>(`/api/projects/${enc(key ?? '')}/forecast`),
    enabled: !!key,
  })
}

export function useSignals(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'signals', scope],
    queryFn: () => apiGet<ProjectSignals>(`/api/projects/${enc(key ?? '')}/signals`),
    enabled: !!key,
  })
}

/**
 * The validated LLM brief; only fetched once asked for (it can take a while). Errors: 422 with a
 * BriefRejected body, 503 when LM Studio is not running, 404 when the project is not scored.
 */
export function useBrief(key: string | null, requested: boolean) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'brief', scope],
    queryFn: () => apiGet<BriefOut>(`/api/projects/${enc(key ?? '')}/brief`),
    enabled: !!key && requested,
    staleTime: Infinity,
  })
}

/** Every web research fact of one project, newest first (every role; the public gets the redacted facts). */
export function useResearch(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'research', scope],
    queryFn: () => apiGet<ProjectResearch>(`/api/projects/${enc(key ?? '')}/research`),
    enabled: !!key,
  })
}

/** Web research over the viewer's current projects: coverage, blockers by category and state, the newest blockers. */
export function useResearchSummary() {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['research', 'summary', scope],
    queryFn: () => apiGet<ResearchSummary>('/api/research/summary'),
  })
}

/**
 * The AI second opinion, generated on demand like the brief (a minute or two on the local model); only fetched
 * once asked for. The fetch keeps going when its panel closes, and the answer lands in this cache. Errors: 422
 * with a SecondOpinionRejected body, 503 when LM Studio is not running, 404 when the project is not scored.
 */
export function useSecondOpinion(key: string | null, requested: boolean) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'second-opinion', scope],
    queryFn: () => apiGet<SecondOpinionOut>(`/api/projects/${enc(key ?? '')}/second-opinion`),
    enabled: !!key && requested,
    staleTime: Infinity,
  })
}

/** The stored second opinion for the project's current evidence, never generating one; status 'none' when absent. */
export function useCachedSecondOpinion(key: string | null) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['project', key, 'second-opinion', 'cached', scope],
    queryFn: () =>
      apiGet<SecondOpinionOut | SecondOpinionNone>(`/api/projects/${enc(key ?? '')}/second-opinion`, { cached: 1 }),
    enabled: !!key,
  })
}

/** Champion registry + the champion run's backtest and ablation tables (a few dozen rows). */
export function useModels() {
  const scope = useScopeKey()
  return useQuery({ queryKey: ['models', scope], queryFn: () => apiGet<ModelsOut>('/api/models') })
}

/** includeHidden: also the agencies with n < 5 */
export function useAgencyMatrix(includeHidden: boolean) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['agencies', 'matrix', includeHidden, scope],
    queryFn: () => apiGet<AgencyMatrix>('/api/agencies/matrix', { include_hidden: includeHidden || undefined }),
    placeholderData: keepPreviousData,
  })
}

/** Current projects of one canonical agency, riskiest first. */
export function useAgencyProjects(agency: string | null, page: number, size = 20) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['agencies', agency, 'projects', page, size, scope],
    queryFn: () => apiGet<ProjectPage>(`/api/agencies/${enc(agency ?? '')}/projects`, { page, size }),
    placeholderData: keepPreviousData,
    enabled: !!agency,
  })
}

/** Every bottleneck in one page (13 today); the page filters and sorts them itself. */
export function useBottlenecks() {
  // ponytail: one page of 100, server-side filters and paging if clusters ever pass that
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['bottlenecks', scope],
    queryFn: () => apiGet<BottleneckPage>('/api/bottlenecks', { size: 100 }),
  })
}

export function useBottleneck(id: string | null, page: number, size = 20) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['bottlenecks', id, page, size, scope],
    queryFn: () => apiGet<BottleneckDetail>(`/api/bottlenecks/${enc(id ?? '')}`, { page, size }),
    placeholderData: keepPreviousData,
    enabled: !!id,
  })
}

export function useExternalSummary() {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['external', 'summary', scope],
    queryFn: () => apiGet<ExternalSummary>('/api/external/summary'),
  })
}

/** enabled false: not asked (a viewer without alerts) */
export function useAlerts(query: AlertQuery = {}, enabled = true) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['alerts', query, scope],
    queryFn: () => apiGet<AlertPage>('/api/alerts', query),
    placeholderData: keepPreviousData,
    enabled,
    // no polling: useAlertStream refetches every alert query when /api/stream pushes one
  })
}

/** Acknowledged as the signed-in user (the session cookie); the backend records who. */
export function useAckAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiPost<Alert>(`/api/alerts/${id}/ack`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['alerts'] }),
  })
}

export function useLiveStatus() {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['live', 'status', scope],
    queryFn: () => apiGet<LiveStatus>('/api/live/status'),
    // every 5 s while a job runs, so its progress and end show without a reload
    refetchInterval: (q) => (q.state.data?.scout.running || q.state.data?.watch.running ? 5_000 : 30_000),
  })
}

/** Runs the inbox watcher now (in the background on the server); its result shows in the status and the alerts. */
export function useWatchNow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<JobStarted>('/api/jobs/watch'),
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
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['signals', 'feed', page, size, filters, scope],
    queryFn: () => apiGet<SignalFeed>('/api/signals/feed', { page, size, ...filters }),
    placeholderData: keepPreviousData,
  })
}

/** under ['signals'], so the alert stream refreshes it with the feed */
export function useRadarSummary() {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['signals', 'radar-summary', scope],
    queryFn: () => apiGet<RadarSummary>('/api/radar/summary'),
  })
}

/** Worker-cell memos the viewer may see: addressed to their role, on their projects (IPMD: all). */
export function useDispatchDrafts() {
  const scope = useScopeKey()
  return useQuery({ queryKey: ['dispatch', 'drafts', scope], queryFn: () => apiGet<DispatchDraft[]>('/api/dispatch') })
}

/** Starts a scout batch in the background; its progress shows in the live status (scout.running). */
export function useScoutNow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<JobStarted>('/api/jobs/scout'),
    onSuccess: () => client.invalidateQueries({ queryKey: ['live'] }),
  })
}

/* administration (need admin; contracts/auth.ts): sign-up requests, accounts and the audit log. Under ['admin'] so
   one review or update refetches every admin list. */

export function useSignups(status: SignupStatus) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['admin', 'signups', status, scope],
    queryFn: () => apiGet<SignupRow[]>('/api/admin/signups', { status }),
  })
}

/** approve (the role and scope may be corrected in the body; answers the User) or reject one request */
export function useReviewSignup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision, body }: { id: number; decision: 'approve' | 'reject'; body: ApproveSignup | RejectSignup }) =>
      apiPost<User | undefined>(`/api/admin/signups/${id}/${decision}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin'] }),
  })
}

/** one page of accounts, filtered by q over email and name */
export function useUsers(q: string, page: number, size = 25) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['admin', 'users', q, page, size, scope],
    queryFn: () => apiGet<UserPage>('/api/admin/users', { q, page, size }),
    placeholderData: keepPreviousData,
  })
}

/** status, role, scope or the admin flag of one account; the backend refuses an admin's own demotion or disabling */
export function useUpdateUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: UserUpdate }) => apiPost<User>(`/api/admin/users/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })
}

/** a one-time reset token for the account: the page shows it once and never stores it */
export function useResetUserPassword() {
  return useMutation({ mutationFn: (id: number) => apiPost<ResetToken>(`/api/admin/users/${id}/reset-password`) })
}

export function useAudit(query: AuditQuery) {
  const scope = useScopeKey()
  return useQuery({
    queryKey: ['admin', 'audit', query, scope],
    queryFn: () => apiGet<AuditPage>('/api/admin/audit', query),
    placeholderData: keepPreviousData,
  })
}
