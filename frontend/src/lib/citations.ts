/**
 * src/lib/citations.ts
 *
 * Splits LLM text into plain runs, **bold** runs and citation markers, so the views build them as React nodes and
 * never inject HTML. Two marker styles: the assistant's source numbers `[1]`, `[1, 3]`, and the second opinion's
 * evidence ids `[E2]`, `[E2, E5]`. Anything else in brackets stays text.
 */

export type Segment =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  /** refs: '1', '3' or 'E2', 'E5', in the order written */
  | { kind: 'cite'; refs: string[] }

const PATTERN = {
  number: /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]|\*\*([^*\n]+)\*\*/g,
  evidence: /\[(E\d{1,3}(?:\s*,\s*E\d{1,3})*)\]|\*\*([^*\n]+)\*\*/g,
} as const

export type CiteStyle = keyof typeof PATTERN

export function splitCitations(text: string, style: CiteStyle): Segment[] {
  const out: Segment[] = []
  const re = new RegExp(PATTERN[style])
  let at = 0
  for (const m of text.matchAll(re)) {
    const i = m.index ?? 0
    if (i > at) out.push({ kind: 'text', text: text.slice(at, i) })
    if (m[1] !== undefined) out.push({ kind: 'cite', refs: m[1].split(',').map((r) => r.trim()) })
    else out.push({ kind: 'bold', text: m[2] ?? '' })
    at = i + m[0].length
  }
  if (at < text.length) out.push({ kind: 'text', text: text.slice(at) })
  return out
}

/** every ref the text cites, first mention first, once each */
export function citedRefs(text: string, style: CiteStyle): string[] {
  const refs = splitCitations(text, style).flatMap((s) => (s.kind === 'cite' ? s.refs : []))
  return [...new Set(refs)]
}

/** the URL when it is an http(s) link, else null: a source link never runs script or opens another scheme */
export function webUrl(u: string | null | undefined): string | null {
  return u && /^https?:\/\//i.test(u.trim()) ? u.trim() : null
}
