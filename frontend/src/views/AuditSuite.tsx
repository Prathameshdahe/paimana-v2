import { MOCK_BENCHMARK_ROWS, MOCK_CUF_AUDIT_ROWS } from '@/mocks/audit'
import { BenchmarkMatrix } from './audit-suite/BenchmarkMatrix'
import { CUFAuditTable } from './audit-suite/CUFAuditTable'

// ponytail: still the hand-copied v1 numbers in mocks/audit.ts; the Models page will read /api/models
export function AuditSuite() {
  const benchmarks = MOCK_BENCHMARK_ROWS
  const cufAudit = MOCK_CUF_AUDIT_ROWS

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono text-sm font-medium tracking-wider text-fg-base uppercase">
            Transparency & Audit Suite
          </h1>
          <span className="font-mono text-[11px] tracking-widest text-fg-muted font-medium">
            VERIFY
          </span>
        </div>
        <div className="font-mono text-[11px] text-fg-muted">
          clause (b) + (c) compliance
        </div>
      </div>

      <div className="h-px bg-border-subtle" />

      <BenchmarkMatrix rows={benchmarks} />

      {/* Clause (c) Section Divider */}
      <div className="pt-6 pb-2">
        <div className="relative flex items-center">
          <div className="flex-grow border-t border-border-default" />
          <div className="mx-4 flex items-center gap-2 border border-border-default bg-surface-panel px-4 py-1.5 shadow-xs">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            <span className="font-mono text-xs font-semibold tracking-wider text-fg-base uppercase">
              Clause (c) · CUF Field Utility & Missing Variable Audit
            </span>
            <span className="font-mono text-[11px] text-fg-muted">
              (Statutory Ground Truth Verification)
            </span>
          </div>
          <div className="flex-grow border-t border-border-default" />
        </div>
      </div>

      <CUFAuditTable rows={cufAudit} />
    </div>
  )
}
