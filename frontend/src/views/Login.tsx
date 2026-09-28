import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AccountLayout } from '@/components/layout/AccountLayout'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Field, FormError, FormNotice, PasswordInput } from '@/components/common/Form'
import { login, loginError } from '@/lib/auth/authApi'
import { DemoRoleList } from '@/components/common/DemoRoleList'
import { useDemo } from '@/lib/auth/demo'
import { useSession } from '@/lib/auth/SessionContext'

/** where /login sends a viewer afterwards: back to the officials' page that sent them here, else Home */
interface FromState {
  from?: string
  expired?: boolean
}

/**
 * Sign-in in the account frame (components/layout/AccountLayout). With the demo sign-in on (backend DEMO_LOGIN, a
 * prototype setting) the card lists the roles and one click opens the dashboard as that role, a ministry or agency
 * official for any ministry or agency (components/common/DemoRoleList); the email form stays one link away. Otherwise the card is the email form (POST /api/auth/login): email, password with
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
        <DemoPicker expired={sayExpired} onEmail={() => setWithEmail(true)} />
      </AccountLayout>
    )
  }
  return (
    <AccountLayout>
      <EmailSignIn expired={sayExpired} onDemo={demoOn ? () => setWithEmail(false) : undefined} />
    </AccountLayout>
  )
}

/** the one-click list (components/common/DemoRoleList): the public, then every official view the backend offers */
function DemoPicker({ expired, onEmail }: { expired: boolean; onEmail: () => void }) {
  return (
    <>
      <h2 className="text-xl font-semibold text-fg-base">Open the dashboard as</h2>
      <p className="mt-1 text-sm text-fg-muted">
        Prototype mode: one click signs in to a demo account of that role. Pick any ministry or agency from its list.
      </p>
      {expired && <div className="mt-4"><FormNotice tone="warning">Your session expired. Pick a role again.</FormNotice></div>}
      <div className="mt-6">
        <DemoRoleList variant="card" />
      </div>
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
