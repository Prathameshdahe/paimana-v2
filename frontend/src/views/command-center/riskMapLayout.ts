/**
 * The risk map's geometry, kept apart from the component so it can be checked on its own. x is months from as-of to
 * the anticipated completion on a piecewise scale (an overdue strip, then due now, 6 mo, 1 yr, 2 yr, later); y is a
 * lane per delay word, or per tier before the backend sends words. Inside a lane dots stack as a beeswarm: x binned
 * to a dot's width, each bin stacked alternately up and down from the lane centre in the order of a hash of the
 * project key. A position therefore derives only from the due date and the key, never from a hidden number, and the
 * picture is the same on every load. A bin that would overflow its lane folds the rest into one "+n" mark.
 */
import type { Flag, MapRow, Outlook, OutlookWord, Tier } from '@/contracts/project'

export type LaneMode = 'outlook' | 'tier'
export type Zoom = '12' | '36' | 'all'

export const ZOOMS: Array<{ id: Zoom; label: string }> = [
  { id: '12', label: 'Next 12 mo' },
  { id: '36', label: '3 yr' },
  { id: 'all', label: 'All' },
]

/** the three named dot sizes by anticipated cost, spelled out in the legend */
export const SIZES = [
  { r: 3, label: 'under ₹500 Cr', max: 500 },
  { r: 5, label: '₹500–5,000 Cr', max: 5000 },
  { r: 8, label: 'above ₹5,000 Cr', max: Infinity },
] as const

export function radiusOf(costCr: number | null | undefined): number {
  const c = costCr ?? 0
  return (SIZES.find((s) => c < s.max) ?? SIZES[2]).r
}

/** FNV-1a: the stable order of dots inside a bin */
export function hashKey(key: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

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
  /** how many are hidden in a collapsed lane (the portfolio's count) */
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
}

export interface LaneBox extends LaneSpec {
  y0: number
  y1: number
  count: number
  /** plotted rows past the zoom window, counted at the right edge */
  later: number
}

export interface OverflowMark {
  lane: number
  x: number
  y: number
  n: number
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
  dots: Dot[]
  /** each lane's dots in due-date order: the keyboard walk */
  byLane: Dot[][]
  overflow: OverflowMark[]
  ticks: Tick[]
  /** rows with a date that fall past the zoom window */
  later: number
  /** rows with no completion date (never plotted) */
  noDate: number
  /** dots bucketed by bin index for hit testing */
  bins: Map<number, Dot[]>
  binW: number
}

export const LABEL_W = 104
export const RIGHT_W = 44
export const AXIS_H = 26
export const TOP_PAD = 6
export const BIN_W = 11
export const COLLAPSED_H = 6
const OVERDUE_SHARE = 0.13
/** 3 years overdue or more sits at the strip's left edge */
const OVERDUE_SPAN = 36

type Segment = [number, number, number, string | null]

