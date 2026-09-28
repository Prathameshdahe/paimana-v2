import React, { memo, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { Meter } from './KPIRibbon'
import { TIER_COLOR, TIER_LABEL, TIER_TEXT, TIERS, tierKey } from '@/lib/riskPalette'
import { OUTLOOK_TONE, OUTLOOK_WORDS, TONE_DOT, TONE_TEXT, outlookOf, toneOf } from '@/lib/outlook'
import { dueIn } from '@/lib/headline'
import { cn, formatDate, formatINR } from '@/lib/formatters'
import {
  AXIS_H, LABEL_W, OVERFLOW_H, SIZES, ZOOMS, hitTest, keysIn, layoutMap, markAt, resumeIndex, type Dot, type LaneMode, type LaneSpec,
  type MapLayout, type OverflowMark, type Zoom,
} from './riskMapLayout'
import type { MapRow, Outlook, OutlookWord, TierFilter } from '@/contracts/project'
import type { TierCount } from '@/contracts/portfolio'

interface RiskMapProps {
  rows: MapRow[] | undefined
  /** set when rows are only the riskiest few of the scope (no map endpoint) */
  partial: { shown: number; total: number } | null
  isLoading: boolean
  error: unknown
  asof: string | undefined
  /** the developer: words may be derived from numbers when the backend sends none */
  numbers: boolean
  /** the shared tier filter: in tier lanes the other tiers collapse */
  tierFilter: TierFilter | undefined
  tierCounts: TierCount[] | undefined
  /** the open side panel's project: its dot keeps an accent ring */
  openKey: string | null
  onOpen: (key: string) => void
  selection: ReadonlySet<string>
  onSelect: (keys: string[], add: boolean) => void
  onToggle: (key: string) => void
  onClearSelection: () => void
  /** lists the projects without a completion date (the Watch tier) */
  onListNoDate: () => void
  filtersActive: boolean
  onClearFilters: () => void
  className?: string
}

/** the words a dot says: its aria text, the hover card's outlook line and the live region */
function dotText(row: MapRow, o: Outlook | null, asof: string | undefined): string {
  const due = dueIn(row.anticipatedCompletion, asof)
  return [
    row.key,
    TIER_LABEL[tierKey(row.tier)],
    due?.text,
    o?.delay ? `delay ${o.delay}` : null,
  ].filter(Boolean).join(', ')
}

/** container width, measured; the server render and the first paint use the fallback */
function useWidth(ref: React.RefObject<HTMLDivElement | null>, fallback = 880): number {
  const [w, setW] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) setW(Math.round(width))
    })
    ro.observe(el)
    if (el.clientWidth) setW(el.clientWidth)
    return () => ro.disconnect()
  }, [ref])
  return w
}

function laneSpecs(mode: LaneMode, tierFilter: TierFilter | undefined, counts: TierCount[] | undefined, withNotRanked: boolean): LaneSpec[] {
  if (mode === 'outlook') {
    const words: LaneSpec[] = OUTLOOK_WORDS.map((w) => ({ id: w, label: w, word: w, collapsed: false }))
    return withNotRanked ? [...words, { id: 'none', label: 'not ranked', word: null, collapsed: false, thin: true }] : words
  }
  return TIERS.map((t) => ({
    id: t,
    label: TIER_LABEL[t],
    word: t,
    collapsed: !!tierFilter && tierFilter !== t,
    hidden: counts?.find((c) => c.tier === t)?.n ?? 0,
  }))
}

/** every dot, drawn once per data or selection change; hover and focus draw on top */
const DotsLayer = memo(function DotsLayer({ dots, selection, openKey }: {
  dots: Dot[]
  selection: ReadonlySet<string>
  openKey: string | null
}) {
  const fading = selection.size > 0
  return (
    <g>
      {dots.map((d) => {
        const t = tierKey(d.row.tier)
        const faded = fading && !selection.has(d.key)
        const notice = d.row.flags.includes('early_notice')
        return (
          <g key={d.key} opacity={faded ? 0.25 : 1}>
            {notice && (
              <circle cx={d.x} cy={d.y} r={d.r + (d.row.override ? 4.5 : 2.5)} fill="none" strokeWidth={1}
                className="stroke-critical" />
            )}
            {d.row.override && (
              <circle cx={d.x} cy={d.y} r={d.r + 2.5} fill="none" strokeWidth={1.25} strokeDasharray="2 2"
                className="stroke-fg-base" />
            )}
            <circle cx={d.x} cy={d.y} r={d.r} fill={TIER_COLOR[t]} fillOpacity={0.85}
              strokeWidth={d.key === openKey ? 2 : 1}
              className={d.key === openKey ? 'stroke-accent' : 'stroke-surface-panel'} />
          </g>
        )
      })}
    </g>
  )
})

