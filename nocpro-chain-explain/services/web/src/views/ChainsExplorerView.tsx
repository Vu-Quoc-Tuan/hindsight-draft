import { useMemo, useState, type ReactNode } from 'react'

import type { ChainList } from '../types'
import { formatDuration } from '../format'

interface ChainsExplorerViewProps {
  chainList: ChainList | null
  onSelectChain: (chainId: string) => void
}

type ChainKindFilter = 'ALL' | 'MULTI' | 'SINGLETON'
type TemporalFilter = 'ALL' | 'AVAILABLE' | 'UNAVAILABLE'
type SortColumn = 'chain' | 'members' | 'first_alarm' | 'last_alarm' | 'duration' | null
type SortDirection = 'asc' | 'desc'

function compactTimestamp(value: string | null) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function FilterButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded px-3 py-1 font-code-sm text-[11px] transition-all cursor-pointer ${
        active
          ? 'bg-secondary font-bold text-[#070e1d] shadow-sm'
          : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
      }`}
    >
      {children}
    </button>
  )
}

export function ChainsExplorerView({ chainList, onSelectChain }: ChainsExplorerViewProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [kindFilter, setKindFilter] = useState<ChainKindFilter>('ALL')
  const [temporalFilter, setTemporalFilter] = useState<TemporalFilter>('ALL')
  const [sortColumn, setSortColumn] = useState<SortColumn>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  const chains = useMemo(() => chainList?.chains ?? [], [chainList])
  const facts = useMemo(() => ({
    alarmCount: chains.reduce((total, chain) => total + chain.member_count, 0),
    singletonCount: chains.filter(chain => chain.is_singleton).length,
    temporalCount: chains.filter(chain => chain.start_time && chain.end_time).length,
  }), [chains])

  const filteredChains = useMemo(() => {
    const query = searchTerm.trim().toLowerCase()
    return chains.filter(chain => {
      if (query && !chain.chain_id.toLowerCase().includes(query) && !chain.title.toLowerCase().includes(query)) return false
      if (kindFilter === 'MULTI' && chain.is_singleton) return false
      if (kindFilter === 'SINGLETON' && !chain.is_singleton) return false
      const hasTemporalRange = Boolean(chain.start_time && chain.end_time)
      if (temporalFilter === 'AVAILABLE' && !hasTemporalRange) return false
      if (temporalFilter === 'UNAVAILABLE' && hasTemporalRange) return false
      return true
    })
  }, [chains, kindFilter, searchTerm, temporalFilter])

  const sortedChains = useMemo(() => {
    const list = [...filteredChains]
    if (!sortColumn) return list

    return list.sort((a, b) => {
      let comparison = 0
      if (sortColumn === 'members') {
        comparison = b.member_count - a.member_count
      } else if (sortColumn === 'duration') {
        comparison = (b.duration_seconds ?? -1) - (a.duration_seconds ?? -1)
      } else if (sortColumn === 'first_alarm') {
        const tA = a.start_time ? new Date(a.start_time).getTime() : 0
        const tB = b.start_time ? new Date(b.start_time).getTime() : 0
        comparison = tB - tA
      } else if (sortColumn === 'last_alarm') {
        const tA = a.end_time ? new Date(a.end_time).getTime() : 0
        const tB = b.end_time ? new Date(b.end_time).getTime() : 0
        comparison = tB - tA
      } else if (sortColumn === 'chain') {
        comparison = a.chain_id.localeCompare(b.chain_id, undefined, { numeric: true })
      }

      if (sortDirection === 'asc') {
        comparison = -comparison
      }

      return comparison || a.chain_id.localeCompare(b.chain_id, undefined, { numeric: true })
    })
  }, [filteredChains, sortColumn, sortDirection])

  const handleSort = (column: NonNullable<SortColumn>) => {
    if (sortColumn !== column) {
      setSortColumn(column)
      setSortDirection(column === 'chain' ? 'asc' : 'desc')
    } else if (sortDirection === 'desc') {
      setSortDirection('asc')
    } else {
      setSortColumn(null)
      setSortDirection('desc')
    }
  }

  return (
    <div className="flex w-full flex-col gap-space-md p-space-md lg:p-space-lg">
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-low shadow-md">
        <div className="grid grid-cols-2 border-b border-surface-container-high md:grid-cols-4">
          {[
            ['Chains', chains.length.toLocaleString()],
            ['Observed alarms', facts.alarmCount.toLocaleString()],
            ['Singletons', facts.singletonCount.toLocaleString()],
            ['Timed chains', `${facts.temporalCount}/${chains.length}`],
          ].map(([label, value]) => (
            <div key={label} className="border-r border-surface-container-high px-space-md py-space-sm last:border-r-0">
              <div className="font-label-caps text-label-caps uppercase tracking-[0.14em] text-on-surface-variant">{label}</div>
              <div className="mt-1 font-code-lg text-lg font-bold text-on-surface">{value}</div>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-space-md p-space-md">
          {/* Row 1: Search input */}
          <label className="relative flex w-full items-center">
            <span aria-hidden="true" className="material-symbols-outlined absolute left-space-sm text-[18px] text-on-surface-variant">search</span>
            <span className="sr-only">Search chains</span>
            <input
              type="search"
              value={searchTerm}
              onChange={event => setSearchTerm(event.target.value)}
              placeholder="Search chain ID or observed title…"
              className="h-space-panel-header-h w-full rounded-lg border border-surface-container-highest bg-surface-container-lowest pl-9 pr-10 font-code-md text-code-md text-on-surface placeholder:text-on-surface-variant/60 focus:border-secondary focus:outline-none transition-colors"
            />
            {searchTerm ? (
              <button
                type="button"
                aria-label="Clear chain search"
                onClick={() => setSearchTerm('')}
                className="absolute right-space-sm text-on-surface-variant hover:text-on-surface cursor-pointer"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[17px]">close</span>
              </button>
            ) : null}
          </label>

          {/* Row 2: 3-Group Filter Bar: Left (KIND), Middle (TIME), Right (SORT) */}
          <div className="flex w-full flex-wrap items-center justify-between gap-space-sm">
            {/* Left: Filter by Kind */}
            <div className="flex items-center rounded-lg border border-surface-container-highest bg-[#0a101d] p-1 shadow-sm">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-extrabold uppercase tracking-wider text-secondary bg-secondary/10 rounded border border-secondary/20 mr-1.5 select-none">
                <span aria-hidden="true" className="material-symbols-outlined text-[14px]">tune</span>
                <span>KIND</span>
              </span>
              <div className="h-4 w-px bg-surface-container-highest mr-1.5" />
              <div className="flex items-center gap-0.5">
                <FilterButton active={kindFilter === 'ALL'} onClick={() => setKindFilter('ALL')}>All</FilterButton>
                <FilterButton active={kindFilter === 'MULTI'} onClick={() => setKindFilter('MULTI')}>Multi-alarm</FilterButton>
                <FilterButton active={kindFilter === 'SINGLETON'} onClick={() => setKindFilter('SINGLETON')}>Singleton</FilterButton>
              </div>
            </div>

            {/* Middle: Filter by Time */}
            <div className="flex items-center rounded-lg border border-surface-container-highest bg-[#0a101d] p-1 shadow-sm">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-extrabold uppercase tracking-wider text-primary bg-primary/10 rounded border border-primary/20 mr-1.5 select-none">
                <span aria-hidden="true" className="material-symbols-outlined text-[14px]">schedule</span>
                <span>TIME</span>
              </span>
              <div className="h-4 w-px bg-surface-container-highest mr-1.5" />
              <div className="flex items-center gap-0.5">
                <FilterButton active={temporalFilter === 'ALL'} onClick={() => setTemporalFilter('ALL')}>All</FilterButton>
                <FilterButton active={temporalFilter === 'AVAILABLE'} onClick={() => setTemporalFilter('AVAILABLE')}>Available</FilterButton>
                <FilterButton active={temporalFilter === 'UNAVAILABLE'} onClick={() => setTemporalFilter('UNAVAILABLE')}>Unavailable</FilterButton>
              </div>
            </div>

            {/* Right: Sort controls */}
            <div className="flex items-center rounded-lg border border-surface-container-highest bg-[#0a101d] p-1 shadow-sm">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-extrabold uppercase tracking-wider text-tertiary bg-tertiary/10 rounded border border-tertiary/20 mr-1.5 select-none">
                <span aria-hidden="true" className="material-symbols-outlined text-[14px]">sort</span>
                <span>SORT</span>
              </span>
              <div className="h-4 w-px bg-surface-container-highest mr-1.5" />
              <div className="flex items-center gap-0.5">
                <FilterButton
                  active={sortColumn === null}
                  onClick={() => { setSortColumn(null); setSortDirection('desc') }}
                >
                  Default
                </FilterButton>
                <FilterButton
                  active={sortColumn === 'members' && sortDirection === 'desc'}
                  onClick={() => { setSortColumn('members'); setSortDirection('desc') }}
                >
                  Most members
                </FilterButton>
                <FilterButton
                  active={sortColumn === 'members' && sortDirection === 'asc'}
                  onClick={() => { setSortColumn('members'); setSortDirection('asc') }}
                >
                  Fewest
                </FilterButton>
                <FilterButton
                  active={sortColumn === 'duration' && sortDirection === 'desc'}
                  onClick={() => { setSortColumn('duration'); setSortDirection('desc') }}
                >
                  Longest
                </FilterButton>
              </div>
            </div>
          </div>

          {/* Row 3: Status & Note */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-container-high/60 pt-space-sm text-code-sm text-xs text-on-surface-variant">
            <div className="flex items-center gap-2">
              <span>
                Showing <strong className="text-on-surface">{sortedChains.length.toLocaleString()}</strong> of {chains.length.toLocaleString()} chains
                {sortColumn === 'members' && (
                  <span className="ml-1 text-secondary font-medium">
                    · Sorted by {sortDirection === 'desc' ? 'most members' : 'fewest members'}
                  </span>
                )}
                {sortColumn === 'duration' && (
                  <span className="ml-1 text-secondary font-medium">
                    · Sorted by {sortDirection === 'desc' ? 'longest duration' : 'shortest duration'}
                  </span>
                )}
                {sortColumn && sortColumn !== 'members' && sortColumn !== 'duration' && (
                  <span className="ml-1 text-secondary font-medium">
                    · Sorted by {sortColumn} ({sortDirection})
                  </span>
                )}
              </span>

              {(kindFilter !== 'ALL' || temporalFilter !== 'ALL' || searchTerm || sortColumn !== null) && (
                <button
                  type="button"
                  onClick={() => { setKindFilter('ALL'); setTemporalFilter('ALL'); setSearchTerm(''); setSortColumn(null); setSortDirection('desc') }}
                  className="inline-flex items-center gap-1 rounded bg-[#141d30] px-2 py-0.5 text-[11px] font-code-sm text-secondary hover:text-primary hover:bg-[#1a253c] border border-[#22304c] transition-all cursor-pointer"
                  title="Reset all filters and sorting"
                >
                  <span className="material-symbols-outlined text-[13px]">filter_alt_off</span>
                  <span>Reset filters</span>
                </button>
              )}
            </div>
            <div className="text-[11px] text-[#64748b]">
              Snapshot-level results do not run Audit automatically.
            </div>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-low shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse text-left font-body-sm">
            <thead>
              <tr className="h-space-panel-header-h border-b border-surface-container-high bg-surface-container font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant">
                <th className="px-space-sm">
                  <button
                    type="button"
                    onClick={() => handleSort('chain')}
                    className="group inline-flex items-center gap-1 font-label-caps text-label-caps uppercase tracking-wider hover:text-on-surface cursor-pointer select-none"
                    title="Sort by Chain ID"
                  >
                    <span>Chain</span>
                    {sortColumn === 'chain' ? (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-secondary font-bold">
                        {sortDirection === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                      </span>
                    ) : (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] opacity-20 group-hover:opacity-100 transition-opacity">
                        unfold_more
                      </span>
                    )}
                  </button>
                </th>
                <th className="px-space-sm">
                  <button
                    type="button"
                    onClick={() => handleSort('members')}
                    className="group inline-flex items-center gap-1 font-label-caps text-label-caps uppercase tracking-wider hover:text-on-surface cursor-pointer select-none"
                    title="Sort by Member count (Most members)"
                  >
                    <span>Members</span>
                    {sortColumn === 'members' ? (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-secondary font-bold">
                        {sortDirection === 'desc' ? 'arrow_downward' : 'arrow_upward'}
                      </span>
                    ) : (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] opacity-20 group-hover:opacity-100 transition-opacity">
                        unfold_more
                      </span>
                    )}
                  </button>
                </th>
                <th className="px-space-sm">Observed title</th>
                <th className="px-space-sm">
                  <button
                    type="button"
                    onClick={() => handleSort('first_alarm')}
                    className="group inline-flex items-center gap-1 font-label-caps text-label-caps uppercase tracking-wider hover:text-on-surface cursor-pointer select-none"
                    title="Sort by First alarm timestamp"
                  >
                    <span>First alarm</span>
                    {sortColumn === 'first_alarm' ? (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-secondary font-bold">
                        {sortDirection === 'desc' ? 'arrow_downward' : 'arrow_upward'}
                      </span>
                    ) : (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] opacity-20 group-hover:opacity-100 transition-opacity">
                        unfold_more
                      </span>
                    )}
                  </button>
                </th>
                <th className="px-space-sm">
                  <button
                    type="button"
                    onClick={() => handleSort('last_alarm')}
                    className="group inline-flex items-center gap-1 font-label-caps text-label-caps uppercase tracking-wider hover:text-on-surface cursor-pointer select-none"
                    title="Sort by Last alarm timestamp"
                  >
                    <span>Last alarm</span>
                    {sortColumn === 'last_alarm' ? (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-secondary font-bold">
                        {sortDirection === 'desc' ? 'arrow_downward' : 'arrow_upward'}
                      </span>
                    ) : (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] opacity-20 group-hover:opacity-100 transition-opacity">
                        unfold_more
                      </span>
                    )}
                  </button>
                </th>
                <th className="px-space-sm">
                  <button
                    type="button"
                    onClick={() => handleSort('duration')}
                    className="group inline-flex items-center gap-1 font-label-caps text-label-caps uppercase tracking-wider hover:text-on-surface cursor-pointer select-none"
                    title="Sort by Duration"
                  >
                    <span>Duration</span>
                    {sortColumn === 'duration' ? (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-secondary font-bold">
                        {sortDirection === 'desc' ? 'arrow_downward' : 'arrow_upward'}
                      </span>
                    ) : (
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px] opacity-20 group-hover:opacity-100 transition-opacity">
                        unfold_more
                      </span>
                    )}
                  </button>
                </th>
                <th className="px-space-sm">Structural Audit</th>
                <th className="px-space-sm text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container-high/40 font-code-sm text-[13px]">
              {sortedChains.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center">
                    <span aria-hidden="true" className="material-symbols-outlined mb-2 block text-3xl text-on-surface-variant">search_off</span>
                    <span className="text-on-surface-variant">No chains match the current filters.</span>
                  </td>
                </tr>
              ) : (
                sortedChains.map(chain => {
                  return (
                    <tr
                      key={chain.chain_id}
                      className="hover:bg-surface-container/70 cursor-pointer transition-colors"
                      onClick={() => onSelectChain(chain.chain_id)}
                    >
                      <td className="px-space-sm py-space-sm font-semibold text-primary">{chain.chain_id}</td>
                      <td className="px-space-sm py-space-sm text-base font-bold text-on-surface">{chain.member_count}</td>
                      <td className="px-space-sm py-space-sm"><span className="block max-w-[260px] truncate text-on-surface" title={chain.title}>{chain.title || 'Unavailable'}</span></td>
                      <td className="px-space-sm py-space-sm text-on-surface-variant">{compactTimestamp(chain.start_time)}</td>
                      <td className="px-space-sm py-space-sm text-on-surface-variant">{compactTimestamp(chain.end_time)}</td>
                      <td className="px-space-sm py-space-sm text-on-surface-variant">{formatDuration(chain.duration_seconds)}</td>
                      <td className="px-space-sm py-space-sm"><span className="inline-flex items-center gap-1 rounded bg-surface-container px-space-xs py-space-2xs text-on-surface-variant"><span aria-hidden="true" className="material-symbols-outlined text-[14px]">query_stats</span>Audit on demand</span></td>
                      <td className="px-space-sm py-space-sm text-right">
                        <button
                          type="button"
                          className="rounded border border-secondary/30 px-space-sm py-1 text-secondary transition-colors hover:bg-secondary-container/20 cursor-pointer"
                          onClick={event => { event.stopPropagation(); onSelectChain(chain.chain_id) }}
                        >
                          Inspect →
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
