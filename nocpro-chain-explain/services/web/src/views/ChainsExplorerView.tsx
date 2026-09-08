import { useMemo, useState, type MouseEvent, type ReactNode } from 'react'

import type { ChainList } from '../types'

interface ChainsExplorerViewProps {
  chainList: ChainList | null
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainIds: string[]) => void
}

type ChainKindFilter = 'ALL' | 'MULTI' | 'SINGLETON'
type TemporalFilter = 'ALL' | 'AVAILABLE' | 'UNAVAILABLE'

function formatDuration(seconds: number | null) {
  if (seconds == null) return 'Unavailable'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function compactTimestamp(value: string | null) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function FilterButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`rounded px-2.5 py-1 font-code-sm text-[11px] transition-colors ${active
      ? 'bg-secondary font-bold text-on-secondary'
      : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'}`}
  >{children}</button>
}

export function ChainsExplorerView({ chainList, onSelectChain, onCompareChains }: ChainsExplorerViewProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [kindFilter, setKindFilter] = useState<ChainKindFilter>('ALL')
  const [temporalFilter, setTemporalFilter] = useState<TemporalFilter>('ALL')
  const [selectedChainIds, setSelectedChainIds] = useState<Set<string>>(new Set())
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

  const visibleChainIds = useMemo(() => new Set(filteredChains.map(chain => chain.chain_id)), [filteredChains])
  const visibleSelectedChainIds = useMemo(
    () => new Set([...selectedChainIds].filter(id => visibleChainIds.has(id))),
    [selectedChainIds, visibleChainIds],
  )

  const toggleSelectChain = (id: string, event: MouseEvent) => {
    event.stopPropagation()
    setSelectedChainIds(current => {
      const next = new Set([...current].filter(candidateId => visibleChainIds.has(candidateId)))
      if (next.has(id)) next.delete(id)
      else {
        if (next.size >= 2) next.delete(next.values().next().value as string)
        next.add(id)
      }
      return next
    })
  }

  return <div className="flex w-full flex-col gap-space-md p-space-md lg:p-space-lg">
    <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-low shadow-md">
      <div className="grid grid-cols-2 border-b border-surface-container-high md:grid-cols-4">
        {[
          ['Chains', chains.length.toLocaleString()],
          ['Observed alarms', facts.alarmCount.toLocaleString()],
          ['Singletons', facts.singletonCount.toLocaleString()],
          ['Timed chains', `${facts.temporalCount}/${chains.length}`],
        ].map(([label, value]) => <div key={label} className="border-r border-surface-container-high px-space-md py-space-sm last:border-r-0">
          <div className="font-label-caps text-label-caps uppercase tracking-[0.14em] text-on-surface-variant">{label}</div>
          <div className="mt-1 font-code-lg text-lg font-bold text-on-surface">{value}</div>
        </div>)}
      </div>

      <div className="flex flex-col gap-space-md p-space-md">
        <div className="grid grid-cols-1 gap-space-sm xl:grid-cols-[minmax(280px,1fr)_auto_auto] xl:items-center">
          <label className="relative flex items-center">
            <span aria-hidden="true" className="material-symbols-outlined absolute left-space-sm text-[18px] text-on-surface-variant">search</span>
            <span className="sr-only">Search chains</span>
            <input type="search" value={searchTerm} onChange={event => { setSearchTerm(event.target.value); setSelectedChainIds(new Set()) }} placeholder="Search chain ID or observed title…" className="h-space-panel-header-h w-full rounded border border-surface-container-highest bg-surface-container-lowest pl-9 pr-10 font-code-md text-code-md text-on-surface placeholder:text-on-surface-variant/60 focus:border-secondary focus:outline-none" />
            {searchTerm ? <button type="button" aria-label="Clear chain search" onClick={() => { setSearchTerm(''); setSelectedChainIds(new Set()) }} className="absolute right-space-sm text-on-surface-variant hover:text-on-surface"><span aria-hidden="true" className="material-symbols-outlined text-[17px]">close</span></button> : null}
          </label>
          <div className="flex items-center gap-1 rounded border border-surface-container-highest bg-surface-container p-0.5">
            <span className="px-2 font-label-caps text-label-caps uppercase text-on-surface-variant">Kind</span>
            <FilterButton active={kindFilter === 'ALL'} onClick={() => { setKindFilter('ALL'); setSelectedChainIds(new Set()) }}>All</FilterButton>
            <FilterButton active={kindFilter === 'MULTI'} onClick={() => { setKindFilter('MULTI'); setSelectedChainIds(new Set()) }}>Multi-alarm</FilterButton>
            <FilterButton active={kindFilter === 'SINGLETON'} onClick={() => { setKindFilter('SINGLETON'); setSelectedChainIds(new Set()) }}>Singleton</FilterButton>
          </div>
          <div className="flex items-center gap-1 rounded border border-surface-container-highest bg-surface-container p-0.5">
            <span className="px-2 font-label-caps text-label-caps uppercase text-on-surface-variant">Time</span>
            <FilterButton active={temporalFilter === 'ALL'} onClick={() => { setTemporalFilter('ALL'); setSelectedChainIds(new Set()) }}>All</FilterButton>
            <FilterButton active={temporalFilter === 'AVAILABLE'} onClick={() => { setTemporalFilter('AVAILABLE'); setSelectedChainIds(new Set()) }}>Available</FilterButton>
            <FilterButton active={temporalFilter === 'UNAVAILABLE'} onClick={() => { setTemporalFilter('UNAVAILABLE'); setSelectedChainIds(new Set()) }}>Unavailable</FilterButton>
          </div>
        </div>

        <div className="flex flex-col gap-space-xs border-t border-surface-container-high/60 pt-space-sm sm:flex-row sm:items-center sm:justify-between">
          <p className="font-code-sm text-code-sm text-on-surface-variant">Showing <strong className="text-on-surface">{filteredChains.length}</strong> of {chains.length} chains · Snapshot-level results do not run Audit automatically.</p>
          <div className="flex items-center gap-space-sm">
            {visibleSelectedChainIds.size ? <span className="font-code-sm text-secondary">{visibleSelectedChainIds.size} selected</span> : null}
            <button type="button" disabled={visibleSelectedChainIds.size !== 2} className="inline-flex items-center gap-space-xs rounded bg-primary-container px-space-md py-space-xs font-code-sm font-bold text-on-primary shadow-sm transition-colors hover:bg-primary-container/80 disabled:cursor-not-allowed disabled:opacity-35" onClick={() => onCompareChains(Array.from(visibleSelectedChainIds))}><span aria-hidden="true" className="material-symbols-outlined text-[16px]">compare_arrows</span>Compare pair</button>
          </div>
        </div>
      </div>
    </section>

    <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-low shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] border-collapse text-left font-body-sm">
          <thead><tr className="h-space-panel-header-h border-b border-surface-container-high bg-surface-container font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant">
            <th className="w-10 px-3 text-center"><span className="sr-only">Select up to two chains for comparison</span></th>
            <th className="px-space-sm">Chain</th><th className="px-space-sm">Members</th><th className="px-space-sm">Observed title</th><th className="px-space-sm">First alarm</th><th className="px-space-sm">Last alarm</th><th className="px-space-sm">Duration</th><th className="px-space-sm">Structural Audit</th><th className="px-space-sm text-right">Action</th>
          </tr></thead>
          <tbody className="divide-y divide-surface-container-high/40 font-code-sm text-[13px]">
            {filteredChains.length === 0 ? <tr><td colSpan={9} className="py-16 text-center"><span aria-hidden="true" className="material-symbols-outlined mb-2 block text-3xl text-on-surface-variant">search_off</span><span className="text-on-surface-variant">No chains match the current filters.</span></td></tr> : filteredChains.map(chain => {
              const selected = visibleSelectedChainIds.has(chain.chain_id)
              return <tr key={chain.chain_id} className={`${selected ? 'bg-surface-container-high/80' : 'hover:bg-surface-container'} cursor-pointer transition-colors`} onClick={() => onSelectChain(chain.chain_id)}>
                <td className="px-3 py-space-sm text-center" onClick={event => toggleSelectChain(chain.chain_id, event)}><input aria-label={`Select ${chain.chain_id}`} type="checkbox" checked={selected} onChange={() => {}} className="accent-secondary" /></td>
                <td className="px-space-sm py-space-sm font-semibold text-primary">{chain.chain_id}</td>
                <td className="px-space-sm py-space-sm text-base font-bold text-on-surface">{chain.member_count}</td>
                <td className="px-space-sm py-space-sm"><span className="block max-w-[260px] truncate text-on-surface" title={chain.title}>{chain.title || 'Unavailable'}</span></td>
                <td className="px-space-sm py-space-sm text-on-surface-variant">{compactTimestamp(chain.start_time)}</td>
                <td className="px-space-sm py-space-sm text-on-surface-variant">{compactTimestamp(chain.end_time)}</td>
                <td className="px-space-sm py-space-sm text-on-surface-variant">{formatDuration(chain.duration_seconds)}</td>
                <td className="px-space-sm py-space-sm"><span className="inline-flex items-center gap-1 rounded bg-surface-container px-space-xs py-space-2xs text-on-surface-variant"><span aria-hidden="true" className="material-symbols-outlined text-[14px]">query_stats</span>Audit on demand</span></td>
                <td className="px-space-sm py-space-sm text-right"><button className="rounded border border-secondary/30 px-space-sm py-1 text-secondary transition-colors hover:bg-secondary-container/20" onClick={event => { event.stopPropagation(); onSelectChain(chain.chain_id) }}>Inspect →</button></td>
              </tr>
            })}
          </tbody>
        </table>
      </div>
    </section>
  </div>
}
