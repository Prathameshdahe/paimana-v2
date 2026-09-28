/**
 * src/lib/api.ts
 *
 * The typed fetch helpers every query hook uses. Requests go to API_BASE + path: '' by default, so they are
 * same-origin (the Vite dev server proxies /api to the backend, nginx does in production) and the session cookie
 * rides along; VITE_API_BASE overrides for a backend on another origin, where `credentials: 'include'` and the
 * backend's CORS allow-list (settings.allowed_origins) carry the cookie.
 *
 * Sessions (lib/auth/SessionContext): the backend sets an HttpOnly cookie at sign-in and GET /api/auth/me returns the
 * CSRF token, which every non-GET request sends back as X-CSRF-Token. The public has no cookie and no token, and
 * needs neither. A 401 on any call means the session is gone (expired, revoked, signed out elsewhere): the session
 * context hears it through onUnauthorized and turns the viewer public.
 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

export const START_BACKEND = 'python -m uvicorn backend.main:app --port 8000 --timeout-graceful-shutdown 3'

export type Params = Record<string, string | number | boolean | null | undefined>

let csrfToken: string | null = null

/** the session's CSRF token from GET /api/auth/me, or null when the viewer is the public */
export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

let unauthorized: (() => void) | null = null

/** called once per 401 answer (unless the request said quiet401): the session context clears the session */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorized = handler
}

/** a 401 seen by a caller that does not go through request() (the chat stream) */
export function reportUnauthorized(): void {
  unauthorized?.()
}

/** the headers a non-GET request needs beyond its body: the CSRF token when signed in (the chat stream uses it too) */
export function authHeaders(): Record<string, string> {
  return csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
}

/** status 0: the request never reached the backend (not running, wrong API_BASE, CORS). */
export class ApiError extends Error {
  status: number
  /** the parsed JSON error body, when there is one */
  body: unknown
  /** seconds to wait, from a Retry-After header (429, 423) or a `retryAfter` in the body; null when not given */
  retryAfter: number | null
  constructor(status: number, message: string, body?: unknown, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.body = body
    this.retryAfter = retryAfter
  }
}

export function isOffline(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0
}

export function url(path: string, params?: Params): string {
  const u = new URL(API_BASE + path, window.location.origin)
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, String(v))
  }
  return u.toString()
}

export interface RequestOptions {
  /** a 401 is a normal answer here (GET /api/auth/me for the public): do not tell the session it was lost */
  quiet401?: boolean
}

/** "Please try again in 40 seconds." / "in 15 minutes." */
export function waitText(seconds: number): string {
  const s = Math.ceil(seconds)
  if (s < 90) return `${s} second${s === 1 ? '' : 's'}`
  const m = Math.ceil(s / 60)
  return `${m} minute${m === 1 ? '' : 's'}`
}

/**
 * A failed response as an ApiError: the message is the JSON `detail` when there is one, else for a 429 or 423 with a
 * Retry-After the wait, else the status text.
 */
export async function failure(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`
  let body: unknown
  let given = false
  try {
    body = await res.json()
    const d = (body as { detail?: unknown } | null)?.detail
    if (typeof d === 'string') {
      detail = d
      given = true
    }
  } catch {
    // not a JSON error body
  }
  const fromBody = (body as { retryAfter?: unknown } | null)?.retryAfter
  const header = Number(res.headers.get('Retry-After'))
  const wait = typeof fromBody === 'number' && fromBody > 0 ? fromBody : header > 0 ? header : null
  if ((res.status === 429 || res.status === 423) && !given && wait) detail = `Please try again in ${waitText(wait)}.`
  return new ApiError(res.status, detail, body, wait)
}

/** the JSON body; a 204 or an empty body is undefined */
async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

async function request<T>(method: string, path: string, params?: Params, body?: unknown, opts?: RequestOptions): Promise<T> {
  let res: Response
  try {
    res = await fetch(url(path, params), {
      method,
      headers: {
        ...(method === 'GET' ? {} : authHeaders()),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
    })
  } catch {
    throw new ApiError(0, `backend not reachable at ${API_BASE || window.location.origin}`)
  }
  if (res.status === 401 && !opts?.quiet401) unauthorized?.()
  if (!res.ok) throw await failure(res)
  return parse<T>(res)
}

export function apiGet<T>(path: string, params?: Params, opts?: RequestOptions): Promise<T> {
  return request<T>('GET', path, params, undefined, opts)
}

export function apiPost<T>(path: string, body?: unknown, params?: Params, opts?: RequestOptions): Promise<T> {
  return request<T>('POST', path, params, body, opts)
}
