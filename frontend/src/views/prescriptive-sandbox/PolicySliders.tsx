import { Slider } from '@/components/ui/Slider'
import { Button } from '@/components/ui/Button'
import { formatINR, formatPct } from '@/lib/formatters'
import type { SandboxControls } from '@/contracts/sandbox'

interface PolicySlidersProps {
  controls: SandboxControls
  onChange: (controls: SandboxControls) => void
  onReset: () => void
}

export function PolicySliders({ controls, onChange, onReset }: PolicySlidersProps) {
  return (
    <div className="border border-border-subtle bg-surface-panel">
      <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
        <span className="text-xs font-sans font-bold uppercase tracking-wider text-fg-muted">
          Policy Levers
        </span>
        <Button variant="ghost" size="sm" onClick={onReset}>
          RESET
        </Button>
      </div>

      <div className="divide-y divide-border-subtle">
        {/* Lever 1 */}
        <div className="px-4 py-3 space-y-2">
          <div className="font-sans text-sm font-semibold text-fg-base">
            Statutory Clearance Fast-Tracking
          </div>
          <div className="font-sans text-xs text-fg-muted">
            MoEFCC Stage-II, Section 11/19, utility NOCs
          </div>
          <Slider
            label="Clearance Compression"
            valueDisplay={`${controls.clearanceAccelerationDays}d`}
            min={0} max={90} step={5}
            value={[controls.clearanceAccelerationDays]}
            onValueChange={([val]) => onChange({ ...controls, clearanceAccelerationDays: val ?? 0 })}
          />
        </div>

        {/* Lever 2 */}
        <div className="px-4 py-3 space-y-2">
          <div className="font-sans text-sm font-semibold text-fg-base">
            Emergency Working Capital Tranche
          </div>
          <div className="font-sans text-xs text-fg-muted">
            EPC liquidity unlock, sub-contractor bills
          </div>
          <Slider
            label="Capital Injection"
            valueDisplay={formatINR(controls.capitalTrancheInjectionCr)}
            min={0} max={300} step={10}
            value={[controls.capitalTrancheInjectionCr]}
            onValueChange={([val]) => onChange({ ...controls, capitalTrancheInjectionCr: val ?? 0 })}
          />
        </div>

        {/* Lever 3 */}
        <div className="px-4 py-3 space-y-2">
          <div className="font-sans text-sm font-semibold text-fg-base">
            Workforce & Equipment Mobilization
          </div>
          <div className="font-sans text-xs text-fg-muted">
            24x7 shifts, supplementary machinery
          </div>
          <Slider
            label="Mobilization Surge"
            valueDisplay={`+${formatPct(controls.workforceMobilizationPct, 0)}`}
            min={0} max={50} step={5}
            value={[controls.workforceMobilizationPct]}
            onValueChange={([val]) => onChange({ ...controls, workforceMobilizationPct: val ?? 0 })}
          />
        </div>
      </div>
    </div>
  )
}
