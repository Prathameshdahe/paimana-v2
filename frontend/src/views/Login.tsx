import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { AccountLayout } from '@/components/layout/AccountLayout'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Field, FormError, FormNotice, PasswordInput } from '@/components/common/Form'
import { login, loginError } from '@/lib/auth/authApi'
import { DEMO_HINTS, DEMO_ICONS, demoRoleOf, useDemo, useOpenRole } from '@/lib/auth/demo'
import { useSession } from '@/lib/auth/SessionContext'
import type { DemoOption } from '@/contracts/auth'

/** where /login sends a viewer afterwards: back to the officials' page that sent them here, else Home */
interface FromState {
  from?: string
  expired?: boolean
}

/**
 * Sign-in in the account frame (components/layout/AccountLayout). With the demo sign-in on (backend DEMO_LOGIN, a
 * prototype setting) the card lists the roles and one click opens the dashboard as that role (lib/auth/demo); the
 * email form stays one link away. Otherwise the card is the email form (POST /api/auth/login): email, password with
 * show/hide, one primary button, and the two ways out for someone without an account. Errors stay inline. A viewer
 * sent here from an officials' page goes back to it after signing in, and an expired session says so.
 */
export function Login() {
  const demo = useDemo()
  const [withEmail, setWithEmail] = useState(false)
  const { expired } = useSession()
  const { state } = useLocation()
  const sayExpired = expired || !!(state as FromState | null)?.expired
  const demoOn = !!demo.data?.enabled

  if (demo.isLoading) return <AccountLayout><div className="h-64" aria-busy="true" /></AccountLayout>
  if (demoOn && !withEmail) {
    return (
      <AccountLayout wide>
        <DemoPicker roles={demo.data?.roles ?? []} expired={sayExpired} onEmail={() => setWithEmail(true)} />
      </AccountLayout>
    )
  }
  return (
    <AccountLayout>
      <EmailSignIn expired={sayExpired} onDemo={demoOn ? () => setWithEmail(false) : undefined} />
    </AccountLayout>
  )
}

/** the one-click list: the public, then every role the backend offers, each a button that opens its home page */
function DemoPicker({ roles, expired, onEmail }: { roles: DemoOption[]; expired: boolean; onEmail: () => void }) {
  const session = useSession()
  const current = session.role ? demoRoleOf(session) : 'public'
  const { open, pending, error } = useOpenRole()
  const options: Array<DemoOption | { role: 'public'; label: string; scope: null }> = [
    { role: 'public', label: 'Public', scope: null },
    ...roles,
  ]

  return (
    <>
      <h2 className="text-xl font-semibold text-fg-base">Open the dashboard as</h2>
      <p className="mt-1 text-sm text-fg-muted">Prototype mode: one click signs in to a demo account of that role.</p>
      {expired && <div className="mt-4"><FormNotice tone="warning">Your session expired. Pick a role again.</FormNotice></div>}

      <ul className="mt-6 space-y-2">
        {options.map((o) => {
          const Icon = DEMO_ICONS[o.role]
          const here = current === o.role
          return (
            <li key={o.role}>
              <button
                type="button"
                onClick={() => open(o.role)}
                disabled={!!pending}
                className="group flex w-full items-center gap-3 rounded-lg border border-border-default bg-surface-base px-3 py-2.5 text-left transition-colors hover:border-accent/50 hover:bg-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-wait disabled:opacity-60"
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-fg-base/5 text-fg-muted transition-colors group-hover:text-accent">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-fg-base">
                    {o.label}
                    {here && <span className="ml-2 text-xs font-normal text-fg-dimmed">current</span>}
                  </span>
                  <span className="block truncate text-xs text-fg-dimmed">{o.scope ?? DEMO_HINTS[o.role]}</span>
                </span>
                {pending === o.role ? (
                  <span className="text-xs text-fg-muted">Opening…</span>
                ) : (
                  <ChevronRight className="size-4 shrink-0 text-fg-dimmed transition-colors group-hover:text-accent" aria-hidden="true" />
                )}
              </button>
            </li>
          )
        })}
      </ul>

      {error && <div className="mt-4"><FormError>{error}</FormError></div>}
      <button
        type="button"
        onClick={onEmail}
        className="mt-5 text-sm font-medium text-accent underline-offset-2 hover:underline focus-visible:outline-none focus-visible:underline"
      >
        Sign in with email and password instead
      </button>
    </>
  )
}

/** the real sign-in: email and password */
function EmailSignIn({ expired, onDemo }: { expired: boolean; onDemo?: () => void }) {
  const { signIn } = useSession()
  const navigate = useNavigate()
  const { state } = useLocation()
  const from = (state as FromState | null)?.from
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    setPending(true)
    setError(null)
    try {
      const me = await login({ email: email.trim(), password })
      signIn(me)
      navigate(from && from.startsWith('/') ? from : '/', { replace: true })
    } catch (err) {
      setError(loginError(err))
      setPending(false)
    }
  }

  return (
    <>
      <h2 className="text-xl font-semibold text-fg-base">Sign in</h2>
      <p className="mt-1 text-sm text-fg-muted">Officials sign in with their account. The public needs none.</p>

      <form onSubmit={submit} noValidate className="mt-6 space-y-4">
        {expired && <FormNotice tone="warning">Your session expired. Sign in again.</FormNotice>}
        <Field label="Email">
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="email"
              name="email"
              autoComplete="username"
              autoFocus
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-describedby={describedBy}
              className="py-2.5"
            />
          )}
        </Field>
        <Field label="Password">
          {({ id, describedBy }) => (
            <PasswordInput
              id={id}
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={describedBy}
              className="py-2.5"
            />
          )}
        </Field>
        {error && <FormError>{error}</FormError>}
        <Button type="submit" variant="primary" className="w-full" disabled={pending || !email.trim() || !password}>
          {pending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>

      <p className="mt-5 text-sm text-fg-muted">
        No account yet?{' '}
        <Link to="/signup" className="font-medium text-accent underline-offset-2 hover:underline">Request access</Link>
      </p>
      <Button variant="secondary" className="mt-4 w-full" onClick={() => navigate('/')}>
        Continue as public
      </Button>
      {onDemo && (
        <button
          type="button"
          onClick={onDemo}
          className="mt-4 w-full text-center text-sm font-medium text-accent underline-offset-2 hover:underline focus-visible:outline-none focus-visible:underline"
        >
          Back to the one-click roles
        </button>
      )}
    </>
  )
}
