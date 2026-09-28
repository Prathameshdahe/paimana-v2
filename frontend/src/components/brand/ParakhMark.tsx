import { useId, useMemo } from 'react'
import { cn } from '@/lib/formatters'
import { PARAKH_MARKUP, PARAKH_VIEWBOX } from './parakhMarkup'
import './parakh.css'

/** The beacon: stable (green, slow), watch (amber, the brand colour), critical (red, fast, a double ring). */
export type BeaconStatus = 'stable' | 'watch' | 'critical'

interface ParakhMarkProps {
  /** width and height in px */
  size?: number
  status?: BeaconStatus
  /** the inks for a light or a dark background */
  tone?: 'light' | 'dark'
  /** false: the still mark */
  animated?: boolean
  /** draw the mark in once before the loop starts */
  intro?: boolean
  /** the accessible name; without one the mark is decorative (next to the word PARAKH) */
  title?: string
  className?: string
}

function escapeText(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/**
 * The PARAKH mark: a lens (octagon, eye, iris), a small network whose pulses rise to the beacon, and the beacon, whose
 * colour and pace follow `status`. brand/build_brand.py writes the markup (parakhMarkup.ts, static and trusted) and
 * parakh.css animates it; reduced motion shows the still mark.
 */
export function ParakhMark({
  size = 32,
  status = 'watch',
  tone = 'light',
  animated = true,
  intro = false,
  title,
  className,
}: ParakhMarkProps) {
  // one mask per instance: useId's punctuation is not wanted inside url(#...)
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, '')
  const html = useMemo(
    () => (title ? `<title>${escapeText(title)}</title>` : '') + PARAKH_MARKUP.replaceAll('__UID__', uid),
    [uid, title],
  )
  return (
    <svg
      className={cn('pk shrink-0', className)}
      viewBox={PARAKH_VIEWBOX}
      width={size}
      height={size}
      data-status={status}
      data-tone={tone}
      data-animated={animated}
      data-intro={intro}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
