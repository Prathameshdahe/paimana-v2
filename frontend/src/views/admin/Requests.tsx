import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input, Select } from '@/components/ui/Input'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useReviewSignup, useSignups } from '@/lib/queries'
import { formatDateTime } from '@/lib/formatters'
import { Outcome, RoleScopeEditor, Table } from './parts'
import { ROLE_LABEL, scopeComplete, scopeOf, TD, TH, type RoleScope } from './lib'
import type { SignupRow, SignupStatus } from '@/contracts/auth'

const STATUSES: SignupStatus[] = ['pending', 'approved', 'rejected']

/**
 * Sign-up requests (GET /api/admin/signups?status=): the pending ones with a review row per request — the role and
 * scope as asked, editable before approval, a note, Approve (creates the account, POST .../approve) or Reject
 * (POST .../reject, note required). Approved and rejected requests show who decided and the note.
 */
export function Requests() {
  const [status, setStatus] = useState<SignupStatus>('pending')
  const list = useSignups(status)
  const [openId, setOpenId] = useState<number | null>(null)
  const rows = list.data ?? []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
        <label className="flex items-center gap-2">
          Status
          <Select aria-label="Request status" value={status} onChange={(e) => { setStatus(e.target.value as SignupStatus); setOpenId(null) }}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </label>
        {list.data && <span>{rows.length} {status} request{rows.length === 1 ? '' : 's'}</span>}
      </div>

      {list.error ? (
        <ApiErrorNote error={list.error} />
      ) : !list.data ? (
        <div className="space-y-2 px-4 py-4" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="h-8 animate-pulse rounded-lg bg-surface-input/60" />)}</div>
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-border-subtle bg-surface-panel py-8 text-center text-sm text-fg-muted">No {status} requests right now.</p>
      ) : (
        <Table label={`${status} sign-up requests`}>
          <thead>
            <tr className="border-b border-border-subtle">
              <th scope="col" className={TH}>Requested</th>
              <th scope="col" className={TH}>Email</th>
              <th scope="col" className={TH}>Name</th>
              <th scope="col" className={TH}>Role and scope</th>
              <th scope="col" className={TH}>Why</th>
              <th scope="col" className={TH}>From</th>
              <th scope="col" className={TH}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <RequestRows key={r.id} r={r} open={openId === r.id} onToggle={() => setOpenId(openId === r.id ? null : r.id)} />
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}

function RequestRows({ r, open, onToggle }: { r: SignupRow; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="border-b border-border-subtle/60">
        <td className={`${TD} whitespace-nowrap text-fg-muted`}>{formatDateTime(r.createdAt)}</td>
        <td className={`${TD} max-w-[16rem] truncate`} title={r.email}>{r.email}</td>
        <td className={`${TD} max-w-[12rem] truncate`} title={r.displayName ?? undefined}>{r.displayName ?? '—'}</td>
        <td className={`${TD} max-w-[16rem]`}>
          {ROLE_LABEL[r.role]}
          {scopeOf(r) && <span className="block truncate text-fg-muted" title={scopeOf(r) ?? undefined}>{scopeOf(r)}</span>}
        </td>
        <td className={`${TD} max-w-[20rem]`}>
          <span className="line-clamp-2" title={r.justification ?? undefined}>{r.justification ?? '—'}</span>
        </td>
        <td className={`${TD} whitespace-nowrap font-mono text-fg-muted`}>{r.ip ?? '—'}</td>
        <td className={`${TD} whitespace-nowrap`}>
          {r.status === 'pending' ? (
            <Button size="sm" variant={open ? 'primary' : 'secondary'} aria-expanded={open} onClick={onToggle}>
              {open ? 'Close' : 'Review'}
            </Button>
          ) : (
            <span className="text-fg-dimmed">
              {r.status}{r.reviewedAt && ` · ${formatDateTime(r.reviewedAt)}`}
              {r.reviewNote && <span className="block max-w-[14rem] truncate" title={r.reviewNote}>{r.reviewNote}</span>}
            </span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border-subtle/60 bg-surface-elevated/50">
          <td colSpan={7} className="px-3 py-3">
            <Review r={r} onClose={onToggle} />
          </td>
        </tr>
      )}
    </>
  )
}

function Review({ r, onClose }: { r: SignupRow; onClose: () => void }) {
  const [v, setV] = useState<RoleScope>({ role: r.role, ministry: r.ministry, agency: r.agency })
  const [note, setNote] = useState('')
  const review = useReviewSignup()
  const [outcome, setOutcome] = useState<string | null>(null)
  const changed = v.role !== r.role || scopeOf(v) !== scopeOf(r)

  const approve = () =>
    review.mutate(
      { id: r.id, decision: 'approve', body: { note: note.trim() || undefined, role: v.role, ministry: v.ministry, agency: v.agency } },
      { onSuccess: (u) => setOutcome(`Account created for ${u?.email ?? r.email}${changed ? ' with the corrected role and scope' : ''}.`) }
    )
  const reject = () =>
    review.mutate({ id: r.id, decision: 'reject', body: { note: note.trim() } }, { onSuccess: () => setOutcome('Request rejected.') })

  if (outcome) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Outcome tone="ok">{outcome}</Outcome>
        <Button size="sm" variant="secondary" onClick={onClose}>Close</Button>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {r.justification && <p className="max-w-3xl whitespace-pre-wrap text-sm leading-relaxed text-fg-base">{r.justification}</p>}
      <RoleScopeEditor value={v} onChange={setV} idPrefix={`req-${r.id}`} />
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <div className="space-y-1">
          <label htmlFor={`req-${r.id}-note`} className="block text-xs font-medium text-fg-muted">
            Note <span className="font-normal text-fg-dimmed">· kept with the decision; required to reject</span>
          </label>
          <Input id={`req-${r.id}-note`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className="py-1.5 text-sm" />
        </div>
        <div className="flex items-end gap-2">
          <Button size="sm" variant="primary" disabled={review.isPending || !scopeComplete(v)} onClick={approve}>
            {review.isPending && review.variables?.decision === 'approve' ? 'Approving…' : 'Approve'}
          </Button>
          <Button size="sm" variant="secondary" disabled={review.isPending || !note.trim()} onClick={reject}>
            {review.isPending && review.variables?.decision === 'reject' ? 'Rejecting…' : 'Reject'}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
      {review.error && <Outcome tone="error">{review.error instanceof Error ? review.error.message : String(review.error)}</Outcome>}
    </div>
  )
}
