/**
 * The risk map's geometry, kept apart from the component so it can be checked on its own. x is months from as-of to
 * the anticipated completion on a piecewise scale (an overdue strip, then due now, 6 mo, 1 yr, 2 yr, later; the near
 * term weighted wider); y is a lane per delay word, or per tier before the backend sends words. The reports give the
 * anticipated completion as a month, so a dot may sit anywhere inside its month's stretch of the axis: a month's
 * projects fill the columns (one dot wide) that fall inside that stretch, round robin in the order of a hash of the
 * project key, and each column stacks alternately up and down from the lane centre. A position therefore derives only
 * from the due date and the key, never from a hidden number, and the picture is the same on every load. A lane grows
 * with its tallest column up to LANE_MAX; a column taller than that folds the rest into a "+n" mark in a strip at the
 * lane's top, and the folded rows stay reachable: the mark lists them, a brush over their column selects them and the
 * keyboard walk visits them.
 */
import type { Flag, MapRow, Outlook, OutlookWord, Tier } from '@/contracts/project'

export type LaneMode = 'outlook' | 'tier'
export type Zoom = '12' | '36' | 'all'

export const ZOOMS: Array<{ id: Zoom; label: string }> = [
  { id: '12', label: 'Next 12 mo' },
  { id: '36', label: '3 yr' },
  { id: 'all', label: 'All' },
]

/** the three named dot sizes by anticipated cost, spelled out in the legend; the largest fits one column */
export const SIZES = [
  { r: 3, label: 'under ₹500 Cr', max: 500 },
  { r: 4.5, label: '₹500–5,000 Cr', max: 5000 },
  { r: 5.5, label: 'above ₹5,000 Cr', max: Infinity },
] as const

export function radiusOf(costCr: number | null | undefined): number {
  const c = costCr ?? 0
  return (SIZES.find((s) => c < s.max) ?? SIZES[2]).r
}

/** FNV-1a: the stable order of dots inside a column */
export function hashKey(key: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/** whole months from as-of to the date (the reports give the anticipated completion as a month) */
export function monthsFrom(asof: string, date: string): number {
  const a = new Date(asof)
  const b = new Date(date)
  return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth())
}

export interface LaneSpec {
  id: string
  label: string
  /** outlook word or tier; null for the 'not ranked' lane */
  word: OutlookWord | Tier | null
  /** collapsed to a thin strip (its tier is switched off) */
  collapsed: boolean
  /** how many are hidden in a collapsed lane; undefined when not known (a filter the counts cannot follow) */
  hidden?: number
  thin?: boolean
}

export interface Dot {
  key: string
  row: MapRow
  lane: number
  x: number
  y: number
  r: number
  months: number
  /** not drawn: folded into the "+n" mark at (x, y); only the keyboard walk visits it */
  folded?: boolean
}

export interface LaneBox extends LaneSpec {
  y0: number
  y1: number
  /** rows in the window in this lane, drawn and folded (the label and the keyboard walk say the same) */
  count: number
  /** plotted rows past the zoom window, counted at the right edge */
  later: number
}

export interface OverflowMark {
  lane: number
  /** the label's centre */
  x: number
  y: number
  n: number
  /** the folded rows it stands for */
  keys: string[]
  /** half the label's width, for hit testing */
  halfW: number
}

/** one column's folded rows: a brush over the column selects them */
export interface FoldedColumn {
  lane: number
  x: number
  keys: string[]
}

export interface Tick {
  x: number
  label: string
}

export interface MapLayout {
  width: number
  height: number
  plotX0: number
  plotX1: number
  nowX: number
  overdueX0: number
  lanes: LaneBox[]
  /** the drawn dots */
  dots: Dot[]
  /** each lane's rows in due-date order, drawn and folded: the keyboard walk */
  byLane: Dot[][]
  overflow: OverflowMark[]
  folded: FoldedColumn[]
  ticks: Tick[]
  /** rows with a date that fall past the zoom window */
  later: number
  /** rows with no completion date (never plotted) */
  noDate: number
  /** drawn dots bucketed by column for hit testing */
  bins: Map<number, Dot[]>
  binW: number
}

export const LABEL_W = 104
export const RIGHT_W = 44
export const AXIS_H = 26
export const TOP_PAD = 6
/** a column: the largest dot's width plus a pixel, so neighbouring columns never overlap */
export const BIN_W = 12
export const COLLAPSED_H = 6
export const LANE_MIN = 56
export const LANE_MAX = 200
/** the strip at the top of a lane that holds its "+n" marks, above every dot */
export const OVERFLOW_H = 15
const OVERDUE_SHARE = 0.15
/** 3 years overdue or more sits at the strip's left edge; the strip is a square-root scale, so the last months get room */
const OVERDUE_SPAN = 36

