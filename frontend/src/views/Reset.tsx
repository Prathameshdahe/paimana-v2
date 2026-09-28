import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AccountLayout } from '@/components/layout/AccountLayout'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Field, FormError, FormNotice } from '@/components/common/Form'
import { PasswordPair } from '@/components/common/PasswordPair'
import { resetError, resetPassword } from '@/lib/auth/authApi'
import { checkPassword } from '@/lib/auth/password'

/**
 * Set a new password with the one-time token an IPMD administrator issued (POST /api/auth/reset). The token comes
 * from the link's ?token= or is typed; the new password is checked against the policy before it is sent. On 204
 * the form gives way to a notice and the sign-in link — the reset does not sign the viewer in.
 */
export function Reset() {
  const [params] = useSearchParams()
  const [token, setToken] = useState(params.get('token') ?? '')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const ready = !!token.trim() && checkPassword(password).ok && password === confirm

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready || pending) return
    setPending(true)
    setError(null)
    try {
      await resetPassword({ token: token.trim(), password })
      setDone(true)
    } catch (err) {
      setError(resetError(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <AccountLayout>
      <h2 className="text-xl font-semibold text-fg-base">Set a new password</h2>
      <p className="mt-1 text-sm text-fg-muted">With the one-time token your administrator gave you.</p>

      {done ? (
        <div className="mt-6 space-y-4">
          <FormNotice tone="success">Your password is set. Sign in with it.</FormNotice>
          <Link to="/login" className="inline-block text-sm font-medium text-accent underline-offset-2 hover:underline">Go to sign in</Link>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="mt-6 space-y-4">
          <Field label="Reset token">
            {({ id, describedBy }) => (
              <Input id={id} name="token" autoComplete="off" spellCheck={false} required value={token} autoFocus={!token}
                onChange={(e) => setToken(e.target.value)} aria-describedby={describedBy} className="py-2.5 font-mono" />
            )}
          </Field>
          <PasswordPair password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} label="New password" />
          {error && <FormError>{error}</FormError>}
          <Button type="submit" variant="primary" className="w-full" disabled={!ready || pending}>
            {pending ? 'Saving…' : 'Set the password'}
          </Button>
        </form>
      )}

      <p className="mt-5 text-sm text-fg-muted">
        <Link to="/login" className="font-medium text-accent underline-offset-2 hover:underline">Back to sign in</Link>
      </p>
    </AccountLayout>
  )
}
