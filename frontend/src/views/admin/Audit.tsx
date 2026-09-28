import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useAudit } from '@/lib/queries'
import { formatDateTime } from '@/lib/formatters'
import { Pager, Table } from './parts'
import { detailText, TD, TH } from './lib'
import type { AuditQuery } from '@/contracts/auth'

const SIZE = 50

/**
 * The audit log (GET /api/admin/audit, paged): who did what, to what, from where, since when — filtered by a date,
 * a user (email or id) and an action word. Read-only; the log is written by the backend on every write route.
 */
export function Audit() {
  const [draft, setDraft] = useState({ since: '', user: '', action: '' })
  const [query, setQuery] = useState<AuditQuery>({ page: 1, size: SIZE })
  const audit = useAudit(query)

  function apply(e: FormEvent) {
    e.preventDefault()
    setQuery({
      since: draft.since || undefined,
      user: draft.user.trim() || undefined,
      action: draft.action.trim() || undefined,
      page: 1,
      size: SIZE,
    })
  }

  const data = audit.data
  return (
    <div className="space-y-3">
      <form onSubmit={apply} className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-xs text-fg-muted">
          Since
          <Input type="date" value={draft.since} onChange={(e) => setDraft({ ...draft, since: e.target.value })} className="w-44 py-1.5 text-sm" />
        </label>
        <label className="space-y-1 text-xs text-fg-muted">
          User
          <Input placeholder="Email or id" value={draft.user} onChange={(e) => setDraft({ ...draft, user: e.target.value })} className="w-56 py-1.5 text-sm" />
        </label>
        <label className="space-y-1 text-xs text-fg-muted">
          Action
          <Input placeholder="login, ack, approve…" value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} className="w-48 py-1.5 text-sm" />
        </label>
        <Button type="submit" size="sm" variant="secondary">Apply</Button>
      </form>

      {audit.error ? (
        <ApiErrorNote error={audit.error} />
      ) : !data ? (
        <p className="py-6 text-center text-xs text-fg-dimmed">loading…</p>
      ) : (
        <>
          <Table label="audit log">
            <thead>
              <tr className="border-b border-border-subtle">
                <th scope="col" className={TH}>At</th>
                <th scope="col" className={TH}>User</th>
                <th scope="col" className={TH}>Role</th>
                <th scope="col" className={TH}>Action</th>
                <th scope="col" className={TH}>Target</th>
                <th scope="col" className={TH}>From</th>
                <th scope="col" className={TH}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-sm text-fg-dimmed">No audit rows match.</td></tr>
              )}
              {data.items.map((r) => {
                const detail = detailText(r.detail)
                return (
                  <tr key={r.id} className="border-b border-border-subtle/60">
                    <td className={`${TD} whitespace-nowrap text-fg-muted`}>{formatDateTime(r.at)}</td>
                    <td className={`${TD} max-w-[14rem] truncate`} title={r.email ?? undefined}>{r.email ?? (r.userId !== null ? `user ${r.userId}` : 'public')}</td>
                    <td className={`${TD} whitespace-nowrap text-fg-muted`}>{r.role ?? '—'}</td>
                    <td className={`${TD} whitespace-nowrap font-medium`}>{r.action}</td>
                    <td className={`${TD} max-w-[12rem] truncate font-mono`} title={r.target ?? undefined}>{r.target ?? '—'}</td>
                    <td className={`${TD} whitespace-nowrap font-mono text-fg-muted`}>{r.ip ?? '—'}</td>
                    <td className={`${TD} max-w-[24rem] truncate text-fg-muted`} title={detail || undefined}>{detail || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
          <Pager page={data.page} size={data.size} total={data.total} onPage={(page) => setQuery((q) => ({ ...q, page }))} />
        </>
      )}
    </div>
  )
}
