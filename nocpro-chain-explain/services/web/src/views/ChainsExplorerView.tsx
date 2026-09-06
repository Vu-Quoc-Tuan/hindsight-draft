import { useMemo, useState, type MouseEvent } from 'react'

import type { ChainList } from '../types'

interface ChainsExplorerViewProps {
  chainList: ChainList | null
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainIds: string[]) => void
}

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

export function ChainsExplorerView({ chainList, onSelectChain, onCompareChains }: ChainsExplorerViewProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedChainIds, setSelectedChainIds] = useState<Set<string>>(new Set())
  const chains = useMemo(() => chainList?.chains ?? [], [chainList])
  const filteredChains = useMemo(() => {
    const query = searchTerm.trim().toLowerCase()
    if (!query) return chains
    return chains.filter(chain => chain.chain_id.toLowerCase().includes(query) || chain.title.toLowerCase().includes(query))
  }, [chains, searchTerm])

  const toggleSelectChain = (id: string, event: MouseEvent) => {
    event.stopPropagation()
    setSelectedChainIds(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => setSelectedChainIds(current => current.size === filteredChains.length
    ? new Set()
    : new Set(filteredChains.map(chain => chain.chain_id)))

  return <div className="w-full flex flex-col gap-space-md p-space-lg">
    <div className="bg-surface-container-low rounded-lg p-space-md border border-surface-container-high shadow-sm flex flex-col gap-space-sm">
      <div className="flex flex-col md:flex-row md:items-center gap-space-sm">
        <label className="relative flex flex-1 items-center">
          <span className="material-symbols-outlined absolute left-space-sm text-on-surface-variant text-[18px]">search</span>
          <span className="sr-only">Search chains</span>
          <input type="search" value={searchTerm} onChange={event => setSearchTerm(event.target.value)} placeholder="Search chain ID or title" className="w-full bg-surface-container-lowest text-on-surface font-code-md text-code-md pl-9 pr-space-md h-space-panel-header-h rounded border border-surface-container-highest placeholder:text-on-surface-variant/60 focus:outline-none focus:border-secondary" />
        </label>
        {selectedChainIds.size > 1 && <button className="px-space-md py-space-xs bg-primary-container text-on-primary font-code-sm text-code-sm font-bold rounded" onClick={() => onCompareChains(Array.from(selectedChainIds))}>Compare {selectedChainIds.size} chains</button>}
      </div>
      <div className="font-code-sm text-code-sm text-on-surface-variant">Showing <strong className="text-on-surface">{filteredChains.length}</strong> of {chains.length} chains. Snapshot-level results do not run Audit automatically.</div>
    </div>
    <div className="bg-surface-container-low rounded-lg border border-surface-container-high shadow-sm overflow-hidden"><div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-left border-collapse font-body-sm">
        <thead><tr className="bg-surface-container border-b border-surface-container-high font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">
          <th className="w-10 px-3 py-space-sm text-center"><input aria-label="Select all visible chains" type="checkbox" checked={filteredChains.length > 0 && selectedChainIds.size === filteredChains.length} onChange={toggleSelectAll} /></th>
          <th className="px-space-sm">Chain ID</th><th className="px-space-sm">Members</th><th className="px-space-sm">Observed title</th><th className="px-space-sm">Temporal range</th><th className="px-space-sm">Duration</th><th className="px-space-sm">Structural Audit</th><th className="px-space-sm text-right">Action</th>
        </tr></thead>
        <tbody className="divide-y divide-surface-container-high/40 font-code-sm text-[13px]">
          {filteredChains.length === 0 ? <tr><td colSpan={8} className="py-12 text-center text-on-surface-variant">No chains match the current search.</td></tr> : filteredChains.map(chain => {
            const selected = selectedChainIds.has(chain.chain_id)
            return <tr key={chain.chain_id} className={selected ? 'bg-surface-container-high/80' : 'hover:bg-surface-container'} onClick={() => onSelectChain(chain.chain_id)}>
              <td className="px-3 py-space-sm text-center" onClick={event => toggleSelectChain(chain.chain_id, event)}><input aria-label={`Select ${chain.chain_id}`} type="checkbox" checked={selected} onChange={() => {}} /></td>
              <td className="px-space-sm py-space-sm font-bold text-primary">{chain.chain_id}</td>
              <td className="px-space-sm py-space-sm text-on-surface">{chain.member_count}</td>
              <td className="px-space-sm py-space-sm"><span className="block max-w-[300px] truncate" title={chain.title}>{chain.title || 'Unavailable'}</span><small className="text-on-surface-variant">{chain.is_singleton ? 'Singleton' : 'Multi-alarm chain'}</small></td>
              <td className="px-space-sm py-space-sm text-on-surface-variant"><span className="block">{compactTimestamp(chain.start_time)}</span><span className="block">{compactTimestamp(chain.end_time)}</span></td>
              <td className="px-space-sm py-space-sm text-on-surface-variant">{formatDuration(chain.duration_seconds)}</td>
              <td className="px-space-sm py-space-sm"><span className="rounded bg-surface-container px-space-xs py-space-2xs text-on-surface-variant">Audit on demand</span></td>
              <td className="px-space-sm py-space-sm text-right"><button className="rounded border border-secondary/30 px-space-sm py-1 text-secondary" onClick={event => { event.stopPropagation(); onSelectChain(chain.chain_id) }}>Inspect →</button></td>
            </tr>
          })}
        </tbody>
      </table>
    </div></div>
  </div>
}