/**
 * The command centre's risk map: every project in view as a dot, placed by when it is due (further left is sooner,
 * the hatched strip is overdue) and by lane: the delay outlook in words, or the tier until the backend sends words.
 * Size is the anticipated cost in three named steps; a red outer ring is early notice, a dashed ring stalled.
 * Hover shows a card, click opens the side panel, dragging on empty canvas selects the dots under it for the table
 * (Shift adds; on touch after a short hold), Escape clears. A month too crowded for its lane folds the rest into a
 * "+n" mark above the dots: clicking it lists those projects in the table, a brush over their column takes them too,
 * and the keyboard walk visits them. Keyboard: one tab stop per lane; Left and Right walk the
 * lane in due-date order, Up and Down change lane, Home and End jump, Enter opens, Space selects. The table below is
 * the full screen-reader path. No wheel zoom (the page must scroll): three presets set the window instead.
 */
export function RiskMap(p: RiskMapProps) {
  const { rows, asof, numbers } = p
  const box = useRef<HTMLDivElement>(null)
  const width = useWidth(box)
  const [zoom, setZoom] = useState<Zoom>('36')
  const [hover, setHover] = useState<Dot | null>(null)
  const [hoverMark, setHoverMark] = useState<OverflowMark | null>(null)
  const [focus, setFocus] = useState<{ lane: number; index: number } | null>(null)
  const [brush, setBrush] = useState<{ x0: number; y0: number; x1: number; y1: number; add: boolean } | null>(null)
  const [live, setLive] = useState('')
  const laneRefs = useRef<Array<SVGGElement | null>>([])
  // each lane's last walk index by lane id: coming back to a lane (after the side panel, or a Tab away) resumes there
  const lastIndex = useRef(new Map<string, number>())
  const svgRef = useRef<SVGSVGElement>(null)
  const frame = useRef<number | null>(null)
  const press = useRef<{
    x: number; y: number; dot: Dot | null; mark: OverflowMark | null; add: boolean; timer: number | null; armed: boolean; moved: boolean
  } | null>(null)
  // an id safe inside url(#...): useId's own may carry colons or guillemets
  const hatchId = `hatch-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

  const words = useMemo(() => {
    const m = new Map<string, Outlook | null>()
    for (const r of rows ?? []) m.set(r.key, outlookOf(r, numbers))
    return m
  }, [rows, numbers])
  const outlook = (r: MapRow) => words.get(r.key) ?? null
  const mode: LaneMode = (rows ?? []).some((r) => words.get(r.key)) ? 'outlook' : 'tier'
  const notRanked = mode === 'outlook' && (rows ?? []).some((r) => r.anticipatedCompletion && !r.noCompletionDate && !words.get(r.key)?.delay)
  const specs = useMemo(() => laneSpecs(mode, p.tierFilter, p.tierCounts, notRanked), [mode, p.tierFilter, p.tierCounts, notRanked])

  const layout: MapLayout | null = useMemo(() => {
    if (!rows || !asof) return null
    return layoutMap({ rows, asof, width, mode, specs, zoom, outlookOf: (r) => words.get(r.key) ?? null })
  }, [rows, asof, width, mode, specs, zoom, words])

  // the no-date count: the rows' own, or the portfolio's Watch count when the rows are only the riskiest few
  const watchN = p.tierCounts?.find((c) => c.tier === 'Watch')?.n ?? 0
  const noDate = p.partial ? (p.tierFilter && p.tierFilter !== 'Watch' ? 0 : watchN) : (layout?.noDate ?? 0)

  useEffect(() => () => { if (frame.current !== null) cancelAnimationFrame(frame.current) }, [])

  const point = (e: React.PointerEvent) => {
    const r = svgRef.current?.getBoundingClientRect()
    return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 }
  }

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if (!layout || e.button !== 0) return
    const { x, y } = point(e)
    const dot = hitTest(layout, x, y)
    const mark = dot ? null : markAt(layout, x, y)
    const touch = e.pointerType === 'touch'
    const state = { x, y, dot, mark, add: e.shiftKey, timer: null as number | null, armed: !dot && !mark && !touch, moved: false }
    // on touch the brush starts after a 150 ms hold, so a swipe still scrolls the page
    if (!dot && !mark && touch) state.timer = window.setTimeout(() => { if (press.current) press.current.armed = true }, 150)
    press.current = state
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!layout) return
    const { x, y } = point(e)
    const pr = press.current
    if (pr) {
      if (Math.hypot(x - pr.x, y - pr.y) > 4) pr.moved = true
      if (pr.timer !== null && pr.moved && !pr.armed) {
        clearTimeout(pr.timer)
        press.current = null
        return
      }
      if (pr.armed && pr.moved) setBrush({ x0: pr.x, y0: pr.y, x1: x, y1: y, add: pr.add })
      return
    }
    if (frame.current !== null) return
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      const dot = hitTest(layout, x, y)
      setHover(dot)
      setHoverMark(dot ? null : markAt(layout, x, y))
    })
  }

  function onPointerUp(e: React.PointerEvent<SVGSVGElement>) {
    const pr = press.current
    press.current = null
    if (!pr || !layout) return
    if (pr.timer !== null) clearTimeout(pr.timer)
    const { x, y } = point(e)
    if (brush) {
      p.onSelect(keysIn(layout, brush.x0, brush.y0, x, y), brush.add)
      setBrush(null)
      return
    }
    if (pr.dot && !pr.moved) p.onOpen(pr.dot.key)
    else if (pr.mark && !pr.moved) p.onSelect(pr.mark.keys, pr.add)
  }

  const focusDot = focus && layout ? layout.byLane[focus.lane]?.[focus.index] ?? null : null

  function moveFocus(lane: number, index: number) {
    const d = layout?.byLane[lane]?.[index]
    if (!d) return
    setFocus({ lane, index })
    const id = layout?.lanes[lane]?.id
    if (id) lastIndex.current.set(id, index)
    setLive(dotText(d.row, outlook(d.row), asof))
  }

  function nearestIndex(lane: number, x: number): number {
    const list = layout?.byLane[lane] ?? []
    let best = 0
    list.forEach((d, i) => { if (Math.abs(d.x - x) < Math.abs((list[best]?.x ?? Infinity) - x)) best = i })
    return best
  }

  function onLaneKey(e: React.KeyboardEvent, lane: number) {
    if (!layout) return
    const list = layout.byLane[lane] ?? []
    const i = focus?.lane === lane ? focus.index : 0
    const cur = list[i]
    const step = (dir: 1 | -1) => {
      for (let l = lane + dir; l >= 0 && l < layout.lanes.length; l += dir) {
        if ((layout.byLane[l]?.length ?? 0) > 0) {
          laneRefs.current[l]?.focus()
          moveFocus(l, nearestIndex(l, cur?.x ?? 0))
          return
        }
      }
    }
    switch (e.key) {
      case 'ArrowRight': moveFocus(lane, Math.min(list.length - 1, i + 1)); break
      case 'ArrowLeft': moveFocus(lane, Math.max(0, i - 1)); break
      case 'ArrowUp': step(-1); break
      case 'ArrowDown': step(1); break
      case 'Home': moveFocus(lane, 0); break
      case 'End': moveFocus(lane, list.length - 1); break
      case 'Enter': if (cur) p.onOpen(cur.key); break
      case ' ': if (cur) p.onToggle(cur.key); break
      case 'Escape': p.onClearSelection(); break
      default: return
    }
    e.preventDefault()
  }

  const shown = hover ?? focusDot
  // a folded row in the keyboard walk rings its "+n" mark
  const shownMark = shown?.folded && layout ? layout.overflow.find((o) => o.lane === shown.lane && o.keys.includes(shown.key)) ?? null : null
  const drawn = layout?.dots.length ?? 0
  const foldedN = layout?.overflow.reduce((s, o) => s + o.n, 0) ?? 0
  const titleRight = (
    <span className="flex flex-wrap items-center gap-2">
      <span className="inline-flex rounded-lg bg-surface-elevated p-0.5" role="group" aria-label="Time window">
        {ZOOMS.map((z) => (
          <button key={z.id} type="button" aria-pressed={zoom === z.id} onClick={() => setZoom(z.id)}
            className={cn(
              'h-7 rounded-md px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
              zoom === z.id ? 'bg-surface-panel text-fg-base shadow-sm' : 'text-fg-muted hover:text-fg-base'
            )}>
            {z.label}
          </button>
        ))}
      </span>
      <a href="#project-list" className="text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
        View as list
      </a>
    </span>
  )

  return (
    <Card className={p.className} title={mode === 'outlook' ? 'Due soon and likely to slip' : 'Due soon, by risk tier'} titleRight={titleRight}>
      <div className="space-y-3 px-5 pb-4 pt-3">
        <Takeaway rows={rows} asof={asof} />
        {p.partial && (
          <p className="text-xs text-fg-dimmed">
            Only the {p.partial.shown} most at risk of {p.partial.total.toLocaleString('en-IN')} are on the map
            {foldedN > 0 && ` (${drawn.toLocaleString('en-IN')} as dots, ${foldedN.toLocaleString('en-IN')} in the +n counts)`}; narrow the
            filters to place the others.
          </p>
        )}

        <a href="#project-list"
          className="sr-only focus:not-sr-only focus:inline-block focus:rounded-md focus:bg-surface-elevated focus:px-2 focus:py-1 focus:text-xs focus:text-fg-base">
          Skip to the project list
        </a>

        <div ref={box} className="relative w-full">
          {p.error ? (
            <ApiErrorNote error={p.error} />
          ) : !layout ? (
            <MapSkeleton />
          ) : (rows?.length ?? 0) === 0 ? (
            <Empty>
              No project matches these filters.{' '}
              {p.filtersActive && <button type="button" onClick={p.onClearFilters} className="font-medium text-accent hover:underline">Clear filters</button>}
            </Empty>
          ) : layout.dots.length === 0 && layout.later === 0 ? (
            <Empty>
              Nothing here has a completion date, so it cannot be placed by due date.
              {noDate > 0 && ` The ${noDate.toLocaleString('en-IN')} projects without one are in the table below.`}
            </Empty>
          ) : layout.dots.length === 0 ? (
            <Empty>
              Nothing is due {zoom === '12' ? 'in the next 12 months' : 'in the next three years'} here.{' '}
              <button type="button" onClick={() => setZoom('all')} className="font-medium text-accent hover:underline">Show all</button>
            </Empty>
          ) : (
            <div role="group" aria-label="Risk map" className="relative">
              <svg
                ref={svgRef}
                width={layout.width}
                height={layout.height}
                className="block touch-pan-y select-none"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerLeave={() => { if (!press.current) { setHover(null); setHoverMark(null) } }}
                onPointerCancel={() => { press.current = null; setBrush(null) }}
                style={{ cursor: hover || hoverMark ? 'pointer' : brush ? 'crosshair' : 'default' }}
              >
                <defs>
                  <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <line x1="0" y1="0" x2="0" y2="6" strokeWidth="2" className="stroke-fg-dimmed/15" />
                  </pattern>
                </defs>
                <Frame layout={layout} hatch={`url(#${hatchId})`} />
                {layout.lanes.map((lane, li) => (
                  <g
                    key={lane.id}
                    ref={(el) => { laneRefs.current[li] = el }}
                    tabIndex={!lane.collapsed && (layout.byLane[li]?.length ?? 0) > 0 ? 0 : -1}
                    role="group"
                    aria-label={laneAria(mode, lane.label, layout.byLane[li]?.length ?? 0, lane.collapsed)}
                    onFocus={() => { if (focus?.lane !== li) moveFocus(li, resumeIndex(lastIndex.current.get(lane.id), layout.byLane[li]?.length ?? 0)) }}
                    onBlur={() => setFocus((f) => (f?.lane === li ? null : f))}
                    onKeyDown={(e) => onLaneKey(e, li)}
                    className="outline-none"
                  >
                    <LaneLabel mode={mode} lane={lane} />
                  </g>
                ))}
                <DotsLayer dots={layout.dots} selection={p.selection} openKey={p.openKey} />
                {layout.overflow.map((o) => (
                  <g key={`${o.lane}-${o.x}`} className={hoverMark === o ? 'text-fg-base' : 'text-fg-muted'}>
                    <title>{`${o.n} more due then than fit here: click to list them`}</title>
                    <rect x={o.x - o.halfW} y={o.y - OVERFLOW_H / 2 + 1} width={2 * o.halfW} height={OVERFLOW_H - 2} rx={4}
                      className={hoverMark === o ? 'fill-surface-input' : 'fill-transparent'} />
                    <text x={o.x} y={o.y + 4} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-current">+{o.n}</text>
                  </g>
                ))}
                {shownMark && (
                  <rect x={shownMark.x - shownMark.halfW - 2} y={shownMark.y - OVERFLOW_H / 2} width={2 * shownMark.halfW + 4} height={OVERFLOW_H}
                    rx={5} fill="none" strokeWidth={2} className="stroke-accent" pointerEvents="none" />
                )}
                {shown && !shown.folded && (
                  <circle cx={shown.x} cy={shown.y} r={shown.r + (shown === focusDot && !hover ? 4 : 1.5)} fill="none"
                    strokeWidth={2} className={shown === focusDot && !hover ? 'stroke-accent' : 'stroke-fg-base'} pointerEvents="none" />
                )}
                {brush && (
                  <rect x={Math.min(brush.x0, brush.x1)} y={Math.min(brush.y0, brush.y1)} width={Math.abs(brush.x1 - brush.x0)}
                    height={Math.abs(brush.y1 - brush.y0)} className="fill-accent/15 stroke-accent" strokeWidth={1} pointerEvents="none" />
                )}
              </svg>
              {shown && <HoverCard dot={shown} layout={layout} outlook={outlook(shown.row)} asof={asof} />}
            </div>
          )}
          <div className="sr-only" aria-live="polite">{live}</div>
        </div>

        {layout && layout.later > 0 && layout.dots.length > 0 && (
          <p className="text-xs text-fg-muted">
            {layout.later.toLocaleString('en-IN')} more {layout.later === 1 ? 'is' : 'are'} due after {zoom === '12' ? 'the next 12 months' : 'the next three years'} (counted
            at the right edge of each lane).{' '}
            <button type="button" onClick={() => setZoom('all')} className="font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
              Show all
            </button>
          </p>
        )}
        {noDate > 0 && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-dashed border-border-default px-3 py-1.5 text-xs text-fg-muted">
            <span className="size-2 rounded-full" style={{ background: TIER_COLOR.Watch }} aria-hidden="true" />
            {noDate.toLocaleString('en-IN')} project{noDate === 1 ? ' has' : 's have'} no completion date, so {noDate === 1 ? 'it is' : 'they are'} not placed
            {p.tierFilter !== 'Watch' && (
              <button type="button" onClick={p.onListNoDate} className="font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                · list them
              </button>
            )}
          </div>
        )}

        <Legend mode={mode} />
      </div>
    </Card>
  )
}

