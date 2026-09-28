import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { onUnauthorized, setCsrfToken } from '@/lib/api'
import { fetchMe, logout } from './authApi'
import { PUBLIC, sessionOf, type Session } from './session'
import type { Me } from '@/contracts/auth'

export type { AccountRole, OfficialRole, Role, Session } from './session'

/**
 * src/lib/auth/SessionContext.tsx
 *
 * Who is signed in, from the backend's session cookie. On load GET /api/auth/me gives Me — role, scope, the admin
 * flag and the CSRF token that lib/api.ts sends with every non-GET request; 401 (and 404 from a backend without the
 * sign-in routes) is no session, which is the public. Nothing about the viewer is kept in the browser: the cookie
 * is HttpOnly and the backend cuts every answer to the session's scope (backend/access.py). signIn(me) is called by
 * /login after POST /api/auth/login; signOut() posts /api/auth/logout. Both clear the query cache so no official's
 * data stays in memory. A 401 on any later call (lib/api.ts onUnauthorized) clears the session as expired, which
 * RequireRole turns into a notice on /login and the top bar into a banner.
 */
export interface SessionState extends Session {
  /** 'loading' until GET /api/auth/me answered once: the routes wait for it, so an official never sees the public page first */
  status: 'loading' | 'ready'
  /** a signed-in session was lost on a later call (401); cleared by the next sign-in or sign-out */
  expired: boolean
  signIn: (me: Me) => void
  signOut: () => Promise<void>
}

const SessionContext = createContext<SessionState | null>(null)

interface Held {
  status: 'loading' | 'ready'
  session: Session
  expired: boolean
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [held, setHeld] = useState<Held>({ status: 'loading', session: PUBLIC, expired: false })

  useEffect(() => {
    let live = true
    // a 401 while signed in: the session is gone; the cache goes after the failing call has settled
    onUnauthorized(() => {
      setCsrfToken(null)
      setHeld((h) => {
        if (!h.session.role) return h
        setTimeout(() => client.clear(), 0)
        return { status: 'ready', session: PUBLIC, expired: true }
      })
    })
    fetchMe()
      .then((me) => {
        if (!live) return
        setCsrfToken(me?.csrfToken ?? null)
        setHeld({ status: 'ready', session: me ? sessionOf(me) : PUBLIC, expired: false })
      })
      .catch(() => {
        if (live) setHeld({ status: 'ready', session: PUBLIC, expired: false })
      })
    return () => {
      live = false
      onUnauthorized(null)
    }
  }, [client])

  const signIn = useCallback((me: Me) => {
    setCsrfToken(me.csrfToken)
    setHeld({ status: 'ready', session: sessionOf(me), expired: false })
    client.clear()
  }, [client])

  const signOut = useCallback(async () => {
    try {
      await logout() // needs the CSRF token, so before it is cleared
    } catch {
      // the session is dropped here whatever the backend said; an unreachable backend cannot keep it alive
    }
    setCsrfToken(null)
    setHeld({ status: 'ready', session: PUBLIC, expired: false })
    client.clear()
  }, [client])

  return (
    <SessionContext.Provider value={{ ...held.session, status: held.status, expired: held.expired, signIn, signOut }}>
      {children}
    </SessionContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionState {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession() must be used within <SessionProvider>')
  return ctx
}

/** The scope a query depends on; part of every query key, so a sign-in or sign-out refetches. */
// eslint-disable-next-line react-refresh/only-export-components
export function useScopeKey(): string {
  const { role, ministry, agency } = useSession()
  return `${role ?? 'public'}:${ministry ?? agency ?? ''}`
}
