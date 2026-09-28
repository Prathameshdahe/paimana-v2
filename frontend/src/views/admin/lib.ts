/**
 * src/views/admin/lib.ts
 *
 * What the three administration tabs share without JSX: the role words, the role-and-scope pair and its rules, the
 * table cell classes and the audit detail text. The components they share are in parts.tsx.
 */
import type { AuditRow, OfficialRole } from '@/contracts/auth'

export const ROLE_LABEL: Record<OfficialRole, string> = {
  ministry_official: 'Ministry official',
  agency_official: 'Agency official',
  ipmd_analyst: 'IPMD analyst',
}
export const ROLES: OfficialRole[] = ['ministry_official', 'agency_official', 'ipmd_analyst']

export interface RoleScope {
  role: OfficialRole
  ministry: string | null
  agency: string | null
}

/** the scope a role reads: the ministry, the agency, or none for IPMD */
export function scopeOf(v: RoleScope): string | null {
  return v.role === 'ministry_official' ? v.ministry : v.role === 'agency_official' ? v.agency : null
}

/**
 * an account the lists may show: never the hidden developer (the backend leaves it out of /api/admin/users too;
 * this keeps a stray row off the page)
 */
export function listed(u: { role: string }): boolean {
  return u.role !== 'developer'
}

/** a scoped role has its scope; IPMD needs none */
export function scopeComplete(v: RoleScope): boolean {
  return v.role === 'ipmd_analyst' || !!scopeOf(v)
}

export const TH = 'px-2 py-1.5 text-left text-xs font-medium text-fg-muted'
export const TD = 'px-2 py-1.5 align-top text-xs text-fg-base'

/** an audit row's detail in one line: the string as sent, or the JSON of an object */
export function detailText(d: AuditRow['detail']): string {
  if (d === null || d === undefined) return ''
  return typeof d === 'string' ? d : JSON.stringify(d)
}