/** [from months, to months, weight, label at `to`] per zoom; the first segment starts at "due now" */
function segments(zoom: Zoom, maxMonths: number): Segment[] {
  if (zoom === '12') return [[0, 6, 1, '6 mo'], [6, 12, 1, '1 yr']]
  if (zoom === '36') return [[0, 6, 1, '6 mo'], [6, 12, 1, '1 yr'], [12, 24, 1.2, '2 yr'], [24, 36, 1, '3 yr']]
  const segs: Segment[] = [[0, 6, 1, '6 mo'], [6, 12, 1, '1 yr'], [12, 24, 1.2, '2 yr']]
  if (maxMonths > 24) segs.push([24, Math.max(maxMonths, 25), 1.4, null])
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
    if (m < 0) return nowX - BIN_W / 2 - Math.min(1, -m / OVERDUE_SPAN) * (overdueW - BIN_W)
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

  // lane heights: proportional to the square root of the count, 56-176 px; thin lanes and collapsed strips smaller
  let y = TOP_PAD
  const lanes: LaneBox[] = specs.map((s, i) => {
    const count = perLane[i]?.length ?? 0
    const h = s.collapsed ? COLLAPSED_H
      : s.thin ? clamp(8 * Math.sqrt(count) + 20, 26, 64)
      : count === 0 ? 40 : clamp(10 * Math.sqrt(count), 56, 176)
    const box = { ...s, y0: y, y1: y + h, count, later: laterPer[i] ?? 0 }
    y += h + (s.collapsed ? 4 : 2)
    return box
  })
  const height = y + AXIS_H

  const dots: Dot[] = []
  const overflow: OverflowMark[] = []
  lanes.forEach((lane, li) => {
    if (lane.collapsed) return
    const mid = (lane.y0 + lane.y1) / 2
    const half = (lane.y1 - lane.y0) / 2 - 1
    // columns run out from the "due now" rule both ways, so no stack straddles it and every column is one bin wide
    const byBin = new Map<number, { cx: number; list: Array<{ row: MapRow; months: number }> }>()
    for (const d of perLane[li] ?? []) {
      const x = scale(d.months)
      const cx = d.months < 0
        ? nowX - (Math.min(Math.floor((nowX - x) / BIN_W), maxOverdueBin) + 0.5) * BIN_W
        : nowX + (Math.min(Math.floor((x - nowX) / BIN_W), maxFutureBin) + 0.5) * BIN_W
      const bin = Math.round((cx - plotX0) / BIN_W * 2)
      const slot = byBin.get(bin) ?? { cx, list: [] }
      slot.list.push(d)
      byBin.set(bin, slot)
    }
    const spilled = new Map<number, number>()
    for (const [bin, { cx, list }] of byBin) {
      list.sort((a, b) => hashKey(a.row.key) - hashKey(b.row.key) || (a.row.key < b.row.key ? -1 : 1))
      let up = 0
      let down = 0
      let n = 0
      list.forEach((d, i) => {
        const r = radiusOf(d.row.anticipatedCostCr)
        let cy: number
        if (i === 0) {
          cy = mid
          up = r
          down = r
        } else if (i % 2 === 1) {
          cy = mid - up - 1 - r
          up += 2 * r + 1
        } else {
          cy = mid + down + 1 + r
          down += 2 * r + 1
        }
        if (Math.abs(cy - mid) + r > half && i > 0) {
          n++
          return
        }
        dots.push({ key: d.row.key, row: d.row, lane: li, x: cx, y: cy, r, months: d.months })
      })
      if (n > 0) spilled.set(bin, (spilled.get(bin) ?? 0) + n)
    }
    // runs of neighbouring overflowing bins make one mark at the run's middle
    const runs: Array<{ first: number; last: number; n: number }> = []
    for (const bin of [...spilled.keys()].sort((a, b) => a - b)) {
      const n = spilled.get(bin) ?? 0
      const prev = runs[runs.length - 1]
      if (prev && bin - prev.last <= 2) {
        prev.last = bin
        prev.n += n
      } else {
        runs.push({ first: bin, last: bin, n })
      }
    }
    for (const run of runs) {
      overflow.push({ lane: li, x: plotX0 + ((run.first + run.last) / 4) * BIN_W, y: lane.y0 + 1, n: run.n })
    }
  })

  const byLane = lanes.map((_, li) =>
    dots.filter((d) => d.lane === li).sort((a, b) => a.months - b.months || a.x - b.x || a.y - b.y))
  const bins = new Map<number, Dot[]>()
  for (const d of dots) {
    const b = Math.floor((d.x - plotX0) / BIN_W)
    const list = bins.get(b) ?? []
    list.push(d)
    bins.set(b, list)
  }

  return {
    width, height, plotX0, plotX1, nowX, overdueX0: plotX0, lanes, dots, byLane, overflow, ticks, later, noDate, bins,
    binW: BIN_W,
  }
}

/** the dot under (x, y), within its radius plus a little slack; null when none */
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

/** the keys whose dot centre is inside the rectangle */
export function keysIn(layout: MapLayout, x0: number, y0: number, x1: number, y1: number): string[] {
  const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)]
  const [c, d] = [Math.min(y0, y1), Math.max(y0, y1)]
  return layout.dots.filter((p) => p.x >= a && p.x <= b && p.y >= c && p.y <= d).map((p) => p.key)
}

/** does a row carry the early-notice flag */
export const hasFlag = (row: { flags: Flag[] }, f: Flag) => row.flags.includes(f)
