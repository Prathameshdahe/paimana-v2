import { useState, useMemo, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { MonoFigure } from '@/components/ui/MonoFigure'
import { Search } from 'lucide-react'
import { formatINR, formatPct, formatRunwayDays, cn } from '@/lib/formatters'
import type { Project, RiskTier, Sector } from '@/contracts/project'

interface TriageTableProps {
  projects: Project[]
  selectedProjectId?: string | null
  onSelectProject?: (projectId: string) => void
  onOpenDetail?: (projectId: string) => void
}

type SortField = 'compositeRiskScore' | 'actionableRunwayDays' | 'overrunForecastCr' | 'disparityDeltaPct'

/**
 * TriageTable — high-density 32px-row operational queue.
 * Bloomberg-style tabular layout. Zero icons in table body.
 * Sort indicators: plain ▲/▼ in monospace header.
 */
export function TriageTable({
  projects,
  selectedProjectId,
  onSelectProject,
  onOpenDetail,
}: TriageTableProps) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [selectedTier, setSelectedTier] = useState<RiskTier | 'ALL'>('ALL')
  const [selectedSector, setSelectedSector] = useState<Sector | 'ALL'>('ALL')
  const [selectedState, setSelectedState] = useState<string>(searchParams.get('state') ?? 'ALL')
  const [selectedType, setSelectedType] = useState<string>('ALL')
  const [sortField, setSortField] = useState<SortField>('compositeRiskScore')
  const [sortAsc, setSortAsc] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 20

  // Auto-reveal and scroll selected project into view
  useEffect(() => {
    if (!selectedProjectId) return undefined

    const match = projects.find((p) => p.id === selectedProjectId)
    if (match) {
      if (selectedTier !== 'ALL' && match.riskTier !== selectedTier) {
        setSelectedTier('ALL')
      }
      if (selectedSector !== 'ALL' && match.sector !== selectedSector) {
        setSelectedSector('ALL')
      }
    }
    const timer = setTimeout(() => {
      const el = document.getElementById(`triage-row-${selectedProjectId}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }, 60)
    return () => clearTimeout(timer)
  }, [selectedProjectId, projects, selectedTier, selectedSector])

  const sectors = useMemo(() => {
    const set = new Set<Sector>()
    projects.forEach((p) => set.add(p.sector))
    return Array.from(set).sort()
  }, [projects])

  const states = useMemo(() => {
    const set = new Set<string>()
    projects.forEach((p) => set.add(p.state))
    return Array.from(set).sort()
  }, [projects])

  const types = useMemo(() => {
    const set = new Set<string>()
    projects.forEach((p) => p.projectType && set.add(p.projectType))
    return Array.from(set).sort()
  }, [projects])

  // one-time consume of ?state= from the India map click-through
  useEffect(() => {
    const s = searchParams.get('state')
    if (s) {
      setSelectedState(s)
      setSearchParams((prev) => { prev.delete('state'); return prev }, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtered = useMemo(() => {
    return projects
      .filter((p) => {
        if (selectedTier !== 'ALL' && p.riskTier !== selectedTier) return false
        if (selectedSector !== 'ALL' && p.sector !== selectedSector) return false
        if (selectedState !== 'ALL' && p.state !== selectedState) return false
        if (selectedType !== 'ALL' && p.projectType !== selectedType) return false
        if (search.trim() !== '') {
          const q = search.toLowerCase()
          return (
            p.name.toLowerCase().includes(q) ||
            p.code.toLowerCase().includes(q) ||
            p.agency.toLowerCase().includes(q) ||
            p.state.toLowerCase().includes(q) ||
            p.ministry.toLowerCase().includes(q)
          )
        }
        return true
      })
      .sort((a, b) => {
        const va = a[sortField], vb = b[sortField]
        return sortAsc ? va - vb : vb - va
      })
  }, [projects, selectedTier, selectedSector, selectedState, selectedType, search, sortField, sortAsc])

  useEffect(() => {
    setCurrentPage(1)
  }, [search, selectedTier, selectedSector, selectedState, selectedType, sortField, sortAsc])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, currentPage])

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortAsc(!sortAsc)
    else { setSortField(field); setSortAsc(false) }
  }

  const sortIcon = (field: SortField) =>
    sortField === field ? (sortAsc ? ' ▲' : ' ▼') : ''

  return (
    <Card
      title={`Triage Register · ${filtered.length}/${projects.length}`}
      titleRight={
        <div className="flex items-center gap-2">
          {/* Tier filters */}
          {(['ALL', 'CRITICAL', 'WARNING', 'NORMAL'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setSelectedTier(t)}
              className={cn(
                'font-sans text-[11px] font-bold tracking-wider px-2.5 py-1 rounded-sm transition-all uppercase',
                selectedTier === t
                  ? t === 'CRITICAL' ? 'text-white bg-critical shadow-sm'
                    : t === 'WARNING' ? 'text-white bg-warning shadow-sm'
                    : t === 'NORMAL' ? 'text-white bg-stable shadow-sm'
                    : 'text-white bg-fg-base shadow-sm'
                  : 'text-fg-dimmed hover:text-fg-base bg-surface-elevated/50 hover:bg-surface-elevated'
              )}
            >
              {t}
            </button>
          ))}

          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value as Sector | 'ALL')}
            className="bg-surface-input border border-border-default px-2 py-0.5 text-[11px] font-sans font-semibold uppercase text-fg-muted focus:outline-none"
          >
            <option value="ALL">ALL SECTORS</option>
            {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          <select
            value={selectedState}
            onChange={(e) => setSelectedState(e.target.value)}
            className="bg-surface-input border border-border-default px-2 py-0.5 text-[11px] font-sans font-semibold uppercase text-fg-muted focus:outline-none"
          >
            <option value="ALL">ALL STATES</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          {types.length > 0 && (
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="bg-surface-input border border-border-default px-2 py-0.5 text-[11px] font-sans font-semibold uppercase text-fg-muted focus:outline-none"
            >
              <option value="ALL">ALL TYPES</option>
              {types.map((t) => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
            </select>
          )}
        </div>
      }
    >
      {/* Search bar */}
      <div className="border-b border-border-subtle px-5 py-4 bg-surface-panel/50">
        <div className="flex items-center gap-2.5 bg-surface-input px-3.5 py-2.5 rounded-md border border-border-default focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/20 transition-all shadow-inner">
          <Search className="w-4 h-4 text-fg-dimmed" />
          <input
            type="text"
            placeholder="Search by project code, name, agency, or state..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent text-sm font-sans font-medium text-fg-base placeholder:text-fg-dimmed focus:outline-none"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left font-mono text-[13px]">
          <thead>
            <tr className="border-b border-border-default text-fg-dimmed font-sans text-xs uppercase tracking-wider">
              <th className="py-3 px-5 font-semibold w-[260px]">PROJECT</th>
              <th className="py-3 px-5 font-semibold">AGENCY</th>
              <th
                className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right"
                onClick={() => handleSort('compositeRiskScore')}
              >
                RISK{sortIcon('compositeRiskScore')}
              </th>
              <th
                className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right"
                onClick={() => handleSort('actionableRunwayDays')}
              >
                RUNWAY{sortIcon('actionableRunwayDays')}
              </th>
              <th
                className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right"
                onClick={() => handleSort('overrunForecastCr')}
              >
                OVERRUN{sortIcon('overrunForecastCr')}
              </th>
              <th
                className="py-3 px-5 font-semibold cursor-pointer hover:text-fg-muted text-right"
                onClick={() => handleSort('disparityDeltaPct')}
              >
                BUDGET/WORK GAP{sortIcon('disparityDeltaPct')}
              </th>
              <th className="py-3 px-5 font-semibold text-right">SLIPPAGE RATE</th>
            </tr>
          </thead>
          <tbody>
            {paginatedData.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-6 text-center text-fg-dimmed text-xs">
                  No projects match filter criteria.
                </td>
              </tr>
            ) : (
              paginatedData.map((p) => {
                const isSelected = p.id === selectedProjectId

                return (
                  <tr
                    key={p.id}
                    id={`triage-row-${p.id}`}
                    onClick={() => {
                      if (onSelectProject) onSelectProject(p.id)
                      if (onOpenDetail) onOpenDetail(p.id)
                      else navigate(`/projects/${p.id}`)
                    }}
                    className={cn(
                      'border-b transition-all h-14 cursor-pointer',
                      isSelected
                        ? 'bg-accent/15 border-l-4 border-l-accent border-b-border-default shadow-sm'
                        : 'border-border-subtle/60 hover:bg-surface-elevated/50'
                    )}
                  >
                    {/* Project */}
                    <td className="py-3 px-5">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          'text-[12px]',
                          p.riskTier === 'CRITICAL' ? 'text-critical' :
                          p.riskTier === 'WARNING' ? 'text-warning' : 'text-stable'
                        )}>
                          [{p.riskTier}]
                        </span>
                        <span className="text-fg-base font-sans truncate max-w-[200px] text-sm font-semibold">{p.name}</span>
                      </div>
                      <div className="text-[12px] font-sans text-fg-dimmed pl-[44px] mt-1 font-medium">
                        <span className="font-mono">{p.code}</span> · {p.sector}
                      </div>
                    </td>

                    {/* Agency */}
                    <td className="py-3 px-5 font-sans text-fg-muted truncate max-w-[180px]">
                      <span className="text-[13px] font-semibold">{p.agency}</span>
                      <div className="text-[12px] font-medium text-fg-dimmed mt-1">{p.state}</div>
                    </td>

                    {/* Risk Score */}
                    <td className="py-3 px-5 text-right">
                      <MonoFigure
                        size="base"
                        sentiment={
                          p.riskTier === 'CRITICAL' ? 'critical' :
                          p.riskTier === 'WARNING' ? 'warning' : 'stable'
                        }
                      >
                        {p.compositeRiskScore}
                      </MonoFigure>
                    </td>

                  {/* Runway */}
                  <td className="py-3 px-5 text-right">
                    <span className={cn(
                      'font-mono text-[13px]',
                      p.actionableRunwayDays <= 30 ? 'text-critical font-semibold' : 'text-fg-base'
                    )}>
                      {formatRunwayDays(p.actionableRunwayDays)}
                    </span>
                  </td>

                  {/* Overrun */}
                  <td className="py-3 px-5 text-right text-critical font-medium tabular-nums font-mono">
                    {p.overrunForecastCr > 0 ? '+' : ''}{formatINR(p.overrunForecastCr)}
                  </td>

                  {/* Disparity */}
                  <td className="py-3 px-5 text-right font-medium font-mono tabular-nums">
                    <span className={cn(
                      p.disparityDeltaPct > 15 ? 'text-critical' :
                      p.disparityDeltaPct > 5 ? 'text-warning' : 'text-stable'
                    )}>
                      {p.disparityDeltaPct > 0 ? '+' : ''}{formatPct(p.disparityDeltaPct)}
                    </span>
                  </td>

                  {/* Float Velocity */}
                  <td className="py-3 px-5 text-right text-fg-muted">
                    {formatPct(p.floatDepletionVelocity)}/mo
                  </td>
                </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-default px-5 py-3 bg-surface-panel/50">
          <div className="font-sans text-[11px] text-fg-dimmed font-semibold tracking-wider">
            PAGE <span className="text-fg-base">{currentPage}</span> OF <span className="text-fg-base">{totalPages}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={currentPage === 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              className="px-3 py-1.5 bg-surface-input text-[11px] font-sans font-bold uppercase text-fg-base rounded border border-border-default disabled:opacity-30 disabled:cursor-not-allowed hover:not-disabled:bg-surface-elevated transition-colors shadow-sm"
            >
              Prev
            </button>
            <button
              disabled={currentPage === totalPages}
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              className="px-3 py-1.5 bg-surface-input text-[11px] font-sans font-bold uppercase text-fg-base rounded border border-border-default disabled:opacity-30 disabled:cursor-not-allowed hover:not-disabled:bg-surface-elevated transition-colors shadow-sm"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}
