import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MOCK_PROJECTS } from '@/mocks/projects'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { formatINRShort, formatMonths } from '@/lib/formatters'

/**
 * Action-oriented alert feed — distinct from the Triage Table (which is a
 * browse/sort/filter register). This is "what needs a decision right now",
 * sorted by urgency, with an acknowledge action so it reads as a workflow
 * inbox rather than a dashboard widget.
 *
 * Acknowledged state is local (useState), there is no persistence layer yet.
 * Resets on reload. Fine for a demo; swap for a real store when there's a
 * backend to write to.
 */
export function EarlyWarningInbox() {
  const navigate = useNavigate()
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set())

  const alerts = useMemo(() => {
    return MOCK_PROJECTS
      .filter((p) => p.riskTier === 'CRITICAL' || p.actionableRunwayDays <= 30)
      .sort((a, b) => b.compositeRiskScore - a.compositeRiskScore)
      .slice(0, 30)
  }, [])

  const visible = alerts.filter((a) => !acknowledged.has(a.id))

  return (
    <Card
      title="Early Warning Inbox"
      titleRight={<span className="text-[11px] font-mono text-fg-dimmed">{visible.length} open</span>}
      className="h-full flex flex-col"
    >
      {visible.length === 0 ? (
        <div className="px-5 py-8 text-center text-xs font-mono text-fg-dimmed">All clear — no critical or &le;30-day-runway projects.</div>
      ) : (
        <div className="divide-y divide-border-subtle flex-1 overflow-y-auto">
          {visible.map((p) => (
            <div key={p.id} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-elevated">
              <Badge tier={p.riskTier} />
              <button
                onClick={() => navigate(`/projects/${p.id}`)}
                className="flex-1 min-w-0 text-left"
              >
                <div className="truncate text-xs font-medium text-fg-base">{p.name}</div>
                <div className="truncate text-[11px] font-mono text-fg-dimmed">
                  {p.code} · {p.sector} · {p.state} · {p.actionableRunwayDays}d runway · {formatMonths(p.predictedDelayMonths)} delay · {formatINRShort(p.overrunForecastCr)} overrun
                </div>
              </button>
              <Button size="sm" variant="ghost" onClick={() => setAcknowledged((s) => new Set(s).add(p.id))}>
                Acknowledge
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