function laneAria(mode: LaneMode, label: string, n: number, collapsed: boolean): string {
  if (collapsed) return `${label}: hidden by the tier filter`
  const name = mode === 'outlook' ? (label === 'not ranked' ? 'Not ranked' : `Delay ${label}`) : label
  return `${name}: ${n} project${n === 1 ? '' : 's'}. Left and right move between them, up and down change lane, Enter opens, Space selects.`
}

/** the lane bands, the overdue strip, the grid and the time axis */
function Frame({ layout, hatch }: { layout: MapLayout; hatch: string }) {
  const bottom = layout.height - AXIS_H
  return (
    <g aria-hidden="true">
      {layout.lanes.map((lane, i) => (
        <rect key={lane.id} x={layout.plotX0} y={lane.y0} width={layout.plotX1 - layout.plotX0} height={lane.y1 - lane.y0}
          className={lane.collapsed ? 'fill-surface-input' : i % 2 === 0 ? 'fill-surface-elevated' : 'fill-surface-panel'} rx={3} />
      ))}
      <rect x={layout.overdueX0} y={layout.lanes[0]?.y0 ?? 0} width={layout.nowX - layout.overdueX0} height={bottom - (layout.lanes[0]?.y0 ?? 0)}
        fill={hatch} />
      {layout.ticks.map((t) => (
        <line key={t.label} x1={t.x} x2={t.x} y1={layout.lanes[0]?.y0 ?? 0} y2={bottom}
          strokeWidth={t.label === 'due now' ? 1.5 : 1} strokeDasharray={t.label === 'due now' ? undefined : '2 4'}
          className={t.label === 'due now' ? 'stroke-fg-muted' : 'stroke-border-default'} />
      ))}
      <text x={(layout.overdueX0 + layout.nowX) / 2} y={bottom + 17} textAnchor="middle" fontSize={12} className="fill-fg-dimmed">
        overdue
      </text>
      {layout.ticks.map((t) => (
        <text key={t.label} x={t.x} y={bottom + 17} textAnchor={t.label === 'due now' ? 'start' : 'middle'} dx={t.label === 'due now' ? 4 : 0}
          fontSize={12} className={t.label === 'due now' ? 'fill-fg-muted font-medium' : 'fill-fg-dimmed'}>
          {t.label}
        </text>
      ))}
      {layout.lanes.map((lane) => lane.later > 0 && (
        <text key={`later-${lane.id}`} x={layout.plotX1 + 6} y={(lane.y0 + lane.y1) / 2 + 4} fontSize={12} className="fill-fg-dimmed">
          +{lane.later}
        </text>
      ))}
    </g>
  )
}