type Segment = [number, number, number, string | null]

/** [from months, to months, weight, label at `to`] per zoom; the first segment starts at "due now" */
function segments(zoom: Zoom, maxMonths: number): Segment[] {
  if (zoom === '12') return [[0, 6, 1.2, '6 mo'], [6, 12, 1, '1 yr']]
  if (zoom === '36') return [[0, 6, 2, '6 mo'], [6, 12, 1.3, '1 yr'], [12, 24, 1, '2 yr'], [24, 36, 0.6, '3 yr']]
  const segs: Segment[] = [[0, 6, 2, '6 mo'], [6, 12, 1.3, '1 yr'], [12, 24, 1, '2 yr']]
  if (maxMonths > 24) segs.push([24, Math.max(maxMonths + 1, 25), 0.8, null])
  return segs
}

export function zoomMax(zoom: Zoom): number {
  return zoom === '12' ? 12 : zoom === '36' ? 36 : Infinity
}

/** the lane a row sits in, or -1 when it has a date but no lane (its lane is not drawn) */
export function laneOf(mode: LaneMode, row: MapRow, outlook: Outlook | null, specs: LaneSpec[]): number {
  if (mode === 'tier') return specs.findIndex((s) => s.word === row.tier)
  const delay = outlook?.delay ?? null
  return delay ? specs.findIndex((s) => s.word === delay) : specs.findIndex((s) => s.word === null)
}

