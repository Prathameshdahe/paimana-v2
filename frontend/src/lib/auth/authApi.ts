/**
 * src/lib/auth/authApi.ts
 *
 * The sign-in calls (backend /api/auth/*, contracts/auth.ts) as plain functions: the session context and the
 * sign-in, request-access, reset and change-password forms call them. They are not query hooks because none of
 * them is cached; each is one action with one answer. loginError puts a failed sign-in into one sentence.
 */
import { ApiError, apiGet, apiPost, isOffline, waitText } from '@/lib/api'
import type {
  DemoInfo, DemoLoginRequest, LoginRequest, Me, PasswordChange, PasswordReset, SignupAccepted, SignupRequest,
} from '@/contracts/auth'

/**
 * Who the cookie says is signed in, or null for the public. 401 is the public's normal answer; so is 404 from a
 * backend without the sign-in routes yet, and so is an unreachable backend (the pages say so themselves).
 */
export async function fetchMe(): Promise<Me | null> {
  try {
    return await apiGet<Me>('/api/auth/me', undefined, { quiet401: true })
  } catch (e) {
    if (e instanceof ApiError) return null
    throw e
  }
}

/** 200 Me (and the cookie) | 401 generic | 423 locked (retryAfter) | 429 (retryAfter) */
export function login(body: LoginRequest): Promise<Me> {
  return apiPost<Me>('/api/auth/login', body, undefined, { quiet401: true })
}

/**
 * whether the one-click demo sign-in is on; an older backend without the route (404) is { enabled: false }. Any other
 * failure (the api restarting, unreachable) is thrown, so the query retries instead of remembering "off".
 */
export async function demoInfo(): Promise<DemoInfo> {
  try {
    return await apiGet<DemoInfo>('/api/auth/demo', undefined, { quiet401: true })
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { enabled: false, roles: [] }
    throw e
  }
}

/**
 * 200 Me (and the cookie) for the role's demo account, for the ministry or agency named; replaces the current
 * session, so it switches roles and scopes | 400 an unknown ministry or agency
 */
export function demoLogin(body: DemoLoginRequest): Promise<Me> {
  return apiPost<Me>('/api/auth/demo', body, undefined, { quiet401: true })
}

/** 204; the session is revoked on the backend and the cookie cleared */
export function logout(): Promise<void> {
  return apiPost<undefined>('/api/auth/logout', undefined, undefined, { quiet401: true })
}

/** 202 {id} | 409 a request for this email is pending | 400/422 unknown scope or a weak password | 429 */
export function signup(body: SignupRequest): Promise<SignupAccepted> {
  return apiPost<SignupAccepted>('/api/auth/signup', body)
}

/** 204 | 401 the current password is wrong | 422 the new one fails the policy */
export function changePassword(body: PasswordChange): Promise<void> {
  return apiPost<undefined>('/api/auth/password', body, undefined, { quiet401: true })
}

/** 204 | 400/404 the token is unknown, used or expired | 422 the password fails the policy */
export function resetPassword(body: PasswordReset): Promise<void> {
  return apiPost<undefined>('/api/auth/reset', body)
}

/** a failed sign-in in one sentence; the 401 text is the backend's generic one and never says which half was wrong */
export function loginError(e: unknown): string {
  if (isOffline(e)) return 'The service is not reachable. Try again in a moment, or tell your administrator.'
  if (!(e instanceof ApiError)) return String(e)
  if (e.status === 401) return e.message || 'Email or password is wrong, or the account is locked or disabled.'
  if (e.status === 423) {
    return e.retryAfter ? `This account is locked. Try again in ${waitText(e.retryAfter)}.` : e.message
  }
  if (e.status === 429) return e.retryAfter ? `Too many attempts. Try again in ${waitText(e.retryAfter)}.` : e.message
  if (e.status === 404) return 'Sign-in is not available on this server yet.'
  return e.message
}

/** a failed access request in one sentence */
export function signupError(e: unknown): string {
  if (isOffline(e)) return 'The service is not reachable. Try again in a moment.'
  if (!(e instanceof ApiError)) return String(e)
  if (e.status === 409) return 'A request for this email is already waiting for review.'
  if (e.status === 429) return e.retryAfter ? `Too many requests from this network. Try again in ${waitText(e.retryAfter)}.` : e.message
  if (e.status === 404) return 'Requesting access is not available on this server yet.'
  return e.message
}

/** a failed password reset in one sentence */
export function resetError(e: unknown): string {
  if (isOffline(e)) return 'The service is not reachable. Try again in a moment.'
  if (!(e instanceof ApiError)) return String(e)
  if (e.status === 400 || e.status === 404) {
    return 'This reset token is not valid: it may have been used or expired. Ask your administrator for a new one.'
  }
  if (e.status === 429) return e.retryAfter ? `Too many attempts. Try again in ${waitText(e.retryAfter)}.` : e.message
  return e.message
}
