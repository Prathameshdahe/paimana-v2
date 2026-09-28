import { useId, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/formatters'

/**
 * The pieces the account forms share (sign-in, request access, reset, change password): a labelled field with its
 * hint and inline error, a password input with show/hide, and the one way an error or a notice is shown above a
 * button. Plain and still: these pages animate nothing.
 */

/** a label over one control; the control gets the id, the hint and the error are read with it */
export function Field({ label, hint, error, children, id: given, className }: {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  /** renders the control: it must put `id` on the input and `describedBy` on aria-describedby */
  children: (a: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode
  id?: string
  className?: string
}) {
  const auto = useId()
  const id = given ?? auto
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-sm font-medium text-fg-base">{label}</label>
      {children({ id, describedBy, invalid: !!error })}
      {hint && <p id={hintId} className="text-xs text-fg-dimmed">{hint}</p>}
      {error && <p id={errorId} className="text-xs text-critical">{error}</p>}
    </div>
  )
}

/** a password box with a show/hide toggle; the toggle never submits the form */
export function PasswordInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <Input type={shown ? 'text' : 'password'} className={cn('pr-11', className)} spellCheck={false} {...props} />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? 'Hide the password' : 'Show the password'}
        aria-pressed={shown}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-fg-dimmed hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        {shown ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
      </button>
    </div>
  )
}

/** the error of a whole form, announced at once */
export function FormError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
      {children}
    </p>
  )
}

/** a notice that is not an error (a session that expired, a password that was set) */
export function FormNotice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'success' }) {
  const cls = {
    info: 'border-border-default bg-surface-elevated text-fg-base',
    warning: 'border-warning/40 bg-warning/5 text-warning',
    success: 'border-stable/40 bg-stable/5 text-stable',
  }[tone]
  return (
    <p role="status" className={cn('border px-3 py-2 text-sm', cls)}>
      {children}
    </p>
  )
}
