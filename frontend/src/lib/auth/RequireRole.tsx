import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useRole } from './RoleContext'
import { canOpen } from './access'

/**
 * Route gate from the access map (lib/auth/access.ts). A page the public may open needs no sign-in.
 * Not signed in and the page is for officials -> /login; signed in without access -> Home.
 */
export function RequireRole({ children }: { children: ReactNode }) {
  const { role } = useRole()
  const { pathname } = useLocation()

  if (canOpen(role, pathname)) return <>{children}</>
  return <Navigate to={role ? '/' : '/login'} replace />
}
