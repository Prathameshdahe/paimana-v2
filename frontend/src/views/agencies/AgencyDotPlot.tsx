import { useMemo, useState } from 'react'
import { SCHEDULE_PHRASE, COST_PHRASE } from '@/lib/agencyWords'
import { hashKey } from '@/views/command-center/riskMapLayout'
import { cn, formatINRShort } from '@/lib/formatters'
import type { AgencyPoint, ScheduleWord } from '@/contracts/intel'

/** the three word columns, left to right */
const COLUMNS: Array<{ word: ScheduleWord; label: string }> = [
  { word: 'usually earlier', label: 'earlier than planned' },
  { word: 'about on time', label: 'about on time' },
  { word: 'usually later', label: 'later than planned' },
]
const ROW_H = 44
const LABEL_W = 132
const MAX_ROWS = 8

interface Placed { a: AgencyPoint; x: number; y: number; r: number }

/** "5 of 9 agencies in Roads usually finish later than planned" for the sector with the most agencies in words */
function takeaway(bySector: Array<[string, AgencyPoint[]]>): string | null {
  const [sector, rows] = bySector[0] ?? []
  if (!sector || !rows?.length) return null
  const later = rows.filter((a) => a.scheduleWord === 'usually later').length
  return `${later} of the ${rows.length} agencies in ${sector} usually ${later === 1 ? 'finishes' : 'finish'} later than planned.`
}

/**
 * Agencies as dots, one row per sector and three columns by their past schedule word (earlier, about on time,
 * later): a dot sits in its word's column at a spot from a hash of its name, so nothing places it but the word; size
 * is its capital. Grey by default; your own agency is ringed in the accent, the picked one in ink. No axis numbers.
 * The list beside it is the keyboard and screen-reader path; a dot click picks the agency too.
 */
export function AgencyDotPlot({ points, selected, onPick }: {
  points: AgencyPoint[]
  selected: string | null
  onPick: (agency: string) => void
}) {
  const [hover, setHover] = useState<Placed | null>(null)
  const width = 560
  const colW = (width - LABEL_W) / COLUMNS.length

  const { bySector, placed } = useMemo(() => {
    const worded = points.filter((a) => a.sector && COLUMNS.some((c) => c.word === a.scheduleWord))
    const groups = new Map<string, AgencyPoint[]>()
    for (const a of worded) groups.set(a.sector as string, [...(groups.get(a.sector as string) ?? []), a])
    const bySector = [...groups.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, MAX_ROWS)
    const maxCap = Math.max(1, ...worded.map((a) => a.capitalCr))
    const placed: Placed[] = []
    bySector.forEach(([, rows], ri) => {
      for (const a of rows) {
        const ci = COLUMNS.findIndex((c) => c.word === a.scheduleWord)
        const h = hashKey(a.agency)
        const jx = ((h % 1000) / 1000 - 0.5) * (colW - 24)
        const jy = (((h >>> 10) % 1000) / 1000 - 0.5) * (ROW_H - 16)
        placed.push({
          a,
          x: LABEL_W + ci * colW + colW / 2 + jx,
          y: ri * ROW_H + ROW_H / 2 + jy,
          r: 3 + 6 * Math.sqrt(a.capitalCr / maxCap),
        })
      }
    })
    return { bySector, placed }
  }, [points, colW])

  if (bySector.length === 0) {
    return (
      <p className="px-5 py-8 text-center text-sm text-fg-muted">
        How agencies usually finish is not available in words yet, so they cannot be placed here.
      </p>
    )
  }
  const height = bySector.length * ROW_H + 28
  const line = takeaway(bySector)

  return (
    <div className="space-y-3 px-5 py-4">
      {line && <p className="text-base text-fg-base">{line}</p>}
      <div className="relative overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[480px]" role="img" aria-label={line ?? 'Agencies by how their projects usually finish'}
          onMouseLeave={() => setHover(null)}>
          {COLUMNS.map((c, i) => (
            <g key={c.word}>
              <rect x={LABEL_W + i * colW + 2} y={0} width={colW - 4} height={bySector.length * ROW_H}
                className={i === 2 ? 'fill-critical/5' : i === 0 ? 'fill-stable/5' : 'fill-surface-elevated'} rx={6} />
              <text x={LABEL_W + i * colW + colW / 2} y={height - 8} textAnchor="middle" fontSize={12} className="fill-fg-muted">{c.label}</text>
            </g>
          ))}
          {bySector.map(([sector], ri) => (
            <text key={sector} x={LABEL_W - 10} y={ri * ROW_H + ROW_H / 2 + 4} textAnchor="end" fontSize={12} className="fill-fg-base">
              {sector.length > 18 ? `${sector.slice(0, 17)}…` : sector}
            </text>
          ))}
          {placed.map((p) => (
            <circle key={p.a.agency} cx={p.x} cy={p.y} r={p.r}
              className={cn('cursor-pointer fill-fg-dimmed/60',
                p.a.isSelf ? 'stroke-accent' : selected === p.a.agency ? 'stroke-fg-base' : 'stroke-surface-panel')}
              strokeWidth={p.a.isSelf || selected === p.a.agency ? 2.5 : 1}
              onMouseEnter={() => setHover(p)} onClick={() => onPick(p.a.agency)} />
          ))}
        </svg>
        {hover && (
          <div className="pointer-events-none absolute z-10 w-64 rounded-lg border border-border-default bg-surface-panel px-3 py-2 text-xs shadow-pop"
            style={{ left: `${Math.min(70, (hover.x / width) * 100)}%`, top: `${(hover.y / height) * 100}%` }} aria-hidden="true">
            <div className="font-semibold text-fg-base">{hover.a.agency}</div>
            <div className="text-fg-muted">{hover.a.scheduleWord && SCHEDULE_PHRASE[hover.a.scheduleWord]}</div>
            {hover.a.costWord && <div className="text-fg-muted">{COST_PHRASE[hover.a.costWord]}</div>}
            <div className="text-fg-dimmed">{hover.a.nProjects} past · {hover.a.nOpen} open · {formatINRShort(hover.a.capitalCr)}</div>
          </div>
        )}
      </div>
      <p className="text-xs text-fg-dimmed">
        One dot per agency with five or more past projects; a bigger dot runs more capital. A dot&rsquo;s spot inside its column means nothing.
      </p>
    </div>
  )
}
