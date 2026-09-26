import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import type { WorkerRun } from '@/contracts/workers'
import { API_BASE } from '@/lib/api'

async function fetchWorkerRuns(): Promise<WorkerRun[]> {
  const res = await fetch(`${API_BASE}/api/worker-runs`)
  if (!res.ok) throw new Error(`worker-runs fetch failed: ${res.status}`)
  return res.json()
}

async function triggerMonitoringCycle(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/worker-runs/trigger`, { method: 'POST' })
  if (!res.ok) throw new Error(`trigger failed: ${res.status}`)
}

export function WorkerConsole() {
  const queryClient = useQueryClient()

  const { data: runs, isError } = useQuery({
    queryKey: ['workers', 'runs'],
    queryFn: fetchWorkerRuns,
  })

  const trigger = useMutation({
    mutationFn: triggerMonitoringCycle,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workers', 'runs'] })
      queryClient.invalidateQueries({ queryKey: ['dispatch'] })
    },
  })

  const sorted = [...(runs ?? [])].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="font-mono text-sm font-medium uppercase tracking-wider text-fg-base">
          Worker Console
        </h1>
        <div className="flex items-center gap-3">
          {trigger.isError && (
            <span className="font-mono text-[11px] text-critical">
              Trigger failed — is the FastAPI server running?
            </span>
          )}
          <Button variant="primary" onClick={() => trigger.mutate()} disabled={trigger.isPending}>
            {trigger.isPending ? 'Running… (1–3 min)' : 'Run Monitoring Cycle Now'}
          </Button>
        </div>
      </div>

      <div className="h-px bg-border-subtle" />

      {isError || sorted.length === 0 ? (
        <Card>
          <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">
            {isError
              ? 'Backend not running — start the FastAPI server to see worker activity.'
              : 'No worker runs yet.'}
          </div>
        </Card>
      ) : (
        <Card title={`Worker Runs · ${sorted.length}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-border-subtle text-[10px] uppercase tracking-widest text-fg-dimmed">
                  <th className="px-5 py-2 font-medium">Worker</th>
                  <th className="px-3 py-2 font-medium">Model / Version</th>
                  <th className="px-3 py-2 font-medium">Dataset</th>
                  <th className="px-3 py-2 font-medium text-right">Processed</th>
                  <th className="px-3 py-2 font-medium text-right">Alerts</th>
                  <th className="px-3 py-2 font-medium">Timestamp</th>
                  <th className="px-3 py-2 font-medium">Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {sorted.map((run) => (
                  <tr key={run.id} className="hover:bg-surface-elevated">
                    <td className="px-5 py-2 text-fg-base">{run.worker}</td>
                    <td className="px-3 py-2 text-fg-muted">{run.modelVersion}</td>
                    <td className="px-3 py-2 text-fg-muted">{run.dataset}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-fg-base">
                      {run.projectsProcessed}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-fg-base">
                      {run.alertsRaised}
                    </td>
                    <td className="px-3 py-2 text-fg-dimmed">
                      {new Date(run.timestamp).toLocaleString()}
                    </td>
                    <td className="max-w-xs truncate px-3 py-2 text-fg-muted" title={run.summary}>
                      {run.summary}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
