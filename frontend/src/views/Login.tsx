import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'motion/react'
import { Building2, Landmark, Radar, Search, type LucideIcon } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { SonarGrid } from '@/components/ui/sonar-grid'
import { useRole, type Role } from '@/lib/auth/RoleContext'
import { useScopes } from '@/lib/queries'
import { cn } from '@/lib/formatters'
import type { ScopeOption } from '@/contracts/portfolio'

type OfficialRole = Exclude<Role, 'public'>

const ROLE_OPTIONS: Array<{ value: OfficialRole; label: string; hint: string; icon: LucideIcon }> = [
  { value: 'ipmd_analyst', label: 'IPMD Analyst', hint: 'every project', icon: Radar },
  { value: 'ministry_official', label: 'Ministry', hint: 'one ministry', icon: Landmark },
  { value: 'agency_official', label: 'Agency', hint: 'one agency', icon: Building2 },
]

/** A searchable list of ministries or agencies from /api/scopes, with their current project counts. */
function ScopePicker({ options, value, onChange, noun, plural }: {
  options: ScopeOption[]
  value: string
  onChange: (name: string) => void
  noun: string
  plural: string
}) {
  const [q, setQ] = useState('')
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return s ? options.filter((o) => `${o.name} ${o.names ?? ''}`.toLowerCase().includes(s)) : options
  }, [options, q])

  return (
    <div className="space-y-2">
      <Input
        icon={<Search className="size-4" />}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`Search ${options.length} ${plural}`}
        className="py-2 text-sm"
      />
      <div className="max-h-56 overflow-y-auto rounded-md border border-border-subtle" data-lenis-prevent role="listbox">
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
                'flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors',
                o.name === value ? 'bg-accent/15' : 'hover:bg-surface-elevated'
              )}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-fg-base">{o.name}</span>
                {o.ministry && <span className="block truncate text-xs text-fg-dimmed">{o.ministry}</span>}
              </span>
              <span className="shrink-0 rounded-full bg-surface-elevated px-2 py-0.5 text-xs tabular-nums text-fg-muted">
                {o.n}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

/**
 * Prototype sign-in (larger card ported from Pranjal's frontend-dev). An official picks a role and, for a
 * ministry or an agency, which one: every page is then cut to its projects. The public continues
 * without a name.
 */
export function Login() {
  const { setRole } = useRole()
  const navigate = useNavigate()
  const scopes = useScopes()
  const [name, setName] = useState('')
  const [role, setRoleValue] = useState<OfficialRole | ''>('')
  const [scope, setScope] = useState('')
  const reduce = useReducedMotion()

  const picker =
    role === 'ministry_official' ? { options: scopes.data?.ministries, noun: 'ministry', plural: 'ministries' }
      : role === 'agency_official' ? { options: scopes.data?.agencies, noun: 'agency', plural: 'agencies' }
        : null
  const ready = !!role && (!picker || !!scope)

  function handleContinue() {
    if (!role || !ready) return
    const label = ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role
    setRole({
      role,
      displayName: name.trim() || label,
      ministry: role === 'ministry_official' ? scope : undefined,
      agency: role === 'agency_official' ? scope : undefined,
    })
    navigate('/')
  }

  function continueAsPublic() {
    setRole({ role: 'public', displayName: '' })
    navigate('/')
  }

  const enter = (delay: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 14, filter: 'blur(6px)' },
          animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
          transition: { duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] as const },
        }

  return (
    <SonarGrid
      spacing={30}
      speed={220}
      ringWidth={110}
      amplitude={2.6}
      pingEvery={2.8}
      baseOpacity={0.22}
      color="#000000"
      pingArea={[0.15, 0.12, 0.85, 0.75]}
      className="flex min-h-dvh w-full flex-col items-center justify-center bg-white px-4 py-16"
    >
      {/* Radial wash so the card sits on a calm patch of the sonar field. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_50%_45%_at_50%_42%,#ffffff_0%,transparent_100%)]"
      />

      <motion.div {...enter(0)} className="mb-10 flex flex-col items-center text-center">
        <span className="font-sans text-3xl font-extrabold tracking-[0.2em] text-fg-base">
          PAIMANA
          <span className="ml-2 text-base font-bold tracking-widest text-fg-dimmed">RADAR</span>
        </span>
        <span className="mt-3 text-xs text-fg-dimmed">
          Early warning &amp; predictive decision support
        </span>
      </motion.div>

      <motion.div {...enter(0.1)} className="w-full max-w-md">
        <Card
          title="Sign In"
          className="border-border-default bg-surface-panel/95 shadow-2xl shadow-black/10 backdrop-blur-md"
        >
          <div className="space-y-5 px-8 py-6">
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Role">
              {ROLE_OPTIONS.map(({ value, label, hint, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={role === value}
                  onClick={() => {
                    setRoleValue(value)
                    setScope('')
                  }}
                  className={cn(
                    'flex flex-col items-center gap-1.5 rounded-lg border px-2 py-3 text-center transition-colors',
                    role === value
                      ? 'border-accent bg-accent/10 text-fg-base'
                      : 'border-border-default text-fg-muted hover:border-border-strong hover:text-fg-base'
                  )}
                >
                  <Icon className="size-5" strokeWidth={1.75} />
                  <span className="text-sm font-semibold leading-tight">{label}</span>
                  <span className="text-xs text-fg-dimmed">{hint}</span>
                </button>
              ))}
            </div>

            {picker && (
              <div className="space-y-2">
                <label className="block text-xs font-semibold text-fg-dimmed">
                  Your {picker.noun}
                </label>
                {picker.options ? (
                  <ScopePicker options={picker.options} value={scope} onChange={setScope} noun={picker.noun} plural={picker.plural} />
                ) : (
                  <div className="text-sm text-fg-dimmed">
                    {scopes.error ? 'Backend not reachable — the list needs it.' : 'Loading…'}
                  </div>
                )}
              </div>
            )}

            {role && (
              <div className="space-y-2">
                <label className="block text-xs font-semibold text-fg-dimmed">
                  Name <span className="font-normal normal-case tracking-normal">(optional)</span>
                </label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" className="py-2 text-sm" />
              </div>
            )}

            <Button variant="primary" className="w-full justify-center py-2.5 text-sm" disabled={!ready} onClick={handleContinue}>
              {picker && scope ? `Continue as ${scope}` : 'Continue'}
            </Button>

            <div className="flex items-center gap-3 text-xs text-fg-dimmed">
              <span className="h-px flex-1 bg-border-subtle" />
              or
              <span className="h-px flex-1 bg-border-subtle" />
            </div>

            <button
              type="button"
              onClick={continueAsPublic}
              className="w-full rounded-md border border-border-default py-2.5 text-sm font-medium text-fg-muted transition-colors hover:border-border-strong hover:text-fg-base"
            >
              Continue as public
            </button>

            <p className="text-center text-xs text-fg-dimmed">Prototype sign-in: no password, not real authentication.</p>
          </div>
        </Card>
      </motion.div>
    </SonarGrid>
  )
}