export interface LayoutInput {
  rows: MapRow[]
  asof: string
  width: number
  mode: LaneMode
  specs: LaneSpec[]
  zoom: Zoom
  outlookOf: (r: MapRow) => Outlook | null
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** a "+n" label's half width at 12 px (about 7 px a character, a little padding) */
export const markHalfW = (n: number) => (7 * (String(n).length + 1) + 6) / 2

interface Placed { row: MapRow; months: number; r: number }

/** alternate up / down stacking from the centre: each item's offset from the centre, and the larger half extent */
function stack(rs: number[]): { offsets: number[]; half: number } {
  let up = 0
  let down = 0
  const offsets = rs.map((r, i) => {
    if (i === 0) {
      up = r
      down = r
      return 0
    }
    if (i % 2 === 1) {
      const o = -(up + 1 + r)
      up += 2 * r + 1
      return o
    }
    const o = down + 1 + r
    down += 2 * r + 1
    return o
  })
  return { offsets, half: Math.max(up, down) }
}

export function layoutMap({ rows, asof, width, mode, specs, zoom, outlookOf }: LayoutInput): MapLayout {
  const plotX0 = LABEL_W
  const plotX1 = Math.max(plotX0 + 200, width - RIGHT_W)
  const plotW = plotX1 - plotX0
  const overdueW = plotW * OVERDUE_SHARE
  const nowX = plotX0 + overdueW
  const maxOverdueBin = Math.max(0, Math.floor(overdueW / BIN_W) - 1)
  const maxFutureBin = Math.max(0, Math.floor((plotX1 - nowX) / BIN_W) - 1)

  const dated = rows
    .filter((r) => r.anticipatedCompletion && !r.noCompletionDate)
    .map((r) => ({ row: r, months: monthsFrom(asof, r.anticipatedCompletion as string) }))
    .filter((d) => !Number.isNaN(d.months))
  const noDate = rows.length - dated.length
  const maxMonths = Math.max(0, ...dated.map((d) => d.months))
  const segs = segments(zoom, maxMonths)
  const totalW = segs.reduce((s, [, , w]) => s + w, 0)
  const scale = (m: number): number => {
    if (m < 0) return nowX - Math.sqrt(Math.min(1, -m / OVERDUE_SPAN)) * overdueW
    let x = nowX
    for (const [a, b, w] of segs) {
      const segW = ((plotX1 - nowX) * w) / totalW
      if (m <= b) return x + ((m - a) / (b - a)) * segW
      x += segW
    }
    return plotX1
  }
  const ticks: Tick[] = [{ x: nowX, label: 'due now' }]
  let tx = nowX
  for (const [, , w, label] of segs) {
    const segW = ((plotX1 - nowX) * w) / totalW
    ticks.push(label ? { x: tx + segW, label } : { x: tx + segW / 2, label: 'later' })
    tx += segW
  }

  // a column id: 0, 1, 2 ... right of the "due now" rule, -1, -2 ... left of it; and its centre
  const colX = (c: number) => (c >= 0 ? nowX + (c + 0.5) * BIN_W : nowX - (-1 - c + 0.5) * BIN_W)
  /** the columns whose centre falls inside month m's stretch of the axis (at least the one under its middle) */
  const monthCols = new Map<number, number[]>()
  const colsOf = (m: number): number[] => {
    const hit = monthCols.get(m)
    if (hit) return hit
    const x0 = scale(m)
    const x1 = scale(m + 1)
    const cols: number[] = []
    if (m >= 0) {
      const first = Math.max(0, Math.ceil((x0 - nowX) / BIN_W - 0.5))
      const last = Math.min(maxFutureBin, Math.floor((x1 - nowX) / BIN_W - 0.5 - 1e-9))
      for (let c = first; c <= last; c++) cols.push(c)
      if (!cols.length) cols.push(clamp(Math.floor(((x0 + x1) / 2 - nowX) / BIN_W), 0, maxFutureBin))
    } else {
      const first = Math.max(0, Math.ceil((nowX - x1) / BIN_W - 0.5))
      const last = Math.min(maxOverdueBin, Math.floor((nowX - x0) / BIN_W - 0.5 - 1e-9))
      for (let j = first; j <= last; j++) cols.push(-1 - j)
      if (!cols.length) cols.push(-1 - clamp(Math.floor((nowX - (x0 + x1) / 2) / BIN_W), 0, maxOverdueBin))
    }
    monthCols.set(m, cols)
    return cols
  }

  // rows per lane, the zoom window applied
  const max = zoomMax(zoom)
  const perLane: Array<Array<{ row: MapRow; months: number }>> = specs.map(() => [])
  const laterPer = specs.map(() => 0)
  let later = 0
  for (const d of dated) {
    const lane = laneOf(mode, d.row, outlookOf(d.row), specs)
    if (lane < 0 || specs[lane]?.collapsed) continue
    if (d.months > max) {
      later++
      laterPer[lane] = (laterPer[lane] ?? 0) + 1
      continue
    }
    perLane[lane]?.push(d)
  }

  // each lane's rows into columns: a month's rows round robin over its columns, in hash order
  const byHash = (a: { row: MapRow }, b: { row: MapRow }) =>
    hashKey(a.row.key) - hashKey(b.row.key) || (a.row.key < b.row.key ? -1 : 1)
  const laneCols = perLane.map((list) => {
    const byMonth = new Map<number, Array<{ row: MapRow; months: number }>>()
    for (const d of list) byMonth.set(d.months, [...(byMonth.get(d.months) ?? []), d])
    const cols = new Map<number, Placed[]>()
    for (const [m, ms] of byMonth) {
      const cs = colsOf(m)
      ms.sort(byHash).forEach((d, i) => {
        const col = cs[i % cs.length] as number
        const list2 = cols.get(col) ?? []
        list2.push({ ...d, r: radiusOf(d.row.anticipatedCostCr) })
        cols.set(col, list2)
      })
    }
    for (const list2 of cols.values()) list2.sort(byHash)
    return cols
  })

  // lane heights: the tallest column's stack, LANE_MIN to LANE_MAX; thin lanes and collapsed strips smaller
  let y = TOP_PAD
  const lanes: LaneBox[] = specs.map((s, i) => {
    const count = perLane[i]?.length ?? 0
    const need = Math.max(0, ...[...(laneCols[i]?.values() ?? [])].map((c) => 2 * stack(c.map((p) => p.r)).half + 2))
    const h = s.collapsed ? COLLAPSED_H
      : s.thin ? clamp(need, 26, 64)
      : count === 0 ? 40 : clamp(need, LANE_MIN, LANE_MAX)
    const box = { ...s, y0: y, y1: y + h, count, later: laterPer[i] ?? 0 }
    y += h + (s.collapsed ? 4 : 2)
    return box
  })
  const height = y + AXIS_H

  const dots: Dot[] = []
  const walk: Dot[][] = lanes.map(() => [])
  const folded: FoldedColumn[] = []
  const overflow: OverflowMark[] = []
  lanes.forEach((lane, li) => {
    if (lane.collapsed) return
    const cols = laneCols[li] ?? new Map<number, Placed[]>()
    const full = (lane.y1 - lane.y0) / 2 - 1
    // the lane folds when a column does not fit: then its top strip holds the marks and the dots sit below it
    const folds = [...cols.values()].some((c) => stack(c.map((p) => p.r)).half > full)
    const top = folds ? lane.y0 + OVERFLOW_H : lane.y0
    const mid = (top + lane.y1) / 2
    const half = (lane.y1 - top) / 2 - 1
    const markY = lane.y0 + OVERFLOW_H / 2
    const spilled: FoldedColumn[] = []
    for (const [col, list] of [...cols.entries()].sort((a, b) => a[0] - b[0])) {
      const cx = colX(col)
      const { offsets } = stack(list.map((p) => p.r))
      const keys: string[] = []
      list.forEach((p, i) => {
        const cy = mid + (offsets[i] ?? 0)
        if (i > 0 && Math.abs(cy - mid) + p.r > half) {
          keys.push(p.row.key)
          walk[li]?.push({ key: p.row.key, row: p.row, lane: li, x: cx, y: markY, r: 0, months: p.months, folded: true })
          return
        }
        const dot = { key: p.row.key, row: p.row, lane: li, x: cx, y: cy, r: p.r, months: p.months }
        dots.push(dot)
        walk[li]?.push(dot)
      })
      if (keys.length) spilled.push({ lane: li, x: cx, keys })
    }
    folded.push(...spilled)
    // neighbouring columns' marks merge while their labels would touch (until none do); a mark centres on its run
    let runs = spilled.map((f) => ({ first: f.x, last: f.x, keys: f.keys }))
    const centre = (r: { first: number; last: number }) => (r.first + r.last) / 2
    for (let merged = true; merged;) {
      merged = false
      const next: typeof runs = []
      for (const r of runs) {
        const prev = next[next.length - 1]
        if (prev && centre(r) - markHalfW(r.keys.length) < centre(prev) + markHalfW(prev.keys.length) + 3) {
          next[next.length - 1] = { first: prev.first, last: r.last, keys: [...prev.keys, ...r.keys] }
          merged = true
        } else {
          next.push(r)
        }
      }
      runs = next
    }
    // a folded row's walk position is its mark
    const markOf = new Map<string, OverflowMark>()
    for (const r of runs) {
      const o = { lane: li, x: centre(r), y: markY, n: r.keys.length, keys: r.keys, halfW: markHalfW(r.keys.length) }
      overflow.push(o)
      for (const k of r.keys) markOf.set(k, o)
    }
    for (const d of walk[li] ?? []) if (d.folded) d.x = markOf.get(d.key)?.x ?? d.x
  })

  const byLane = walk.map((list) => list.sort((a, b) => a.months - b.months || a.x - b.x || a.y - b.y))
  const bins = new Map<number, Dot[]>()
  for (const d of dots) {
    const b = Math.floor((d.x - plotX0) / BIN_W)
    const list = bins.get(b) ?? []
    list.push(d)
    bins.set(b, list)
  }

  return {
    width, height, plotX0, plotX1, nowX, overdueX0: plotX0, lanes, dots, byLane, overflow, folded, ticks, later, noDate,
    bins, binW: BIN_W,
  }
}

/** the drawn dot under (x, y), within its radius plus a little slack; null when none */
export function hitTest(layout: MapLayout, x: number, y: number): Dot | null {
  const b = Math.floor((x - layout.plotX0) / layout.binW)
  let best: Dot | null = null
  let bestD = Infinity
  for (let i = b - 2; i <= b + 2; i++) {
    for (const d of layout.bins.get(i) ?? []) {
      const dist = Math.hypot(d.x - x, d.y - y)
      if (dist <= d.r + 3 && dist < bestD) {
        best = d
        bestD = dist
      }
    }
  }
  return best
}

/**
 * The keys under a brush: every drawn dot whose centre is inside the rectangle, and a column's folded rows when the
 * rectangle takes in the column's centre and crosses its lane's middle or its "+n" strip.
 */
export function keysIn(layout: MapLayout, x0: number, y0: number, x1: number, y1: number): string[] {
  const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)]
  const [c, d] = [Math.min(y0, y1), Math.max(y0, y1)]
  const keys = layout.dots.filter((p) => p.x >= a && p.x <= b && p.y >= c && p.y <= d).map((p) => p.key)
  for (const f of layout.folded) {
    const lane = layout.lanes[f.lane]
    if (!lane || f.x < a || f.x > b) continue
    const mid = (lane.y0 + OVERFLOW_H + lane.y1) / 2
    const markY = lane.y0 + OVERFLOW_H / 2
    if ((mid >= c && mid <= d) || (markY >= c && markY <= d)) keys.push(...f.keys)
  }
  return keys
}

/** the "+n" mark under (x, y); null when none */
export function markAt(layout: MapLayout, x: number, y: number): OverflowMark | null {
  return layout.overflow.find((o) => Math.abs(o.x - x) <= o.halfW && Math.abs(o.y - y) <= OVERFLOW_H / 2) ?? null
}

/** does a row carry the early-notice flag */
export const hasFlag = (row: { flags: Flag[] }, f: Flag) => row.flags.includes(f)
