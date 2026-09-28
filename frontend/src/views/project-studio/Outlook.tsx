/**
 * The project's outlook in words (SPEC9_ui section 6): the tier as a full ring with its word inside, and three
 * statement tiles — "Delay: very likely", "Cost rise: unlikely", "Likely slip: 6 to 12 months" — in the outlook
 * tones. No percentage anywhere: the ring is a whole circle in the tier colour, never an arc that reads as a share.
 */
import { motion } from 'motion/react'
import { DEFAULT_HORIZON, OUTLOOK_ICON, OUTLOOK_NOUN, TONE_TEXT, slipTone, toneOf, type OutlookTone } from '@/lib/outlook'
import { TIER_COLOR, TIER_LABEL, TIER_TEXT, tierKey } from '@/lib/riskPalette'
import { cn } from '@/lib/formatters'
import type { Outlook, OutlookWord, SlipBand, Tier } from '@/contracts/project'

const TILE_TONE: Record<OutlookTone | 'muted', string> = {
  critical: 'border-critical/30 bg-critical/5',
  warning: 'border-warning/30 bg-warning/5',
  watch: 'border-watch/30 bg-watch/5',
  stable: 'border-stable/25 bg-stable/5',
  muted: 'border-border-subtle bg-surface-elevated/60',
}

/** the tier as a whole ring in its colour with the word inside; Watch and not scored in grey-violet */
export function TierRing({ tier, size = 'md' }: { tier: Tier | null | undefined; size?: 'sm' | 'md' }) {
  const t = tierKey(tier ?? null)
  const word = !tier ? 'Not scored' : t === 'Watch' ? 'Watch' : TIER_LABEL[t]
  const px = size === 'sm' ? 'size-20' : 'size-28'
  return (
    <div className={cn('relative shrink-0', px)} role="img" aria-label={`Tier: ${word}`}>
      <svg viewBox="0 0 120 120" className={px} aria-hidden="true">
        <motion.circle cx={60} cy={60} r={50} fill="none" strokeWidth={10} stroke={TIER_COLOR[t]} strokeOpacity={tier ? 1 : 0.4}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.22 }} />
      </svg>
      <span className={cn('absolute inset-0 flex items-center justify-center px-3 text-center font-semibold leading-tight',
        size === 'sm' ? 'text-sm' : 'text-lg', tier ? TIER_TEXT[t] : 'text-fg-muted')}>
        {word}
      </span>
    </div>
  )
}

/** one statement tile: an icon, the noun and its word, in the word's tone; a missing word says why */
function Tile({ part, word, missing }: { part: 'delay' | 'cost' | 'slip'; word: string | null; missing: string }) {
  const Icon = OUTLOOK_ICON[part]
  const tone = part === 'slip' ? slipTone(word as SlipBand | null) : toneOf(word as OutlookWord | null)
  return (
    <div className={cn('flex min-w-0 items-start gap-2.5 rounded-lg border px-3 py-2.5', TILE_TONE[tone])}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', TONE_TEXT[tone])} strokeWidth={2} aria-hidden="true" />
      <div className="min-w-0">
        <div className="text-xs text-fg-muted">{OUTLOOK_NOUN[part]}</div>
        {word ? (
          <div className={cn('text-sm font-semibold leading-snug', TONE_TEXT[tone])}>{word}</div>
        ) : (
          <div className="text-xs leading-snug text-fg-dimmed">{missing}</div>
        )}
      </div>
    </div>
  )
}

/**
 * The three outlook tiles and their horizon. outlook null: the tiles say why (a Watch project is not ranked; a scored
 * one has no words from this backend yet).
 */
export function OutlookTiles({ outlook, tier, className }: { outlook: Outlook | null; tier: Tier | null | undefined; className?: string }) {
  const watch = tierKey(tier ?? null) === 'Watch'
  const why = !tier ? 'not scored in the current portfolio' : watch ? 'not ranked: no completion date in the reports' : 'not available yet'
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="grid gap-2 sm:grid-cols-3">
        <Tile part="delay" word={outlook?.delay ?? null} missing={why} />
        <Tile part="cost" word={outlook?.cost ?? null} missing={why} />
        <Tile part="slip" word={outlook?.slip ?? null} missing={why} />
      </div>
      {outlook && <p className="text-xs text-fg-dimmed">Over the {outlook.horizon ?? DEFAULT_HORIZON}, from the risk model; the reports themselves say what has happened so far.</p>}
    </div>
  )
}
