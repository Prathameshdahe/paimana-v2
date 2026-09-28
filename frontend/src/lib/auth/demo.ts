/**
 * src/lib/auth/demo.ts
 *
 * The one-click demo sign-in for recording a prototype walk-through (backend DEMO_LOGIN, off by default and in
 * production): GET /api/auth/demo says whether it is on and which roles it offers; one click signs in to that role's
 * demo account with a real session (POST /api/auth/demo), so every page, scope and the numbers policy are exactly
 * those of a real account. The sign-in page shows the roles as buttons and the account menu lists them to switch.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Building2, Globe, Landmark, Radar, ShieldCheck, Wrench, type LucideIcon } from 'lucide-react'
import { demoInfo, demoLogin, loginError } from './authApi'
import { useSession, type Session } from './SessionContext'
import type { DemoRole } from '@/contracts/auth'

/** what each role opens, in a few words, under its name on the button */
export const DEMO_HINTS: Record<DemoRole | 'public', string> = {
  public: 'no sign-in · the public pages',
  ipmd: 'every project · the analyst’s pages',
  ministry: 'one ministry’s projects',
  agency: 'one agency’s projects',
  admin: 'IPMD analyst · sign-up requests and accounts',
  developer: 'everything, with the model’s numbers',
}

export const DEMO_ICONS: Record<DemoRole | 'public', LucideIcon> = {
  public: Globe,
  ipmd: Radar,
  ministry: Landmark,
  agency: Building2,
  admin: ShieldCheck,
  developer: Wrench,
}

/** GET /api/auth/demo, asked once per page load */
export function useDemo() {
  return useQuery({ queryKey: ['auth', 'demo'], queryFn: demoInfo, staleTime: Infinity })
}

/** the demo role the session is (null for the public or an account the demo does not offer) */
export function demoRoleOf(s: Pick<Session, 'role' | 'isAdmin'>): DemoRole | null {
  if (s.role === 'developer') return 'developer'
  if (s.role === 'ipmd_analyst') return s.isAdmin ? 'admin' : 'ipmd'
  if (s.role === 'ministry_official') return 'ministry'
  if (s.role === 'agency_official') return 'agency'
  return null
}

/**
 * open(role): sign in to that role's demo account (or, for 'public', sign out) and go to its home page; pending is
 * the role being opened, error the last failure in one sentence.
 */
export function useOpenRole() {
  const { signIn, signOut, role: current } = useSession()
  const navigate = useNavigate()
  const [pending, setPending] = useState<DemoRole | 'public' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function open(role: DemoRole | 'public') {
    if (pending) return
    setPending(role)
    setError(null)
    try {
      if (role === 'public') {
        if (current) await signOut()
      } else {
        signIn(await demoLogin(role))
      }
      navigate('/', { replace: true })
    } catch (e) {
      setError(loginError(e))
    } finally {
      setPending(null)
    }
  }
  return { open, pending, error }
}
