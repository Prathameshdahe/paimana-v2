/**
 * src/contracts/workers.ts
 *
 * Type contracts for the background worker fleet (Worker Console) and the
 * human-in-the-loop dispatch review queue (Approval Inbox).
 */

export interface WorkerRun {
  id: string
  worker: 'auditor' | 'forecaster' | 'scout' | 'analyst' | 'dispatcher'
  modelVersion: string
  dataset: string
  projectsProcessed: number
  alertsRaised: number
  timestamp: string
  summary: string
}

export interface DispatchDraft {
  id: string
  projectId: string
  projectName: string
  draftMemo: string
  recommendedRecipientRole: 'ipmd_analyst' | 'ministry_official' | 'agency_official'
  status: 'pending' | 'approved' | 'edited' | 'rejected'
  createdAt: string
  evidence: Array<{ tag: string; sourceUrl: string | null; note: string }>
}
