/**
 * src/lib/agencyWords.ts
 *
 * An agency's past pattern in words (SPEC9_ui section 6): the backend's scheduleWord and costWord replace the bias
 * statistics for the four roles. The phrases, tones and the peer sentence the agency pages and homes read. Counts
 * of agencies by their word are facts; nothing here reads a bias.
 */
import { fractionWord } from './headline'
import type { AgencyPoint, CostWord, ScheduleWord } from '@/contracts/intel'

/** the three schedule words the dot plot places, left to right */
export const PLACED_WORDS: ScheduleWord[] = ['usually earlier', 'about on time', 'usually later']

/** agencies with a placed word, by sector, the sector with the most first (at most `max` sectors) */
export function agenciesBySector(points: AgencyPoint[], max = 8): Array<[string, AgencyPoint[]]> {
  const groups = new Map<string, AgencyPoint[]>()
  for (const a of points) {
    if (!a.sector || !a.scheduleWord || !PLACED_WORDS.includes(a.scheduleWord)) continue
    groups.set(a.sector, [...(groups.get(a.sector) ?? []), a])
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, max)
}

/** "5 of the 9 agencies in Roads usually finish later than planned." for the sector with the most agencies in words */
export function agencyTakeaway(points: AgencyPoint[]): string | null {
  const [sector, rows] = agenciesBySector(points, 1)[0] ?? []
  if (!sector || !rows?.length) return null
  const later = rows.filter((a) => a.scheduleWord === 'usually later').length
  const verb = later === 1 ? 'finishes' : 'finish'
  return `${later} of the ${rows.length} agencies in ${sector} usually ${verb} later than planned.`
}

/** page order: the ones to ask about first */
export const SCHEDULE_ORDER: ScheduleWord[] = ['usually later', 'about on time', 'usually earlier', 'too few projects']

export const SCHEDULE_PHRASE: Record<ScheduleWord, string> = {
  'usually later': 'Usually later than planned',
  'about on time': 'About on time',
  'usually earlier': 'Usually earlier than planned',
  'too few projects': 'Too few past projects to say',
}

export const COST_PHRASE: Record<CostWord, string> = {
  'usually costs more': 'Usually costs more than planned',
  'about as planned': 'About as planned',
  'usually costs less': 'Usually costs less than planned',
  'too few projects': 'Too few past projects to say',
}

export const SCHEDULE_TONE: Record<ScheduleWord, 'critical' | 'stable' | 'muted' | 'accent'> = {
  'usually later': 'critical',
  'about on time': 'muted',
  'usually earlier': 'stable',
  'too few projects': 'muted',
}

export const COST_TONE: Record<CostWord, 'critical' | 'stable' | 'muted'> = {
  'usually costs more': 'critical',
  'about as planned': 'muted',
  'usually costs less': 'stable',
  'too few projects': 'muted',
}

/** do the agencies carry words at all (a backend from before the numbers policy sends none) */
export function hasWords(points: AgencyPoint[]): boolean {
  return points.some((a) => a.scheduleWord)
}

/** "most agencies in Roads are about on time": the word most peers share, with its fraction word */
export function peerClause(peers: AgencyPoint[], sector: string | null): string | null {
  const known = peers.filter((a) => a.scheduleWord && a.scheduleWord !== 'too few projects')
  if (known.length < 2) return null
  const counts = new Map<ScheduleWord, number>()
  for (const a of known) {
    const w = a.scheduleWord as ScheduleWord
    counts.set(w, (counts.get(w) ?? 0) + 1)
  }
  const [word, n] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0] ?? []
  if (!word || !n) return null
  const frac = fractionWord(n, known.length)
  const verb = word === 'about on time' ? 'are about on time'
    : word === 'usually later' ? 'usually finish later than planned' : 'usually finish earlier than planned'
  const whole = frac === 'all' || frac === 'most' || frac === 'nearly all'
  const who = whole ? `${frac} agencies` : `${frac} of the agencies`
  return `${who}${sector ? ` in ${sector}` : ''} ${verb}`
}
