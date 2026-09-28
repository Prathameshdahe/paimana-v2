/**
 * src/lib/auth/access.ts
 *
 * The one access map of the frontend: which role opens which page and uses which feature. Routes
 * (App.tsx), the nav, the bell, the chat, live controls, the account menu and the project page all read it.
 * The backend enforces the same rules (backend/access.py POLICY; docs/ACCESS_CONTROL.md) — this map
 * only decides what is shown. No session (not signed in) is the public. Administration is the one page a
 * role alone does not open: it needs the session's admin flag as well (canAdmin). The hidden developer role
 * (SPEC9_ui section 7) is in every group and alone holds the raw model numbers (canSeeNumbers): the four other roles
 * read words, bands, tiers and report facts, and the backend cuts the numbers out of their answers.
 */
import type { Role } from './SessionContext'

const EVERYONE: Role[] = ['public', 'agency_official', 'ministry_official', 'ipmd_analyst', 'developer']
const OFFICIALS: Role[] = ['agency_official', 'ministry_official', 'ipmd_analyst', 'developer']
const MINISTRY_UP: Role[] = ['ministry_official', 'ipmd_analyst', 'developer']
const IPMD: Role[] = ['ipmd_analyst', 'developer']
const DEVELOPER: Role[] = ['developer']

export const FEATURE_ROLES = {
  /**
   * the officials' project evidence (backend: insights): the paths ahead, similar past projects, the AI brief, linked
   * news and the checks' evidence lines — in words; the numbers behind them are canSeeNumbers
   */
  canSeeDrivers: OFFICIALS,
  /** alert bell, alert inbox, live stream */
  canSeeAlerts: OFFICIALS,
  canAck: MINISTRY_UP,
  /** the project assistant; each of its tools reads only what the viewer may (backend llm/tools.py) */
  canChat: EVERYONE,
  /** the live job status strip */
  canSeeLive: OFFICIALS,
  /** the linked news feed (External Evidence Radar data) */
  canSeeNews: OFFICIALS,
  /** the AI second opinion on a project (backend: need insights); it never changes the tier */
  canSeeSecondOpinion: OFFICIALS,
  /** check inbox, run scout, worker trigger (backend: jobs) */
  canRunJobs: DEVELOPER,
  /** pipeline-error alerts (backend: IPMD only) */
  canSeePipelineErrors: IPMD,
  /** users and sign-up requests (backend: need admin); the role half of canAdmin */
  canAdmin: IPMD,
  /** the Models page: accuracy, backtests, calibration and the registry (backend: models) */
  canSeeModels: DEVELOPER,
  /** the Worker Console (backend: workers) */
  canSeeWorkers: DEVELOPER,
  /** the audit log, the Administration page's third tab (backend: audit) */
  canSeeAudit: DEVELOPER,
  /**
   * the raw model numbers (backend: numbers): probabilities, SHAP values, quantile intervals, rank percentiles, bias
   * statistics, CIs, lifts, analogue distances and rates, scenario values. The project page's Model detail tab.
   */
  canSeeNumbers: DEVELOPER,
} satisfies Record<string, Role[]>

/** page path (first segment) -> roles that may open it */
export const ROUTE_ROLES: Record<string, Role[]> = {
  '/': EVERYONE,
  '/command': EVERYONE, // the project list + search; read-only for the public
  '/projects': EVERYONE, // the public page is the simple one (no drivers, analogues, intervals)
  '/external': EVERYONE,
  '/bottlenecks': OFFICIALS,
  '/agencies': OFFICIALS,
  '/radar': OFFICIALS,
  '/approvals': OFFICIALS,
  '/models': FEATURE_ROLES.canSeeModels, // accuracy, backtests, calibration: model statistics (SPEC9_ui section 6)
  '/workers': FEATURE_ROLES.canSeeWorkers,
  '/admin': IPMD, // and the admin flag (ADMIN_ROUTES); the audit tab needs canSeeAudit
}

/** pages that need the session's admin flag on top of the role */
const ADMIN_ROUTES = new Set(['/admin'])

export type Feature = keyof typeof FEATURE_ROLES

export function can(role: Role | null, feature: Feature): boolean {
  return FEATURE_ROLES[feature].includes(role ?? 'public')
}

/** an administrator: an IPMD analyst whose account carries the admin flag (secure.txt section 17) */
export function canAdmin(viewer: { role: Role | null; isAdmin: boolean }): boolean {
  return viewer.isAdmin && can(viewer.role, 'canAdmin')
}

const first = (path: string) => '/' + (path.split('/')[1] ?? '')

/** roles for a path: its first segment ('/projects/PRJ-1' -> '/projects'); unknown paths are everyone's */
export function routeRoles(path: string): Role[] {
  return ROUTE_ROLES[first(path)] ?? EVERYONE
}

export function canOpen(role: Role | null, path: string, isAdmin = false): boolean {
  return routeRoles(path).includes(role ?? 'public') && (isAdmin || !ADMIN_ROUTES.has(first(path)))
}
