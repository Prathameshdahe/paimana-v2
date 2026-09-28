/**
 * src/lib/auth/access.ts
 *
 * The one access map of the frontend: which role opens which page and uses which feature. Routes
 * (App.tsx), the nav, the bell, the chat, live controls and the project page all read it. The
 * backend enforces the same rules (backend/access.py POLICY; docs/ACCESS_CONTROL.md) — this map
 * only decides what is shown. No role (not signed in) is the public.
 */
import type { Role } from './RoleContext'

const EVERYONE: Role[] = ['public', 'agency_official', 'ministry_official', 'ipmd_analyst']
const OFFICIALS: Role[] = ['agency_official', 'ministry_official', 'ipmd_analyst']
const MINISTRY_UP: Role[] = ['ministry_official', 'ipmd_analyst']
const IPMD: Role[] = ['ipmd_analyst']

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
  '/models': MINISTRY_UP,
  '/workers': IPMD,
}

export const FEATURE_ROLES = {
  /** SHAP drivers, analogues, quantile intervals, provenance, forecast, brief, project news */
  canSeeDrivers: OFFICIALS,
  /** alert bell, alert inbox, live stream */
  canSeeAlerts: OFFICIALS,
  canAck: MINISTRY_UP,
  canChat: MINISTRY_UP,
  /** the live job status strip */
  canSeeLive: OFFICIALS,
  /** the linked news feed (External Evidence Radar data) */
  canSeeNews: OFFICIALS,
  /** check inbox, run scout, worker trigger */
  canRunJobs: IPMD,
  /** pipeline-error alerts (backend: IPMD only) */
  canSeePipelineErrors: IPMD,
  /** model versions and data provenance in the top bar */
  canSeeModelVersion: OFFICIALS,
} satisfies Record<string, Role[]>

export type Feature = keyof typeof FEATURE_ROLES

export function can(role: Role | null, feature: Feature): boolean {
  return FEATURE_ROLES[feature].includes(role ?? 'public')
}

/** roles for a path: its first segment ('/projects/PRJ-1' -> '/projects'); unknown paths are everyone's */
export function routeRoles(path: string): Role[] {
  return ROUTE_ROLES['/' + (path.split('/')[1] ?? '')] ?? EVERYONE
}

export function canOpen(role: Role | null, path: string): boolean {
  return routeRoles(path).includes(role ?? 'public')
}
