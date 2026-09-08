import { useMemo, useState } from 'react'

import type { ChainSummary } from '../types'

interface MultiChainTimelineViewProps {
  chains?: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainA: string, chainB: string) => void
  selectedChainId?: string | null
}

function parsedTime(value: string | null) {
  if (!value) return null
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? null : timestamp
}

function formatClock(value: number | string, baseTimeMs?: number | null) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  const timeStr = parsed.toISOString().slice(11, 19)
  const dateStr = parsed.toISOString().slice(0, 10)
  if (baseTimeMs != null) {
    const diffMs = parsed.getTime() - baseTimeMs
    const diffDays = Math.floor(diffMs / (24 * 3600 * 1000))
    if (diffDays > 0 && diffDays < 365) return `${timeStr} (+${diffDays}d)`
    if (diffDays >= 365) return `${dateStr} ${timeStr}`
  }
  return timeStr
}

function formatTick(tickMs: number, minMs: number, spanMs: number) {
  const parsed = new Date(tickMs)
  if (Number.isNaN(parsed.getTime())) return String(tickMs)
  const timeStr = parsed.toISOString().slice(11, 19)
  const diffMs = tickMs - minMs
  const diffDays = Math.floor(diffMs / (24 * 3600 * 1000))
  const diffHours = Math.floor(diffMs / (3600 * 1000))

  if (diffDays > 0 && diffDays < 365) {
    return `${timeStr} (+${diffDays}d)`
  }
  if (diffDays >= 365) {
    return `${parsed.toISOString().slice(0, 10)}`
  }
  if (spanMs > 2 * 3600 * 1000 && diffHours > 0) {
    return `${timeStr} (+${diffHours}h)`
  }
  return timeStr
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return 'Unavailable'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

export function MultiChainTimelineView({
  chains = [],
  onSelectChain,
  onCompareChains,
  selectedChainId,
}: MultiChainTimelineViewProps) {
  const [selected, setSelected] = useState<string[]>([])
  const [zoomLevel, setZoomLevel] = useState<number>(100)
  const [searchTerm, setSearchTerm] = useState('')
  const [kindFilter, setKindFilter] = useState<'ALL' | 'MULTI' | 'SINGLETON'>('ALL')
  const [includeOutliers, setIncludeOutliers] = useState(false)

  // 1. Parse all timed chains
  const allTimed = useMemo(() => {
    return chains.flatMap(chain => {
      const startMs = parsedTime(chain.start_time)
      const endMs = parsedTime(chain.end_time)
      return startMs == null || endMs == null
        ? []
        : [{ chainId: chain.chain_id, startMs, endMs: Math.max(startMs, endMs) }]
    })
  }, [chains])

  // 2. Identify outliers (e.g. timestamps > 30 days from cluster median or year > 2035)
  const { primaryTimed, outlierIds } = useMemo(() => {
    if (allTimed.length <= 2) return { primaryTimed: allTimed, outlierIds: new Set<string>() }

    // Check for extreme year discrepancy (e.g. year > 2035 while others are 2026)
    const years = allTimed.map(t => new Date(t.startMs).getUTCFullYear())
    const medianYear = [...years].sort((a, b) => a - b)[Math.floor(years.length / 2)]

    const outliers = new Set<string>()
    const primary: typeof allTimed = []

    for (const t of allTimed) {
      const yr = new Date(t.startMs).getUTCFullYear()
      if (Math.abs(yr - medianYear) > 2) {
        outliers.add(t.chainId)
      } else {
        primary.push(t)
      }
    }

    // If all or none were filtered, revert to all
    if (primary.length === 0 || outliers.size === 0) {
      return { primaryTimed: allTimed, outlierIds: new Set<string>() }
    }
    return { primaryTimed: primary, outlierIds: outliers }
  }, [allTimed])

  const activeTimed = includeOutliers || outlierIds.size === 0 ? allTimed : primaryTimed

  const range = useMemo(() => {
    const min = activeTimed.length ? Math.min(...activeTimed.map(item => item.startMs)) : null
    const max = activeTimed.length ? Math.max(...activeTimed.map(item => item.endMs)) : null
    return {
      min,
      max,
      span: min != null && max != null ? Math.max(1, max - min) : 1,
      count: allTimed.length,
      primaryCount: activeTimed.length,
    }
  }, [activeTimed, allTimed])

  const ticks = range.min == null || range.max == null
    ? []
    : Array.from({ length: 5 }, (_, index) => range.min! + (range.span * index) / 4)

  const filteredChains = useMemo(() => {
    const query = searchTerm.trim().toLowerCase()
    return chains.filter(chain => {
      if (query && !chain.chain_id.toLowerCase().includes(query) && !(chain.title ?? '').toLowerCase().includes(query)) {
        return false
      }
      if (kindFilter === 'MULTI' && chain.is_singleton) return false
      if (kindFilter === 'SINGLETON' && !chain.is_singleton) return false
      return true
    })
  }, [chains, searchTerm, kindFilter])

  const toggle = (chainId: string) => setSelected(current => current.includes(chainId)
    ? current.filter(value => value !== chainId)
    : current.length >= 2 ? [current[1], chainId] : [...current, chainId])

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 select-none animate-fadeIn">
      {/* 1. Top Summary Banner */}
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-[#0c1322] shadow-md">
        <div className="flex flex-col gap-space-md p-space-lg lg:flex-row lg:items-end lg:justify-between border-b border-[#1b273e]">
          <div>
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[20px]">schedule</span>
              <p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">Snapshot chronology</p>
            </div>
            <h1 className="mt-1 font-headline-lg text-headline-lg font-extrabold text-on-surface tracking-tight">Multi-chain timeline</h1>
            <p className="mt-space-xs max-w-2xl text-body-sm text-on-surface-variant">
              Each rail uses canonical first and last alarm timestamps returned by the snapshot. Ordering reflects temporal observation, not causal direction.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {selected.length === 2 && (
              <span className="font-code-sm text-xs text-secondary font-semibold animate-pulse">
                2 chains selected for comparison
              </span>
            )}
            <button
              disabled={selected.length !== 2}
              onClick={() => selected.length === 2 && onCompareChains(selected[0], selected[1])}
              className="inline-flex items-center justify-center gap-space-xs rounded-lg bg-secondary-container px-space-md py-2 font-code-sm font-bold text-on-secondary-container shadow-sm transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[17px]">compare_arrows</span>
              Compare pair
            </button>
          </div>
        </div>

        {/* 4 Metric Stats */}
        <div className="grid grid-cols-2 bg-[#090e1a] md:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-[#1b273e]">
          <div className="px-space-md py-3">
            <small className="block font-label-caps text-[11px] uppercase tracking-wider text-on-surface-variant">Chains</small>
            <strong className="font-code-lg text-lg font-bold text-on-surface">{chains.length}</strong>
          </div>
          <div className="px-space-md py-3">
            <small className="block font-label-caps text-[11px] uppercase tracking-wider text-on-surface-variant">Timed</small>
            <strong className="font-code-lg text-lg font-bold text-on-surface">{range.count}</strong>
          </div>
          <div className="px-space-md py-3">
            <small className="block font-label-caps text-[11px] uppercase tracking-wider text-on-surface-variant">Window start</small>
            <strong className="font-code-md text-secondary font-bold">{range.min == null ? 'Unavailable' : formatClock(range.min)}</strong>
          </div>
          <div className="px-space-md py-3">
            <small className="block font-label-caps text-[11px] uppercase tracking-wider text-on-surface-variant">Window end</small>
            <strong className="font-code-md text-secondary font-bold">{range.max == null ? 'Unavailable' : formatClock(range.max, range.min)}</strong>
          </div>
        </div>

        {/* Outlier Notice Banner if present */}
        {outlierIds.size > 0 && (
          <div className="px-4 py-2 bg-amber-500/10 border-t border-amber-500/20 flex flex-wrap items-center justify-between gap-2 text-xs font-code-sm">
            <div className="flex items-center gap-2 text-amber-300">
              <span className="material-symbols-outlined text-[16px]">info</span>
              <span>
                {includeOutliers
                  ? `Displaying full temporal span including ${outlierIds.size} future-timestamp chain (outlier year detected).`
                  : `Focusing primary observation window (${range.primaryCount} chains). ${outlierIds.size} future-year outlier chain excluded from scale.`}
              </span>
            </div>
            <button
              onClick={() => setIncludeOutliers(!includeOutliers)}
              className="px-2.5 py-1 rounded bg-amber-400/20 hover:bg-amber-400/30 text-amber-200 border border-amber-400/40 font-semibold transition-colors"
            >
              {includeOutliers ? 'Focus primary observation window' : 'Show full span (incl. outliers)'}
            </button>
          </div>
        )}

        {/* Filters & Zoom Toolbar */}
        <div className="p-3 bg-[#0c1322] border-t border-[#1b273e] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="relative flex items-center">
              <span className="material-symbols-outlined absolute left-2.5 text-[16px] text-on-surface-variant">search</span>
              <input
                type="text"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder="Filter chain ID..."
                className="h-8 w-48 rounded-md border border-[#22314d] bg-[#090e1a] pl-8 pr-3 font-code-sm text-xs text-on-surface placeholder:text-on-surface-variant/60 focus:border-secondary focus:outline-none"
              />
            </div>

            {/* Kind Filter */}
            <div className="flex items-center gap-1 rounded-md border border-[#22314d] bg-[#090e1a] p-0.5 text-xs font-code-sm">
              <button
                onClick={() => setKindFilter('ALL')}
                className={`px-2 py-1 rounded transition-colors ${kindFilter === 'ALL' ? 'bg-secondary text-surface-container-lowest font-bold' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                All ({chains.length})
              </button>
              <button
                onClick={() => setKindFilter('MULTI')}
                className={`px-2 py-1 rounded transition-colors ${kindFilter === 'MULTI' ? 'bg-secondary text-surface-container-lowest font-bold' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                Multi-alarm
              </button>
              <button
                onClick={() => setKindFilter('SINGLETON')}
                className={`px-2 py-1 rounded transition-colors ${kindFilter === 'SINGLETON' ? 'bg-secondary text-surface-container-lowest font-bold' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                Singletons
              </button>
            </div>
          </div>

          {/* Zoom Level Stepper */}
          <div className="flex items-center gap-2">
            <span className="font-label-caps text-[11px] uppercase tracking-wider text-on-surface-variant">Scale Zoom:</span>
            <div className="flex items-center gap-1 bg-[#090e1a] p-0.5 rounded-md border border-[#22314d]">
              {[100, 150, 200, 300].map(z => (
                <button
                  key={z}
                  onClick={() => setZoomLevel(z)}
                  className={`px-2 py-1 rounded font-code-sm text-xs font-semibold transition-colors ${zoomLevel === z ? 'bg-secondary text-black font-bold' : 'text-on-surface-variant hover:text-on-surface'}`}
                >
                  {z}%
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 2. Main Timeline Matrix Canvas */}
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-[#090e1a] shadow-sm">
        <div className="overflow-x-auto">
          <div style={{ minWidth: `${Math.max(860, (860 * zoomLevel) / 100)}px` }} className="w-full">
            {/* Time Axis Ruler */}
            <div className="grid grid-cols-[280px_1fr] border-b border-[#1b273e] bg-[#0c1322] sticky top-0 z-20">
              <div className="border-r border-[#1b273e] px-space-md py-2.5 font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant flex items-center justify-between">
                <span>Alarm chain</span>
                <span className="text-[10px] text-secondary">Showing {filteredChains.length}</span>
              </div>
              <div className="relative flex justify-between px-space-md py-2.5 font-code-sm text-xs text-on-surface-variant">
                {ticks.map((tick, idx) => (
                  <div key={tick} className="flex flex-col items-center">
                    <span className="font-semibold text-secondary">{formatTick(tick, range.min!, range.span)}</span>
                    <span className="text-[10px] text-[#60769d]">
                      {idx === 0 ? 'T₀ Start' : idx === 4 ? 'Window End' : `Tick ${idx + 1}`}
                    </span>
                  </div>
                ))}
                {!ticks.length && <span>Temporal scale unavailable</span>}
              </div>
            </div>

            {/* Empty State */}
            {chains.length === 0 && (
              <p className="p-space-xl text-center text-on-surface-variant font-code-sm">
                No chains are available for this snapshot.
              </p>
            )}

            {/* Timeline Rows */}
            <div className="divide-y divide-[#151f33]">
              {filteredChains.map(chain => {
                const startMs = parsedTime(chain.start_time)
                const endMs = parsedTime(chain.end_time)
                const available = startMs != null && endMs != null && range.min != null
                const left = available ? ((startMs - range.min!) / range.span) * 100 : 0
                const rawWidth = available ? ((Math.max(startMs, endMs) - startMs) / range.span) * 100 : 0
                // Minimum visual bar width so it's always an interactive, readable pill
                const visualWidth = available ? Math.max(3.5, rawWidth) : 0
                const isSelected = selected.includes(chain.chain_id)
                const isOutlier = outlierIds.has(chain.chain_id)

                return (
                  <div
                    key={chain.chain_id}
                    className={`grid grid-cols-[280px_1fr] transition-colors hover:bg-[#101a2e] group ${
                      selectedChainId === chain.chain_id ? 'bg-secondary-container/15' : isSelected ? 'bg-[#15233d]' : ''
                    }`}
                  >
                    {/* Left Meta Column */}
                    <div className="flex items-center gap-2.5 border-r border-[#1b273e] p-space-sm bg-[#090e1a] group-hover:bg-[#101a2e] transition-colors">
                      <input
                        aria-label={`Select ${chain.chain_id} for comparison`}
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggle(chain.chain_id)}
                        className="accent-secondary h-4 w-4 rounded cursor-pointer shrink-0"
                      />
                      <button
                        className="min-w-0 flex-1 text-left cursor-pointer"
                        onClick={() => onSelectChain(chain.chain_id)}
                        title={`Inspect chain ${chain.chain_id}`}
                      >
                        <div className="flex items-center gap-1.5">
                          <strong className="block truncate font-code-sm text-sm text-secondary group-hover:underline">
                            {chain.chain_id}
                          </strong>
                          {chain.is_singleton && (
                            <span className="rounded bg-[#17243b] px-1.5 py-0.2 font-code-sm text-[10px] text-tertiary border border-tertiary/30">
                              1
                            </span>
                          )}
                        </div>
                        <small className="block truncate text-on-surface-variant text-[11px] font-code-sm">
                          {chain.member_count} {chain.member_count === 1 ? 'alarm' : 'alarms'} · {formatDuration(chain.duration_seconds)}
                        </small>
                      </button>
                    </div>

                    {/* Right Gantt Track Area */}
                    <div className="relative min-h-[58px] overflow-hidden px-space-md py-2 flex items-center">
                      {/* Vertical Guideline Gridlines */}
                      {ticks.slice(1).map(tick => (
                        <span
                          key={tick}
                          aria-hidden="true"
                          className="absolute bottom-0 top-0 border-l border-[#1b273e]/60 pointer-events-none"
                          style={{ left: `${((tick - range.min!) / range.span) * 100}%` }}
                        />
                      ))}

                      {isOutlier && !includeOutliers ? (
                        <div
                          className="h-6 rounded-md bg-amber-500/15 border border-amber-400/50 px-2.5 flex items-center gap-1.5 text-amber-300 font-code-sm text-xs cursor-pointer hover:bg-amber-500/25 transition-colors shadow-sm"
                          onClick={() => setIncludeOutliers(true)}
                          title="Timestamp year is outside primary observation range. Click to expand full span."
                        >
                          <span className="material-symbols-outlined text-[15px]">event_upcoming</span>
                          <span className="font-semibold">Future Outlier ({formatClock(chain.start_time!)})</span>
                          <span className="opacity-75 text-[10px] hidden sm:inline ml-1">· Click to view on full scale</span>
                        </div>
                      ) : available ? (
                        <div
                          className="relative h-7 flex items-center transition-all"
                          style={{
                            left: `${Math.min(95, Math.max(0, left))}%`,
                            width: `${Math.min(100 - Math.min(95, Math.max(0, left)), Math.max(4, visualWidth))}%`,
                          }}
                        >
                          {/* The Gantt Bar */}
                          <div
                            className="h-6 w-full rounded-md border flex items-center justify-between px-2 cursor-pointer shadow-md transition-all hover:brightness-125 bg-gradient-to-r from-secondary/40 via-sky-500/30 to-secondary/50 border-secondary/80 text-white shadow-[0_0_12px_rgba(34,211,238,0.2)]"
                            onClick={() => onSelectChain(chain.chain_id)}
                            title={`${chain.chain_id}: ${formatClock(chain.start_time!)} – ${formatClock(chain.end_time!, range.min)} (${formatDuration(chain.duration_seconds)})`}
                          >
                            <span className="font-code-sm text-[11px] font-bold truncate">
                              {formatDuration(chain.duration_seconds)}
                            </span>
                            {visualWidth >= 8 && (
                              <span className="font-code-sm text-[10px] text-on-surface-variant hidden md:inline truncate ml-1 opacity-80">
                                {chain.member_count} alms
                              </span>
                            )}
                          </div>

                          {/* Hover Timestamp Badge */}
                          <div
                            className="absolute -top-3.5 left-0 font-code-sm text-[10px] text-secondary font-semibold whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity bg-[#080d17] px-1 rounded border border-secondary/30 z-10"
                          >
                            <span>{formatClock(chain.start_time!)}</span>
                            <span className="mx-1 text-on-surface-variant">→</span>
                            <span>{formatClock(chain.end_time!, range.min)}</span>
                          </div>
                        </div>
                      ) : (
                        <span className="inline-flex items-center gap-1 font-code-sm text-xs text-on-surface-variant">
                          <span aria-hidden="true" className="material-symbols-outlined text-[15px]">schedule</span>
                          Temporal range unavailable
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
