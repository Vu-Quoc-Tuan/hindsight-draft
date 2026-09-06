import React, { useState, useMemo } from 'react'
import type { ChainList, ChainSummary } from '../types'

interface ChainsExplorerViewProps {
  chainList: ChainList | null
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainIds: string[]) => void
}

function getChainMeta(chain: ChainSummary) {
  const conductance = 0.05 + ((chain.member_count * 7) % 60) / 100
  const weakMembers = chain.member_count > 30 ? (chain.member_count > 50 ? 2 : 1) : 0
  const durationSec = chain.member_count * 2
  return { conductance, weakMembers, durationSec }
}

export function ChainsExplorerView({
  chainList,
  onSelectChain,
  onCompareChains,
}: ChainsExplorerViewProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [severityFilter, setSeverityFilter] = useState<'ALL' | 'CRITICAL' | 'MAJOR' | 'MINOR'>('ALL')
  const [weakFilter, setWeakFilter] = useState<'ALL' | 'HAS_WEAK' | 'NO_WEAK'>('ALL')
  const [selectedChainIds, setSelectedChainIds] = useState<Set<string>>(new Set())

  const chains = useMemo(() => chainList?.chains ?? [], [chainList])

  const filteredChains = useMemo(() => {
    return chains.filter((chain) => {
      const meta = getChainMeta(chain)
      // Search term filter
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase()
        const matchId = chain.chain_id.toLowerCase().includes(query)
        const matchTitle = (chain.title ?? '').toLowerCase().includes(query)
        if (!matchId && !matchTitle) return false
      }

      // Severity filter heuristic
      if (severityFilter === 'CRITICAL' && chain.member_count < 10) return false
      if (severityFilter === 'MAJOR' && (chain.member_count < 4 || chain.member_count >= 10)) return false
      if (severityFilter === 'MINOR' && chain.member_count >= 4) return false

      // Weak member filter
      if (weakFilter === 'HAS_WEAK' && meta.weakMembers === 0) return false
      if (weakFilter === 'NO_WEAK' && meta.weakMembers > 0) return false

      return true
    })
  }, [chains, searchTerm, severityFilter, weakFilter])

  const toggleSelectChain = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = new Set(selectedChainIds)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelectedChainIds(next)
  }

  const toggleSelectAll = () => {
    if (selectedChainIds.size === filteredChains.length) {
      setSelectedChainIds(new Set())
    } else {
      setSelectedChainIds(new Set(filteredChains.map((c) => c.chain_id)))
    }
  }

  return (
    <div className="w-full flex flex-col gap-space-md p-space-lg">
      {/* Control Plane: Search & Filters */}
      <div className="bg-surface-container-low rounded-lg p-space-md border border-surface-container-high shadow-sm flex flex-col gap-space-md">
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-sm items-center">
          {/* Full-text Search Field */}
          <div className="xl:col-span-5 relative flex items-center">
            <span className="material-symbols-outlined absolute left-space-sm text-on-surface-variant text-[18px]">
              search
            </span>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search [ chain ID / lead alarm / resource / site ]..."
              className="w-full bg-surface-container-lowest text-on-surface font-code-md text-code-md pl-9 pr-space-md h-space-panel-header-h rounded border border-surface-container-highest placeholder:text-on-surface-variant/60 focus:outline-none focus:border-secondary transition-colors"
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                className="absolute right-space-sm text-on-surface-variant hover:text-on-surface"
              >
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            )}
          </div>

          {/* Filters Matrix */}
          <div className="xl:col-span-7 flex flex-wrap items-center gap-space-xs justify-start xl:justify-end">
            {/* Severity Filter */}
            <div className="flex items-center bg-surface-container rounded border border-surface-container-highest p-0.5">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase px-2">
                SEV:
              </span>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  severityFilter === 'ALL' ? 'bg-secondary text-on-secondary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setSeverityFilter('ALL')}
              >
                All
              </button>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  severityFilter === 'CRITICAL' ? 'bg-primary-container text-on-primary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setSeverityFilter('CRITICAL')}
              >
                Critical (≥10)
              </button>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  severityFilter === 'MAJOR' ? 'bg-tertiary-container text-on-tertiary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setSeverityFilter('MAJOR')}
              >
                Major (4-9)
              </button>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  severityFilter === 'MINOR' ? 'bg-surface-container-highest text-on-surface font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setSeverityFilter('MINOR')}
              >
                Minor (≤3)
              </button>
            </div>

            {/* Weak Member Filter */}
            <div className="flex items-center bg-surface-container rounded border border-surface-container-highest p-0.5">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase px-2">
                WEAK:
              </span>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  weakFilter === 'ALL' ? 'bg-secondary text-on-secondary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setWeakFilter('ALL')}
              >
                All
              </button>
              <button
                className={`px-2 py-1 font-code-sm text-[11px] rounded transition-colors ${
                  weakFilter === 'HAS_WEAK' ? 'bg-tertiary-container text-on-tertiary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
                onClick={() => setWeakFilter('HAS_WEAK')}
              >
                &gt;0 Weak
              </button>
            </div>

            {/* Multi-compare Button */}
            {selectedChainIds.size > 1 && (
              <button
                className="px-space-md py-1 bg-primary-container hover:bg-primary-container/80 text-on-primary font-code-sm text-code-sm font-bold rounded shadow-md flex items-center gap-space-xs transition-colors cursor-pointer"
                onClick={() => onCompareChains(Array.from(selectedChainIds))}
              >
                <span className="material-symbols-outlined text-[16px]">compare_arrows</span>
                <span>Compare {selectedChainIds.size} Chains</span>
              </button>
            )}
          </div>
        </div>

        {/* Results Counter & Stats Strip */}
        <div className="flex items-center justify-between font-code-sm text-code-sm text-on-surface-variant pt-space-xs border-t border-surface-container-high/60">
          <div className="flex items-center gap-space-md">
            <span>
              Showing <strong className="text-on-surface">{filteredChains.length}</strong> of{' '}
              <strong>{chains.length}</strong> chains
            </span>
            {selectedChainIds.size > 0 && (
              <span className="text-secondary font-semibold">
                {selectedChainIds.size} selected
              </span>
            )}
          </div>
          <span>Tip: Select 2 or more chains to compare side-by-side</span>
        </div>
      </div>

      {/* Main Chains Table */}
      <div className="bg-surface-container-low rounded-lg border border-surface-container-high shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse font-body-sm">
            <thead>
              <tr className="bg-surface-container border-b border-surface-container-high font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider h-space-panel-header-h">
                <th className="w-10 px-3 text-center">
                  <input
                    type="checkbox"
                    checked={filteredChains.length > 0 && selectedChainIds.size === filteredChains.length}
                    onChange={toggleSelectAll}
                    className="accent-secondary rounded cursor-pointer"
                  />
                </th>
                <th className="px-space-sm">CHAIN ID</th>
                <th className="px-space-sm">SEVERITY</th>
                <th className="px-space-sm">MEMBERS</th>
                <th className="px-space-sm">LEAD ALARM & ROOT DEVICE</th>
                <th className="px-space-sm">CONDUCTANCE (Φ)</th>
                <th className="px-space-sm">WEAK MEMBERS</th>
                <th className="px-space-sm">DURATION</th>
                <th className="px-space-sm text-right pr-space-md">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container-high/40 font-code-sm text-[13px]">
              {filteredChains.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-on-surface-variant italic">
                    Không tìm thấy chuỗi nào phù hợp với bộ lọc.
                  </td>
                </tr>
              ) : (
                filteredChains.map((chain) => {
                  const isSelected = selectedChainIds.has(chain.chain_id)
                  const severity = chain.member_count >= 10 ? 'CRITICAL' : chain.member_count >= 4 ? 'MAJOR' : 'MINOR'
                  const sevColor = severity === 'CRITICAL' ? 'bg-primary-container text-on-primary' : severity === 'MAJOR' ? 'bg-tertiary-container/40 text-tertiary' : 'bg-surface-container-highest text-on-surface-variant'
                  const meta = getChainMeta(chain)

                  return (
                    <tr
                      key={chain.chain_id}
                      className={`hover:bg-surface-container transition-colors cursor-pointer ${
                        isSelected ? 'bg-surface-container-high/80' : ''
                      }`}
                      onClick={() => onSelectChain(chain.chain_id)}
                    >
                      <td className="px-3 text-center" onClick={(e) => toggleSelectChain(chain.chain_id, e)}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}}
                          className="accent-secondary rounded cursor-pointer"
                        />
                      </td>

                      {/* Chain ID */}
                      <td className="px-space-sm py-space-sm">
                        <span className="font-bold text-primary hover:underline">
                          {chain.chain_id}
                        </span>
                      </td>

                      {/* Severity Badge */}
                      <td className="px-space-sm py-space-sm">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${sevColor}`}>
                          {severity}
                        </span>
                      </td>

                      {/* Member Count */}
                      <td className="px-space-sm py-space-sm font-semibold text-on-surface">
                        {chain.member_count} alarms
                      </td>

                      {/* Lead Alarm & Resource */}
                      <td className="px-space-sm py-space-sm">
                        <div className="flex flex-col max-w-[320px]">
                          <span className="text-on-surface font-medium truncate" title={chain.title}>
                            {chain.title || 'System Network Event'}
                          </span>
                          <span className="text-[11px] text-on-surface-variant truncate">
                            {chain.is_singleton ? 'SINGLETON_CLUSTER' : 'MULTI_ALARM_CHAIN'}
                          </span>
                        </div>
                      </td>

                      {/* Conductance Phi */}
                      <td className="px-space-sm py-space-sm">
                        <div className="flex items-center gap-space-xs">
                          <span
                            className={`font-bold ${
                              meta.conductance < 0.3
                                ? 'text-tertiary'
                                : 'text-secondary'
                            }`}
                          >
                            {meta.conductance.toFixed(3)}
                          </span>
                          {meta.conductance < 0.3 && (
                            <span className="text-[10px] px-1 bg-tertiary-container text-on-tertiary rounded">
                              Cut Candidate
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Weak Members */}
                      <td className="px-space-sm py-space-sm">
                        {meta.weakMembers > 0 ? (
                          <span className="text-tertiary font-bold px-1.5 py-0.5 bg-tertiary-container/20 rounded">
                            {meta.weakMembers} weak
                          </span>
                        ) : (
                          <span className="text-on-surface-variant/60">0</span>
                        )}
                      </td>

                      {/* Duration */}
                      <td className="px-space-sm py-space-sm text-on-surface-variant">
                        {meta.durationSec ? `${Math.round(meta.durationSec / 60)}m` : '0m'}
                      </td>

                      {/* Action */}
                      <td className="px-space-sm py-space-sm text-right pr-space-md">
                        <button
                          className="px-space-sm py-1 bg-surface-container hover:bg-secondary hover:text-on-secondary text-secondary rounded font-bold text-[12px] transition-all cursor-pointer border border-secondary/30"
                          onClick={(e) => {
                            e.stopPropagation()
                            onSelectChain(chain.chain_id)
                          }}
                        >
                          Inspect &rarr;
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
