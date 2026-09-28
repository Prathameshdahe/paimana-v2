import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useSession } from './SessionContext'
import { canOpen } from './access'

/**
 * Route gate from the access map (lib/auth/access.ts). A page the public may open needs no sign-in. Not signed in
 * and the page is for officials -> /login, which comes back here afterwards and says so when the session expired;
 * signed in without access (or /admin without the admin flag) -> Home. Nothing is decided until the session is
 * known, so a refresh on an officials' page never bounces an official to /login.
 */
export function RequireRole({ children }: { children: ReactNode }) {
  const { role, isAdmin, status, expired } = useSession()
  const { pathname, search } = useLocation()

  if (status === 'loading') return null
  if (canOpen(role, pathname, isAdmin)) return <>{children}</>
  if (role) return <Navigate to="/" replace />
  return <Navigate to="/login" replace state={{ from: pathname + search, expired }} />
}
