/**
 * src/lib/auth/session.ts
 *
 * The session as the pages read it (SessionContext holds it): a Me from GET /api/auth/me turned into the role, the
 * scope under the key its role reads, and the admin flag; the public is PUBLIC. Kept apart from the context so the
 * shapes can be imported anywhere (and checked) without a component file.
 */
import type { AccountRole, Me, OfficialRole } from '@/contracts/auth'

export type Role = AccountRole | 'public'
export type { AccountRole, OfficialRole }

export interface Session {
  /** null: the public (no session) */
  role: AccountRole | null
  userId: number | null
  email: string | null
  displayName: string
  /** ministry_official: the ministry they see */
  ministry?: string
  /** agency_official: the canonical agency they see */
  agency?: string
  isAdmin: boolean
  sessionExpiresAt: string | null
}

export const PUBLIC: Session = {
  role: null, userId: null, email: null, displayName: '', isAdmin: false, sessionExpiresAt: null,
}

/**
 * the session a Me describes; the scope goes under the key its role reads. The admin flag counts for IPMD; the
 * developer holds every feature, administration included.
 */
export function sessionOf(me: Me): Session {
  return {
    role: me.role,
    userId: me.userId,
    email: me.email,
    displayName: me.displayName?.trim() || me.email,
    ministry: me.role === 'ministry_official' && me.ministry ? me.ministry : undefined,
    agency: me.role === 'agency_official' && me.agency ? me.agency : undefined,
    isAdmin: (me.role === 'ipmd_analyst' && me.isAdmin) || me.role === 'developer',
    sessionExpiresAt: me.sessionExpiresAt,
  }
}
