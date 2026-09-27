import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { useRole, useScopeKey } from '@/lib/auth/RoleContext'
import type { DispatchDraft } from '@/contracts/workers'
import { apiGet, apiPost } from '@/lib/api'

/**
 * Memos from the worker cell. The backend sends only what the role may see (ported from Pranjal's
 * frontend-dev: an agency or ministry official sees the memos addressed to their role, on their own
 * projects; IPMD sees all) and lets only the addressee decide.
 */
export function ApprovalInbox() {
  const { role } = useRole()
  const scope = useScopeKey()
  const queryClient = useQueryClient()

  const { data: drafts, isError } = useQuery({
    queryKey: ['dispatch', 'drafts', scope],
    queryFn: () => apiGet<DispatchDraft[]>('/api/dispatch'),
  })

  const decide = useMutation({
    mutationFn: (vars: { draftId: string; decision: 'approved' | 'rejected' }) =>
      apiPost<DispatchDraft>('/api/approvals', vars),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dispatch'] })
    },
  })

  const sorted = [...(drafts ?? [])].sort((a, b) => {
    if (a.status === 'pending' && b.status !== 'pending') return -1
    if (a.status !== 'pending' && b.status === 'pending') return 1
    return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  })

  return (
    <div className="mx-auto max-w-[1100px] px-4 py-4 space-y-4">
      <h1 className="font-mono text-sm font-medium uppercase tracking-wider text-fg-base">
        Approval Inbox
      </h1>

      <div className="h-px bg-border-subtle" />

      {decide.isError && (
        <p className="font-mono text-[11px] text-critical">
          Decision failed to save — is the FastAPI server running?
        </p>
      )}

      {isError || sorted.length === 0 ? (
        <Card>
          <div className="px-5 py-8 text-center font-mono text-xs text-fg-dimmed">
            {isError
              ? 'Backend not running — start the FastAPI server to see dispatch drafts.'
              : 'No memos for you yet.'}
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {sorted.map((draft) => {
            const canDecide = draft.status === 'pending' && role === draft.recommendedRecipientRole
            const isPending = decide.isPending && decide.variables?.draftId === draft.id

            return (
              <Card key={draft.id}>
                <div className="space-y-3 px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-fg-base">{draft.projectName}</div>
                      <div className="font-mono text-[10px] uppercase tracking-widest text-fg-dimmed">
                        recommended for {draft.recommendedRecipientRole.replace('_', ' ')}
                      </div>
                    </div>
                    <Badge variant={draft.status === 'pending' ? 'accent' : 'muted'}>
                      [{draft.status.toUpperCase()}]
                    </Badge>
                  </div>

                  <p className="whitespace-pre-wrap font-sans text-xs text-fg-muted">
                    {draft.draftMemo}
                  </p>

                  {draft.evidence.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {draft.evidence.map((ev, i) =>
                        ev.sourceUrl ? (
                          <a
                            key={i}
                            href={ev.sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            title={ev.note}
                            className="rounded-sm border border-border-default bg-surface-elevated px-2 py-0.5 font-mono text-[10px] text-accent hover:border-accent"
                          >
                            {ev.tag}
                          </a>
                        ) : (
                          <span
                            key={i}
                            title={ev.note}
                            className="rounded-sm border border-border-default bg-surface-elevated px-2 py-0.5 font-mono text-[10px] text-fg-dimmed"
                          >
                            {ev.tag}
                          </span>
                        )
                      )}
                    </div>
                  )}

                  {canDecide && (
                    <div className="flex items-center gap-2 pt-1">
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={isPending}
                        onClick={() => decide.mutate({ draftId: draft.id, decision: 'approved' })}
                      >
                        Approve
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={isPending}
                        onClick={() => decide.mutate({ draftId: draft.id, decision: 'rejected' })}
                      >
                        Reject
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
