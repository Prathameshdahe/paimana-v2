import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Field, FormError, FormNotice, PasswordInput } from '@/components/common/Form'
import { login, loginError } from '@/lib/auth/authApi'
import { useSession } from '@/lib/auth/SessionContext'

/** where /login sends a viewer afterwards: back to the officials' page that sent them here, else Home */
interface FromState {
  from?: string
  expired?: boolean
}

const BULLETS = [
  'Ranks every central sector project by its risk of a delay or a cost revision in the next two quarters',
  'Explains each ranking with the evidence behind it: the model’s drivers, report remarks, clearances and land',
  'Alerts the responsible officials when a project’s outlook changes',
]

/**
 * Sign-in (POST /api/auth/login): a formal two-panel page — the product and the ministry on the left, the form on
 * the right; stacked on a narrow screen. No animation and no decoration. The public needs no account: "Continue as
 * public" goes to Home. Errors stay inline (loginError). A viewer sent here from an officials' page goes back to it
 * after signing in, and an expired session says so above the form.
 */
export function Login() {
  const { signIn, expired } = useSession()
  const navigate = useNavigate()
  const { state } = useLocation()
  const from = (state as FromState | null)?.from
  const sayExpired = expired || !!(state as FromState | null)?.expired
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
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <aside className="flex flex-col justify-between bg-fg-base px-6 py-10 text-fg-inverse sm:px-10 lg:w-[40%] lg:px-14 lg:py-14">
        <div>
          <p className="text-xl font-semibold tracking-[0.18em]">
            PAIMANA <span className="text-base font-normal tracking-widest text-fg-inverse/70">RADAR</span>
          </p>
          <h1 className="mt-8 max-w-md text-2xl font-semibold leading-snug lg:text-3xl">
            Early Warning Radar for Central Sector Projects
          </h1>
          <p className="mt-3 text-sm text-fg-inverse/80">Ministry of Statistics and Programme Implementation · IPMD</p>
          <ul className="mt-8 max-w-md space-y-3 text-sm leading-relaxed text-fg-inverse/90">
            {BULLETS.map((b) => (
              <li key={b} className="flex gap-3">
                <span className="mt-2.5 size-1.5 shrink-0 bg-fg-inverse/60" aria-hidden="true" />
                {b}
              </li>
            ))}
          </ul>
        </div>
        <p className="mt-12 text-xs text-fg-inverse/70">Authorised use only. Activity is logged.</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-sm border border-border-default bg-surface-panel p-6 shadow-card sm:p-8">
          <h2 className="text-xl font-semibold text-fg-base">Sign in</h2>
          <p className="mt-1 text-sm text-fg-muted">Officials sign in with their account. The public needs none.</p>

          <form onSubmit={submit} noValidate className="mt-6 space-y-4">
            {sayExpired && <FormNotice tone="warning">Your session expired. Sign in again.</FormNotice>}
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
        </div>
      </main>
    </div>
  )
}
