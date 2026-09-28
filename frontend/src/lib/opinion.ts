/**
 * src/lib/opinion.ts
 *
 * Words for the AI second opinion's 503 (contracts/project.ts SecondOpinionUnavailable): busy first, since the model
 * is up and only taken; then down (LM Studio not reachable: start it); else it was reached and answered nothing in
 * time. A backend without the `down` flag reads as down, the only 503 it knew.
 */
import type { SecondOpinionUnavailable } from '@/contracts/project'

export function unavailableHeadline(body: Partial<SecondOpinionUnavailable> | undefined): string {
  if (body?.busy === true) return 'The local model is busy; try again in a minute'
  if (body?.down === false) return 'The local model did not answer in time; try again'
  return 'The local AI model is not running, so no opinion can be written now'
}
