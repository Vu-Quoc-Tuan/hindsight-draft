export type SubNavTab =
  | 'snapshots-overview'
  | 'snapshot-overview'
  | 'all-chains'
  | 'review-history'
  | 'chain-overview'
  | 'why'
  | 'members'
  | 'structure'
  | 'review'
  | 'evolution'
  | 'topology'
  | 'validation'

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
  // If no chain is selected OR if on a snapshot-level view, top-level navigation is active in NocHeader
  const isSnapshotLevel = (
    currentTab === 'snapshots-overview' ||
    currentTab === 'snapshot-overview' ||
    currentTab === 'all-chains' ||
    currentTab === 'review-history'
  )
  if (!selectedChainId || isSnapshotLevel) {
    return null
  }

  return (
    <div
      style={{ backgroundColor: '#141b2b' }}
      className="sticky top-16 z-20 w-full px-space-lg flex items-center justify-between shadow-md border-b border-surface-container-high/60 overflow-x-auto select-none py-1"
    >
      <div className="flex items-center gap-space-xs shrink-0">
        {/* Return to the active snapshot overview */}
        <button
          className="mr-space-xs px-2.5 py-1.5 font-code-sm text-code-sm text-on-surface-variant hover:text-on-surface bg-surface-container hover:bg-surface-container-high rounded flex items-center gap-1 transition-colors cursor-pointer border border-surface-container-highest"
          onClick={onClearSelectedChain}
          title="Quay lại Overview của snapshot đang mở"
        >
          <span className="material-symbols-outlined text-[16px]">arrow_back</span>
          <span className="font-bold text-secondary">Overview</span>
        </button>

        <span className="h-4 w-px bg-surface-container-highest mr-space-xs" />

        {/* Active Chain Pill */}
        <div className="flex items-center gap-space-xs bg-surface-container-high px-2.5 py-1 rounded mr-space-xs border border-secondary/30">
          <span className="font-label-caps text-label-caps text-secondary uppercase font-bold">CHAIN:</span>
          <span className="font-code-sm text-code-sm text-primary font-bold">{selectedChainId}</span>
        </div>

        <span className="h-4 w-px bg-surface-container-highest mr-space-xs" />

        {/* 05 Chain Overview */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'chain-overview'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('chain-overview')}
        >
          <span className="material-symbols-outlined text-[15px]">hub</span>
          <span>Overview</span>
        </button>

        {/* 06 Timeline & Evolution (Moved up to observation group with clearer name) */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'evolution'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('evolution')}
          title="Tiến trình thời gian xuất hiện cảnh báo (T0, Arrival Velocity) & Vòng đời sự cố"
        >
          <span className="material-symbols-outlined text-[15px]">timeline</span>
          <span>Timeline &amp; Evolution</span>
        </button>

        {/* 07 Topology (Moved up to network observation group) */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'topology'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('topology')}
          title="Sơ đồ chiếu mạng và tương quan topo"
        >
          <span className="material-symbols-outlined text-[15px]">lan</span>
          <span>Topology</span>
        </button>

        {/* 08 WHY */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'why'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('why')}
        >
          <span className="material-symbols-outlined text-[15px]">psychology</span>
          <span>WHY</span>
        </button>

        {/* 09 Member Diagnostics */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'members'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('members')}
        >
          <span className="material-symbols-outlined text-[15px]">table_rows</span>
          <span>Members</span>
        </button>

        {/* 10 Audit & Structure */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'structure'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('structure')}
        >
          <span className="material-symbols-outlined text-[15px]">account_tree</span>
          <span>Audit &amp; Structure</span>
        </button>

        {/* 11 Recommendations & Validation (Final Action: Counterfactual Review + Sign-off) */}
        <button
          className={`px-3 py-1.5 font-body-sm text-xs rounded-md flex items-center gap-1.5 transition-all cursor-pointer font-medium ${
            currentTab === 'review' || currentTab === 'validation'
              ? 'bg-secondary text-surface-container-lowest font-bold shadow-xs'
              : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
          }`}
          onClick={() => onSelectTab('review')}
          title="Đề xuất đối chứng Counterfactual & Phê duyệt vận hành (Operator Sign-off)"
        >
          <span className="material-symbols-outlined text-[15px]">verified_user</span>
          <span>Recommendations &amp; Validation</span>
        </button>
      </div>
    </div>
  )
}
