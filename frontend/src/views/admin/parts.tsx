import type { ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Input'
import { ScopePicker } from '@/components/common/ScopePicker'
import { useScopes } from '@/lib/queries'
import { cn } from '@/lib/formatters'
import { ROLE_LABEL, ROLES, scopeOf, type RoleScope } from './lib'
import type { OfficialRole } from '@/contracts/auth'

/**
 * The components the three administration tabs share: the role-and-scope editor over /api/scopes, the table frame,
 * the pager and the one-line outcome of an action. Plain and dense; every control is a real button, select or input.
 */

/** the role and, for a scoped role, its scope from the searchable list; changing the role clears the scope */
export function RoleScopeEditor({ value, onChange, idPrefix }: {
  value: RoleScope
  onChange: (v: RoleScope) => void
  idPrefix: string
}) {
  const scopes = useScopes()
  const picker =
    value.role === 'ministry_official' ? { options: scopes.data?.ministries, noun: 'ministry', plural: 'ministries' }
      : value.role === 'agency_official' ? { options: scopes.data?.agencies, noun: 'agency', plural: 'agencies' }
        : null
  const chosen = scopeOf(value)
  return (
    <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-role`} className="block text-xs font-medium text-fg-muted">Role</label>
        <Select
          id={`${idPrefix}-role`}
          value={value.role}
          onChange={(e) => onChange({ role: e.target.value as OfficialRole, ministry: null, agency: null })}
          className="w-full max-w-none"
        >
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </Select>
      </div>
      {picker && (
        <div className="space-y-1">
          <label htmlFor={`${idPrefix}-scope`} className="block text-xs font-medium text-fg-muted">
            {picker.noun.charAt(0).toUpperCase() + picker.noun.slice(1)}
            <span className="font-normal text-fg-dimmed">{chosen ? ` · ${chosen}` : ' · none chosen'}</span>
          </label>
          {picker.options ? (
            <ScopePicker
              id={`${idPrefix}-scope`}
              compact
              options={picker.options}
              value={chosen ?? ''}
              onChange={(name) => onChange({
                role: value.role,
                ministry: value.role === 'ministry_official' ? name : null,
                agency: value.role === 'agency_official' ? name : null,
              })}
              noun={picker.noun}
              plural={picker.plural}
            />
          ) : (
            <p className="text-xs text-fg-dimmed">{scopes.error ? 'The list is not available.' : 'Loading…'}</p>
          )}
        </div>
      )}
    </div>
  )
}

/** the table frame every tab uses */
export function Table({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface-panel shadow-card">
      <table className="w-full border-collapse" aria-label={label}>{children}</table>
    </div>
  )
}

/** "1–25 of 132" with Previous and Next */
export function Pager({ page, size, total, onPage, className }: {
  page: number
  size: number
  total: number
  onPage: (page: number) => void
  className?: string
}) {
  const first = total === 0 ? 0 : (page - 1) * size + 1
  const last = Math.min(total, page * size)
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className={cn('flex items-center justify-between gap-3 text-xs text-fg-dimmed', className)}>
      <span>{total === 0 ? 'Nothing to show' : `${first}–${last} of ${total.toLocaleString('en-IN')}`}</span>
      <span className="flex items-center gap-2">
        <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span className="tabular-nums">page {page} of {pages}</span>
        <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </span>
    </div>
  )
}

/** the one-line outcome of an action, in the tone it deserves */
export function Outcome({ tone, children }: { tone: 'ok' | 'error'; children: ReactNode }) {
  return (
    <p role={tone === 'error' ? 'alert' : 'status'} className={cn('text-xs', tone === 'ok' ? 'text-stable' : 'text-critical')}>
      {children}
    </p>
  )
}
