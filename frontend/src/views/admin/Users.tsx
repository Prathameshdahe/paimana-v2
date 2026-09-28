import { useState, type FormEvent } from 'react'
import { Copy } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useResetUserPassword, useUpdateUser, useUsers } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { cn, formatDateTime } from '@/lib/formatters'
import { Outcome, Pager, RoleScopeEditor, Table } from './parts'
import { ROLE_LABEL, scopeComplete, scopeOf, TD, TH, type RoleScope } from './lib'
import type { ResetToken, User } from '@/contracts/auth'

const SIZE = 25
const SELF_NOTE = 'You cannot change your own account'

/**
 * Accounts (GET /api/admin/users, paged, searched by email or name): status, role and scope, the admin flag, the
 * last sign-in; per row Edit (role, scope, admin flag), Disable or Enable, and Reset password, which shows a
 * one-time token once with a copy button — the page never stores it. An administrator's own row cannot be
 * disabled or demoted (the backend refuses too).
 */
export function Users() {
  const me = useSession()
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const users = useUsers(q, page, SIZE)
  const [editing, setEditing] = useState<number | null>(null)
  const [token, setToken] = useState<(ResetToken & { user: User }) | null>(null)
  const update = useUpdateUser()
  const reset = useResetUserPassword()
  const [outcome, setOutcome] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  function search(e: FormEvent) {
    e.preventDefault()
    setQ(typed.trim())
    setPage(1)
  }

  const setStatus = (u: User, status: User['status']) =>
    update.mutate({ id: u.id, body: { status } }, {
      onSuccess: () => setOutcome({ tone: 'ok', text: `${u.email} ${status === 'disabled' ? 'disabled' : 'enabled'}.` }),
      onError: (err) => setOutcome({ tone: 'error', text: err.message }),
    })

  const issueReset = (u: User) =>
    reset.mutate(u.id, {
      onSuccess: (t) => { setToken({ ...t, user: u }); setOutcome(null) },
      onError: (err) => setOutcome({ tone: 'error', text: err.message }),
    })

  const data = users.data
  return (
    <div className="space-y-3">
      <form onSubmit={search} className="flex flex-wrap items-center gap-2">
        <Input aria-label="Search accounts" placeholder="Email or name" value={typed} onChange={(e) => setTyped(e.target.value)} className="w-64 py-1.5 text-sm" />
        <Button type="submit" size="sm" variant="secondary">Search</Button>
        {q && <Button type="button" size="sm" variant="ghost" onClick={() => { setTyped(''); setQ(''); setPage(1) }}>Clear</Button>}
      </form>

      {token && <TokenPanel t={token} onDismiss={() => setToken(null)} />}
      {outcome && <Outcome tone={outcome.tone}>{outcome.text}</Outcome>}

      {users.error ? (
        <ApiErrorNote error={users.error} />
      ) : !data ? (
        <p className="py-6 text-center text-xs text-fg-dimmed">loading…</p>
      ) : (
        <>
          <Table label="accounts">
            <thead>
              <tr className="border-b border-border-subtle">
                <th scope="col" className={TH}>Email</th>
                <th scope="col" className={TH}>Name</th>
                <th scope="col" className={TH}>Role and scope</th>
                <th scope="col" className={TH}>Status</th>
                <th scope="col" className={TH}>Last sign-in</th>
                <th scope="col" className={TH}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 && (
                <tr><td colSpan={6} className="py-8 text-center text-sm text-fg-dimmed">No account matches.</td></tr>
              )}
              {data.items.map((u) => {
                const self = u.id === me.userId
                const busy = update.isPending && update.variables?.id === u.id
                return (
                  <UserRows
                    key={u.id}
                    u={u}
                    self={self}
                    busy={busy}
                    editing={editing === u.id}
                    onEdit={() => setEditing(editing === u.id ? null : u.id)}
                    onStatus={(s) => setStatus(u, s)}
                    onReset={() => issueReset(u)}
                    resetting={reset.isPending && reset.variables === u.id}
                  />
                )
              })}
            </tbody>
          </Table>
          <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />
        </>
      )}
    </div>
  )
}

