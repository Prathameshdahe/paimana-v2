import { Field, PasswordInput } from '@/components/common/Form'
import { checkPassword, POLICY_TEXT } from '@/lib/auth/password'
import { cn } from '@/lib/formatters'

const METER: Record<number, string> = { 0: 'bg-border-default', 1: 'bg-critical', 2: 'bg-warning', 3: 'bg-stable/70', 4: 'bg-stable' }

/**
 * A new password and its confirmation with the policy under the box and a four-step strength meter by rules
 * (lib/auth/password), shared by request access, reset and change password. The policy problems show once the
 * viewer has typed; the mismatch shows once both boxes have something.
 */
export function PasswordPair({ password, confirm, onPassword, onConfirm, email, label = 'Password', disabled }: {
  password: string
  confirm: string
  onPassword: (v: string) => void
  onConfirm: (v: string) => void
  /** the account's email: the password must not contain its name part */
  email?: string
  label?: string
  disabled?: boolean
}) {
  const check = checkPassword(password, email)
  const mismatch = !!password && !!confirm && password !== confirm
  return (
    <>
      <Field label={label} hint={POLICY_TEXT} error={password && !check.ok ? check.problems.join('. ') : undefined}>
        {({ id, describedBy, invalid }) => (
          <div className="space-y-1.5">
            <PasswordInput
              id={id}
              autoComplete="new-password"
              required
              minLength={12}
              value={password}
              onChange={(e) => onPassword(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              disabled={disabled}
              className="py-2.5"
            />
            <div className="flex items-center gap-2" aria-hidden={!password}>
              <div className="flex flex-1 gap-1" role="img" aria-label={password ? `Strength: ${check.label}` : undefined}>
                {[1, 2, 3, 4].map((i) => (
                  <span key={i} className={cn('h-1.5 flex-1 rounded-full', i <= check.score ? METER[check.score] : 'bg-border-subtle')} />
                ))}
              </div>
              <span className="w-16 text-right text-xs text-fg-dimmed">{password ? check.label : ''}</span>
            </div>
          </div>
        )}
      </Field>
      <Field label={`Confirm ${label.toLowerCase()}`} error={mismatch ? 'The two passwords differ' : undefined}>
        {({ id, describedBy, invalid }) => (
          <PasswordInput
            id={id}
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => onConfirm(e.target.value)}
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            disabled={disabled}
            className="py-2.5"
          />
        )}
      </Field>
    </>
  )
}