function LaneLabel({ mode, lane }: { mode: LaneMode; lane: MapLayout['lanes'][number] }) {
  const mid = (lane.y0 + lane.y1) / 2
  if (lane.collapsed) {
    return (
      <text x={LABEL_W - 10} y={mid + 4} textAnchor="end" fontSize={12} className="fill-fg-dimmed">
        {lane.label} · hidden ({(lane.hidden ?? 0).toLocaleString('en-IN')})
      </text>
    )
  }
  const tone = mode === 'outlook' && lane.word ? TONE_TEXT[OUTLOOK_TONE[lane.word as OutlookWord]] : lane.word ? TIER_TEXT[tierKey(lane.word)] : 'text-fg-dimmed'
  return (
    <>
      <text x={LABEL_W - 10} y={mid - (lane.y1 - lane.y0 > 40 ? 2 : -4)} textAnchor="end" fontSize={12} fontWeight={600}
        className={cn('fill-current', tone)}>
        {lane.label}
      </text>
      {lane.y1 - lane.y0 > 40 && (
        <text x={LABEL_W - 10} y={mid + 14} textAnchor="end" fontSize={12} className="fill-fg-dimmed">
          {lane.count.toLocaleString('en-IN')}
        </text>
      )}
    </>
  )
}

function HoverCard({ dot, layout, outlook, asof }: { dot: Dot; layout: MapLayout; outlook: Outlook | null; asof: string | undefined }) {
  const r = dot.row
  const due = dueIn(r.anticipatedCompletion, asof)
  const left = dot.x > layout.width - 300 ? dot.x - 290 : dot.x + 14
  const top = Math.max(0, Math.min(dot.y - 24, layout.height - 190))
  return (
    <div role="presentation" aria-hidden="true"
      className="pointer-events-none absolute z-10 w-[276px] space-y-1.5 rounded-lg border border-border-default bg-surface-panel px-3 py-2.5 text-xs shadow-pop"
      style={{ left, top }}>
      <div className="line-clamp-2 text-sm font-semibold leading-snug text-fg-base">{r.name ?? r.key}</div>
      <div className="truncate text-fg-dimmed">{[r.key, r.sector, r.state].filter(Boolean).join(' · ')}</div>
      <div className="flex flex-wrap gap-1"><Badge tier={r.tier} />{r.override && <StalledBadge />}</div>
      {outlook ? (
        <div className="space-y-0.5">
          {([['Delay', outlook.delay], ['Cost rise', outlook.cost]] as const).map(([noun, w]) => w && (
            <div key={noun} className="flex items-center gap-1.5 text-fg-base">
              <span className={cn('size-1.5 rounded-full', TONE_DOT[toneOf(w)])} />
              {noun} {w}
            </div>
          ))}
          {outlook.slip && <div className="text-fg-muted">Likely slip {outlook.slip}</div>}
        </div>
      ) : tierKey(r.tier) === 'Watch' ? (
        <div className="text-fg-dimmed">Not ranked: no completion date in the reports</div>
      ) : null}
      {r.physicalProgressPct !== null && (
        <div className="flex items-center gap-2">
          <span className="flex-1"><Meter pct={r.physicalProgressPct} className="bg-fg-muted" /></span>
          <span className="tabular-nums text-fg-muted">{Math.round(r.physicalProgressPct)}% done</span>
        </div>
      )}
      <div className={cn(due?.overdue ? 'font-medium text-critical' : 'text-fg-muted')}>
        {due ? `${due.text}${r.anticipatedCompletion ? ` (${formatDate(r.anticipatedCompletion)})` : ''}` : 'No completion date'}
        {r.anticipatedCostCr !== null && <span className="font-normal text-fg-muted"> · {formatINR(r.anticipatedCostCr)}</span>}
      </div>
      {r.topReason && <div className="text-fg-muted">{r.topReason}</div>}
    </div>
  )
}

