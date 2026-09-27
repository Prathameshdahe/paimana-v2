import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'motion/react'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { SonarGrid } from '@/components/ui/sonar-grid'
import { useRole, type Role } from '@/lib/auth/RoleContext'

const ROLE_OPTIONS: Array<{ value: Role; label: string }> = [
  { value: 'ipmd_analyst', label: 'IPMD Analyst' },
  { value: 'ministry_official', label: 'Ministry Official' },
  { value: 'agency_official', label: 'Implementing Agency' },
  { value: 'public', label: 'Public' },
]

export function Login() {
  const { setRole } = useRole()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [role, setRoleValue] = useState<Role | ''>('')
  const reduce = useReducedMotion()

  function handleContinue() {
    if (!role) return
    const label = ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role
    setRole(role, name.trim() || label)
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
        <span className="mt-3 font-mono text-xs uppercase tracking-widest text-fg-dimmed">
          Early warning &amp; predictive decision support
        </span>
      </motion.div>

      <motion.div {...enter(0.1)} className="w-full max-w-md">
        <Card
          title="Sign In"
          className="border-border-default bg-surface-panel/95 shadow-2xl shadow-black/10 backdrop-blur-md"
        >
          <div className="px-8 py-6 space-y-6">
            <p className="font-mono text-xs leading-relaxed text-warning">
              Prototype login — role-based access, not yet connected to real authentication.
            </p>

            <div className="space-y-2">
              <label className="block font-mono text-[11px] uppercase tracking-widest text-fg-dimmed">
                Name
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                className="py-2 text-sm"
              />
            </div>

            <div className="space-y-2">
              <label className="block font-mono text-[11px] uppercase tracking-widest text-fg-dimmed">
                Role
              </label>
              <select
                value={role}
                onChange={(e) => setRoleValue(e.target.value as Role)}
                className="w-full rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-fg-base focus:border-accent focus:outline-none"
              >
                <option value="" disabled>
                  Select a role…
                </option>
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <Button
              variant="primary"
              className="w-full justify-center py-2.5 text-sm"
              disabled={!role}
              onClick={handleContinue}
            >
              Continue
            </Button>
          </div>
        </Card>
      </motion.div>
    </SonarGrid>
  )
}
