import { useId, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/formatters'
import type { ScopeOption } from '@/contracts/portfolio'

/**
 * A searchable list of ministries or agencies from /api/scopes (lib/queries useScopes), with their current project
 * counts: the request-access form picks the scope an account asks for, and the administration corrects it before
 * approval or on a user. The options are buttons in a listbox, so the keyboard reaches every one.
 */
export function ScopePicker({ options, value, onChange, noun, plural, compact, id: given }: {
  options: ScopeOption[]
  value: string
  onChange: (name: string) => void
  /** 'ministry' | 'agency' */
  noun: string
  plural: string
  /** a shorter list, for a table row */
  compact?: boolean
  id?: string
}) {
  const auto = useId()
  const id = given ?? auto
  const [q, setQ] = useState('')
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return s ? options.filter((o) => `${o.name} ${o.names ?? ''}`.toLowerCase().includes(s)) : options
  }, [options, q])

  return (
    <div className="space-y-2">
      <Input
        id={id}
        icon={<Search className="size-4" aria-hidden="true" />}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`Search ${options.length} ${plural}`}
        aria-label={`Search ${plural}`}
        className="py-2 text-sm"
      />
      <div
        className={cn('overflow-y-auto rounded-lg border border-border-default bg-surface-panel', compact ? 'max-h-40' : 'max-h-56')}
        data-lenis-prevent
        role="listbox"
        aria-label={`${noun} options`}
      >
        {shown.length === 0 ? (
          <div className="px-3 py-4 text-center text-sm text-fg-dimmed">No {noun} matches “{q}”</div>
        ) : (
          shown.map((o) => (
            <button
              key={o.name}
              type="button"
              role="option"
              aria-selected={o.name === value}
              onClick={() => onChange(o.name)}
              className={cn(
                'flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent',
                o.name === value ? 'bg-accent/15' : 'hover:bg-surface-elevated'
              )}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-fg-base">{o.name}</span>
                {o.ministry && <span className="block truncate text-xs text-fg-dimmed">{o.ministry}</span>}
              </span>
              <span className="shrink-0 bg-surface-elevated px-2 py-0.5 text-xs tabular-nums text-fg-muted">{o.n}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
