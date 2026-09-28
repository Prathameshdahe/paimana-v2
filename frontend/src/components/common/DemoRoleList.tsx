import { useId, useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { FormError } from '@/components/common/Form'
import { DEMO_HINTS, DEMO_ICONS, demoRoleOf, useDemo, useOpenRole } from '@/lib/auth/demo'
import { useSession } from '@/lib/auth/SessionContext'
import { useScopes } from '@/lib/queries'
import { cn } from '@/lib/formatters'
import type { DemoOption, DemoRole } from '@/contracts/auth'
import type { ScopeOption } from '@/contracts/portfolio'

type Option = DemoOption | { role: 'public'; label: string; scope: null }
type ScopedRole = Extract<DemoRole, 'ministry' | 'agency'>

const isScoped = (r: Option['role']): r is ScopedRole => r === 'ministry' || r === 'agency'

const projects = (n: number) => `${n.toLocaleString()} project${n === 1 ? '' : 's'}`

/** agencies grouped under their ministry (the ministries in their /api/scopes order, most projects first) */
function agencyGroups(ministries: ScopeOption[], agencies: ScopeOption[]): Array<[string, ScopeOption[]]> {
  const order = new Map(ministries.map((m, i) => [m.name, i]))
  const groups = new Map<string, ScopeOption[]>()
  for (const a of agencies) {
    const k = a.ministry ?? 'Other'
    groups.set(k, [...(groups.get(k) ?? []), a])
  }
  return [...groups.entries()].sort(([a], [b]) => (order.get(a) ?? 999) - (order.get(b) ?? 999))
}

/**
 * The one-click demo roles (lib/auth/demo; backend DEMO_LOGIN): the public, the IPMD analyst, a ministry official, an
 * agency official and the administrator. A ministry or agency row carries a list of every ministry or agency
 * (agencies under their ministry): choosing one opens the dashboard as that official at once, and the arrow opens the
 * one shown. variant 'card' is the sign-in page's list, 'menu' the account menu's compact one; onPicked runs when a
 * role is opened (the menu closes itself).
 */
export function DemoRoleList({ variant, onPicked }: { variant: 'card' | 'menu'; onPicked?: () => void }) {
  const demo = useDemo()
  const scopes = useScopes()
  const session = useSession()
  const { open, pending, error } = useOpenRole()
  const uid = useId()
  const current = session.role ? demoRoleOf(session) : 'public'
  const currentScope = session.ministry ?? session.agency ?? null
  const [chosen, setChosen] = useState<Partial<Record<ScopedRole, string>>>({})
  const groups = useMemo(
    () => agencyGroups(scopes.data?.ministries ?? [], scopes.data?.agencies ?? []),
    [scopes.data],
  )

  const options: Option[] = [{ role: 'public', label: 'Public', scope: null }, ...(demo.data?.roles ?? [])]
  const shown = (o: Option): string | null =>
    isScoped(o.role) ? chosen[o.role] ?? (current === o.role ? currentScope : null) ?? o.scope : null
  const go = (role: Option['role'], scope?: string | null) => {
    onPicked?.()
    void open(role, role === 'ministry' ? { ministry: scope ?? undefined } : role === 'agency' ? { agency: scope ?? undefined } : {})
  }

  const menu = variant === 'menu'
  const rowCls = menu
    ? 'flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-fg-muted'
    : 'flex w-full items-center gap-3 rounded-lg border border-border-default bg-surface-base px-3 py-2.5 text-left'
  const actionCls = menu
    ? 'hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:bg-surface-elevated focus-visible:text-fg-base disabled:opacity-60'
    : 'group transition-colors hover:border-accent/50 hover:bg-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-wait disabled:opacity-60'
  const selectCls = cn(
    'w-full truncate rounded-md border border-border-default bg-surface-panel text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
    menu ? 'mt-1 px-1.5 py-1 text-xs' : 'mt-1 px-2 py-1 text-xs',
  )

  return (
    <>
      <ul className={menu ? '' : 'space-y-2'}>
        {options.map((o) => {
          const Icon = DEMO_ICONS[o.role]
          const here = current === o.role && (!isScoped(o.role) || shown(o) === currentScope)
          const tag = here && <span className="ml-2 text-xs font-normal text-fg-dimmed">current</span>
          const icon = menu ? (
            <Icon className="size-4 shrink-0" aria-hidden="true" />
          ) : (
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-fg-base/5 text-fg-muted transition-colors group-hover:text-accent">
              <Icon className="size-4" aria-hidden="true" />
            </span>
          )
          const busy = pending === o.role && <span className="text-xs text-fg-muted">Opening…</span>

          if (!isScoped(o.role)) {
            return (
              <li key={o.role}>
                <button
                  type="button"
                  onClick={() => go(o.role)}
                  disabled={!!pending || (menu && here)}
                  className={cn(rowCls, actionCls)}
                >
                  {icon}
                  <span className="min-w-0 flex-1">
                    <span className={cn('block', menu ? '' : 'text-sm font-medium text-fg-base')}>{o.label}{tag}</span>
                    {!menu && <span className="block truncate text-xs text-fg-dimmed">{DEMO_HINTS[o.role]}</span>}
                  </span>
                  {busy || (!menu && <ChevronRight className="size-4 shrink-0 text-fg-dimmed transition-colors group-hover:text-accent" aria-hidden="true" />)}
                </button>
              </li>
            )
          }

          const role = o.role
          const value = shown(o) ?? ''
          const id = `${uid}-${role}`
          return (
            <li key={role} className={cn(rowCls, !menu && 'focus-within:border-accent/50')}>
              {icon}
              <div className="min-w-0 flex-1">
                <label htmlFor={id} className={cn('block', menu ? '' : 'text-sm font-medium text-fg-base')}>
                  {o.label}{tag}
                </label>
                <select
                  id={id}
                  value={value}
                  disabled={!!pending || !scopes.data}
                  onChange={(e) => {
                    setChosen((c) => ({ ...c, [role]: e.target.value }))
                    go(role, e.target.value) // choosing a ministry or an agency opens it
                  }}
                  className={selectCls}
                >
                  {!scopes.data && <option value={value}>{value || 'Loading…'}</option>}
                  {role === 'ministry'
                    ? scopes.data?.ministries.map((m) => (
                        <option key={m.name} value={m.name}>{m.name} · {projects(m.n)}</option>
                      ))
                    : groups.map(([ministry, list]) => (
                        <optgroup key={ministry} label={ministry}>
                          {list.map((a) => (
                            <option key={a.name} value={a.name}>{a.name} · {projects(a.n)}</option>
                          ))}
                        </optgroup>
                      ))}
                </select>
              </div>
              {busy || (
                <button
                  type="button"
                  onClick={() => go(role, value || null)}
                  disabled={!!pending}
                  aria-label={`Open as ${o.label}: ${value}`}
                  title={`Open as ${value}`}
                  className={cn(
                    'flex shrink-0 items-center justify-center rounded-md text-fg-dimmed transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60',
                    menu ? 'size-7' : 'size-9 border border-border-default bg-surface-panel hover:border-accent/50',
                  )}
                >
                  <ChevronRight className="size-4" aria-hidden="true" />
                </button>
              )}
            </li>
          )
        })}
      </ul>
      {error && (menu ? (
        <p role="alert" className="px-4 pb-2 text-xs text-critical">{error}</p>
      ) : (
        <div className="mt-4"><FormError>{error}</FormError></div>
      ))}
    </>
  )
}