/** the one line the chart says, from its own rows: how many Critical projects are already overdue */
function Takeaway({ rows, asof }: { rows: MapRow[] | undefined; asof: string | undefined }) {
  if (!rows || !asof) return <p className="h-6 w-2/3 animate-pulse rounded bg-surface-input/70" />
  const crit = rows.filter((r) => r.tier === 'Critical' && r.anticipatedCompletion)
  const over = crit.filter((r) => dueIn(r.anticipatedCompletion, asof)?.overdue).length
  const dated = rows.filter((r) => r.anticipatedCompletion && !r.noCompletionDate)
  const soon = dated.filter((r) => { const d = dueIn(r.anticipatedCompletion, asof); return d && !d.overdue && d.months <= 12 }).length
  const text = crit.length > 0
    ? over > 0
      ? `${over.toLocaleString('en-IN')} of the ${crit.length.toLocaleString('en-IN')} Critical projects here are already past their due date.`
      : `None of the ${crit.length.toLocaleString('en-IN')} Critical projects here is past its due date yet.`
    : dated.length > 0
      ? `${soon.toLocaleString('en-IN')} of the ${dated.length.toLocaleString('en-IN')} dated projects here are due within a year.`
      : 'No project here has a completion date to place.'
  return <p className="text-base text-fg-base">{text}</p>
}

