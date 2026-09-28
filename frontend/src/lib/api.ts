// Base URL of the FastAPI backend. Set VITE_API_BASE in the root .env to override.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export const START_BACKEND = 'python -m uvicorn backend.main:app --port 8000 --timeout-graceful-shutdown 3'

export type Params = Record<string, string | number | boolean | null | undefined>

/**
 * Who is asking, sent with every request as X-Paimana-Role / -Ministry / -Agency (URI-encoded).
 * PROTOTYPE: the backend trusts these (backend/access.py); real auth would replace this source.
 * No role is the public. Set by lib/auth/RoleContext.
 */
let viewer: { role: string | null; ministry?: string; agency?: string } = { role: null }

export function setViewer(v: { role: string | null; ministry?: string; agency?: string }): void {
  viewer = { role: v.role, ministry: v.ministry, agency: v.agency }
}

/** The viewer as request headers; exported for the chat stream (lib/chatStream.ts), which cannot use request(). */
export function viewerHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  if (viewer.role) h['X-Paimana-Role'] = viewer.role
  if (viewer.ministry) h['X-Paimana-Ministry'] = encodeURIComponent(viewer.ministry)
  if (viewer.agency) h['X-Paimana-Agency'] = encodeURIComponent(viewer.agency)
  return h
}

/** The same viewer as query parameters, for EventSource (it cannot send headers). */
export function viewerParams(): Params {
  return { role: viewer.role, ministry: viewer.ministry, agency: viewer.agency }
}

/** status 0: the request never reached the backend (not running, wrong API_BASE, CORS). */
export class ApiError extends Error {
  status: number
  /** the parsed JSON error body, when there is one */
  body: unknown
  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.status = status
    this.body = body
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

async function request<T>(method: string, path: string, params?: Params, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(url(path, params), {
      method,
      headers: body === undefined ? viewerHeaders() : { ...viewerHeaders(), 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, `backend not reachable at ${API_BASE}`)
  }
  if (!res.ok) {
    let detail = res.statusText
    let body: unknown
    try {
      body = await res.json()
      const d = (body as { detail?: unknown } | null)?.detail
      if (typeof d === 'string') detail = d
    } catch {
      // not a JSON error body
    }
    throw new ApiError(res.status, detail, body)
  }
  return res.json() as Promise<T>
}

export function apiGet<T>(path: string, params?: Params): Promise<T> {
  return request<T>('GET', path, params)
}

export function apiPost<T>(path: string, body?: unknown, params?: Params): Promise<T> {
  return request<T>('POST', path, params, body)
}
