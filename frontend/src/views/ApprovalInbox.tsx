import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Page, PageHeader } from '@/components/layout/Page'
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
    <Page narrow>
      <PageHeader title="Approvals" subtitle="Memos from the worker cell, addressed to your role" />

      {decide.isError && (
        <p className="text-xs text-critical">
          Decision failed to save — is the FastAPI server running?
        </p>
      )}

      {isError || sorted.length === 0 ? (
        <Card>
          <div className="px-5 py-8 text-center text-xs text-fg-dimmed">
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
                      <div className="text-xs text-fg-dimmed">
                        recommended for {draft.recommendedRecipientRole.replace('_', ' ')}
                      </div>
                    </div>
                    <Badge variant={draft.status === 'pending' ? 'accent' : 'muted'} className="capitalize">
                      {draft.status}
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
                            className="rounded-sm border border-border-default bg-surface-elevated px-2 py-0.5 text-xs text-accent hover:border-accent"
                          >
                            {ev.tag}
                          </a>
                        ) : (
                          <span
                            key={i}
                            title={ev.note}
                            className="rounded-sm border border-border-default bg-surface-elevated px-2 py-0.5 text-xs text-fg-dimmed"
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
    </Page>
  )
}