function Legend({ mode }: { mode: LaneMode }) {
  return (
    <div className="space-y-2 border-t border-border-subtle pt-3 text-xs text-fg-muted">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {TIERS.map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: TIER_COLOR[t] }} aria-hidden="true" />{TIER_LABEL[t]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="3" className="fill-fg-dimmed" /><circle cx="7" cy="7" r="6" fill="none" className="stroke-critical" /></svg>
          early notice
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="3" className="fill-fg-dimmed" /><circle cx="7" cy="7" r="6" fill="none" strokeDasharray="2 2" className="stroke-fg-base" /></svg>
          stalled
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="font-semibold text-fg-base">+n</span> more due then than fit: click to list them
        </span>
        <span className="inline-flex items-center gap-2">
          {SIZES.map((s) => (
            <span key={s.r} className="inline-flex items-center gap-1">
              <svg width={2 * s.r + 2} height={18} aria-hidden="true"><circle cx={s.r + 1} cy={9} r={s.r} className="fill-fg-dimmed/60" /></svg>
              {s.label}
            </span>
          ))}
        </span>
      </div>
      <p className="text-fg-dimmed">
        {mode === 'outlook'
          ? 'Each dot is a project: further left is due sooner, a higher lane is more likely to be delayed, a bigger dot costs more. Drag across empty space to pick projects for the list.'
          : 'Each dot is a project: further left is due sooner, the lanes are the risk tiers (the delay outlook is not available yet), a bigger dot costs more. Drag across empty space to pick projects for the list.'}
      </p>
    </div>
  )
}

function MapSkeleton() {
  return (
    <div className="animate-pulse space-y-1.5" aria-busy="true" aria-label="Loading the risk map">
      {[88, 120, 150, 110].map((h, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-3 w-20 rounded bg-surface-input" />
          <div className="flex-1 rounded bg-surface-input/70" style={{ height: h }} />
        </div>
      ))}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[180px] items-center justify-center px-6 text-center text-sm text-fg-muted">{children}</div>
}
