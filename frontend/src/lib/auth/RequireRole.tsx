import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useRole, type Role } from './RoleContext'

interface RequireRoleProps {
  children: ReactNode
  /** If set, only these roles may view the route (role must also be non-null). */
  roles?: Role[]
}

/**
 * Route gate for the prototype role picker.
 * No role at all -> /login. Role set but not in the allowed list -> back to Home.
 */
export function RequireRole({ children, roles }: RequireRoleProps) {
  const { role } = useRole()

  if (!role) return <Navigate to="/login" replace />
  if (roles && !roles.includes(role)) return <Navigate to="/" replace />

  return <>{children}</>
}
