export type SubNavTab =
  | 'snapshot-overview'
  | 'chains-explorer'
  | 'multi-chain-timeline'
  | 'compare-chains'
  | 'chain-overview'
  | 'why'
  | 'members'
  | 'structure'
  | 'review'
  | 'evolution'
  | 'topology'

interface SubNavBarProps {
  currentTab: SubNavTab
  onSelectTab: (tab: SubNavTab) => void
  selectedChainId?: string | null
  onClearSelectedChain?: () => void
}

export function SubNavBar({
  currentTab,
  onSelectTab,
  selectedChainId,
  onClearSelectedChain,
}: SubNavBarProps) {
  return (
    <div className="w-full bg-surface-container-low px-space-lg flex items-center justify-between shadow-sm border-b border-surface-container-high/40 overflow-x-auto">
      <div className="flex items-center gap-space-xs">
        {selectedChainId ? (
          <>
            {/* Chain Breadcrumb / Return button */}
            <button
              className="mr-space-sm px-space-sm py-space-sm font-code-sm text-code-sm text-on-surface-variant hover:text-on-surface flex items-center gap-space-xs transition-colors cursor-pointer"
              onClick={onClearSelectedChain}
              title="Quay lại danh sách chuỗi"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
              <span className="font-bold text-secondary">Chains</span>
            </button>
            <span className="h-4 w-px bg-surface-container-highest mr-space-xs" />

            {/* Active Chain Badge */}
            <div className="flex items-center gap-space-xs bg-surface-container-high px-space-sm py-1 rounded mr-space-md border border-secondary/30">
              <span className="font-label-caps text-label-caps text-secondary uppercase">CHAIN:</span>
              <span className="font-code-sm text-code-sm text-primary font-bold">{selectedChainId}</span>
            </div>

            {/* Chain Level Tabs */}
            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'chain-overview'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('chain-overview')}
            >
              <span className="material-symbols-outlined text-[16px]">overview</span>
              <span>Overview</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'why'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('why')}
            >
              <span className="material-symbols-outlined text-[16px]">psychology</span>
              <span>WHY Grouped (Tier 1B)</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'members'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('members')}
            >
              <span className="material-symbols-outlined text-[16px]">table_rows</span>
              <span>Member Diagnostics</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'structure'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('structure')}
            >
              <span className="material-symbols-outlined text-[16px]">account_tree</span>
              <span>Audit & Structure</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'review'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('review')}
            >
              <span className="material-symbols-outlined text-[16px]">alt_route</span>
              <span>14 - Recommendations</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'evolution'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('evolution')}
            >
              <span className="material-symbols-outlined text-[16px]">timeline</span>
              <span>15-16 - Evolution</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'topology'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('topology')}
            >
              <span className="material-symbols-outlined text-[16px]">lan</span>
              <span>17 - Topology</span>
            </button>
          </>
        ) : (
          <>
            {/* Snapshot Level Tabs */}
            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'snapshot-overview'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('snapshot-overview')}
            >
              <span className="material-symbols-outlined text-[16px]">dashboard</span>
              <span>Snapshot Overview</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'chains-explorer'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('chains-explorer')}
            >
              <span className="material-symbols-outlined text-[16px]">hub</span>
              <span>Chains Explorer</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'multi-chain-timeline'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('multi-chain-timeline')}
            >
              <span className="material-symbols-outlined text-[16px]">timeline</span>
              <span>Multi-Chain Timeline</span>
            </button>

            <button
              className={`px-space-md py-space-sm font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
                currentTab === 'compare-chains'
                  ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
              onClick={() => onSelectTab('compare-chains')}
            >
              <span className="material-symbols-outlined text-[16px]">compare_arrows</span>
              <span>Compare Chains</span>
            </button>
          </>
        )}
      </div>

      {selectedChainId && (
        <div className="flex items-center gap-space-sm font-code-sm text-[12px] text-on-surface-variant py-1">
          <span>Tier-1B / Tier-2 Active</span>
        </div>
      )}
    </div>
  )
}
