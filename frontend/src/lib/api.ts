// Base URL of the FastAPI backend. Set VITE_API_BASE in the root .env to override.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export const START_BACKEND = 'python -m uvicorn backend.main:app --port 8000'

export type Params = Record<string, string | number | boolean | null | undefined>

/** status 0: the request never reached the backend (not running, wrong API_BASE, CORS). */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function isOffline(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0
}

function url(path: string, params?: Params): string {
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
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, `backend not reachable at ${API_BASE}`)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = (await res.json()) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
    } catch {
      // not a JSON error body
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export function apiGet<T>(path: string, params?: Params): Promise<T> {
  return request<T>('GET', path, params)
}

export function apiPost<T>(path: string, body?: unknown, params?: Params): Promise<T> {
  return request<T>('POST', path, params, body)
}
