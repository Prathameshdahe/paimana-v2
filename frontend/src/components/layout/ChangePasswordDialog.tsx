import { useEffect, useState, type FormEvent } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Field, FormError, FormNotice, PasswordInput } from '@/components/common/Form'
import { PasswordPair } from '@/components/common/PasswordPair'
import { ApiError, isOffline } from '@/lib/api'
import { changePassword } from '@/lib/auth/authApi'
import { checkPassword } from '@/lib/auth/password'

/** a failed change in one sentence; the 401 here is the current password, not the session (authApi says quiet401) */
function changeError(e: unknown): string {
  if (isOffline(e)) return 'The service is not reachable. Try again in a moment.'
  if (!(e instanceof ApiError)) return String(e)
  if (e.status === 401) return 'The current password is wrong.'
  return e.message
}

/**
 * Change the signed-in account's password (POST /api/auth/password): the current one, the new one twice with the
 * policy and meter (PasswordPair). A modal dialog from the account menu, so it lives in the top bar; it opens
 * clean every time. The backend signs the account's other sessions out; this one stays.
 */
export function ChangePasswordDialog({ open, onOpenChange, email }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  email: string | null
}) {
  const [current, setCurrent] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const ready = !!current && checkPassword(password, email ?? undefined).ok && password === confirm && password !== current

  useEffect(() => {
    if (!open) return
    setCurrent('')
    setPassword('')
    setConfirm('')
    setError(null)
    setDone(false)
    setPending(false)
  }, [open])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready || pending) return
    setPending(true)
    setError(null)
    try {
      await changePassword({ current, new: password })
      setDone(true)
    } catch (err) {
      setError(changeError(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-fg-base/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border-default bg-surface-panel p-6 shadow-pop focus:outline-none">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-lg font-semibold text-fg-base">Change password</Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-fg-muted">
                Your other sessions will be signed out; this one stays.
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="flex size-8 shrink-0 items-center justify-center text-fg-dimmed hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          {done ? (
            <div className="mt-5 space-y-4">
              <FormNotice tone="success">Password changed.</FormNotice>
              <Dialog.Close asChild>
                <Button variant="primary" className="w-full">Done</Button>
              </Dialog.Close>
            </div>
          ) : (
            <form onSubmit={submit} noValidate className="mt-5 space-y-4">
              <Field label="Current password">
                {({ id, describedBy }) => (
                  <PasswordInput id={id} autoComplete="current-password" required autoFocus value={current}
                    onChange={(e) => setCurrent(e.target.value)} aria-describedby={describedBy} className="py-2.5" />
                )}
              </Field>
              <PasswordPair
                password={password}
                confirm={confirm}
                onPassword={setPassword}
                onConfirm={setConfirm}
                email={email ?? undefined}
                label="New password"
              />
              {password && current && password === current && <p className="text-xs text-critical">The new password is the current one.</p>}
              {error && <FormError>{error}</FormError>}
              <div className="flex justify-end gap-2">
                <Dialog.Close asChild>
                  <Button type="button" variant="secondary">Cancel</Button>
                </Dialog.Close>
                <Button type="submit" variant="primary" disabled={!ready || pending}>
                  {pending ? 'Changing…' : 'Change password'}
                </Button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