function UserRows({ u, self, busy, editing, onEdit, onStatus, onReset, resetting }: {
  u: User
  self: boolean
  busy: boolean
  editing: boolean
  onEdit: () => void
  onStatus: (s: User['status']) => void
  onReset: () => void
  resetting: boolean
}) {
  const disabled = u.status === 'disabled'
  const locked = u.lockedUntil && Date.parse(u.lockedUntil) > Date.now()
  return (
    <>
      <tr className={cn('border-b border-border-subtle/60', disabled && 'text-fg-dimmed')}>
        <td className={`${TD} max-w-[16rem] truncate`} title={u.email}>
          {u.email}
          {self && <span className="ml-1 text-fg-dimmed">(you)</span>}
        </td>
        <td className={`${TD} max-w-[12rem] truncate`} title={u.displayName ?? undefined}>{u.displayName ?? '—'}</td>
        <td className={`${TD} max-w-[16rem]`}>
          {ROLE_LABEL[u.role]}{u.isAdmin && <span className="ml-1 bg-accent/10 px-1 text-accent">admin</span>}
          {scopeOf(u) && <span className="block truncate text-fg-muted" title={scopeOf(u) ?? undefined}>{scopeOf(u)}</span>}
        </td>
        <td className={`${TD} whitespace-nowrap`}>
          <span className={disabled ? 'text-critical' : 'text-stable'}>{u.status}</span>
          {locked && <span className="block text-warning" title={`until ${formatDateTime(u.lockedUntil ?? '')}`}>locked</span>}
        </td>
        <td className={`${TD} whitespace-nowrap text-fg-muted`}>{u.lastLoginAt ? formatDateTime(u.lastLoginAt) : 'never'}</td>
        <td className={`${TD} whitespace-nowrap`}>
          <span className="flex flex-wrap gap-1">
            <Button size="sm" variant={editing ? 'primary' : 'ghost'} aria-expanded={editing} onClick={onEdit} disabled={self} title={self ? SELF_NOTE : undefined}>
              {editing ? 'Close' : 'Edit'}
            </Button>
            <Button size="sm" variant="ghost" disabled={self || busy} title={self ? SELF_NOTE : undefined} onClick={() => onStatus(disabled ? 'active' : 'disabled')}>
              {disabled ? 'Enable' : 'Disable'}
            </Button>
            <Button size="sm" variant="ghost" disabled={resetting} onClick={onReset}>
              {resetting ? 'Issuing…' : 'Reset password'}
            </Button>
          </span>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-border-subtle/60 bg-surface-elevated/50">
          <td colSpan={6} className="px-3 py-3"><EditUser u={u} onClose={onEdit} /></td>
        </tr>
      )}
    </>
  )
}

function EditUser({ u, onClose }: { u: User; onClose: () => void }) {
  const [v, setV] = useState<RoleScope>({ role: u.role, ministry: u.ministry, agency: u.agency })
  const [admin, setAdmin] = useState(u.isAdmin && u.role === 'ipmd_analyst')
  const update = useUpdateUser()
  const [done, setDone] = useState(false)
  const isAdminPossible = v.role === 'ipmd_analyst'
  const changed = v.role !== u.role || scopeOf(v) !== scopeOf(u) || (admin && isAdminPossible) !== u.isAdmin

  const save = () =>
    update.mutate(
      { id: u.id, body: { role: v.role, ministry: v.ministry, agency: v.agency, isAdmin: isAdminPossible && admin } },
      { onSuccess: () => setDone(true) }
    )

  if (done) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Outcome tone="ok">Saved.</Outcome>
        <Button size="sm" variant="secondary" onClick={onClose}>Close</Button>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <RoleScopeEditor value={v} onChange={setV} idPrefix={`user-${u.id}`} />
      <label className={cn('flex items-center gap-2 text-xs', isAdminPossible ? 'text-fg-base' : 'text-fg-dimmed')}>
        <input type="checkbox" checked={isAdminPossible && admin} disabled={!isAdminPossible} onChange={(e) => setAdmin(e.target.checked)} className="size-3.5 accent-accent" />
        Administrator{!isAdminPossible && ' (IPMD analysts only)'}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={update.isPending || !changed || !scopeComplete(v)} onClick={save}>
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        {update.error && <Outcome tone="error">{update.error.message}</Outcome>}
      </div>
    </div>
  )
}

/** the one-time token, shown once; copied with the clipboard when the browser allows it */
function TokenPanel({ t, onDismiss }: { t: ResetToken & { user: User }; onDismiss: () => void }) {
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(t.token)
      setCopied('yes')
    } catch {
      setCopied('no')
    }
  }
  return (
    <div role="status" className="space-y-2 border border-accent/40 bg-accent/5 px-4 py-3 text-sm text-fg-base">
      <p>
        One-time reset token for <span className="font-medium">{t.user.email}</span>. It is shown once and not stored
        here: give it to the user, who sets a new password at <span className="font-mono">/reset</span>.
        {t.expiresAt && ` Valid until ${formatDateTime(t.expiresAt)}.`}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="select-all break-all bg-surface-panel px-2 py-1 font-mono text-sm">{t.token}</code>
        <Button size="sm" variant="secondary" onClick={copy}>
          <Copy className="size-3.5" aria-hidden="true" /> {copied === 'yes' ? 'Copied' : 'Copy'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>
        {copied === 'no' && <span className="text-xs text-fg-dimmed">The clipboard is not available here; select the token and copy it.</span>}
      </div>
    </div>
  )
}
