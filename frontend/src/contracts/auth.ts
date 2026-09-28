/**
 * src/contracts/auth.ts
 *
 * Sign-in, accounts and administration (backend/auth, SPEC9 section 2), camelCase as backend/schemas.py serves them.
 * The session itself is an HttpOnly cookie the browser carries; the page only ever sees `Me`. Every non-GET request
 * that carries the cookie must send `Me.csrfToken` back as X-CSRF-Token (lib/api.ts does). The public has no row in
 * app.users: no session is the public.
 */

/** an account's role; the public is no role */
export type OfficialRole = 'agency_official' | 'ministry_official' | 'ipmd_analyst'

/** GET /api/auth/me and the answer of POST /api/auth/login; 401 when not signed in */
export interface Me {
  userId: number
  email: string
  displayName: string | null
  role: OfficialRole
  /** ministry_official: the ministry every page is cut to */
  ministry: string | null
  /** agency_official: the canonical agency every page is cut to */
  agency: string | null
  /** an IPMD analyst who administers users, sign-up requests and the audit log */
  isAdmin: boolean
  csrfToken: string
  sessionExpiresAt: string | null
}

export interface LoginRequest {
  email: string
  password: string
}

/** POST /api/auth/signup -> 202 SignupAccepted; 3 an hour per IP, one pending request per email */
export interface SignupRequest {
  email: string
  displayName: string
  role: OfficialRole
  ministry?: string
  agency?: string
  /** at most 500 characters */
  justification: string
  password: string
}

export interface SignupAccepted {
  id: number
}

/** POST /api/auth/password -> 204; other sessions of the account are signed out */
export interface PasswordChange {
  current: string
  new: string
}

/** POST /api/auth/reset -> 204, with the one-time token an administrator issued */
export interface PasswordReset {
  token: string
  password: string
}

/* administration (need admin): /api/admin/* */

export type SignupStatus = 'pending' | 'approved' | 'rejected'

/** GET /api/admin/signups?status= */
export interface SignupRow {
  id: number
  email: string
  displayName: string | null
  role: OfficialRole
  ministry: string | null
  agency: string | null
  justification: string | null
  status: SignupStatus
  createdAt: string
  reviewedBy: number | null
  reviewedAt: string | null
  reviewNote: string | null
  ip: string | null
}

/** POST /api/admin/signups/{id}/approve: the role and scope may be corrected before the account is created */
export interface ApproveSignup {
  note?: string
  role?: OfficialRole
  ministry?: string | null
  agency?: string | null
}

export interface RejectSignup {
  note: string
}

export type UserStatus = 'active' | 'disabled'

/** an account as the administration lists it and as approve / update return it */
export interface User {
  id: number
  email: string
  displayName: string | null
  role: OfficialRole
  ministry: string | null
  agency: string | null
  isAdmin: boolean
  status: UserStatus
  lockedUntil: string | null
  passwordChangedAt: string | null
  createdAt: string | null
  lastLoginAt: string | null
}

/** GET /api/admin/users?q=&page=&size= */
export interface UserPage {
  total: number
  page: number
  size: number
  items: User[]
}

/** POST /api/admin/users/{id}; an administrator cannot demote or disable themself */
export interface UserUpdate {
  status?: UserStatus
  role?: OfficialRole
  ministry?: string | null
  agency?: string | null
  isAdmin?: boolean
}

/** POST /api/admin/users/{id}/reset-password: shown once, never stored by the page */
export interface ResetToken {
  token: string
  expiresAt?: string | null
}

/** one row of app.audit_log: who did what, from where */
export interface AuditRow {
  id: number
  at: string
  userId: number | null
  email: string | null
  role: string | null
  ip: string | null
  action: string
  /** what it was done to: a project key, an alert id, a user id, or null */
  target: string | null
  detail: string | Record<string, unknown> | null
}

/** GET /api/admin/audit?since=&user=&action=&page=&size= */
export interface AuditPage {
  total: number
  page: number
  size: number
  items: AuditRow[]
}

/** a type, not an interface, so it passes as query Params (lib/api.ts) like AlertQuery does */
export type AuditQuery = {
  /** ISO date or time; rows at or after it */
  since?: string
  /** an email or a user id */
  user?: string
  action?: string
  page?: number
  size?: number
}
