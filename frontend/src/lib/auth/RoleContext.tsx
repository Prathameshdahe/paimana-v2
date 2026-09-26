import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

/**
 * src/lib/auth/RoleContext.tsx
 *
 * PROTOTYPE role picker — no real authentication. Persists to localStorage
 * so a refresh doesn't kick you back to /login. Swap for real session auth
 * (JWT/cookie + backend user lookup) when that exists; this context's shape
 * (role, displayName) can stay the same for consumers.
 */
export type Role = 'ipmd_analyst' | 'ministry_official' | 'agency_official' | 'public'

interface RoleState {
  role: Role | null
  displayName: string
  setRole: (role: Role, displayName: string) => void
  clearRole: () => void
}

const STORAGE_KEY = 'paimana.role'

const RoleContext = createContext<RoleState | null>(null)

function readStored(): { role: Role | null; displayName: string } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { role: null, displayName: '' }
    const parsed = JSON.parse(raw) as { role?: Role; displayName?: string }
    return { role: parsed.role ?? null, displayName: parsed.displayName ?? '' }
  } catch {
    return { role: null, displayName: '' }
  }
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(readStored)

  const setRole = useCallback((role: Role, displayName: string) => {
    setState({ role, displayName })
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ role, displayName }))
    } catch {
      // sandboxed preview / storage disabled — role still works for this session
    }
  }, [])

  const clearRole = useCallback(() => {
    setState({ role: null, displayName: '' })
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // sandboxed preview / storage disabled
    }
  }, [])

  return (
    <RoleContext.Provider value={{ ...state, setRole, clearRole }}>
      {children}
    </RoleContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRole(): RoleState {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole() must be used within <RoleProvider>')
  return ctx
}
