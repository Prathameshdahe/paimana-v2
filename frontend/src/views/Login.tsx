import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AccountLayout } from '@/components/layout/AccountLayout'
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

/**
 * Sign-in (POST /api/auth/login) in the account frame (components/layout/AccountLayout): email, password with
 * show/hide, one primary button, and the two ways out for someone without an account. No animation and no
 * decoration. Errors stay inline (lib/auth/authApi loginError). A viewer sent here from an officials' page goes
 * back to it after signing in, and an expired session says so above the form.
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
    <AccountLayout>
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
    </AccountLayout>
  )
}
