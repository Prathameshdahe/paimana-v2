import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { AccountLayout } from '@/components/layout/AccountLayout'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Field, FormError } from '@/components/common/Form'
import { PasswordPair } from '@/components/common/PasswordPair'
import { ScopePicker } from '@/components/common/ScopePicker'
import { signup, signupError } from '@/lib/auth/authApi'
import { checkPassword } from '@/lib/auth/password'
import { useScopes } from '@/lib/queries'
import { cn } from '@/lib/formatters'
import type { OfficialRole } from '@/contracts/auth'

export const JUSTIFICATION_MAX = 500

const ROLES: Array<{ value: OfficialRole; label: string; hint: string }> = [
  { value: 'ministry_official', label: 'Ministry official', hint: 'the projects of one ministry' },
  { value: 'agency_official', label: 'Agency official', hint: 'the projects of one implementing agency' },
  { value: 'ipmd_analyst', label: 'IPMD analyst', hint: 'every project' },
]

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/**
 * Request access (POST /api/auth/signup): an official's email, name, role and scope (the searchable ministry or
 * agency list), why they need it, and the password they will sign in with once an IPMD administrator approves the
 * request. Everything the policy can check is checked before it is sent; the backend checks it again. On 202 the
 * form gives way to one plain panel: nothing is granted here.
 */
export function Signup() {
  const scopes = useScopes()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<OfficialRole | ''>('')
  const [scope, setScope] = useState('')
  const [why, setWhy] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<number | null>(null)

  const picker =
    role === 'ministry_official' ? { options: scopes.data?.ministries, noun: 'ministry', plural: 'ministries' }
      : role === 'agency_official' ? { options: scopes.data?.agencies, noun: 'agency', plural: 'agencies' }
        : null
  const ready =
    EMAIL.test(email.trim()) && !!name.trim() && !!role && (!picker || !!scope) && !!why.trim()
    && why.length <= JUSTIFICATION_MAX && checkPassword(password, email).ok && password === confirm

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready || !role || pending) return
    setPending(true)
    setError(null)
    try {
      const out = await signup({
        email: email.trim(),
        displayName: name.trim(),
        role,
        ministry: role === 'ministry_official' ? scope : undefined,
        agency: role === 'agency_official' ? scope : undefined,
        justification: why.trim(),
        password,
      })
      setDone(out.id)
    } catch (err) {
      setError(signupError(err))
    } finally {
      setPending(false)
    }
  }

  if (done !== null) {
    return (
      <AccountLayout>
        <h2 className="text-xl font-semibold text-fg-base">Request submitted</h2>
        <p className="mt-3 text-sm leading-relaxed text-fg-base">
          An IPMD administrator will review it; you will be told by your administrator. Sign in with the password you
          chose once the request is approved.
        </p>
        <p className="mt-2 text-xs text-fg-dimmed">Request {done}</p>
        <Link to="/login" className="mt-6 inline-block text-sm font-medium text-accent underline-offset-2 hover:underline">
          Back to sign in
        </Link>
      </AccountLayout>
    )
  }

  return (
    <AccountLayout wide>
      <h2 className="text-xl font-semibold text-fg-base">Request access</h2>
      <p className="mt-1 text-sm text-fg-muted">
        For officials of a ministry, an implementing agency or IPMD. An administrator approves each request.
      </p>

      <form onSubmit={submit} noValidate className="mt-6 space-y-4">
        <Field label="Official email" error={email && !EMAIL.test(email.trim()) ? 'Not an email address' : undefined}>
          {({ id, describedBy, invalid }) => (
            <Input id={id} type="email" name="email" autoComplete="email" autoFocus required value={email}
              onChange={(e) => setEmail(e.target.value)} aria-describedby={describedBy} aria-invalid={invalid || undefined} className="py-2.5" />
          )}
        </Field>
        <Field label="Full name">
          {({ id, describedBy }) => (
            <Input id={id} name="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)}
              aria-describedby={describedBy} className="py-2.5" />
          )}
        </Field>

        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium text-fg-base">Role</legend>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Role">
            {ROLES.map((r) => (
              <button
                key={r.value}
                type="button"
                role="radio"
                aria-checked={role === r.value}
                onClick={() => {
                  setRole(r.value)
                  setScope('')
                }}
                className={cn(
                  'border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                  role === r.value ? 'border-accent bg-accent/10 text-fg-base' : 'border-border-default text-fg-muted hover:border-border-strong hover:text-fg-base'
                )}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span className={cn('size-3 shrink-0 rounded-full border', role === r.value ? 'border-accent bg-accent' : 'border-border-strong')} aria-hidden="true" />
                  {r.label}
                </span>
                <span className="mt-0.5 block pl-5 text-xs text-fg-dimmed">{r.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        {picker && (
          <Field label={`Your ${picker.noun}`} hint={scope ? `Chosen: ${scope}` : `Pick the ${picker.noun} your account is for`}>
            {({ id }) =>
              picker.options ? (
                <ScopePicker id={id} options={picker.options} value={scope} onChange={setScope} noun={picker.noun} plural={picker.plural} />
              ) : (
                <p className="text-sm text-fg-dimmed">{scopes.error ? 'The list is not available: the service is not reachable.' : 'Loading…'}</p>
              )
            }
          </Field>
        )}

        <Field
          label="Why you need access"
          hint={<span className={cn('tabular-nums', why.length > JUSTIFICATION_MAX && 'text-critical')}>{why.length} / {JUSTIFICATION_MAX}</span>}
          error={why.length > JUSTIFICATION_MAX ? `At most ${JUSTIFICATION_MAX} characters` : undefined}
        >
          {({ id, describedBy, invalid }) => (
            <textarea
              id={id}
              required
              rows={3}
              maxLength={JUSTIFICATION_MAX + 50}
              value={why}
              onChange={(e) => setWhy(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              className="w-full resize-y rounded-lg border border-border-default bg-surface-input px-3 py-2 text-sm text-fg-base placeholder:text-fg-dimmed focus:border-accent focus:outline-none"
              placeholder="Your post, and what you will use the radar for"
            />
          )}
        </Field>

        <PasswordPair password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} email={email} />

        {error && <FormError>{error}</FormError>}
        <Button type="submit" variant="primary" className="w-full" disabled={!ready || pending}>
          {pending ? 'Submitting…' : 'Request access'}
        </Button>
      </form>

      <p className="mt-5 text-sm text-fg-muted">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-accent underline-offset-2 hover:underline">Sign in</Link>
      </p>
    </AccountLayout>
  )
}
