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
  // If no chain is selected, top-level navigation is handled by NocHeader
  if (!selectedChainId) {
    return null
  }

  return (
    <div className="w-full bg-surface-container-low px-space-lg flex items-center justify-between shadow-xs border-b border-surface-container-high/40 overflow-x-auto select-none">
      <div className="flex items-center gap-space-xs">
        {/* Return button */}
        <button
          className="mr-space-sm px-space-sm py-2 font-code-sm text-code-sm text-on-surface-variant hover:text-on-surface flex items-center gap-space-xs transition-colors cursor-pointer"
          onClick={onClearSelectedChain}
          title="Quay lại danh sách chuỗi"
        >
          <span className="material-symbols-outlined text-[16px]">arrow_back</span>
          <span className="font-bold text-secondary">Chains</span>
        </button>

        <span className="h-4 w-px bg-surface-container-highest mr-space-xs" />

        {/* Active Chain Badge */}
        <div className="flex items-center gap-space-xs bg-surface-container-high px-space-sm py-1 rounded mr-space-md border border-secondary/30">
          <span className="font-label-caps text-label-caps text-secondary uppercase font-bold">CHAIN:</span>
          <span className="font-code-sm text-code-sm text-primary font-bold">{selectedChainId}</span>
        </div>

        {/* Chain-level clean tabs without mockup numbers */}
        <button
          className={`px-space-md py-2 font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
            currentTab === 'chain-overview'
              ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
              : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('chain-overview')}
        >
          <span className="material-symbols-outlined text-[16px]">hub</span>
          <span>Overview</span>
        </button>

        <button
          className={`px-space-md py-2 font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
            currentTab === 'why'
              ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
              : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('why')}
        >
          <span className="material-symbols-outlined text-[16px]">psychology</span>
          <span>WHY Grouped</span>
        </button>

        <button
          className={`px-space-md py-2 font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
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
          className={`px-space-md py-2 font-body-sm text-body-sm flex items-center gap-space-xs transition-colors cursor-pointer border-b-2 ${
            currentTab === 'structure'
              ? 'border-secondary text-secondary bg-surface-container-high font-semibold'
              : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('structure')}
        >
          <span className="material-symbols-outlined text-[16px]">account_tree</span>
          <span>Audit & Structure</span>
        </button>
      </div>
    </div>
  )
}
