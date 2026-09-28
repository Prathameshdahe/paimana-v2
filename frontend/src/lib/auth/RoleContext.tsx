import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { setViewer } from '@/lib/api'

/**
 * src/lib/auth/RoleContext.tsx
 *
 * PROTOTYPE sign-in — no real authentication. The role and its scope (a
 * ministry or a canonical agency) persist in localStorage so a refresh keeps
 * them, and lib/api.ts sends them as X-Paimana-* headers (the backend cuts
 * every answer to that scope; backend/access.py). No role is the public.
 * Swap for real session auth when it exists; consumers can keep this shape.
 */
export type Role = 'ipmd_analyst' | 'ministry_official' | 'agency_official' | 'public'

export interface Session {
  role: Role | null
  displayName: string
  /** ministry_official: the ministry they see */
  ministry?: string
  /** agency_official: the canonical agency they see */
  agency?: string
}

interface RoleState extends Session {
  setRole: (session: Session) => void
  clearRole: () => void
}

const STORAGE_KEY = 'paimana.role'
const SIGNED_OUT: Session = { role: null, displayName: '' }

const RoleContext = createContext<RoleState | null>(null)

/** A scoped role stored without its scope (an older sign-in) counts as signed out. */
function valid(s: Session): Session {
  if (s.role === 'ministry_official' && !s.ministry) return SIGNED_OUT
  if (s.role === 'agency_official' && !s.agency) return SIGNED_OUT
  return s
}

function readStored(): Session {
  let s = SIGNED_OUT
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const p = JSON.parse(raw) as Partial<Session>
      s = valid({ role: p.role ?? null, displayName: p.displayName ?? '', ministry: p.ministry, agency: p.agency })
    }
  } catch {
    // storage disabled or bad JSON: signed out
  }
  setViewer(s) // before the first query goes out
  return s
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(readStored)

  const setRole = useCallback((session: Session) => {
    const s = valid(session)
    setViewer(s)
    setState(s)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    } catch {
      // sandboxed preview / storage disabled — the role still works for this session
    }
  }, [])

  const clearRole = useCallback(() => {
    setViewer(SIGNED_OUT)
    setState(SIGNED_OUT)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // sandboxed preview / storage disabled
    }
  }, [])

  return <RoleContext.Provider value={{ ...state, setRole, clearRole }}>{children}</RoleContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRole(): RoleState {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole() must be used within <RoleProvider>')
  return ctx
}

/** The scope a query depends on; part of every query key, so switching role refetches. */
// eslint-disable-next-line react-refresh/only-export-components
export function useScopeKey(): string {
  const { role, ministry, agency } = useRole()
  return `${role ?? 'public'}:${ministry ?? agency ?? ''}`
}
