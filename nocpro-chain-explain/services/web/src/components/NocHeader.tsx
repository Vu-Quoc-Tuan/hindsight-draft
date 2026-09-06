interface NocHeaderProps {
  datasetName?: string
  snapshotId?: string
  totalAlarms?: number
  totalChains?: number
  currentView: string
  onNavigate: (view: string) => void
  viewMode: 'operator' | 'research'
  onToggleViewMode: (mode: 'operator' | 'research') => void
  onOpenSettings: () => void
  onOpenAIAnalyst: () => void
  attentionCount?: number
  onOpenAttentionCenter?: () => void
}

export function NocHeader({
  datasetName = 'IT_SERVICES',
  snapshotId = 'S102 / v1',
  totalAlarms = 8714,
  totalChains = 2824,
  currentView,
  onNavigate,
  viewMode,
  onToggleViewMode,
  onOpenSettings,
  onOpenAIAnalyst,
  attentionCount = 3,
  onOpenAttentionCenter,
}: NocHeaderProps) {
  return (
    <header className="fixed top-0 w-full z-50 bg-surface-container-lowest/95 backdrop-blur-md shadow-[0_1px_8px_rgba(0,0,0,0.45)] border-b border-surface-container-high/60">
      <div className="h-16 w-full px-space-lg flex items-center justify-between">
        {/* Left: Brand, Snapshot Info, and Metrics */}
        <div className="flex items-center gap-space-md">
          <div
            className="flex items-center gap-space-sm cursor-pointer"
            onClick={() => onNavigate('snapshot-overview')}
          >
            <div className="w-8 h-8 rounded bg-primary-container flex items-center justify-center font-headline-md font-bold text-on-primary-container shadow-sm">
              <span className="material-symbols-outlined text-[20px]">hub</span>
            </div>
            <div className="flex flex-col">
              <span className="font-headline-md text-[16px] font-bold text-on-surface leading-tight tracking-tight">
                Viettel NocPro Hindsight
              </span>
              <span className="font-code-sm text-[11px] text-on-surface-variant font-medium">
                Mission-Critical Root-Cause & Chain Audit
              </span>
            </div>
          </div>

          <span className="h-6 w-px bg-surface-container-highest ml-space-xs hidden md:block" />

          <div className="hidden lg:flex items-center gap-space-xs font-code-sm text-code-sm text-on-surface-variant">
            <span className="text-secondary font-bold">{datasetName}</span>
            <span>/</span>
            <span className="text-primary font-bold">{snapshotId}</span>
            <span>•</span>
            <span className="text-on-surface font-semibold">{totalAlarms.toLocaleString()} alarms</span>
            <span>·</span>
            <span className="text-on-surface font-semibold">{totalChains.toLocaleString()} chains</span>
          </div>

          <span className="px-space-xs py-0.5 bg-surface-container rounded border border-surface-container-highest font-code-sm text-[11px] text-secondary font-medium hidden xl:inline-block">
            [2 Ready · 1 Partial · 2 Baseline]
          </span>
        </div>

        {/* Center: Global Navigation Links */}
        <nav className="flex items-center gap-space-xs">
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'snapshot-overview'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('snapshot-overview')}
          >
            Overview
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'chains-explorer' || currentView === 'chain-detail'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('chains-explorer')}
          >
            Chains Explorer
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'multi-chain-timeline'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('multi-chain-timeline')}
          >
            Timeline
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'compare-chains'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('compare-chains')}
          >
            Compare
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'topology'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('topology')}
          >
            Topology
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all ${
              currentView === 'evolution'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('evolution')}
          >
            Evolution
          </button>
        </nav>

        {/* Right: Controls, Toggles, Drawer and Settings */}
        <div className="flex items-center gap-space-sm">
          {/* Attention Center Button */}
          <button
            className="relative flex items-center gap-space-xs px-space-sm py-1 bg-surface-container hover:bg-surface-container-high rounded text-on-surface transition-colors cursor-pointer text-code-sm"
            onClick={onOpenAttentionCenter}
            title="Trung tâm cảnh báo cần chú ý"
          >
            <span className="material-symbols-outlined text-tertiary text-[16px]">notifications_active</span>
            <span className="hidden sm:inline font-semibold">Attention</span>
            <span className="px-1.5 py-0.2 bg-tertiary-container text-on-tertiary font-bold rounded-full text-[10px]">
              {attentionCount}
            </span>
          </button>

          {/* AI Analyst Drawer Trigger */}
          <button
            className="flex items-center gap-space-xs px-space-sm py-1 bg-primary-container/20 hover:bg-primary-container/30 text-primary-fixed rounded transition-colors cursor-pointer text-code-sm font-semibold border border-primary-container/30"
            onClick={onOpenAIAnalyst}
            title="Mở trợ lý AI Analyst Streaming"
          >
            <span className="material-symbols-outlined text-[16px] text-primary">auto_awesome</span>
            <span className="hidden sm:inline">AI Analyst</span>
          </button>

          {/* View Mode Switcher: Operator vs Research */}
          <div className="hidden md:flex items-center p-0.5 bg-surface-container rounded border border-surface-container-highest">
            <button
              className={`px-space-sm py-0.5 font-label-caps text-label-caps uppercase rounded transition-all ${
                viewMode === 'operator'
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-xs'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
              onClick={() => onToggleViewMode('operator')}
            >
              Operator
            </button>
            <button
              className={`px-space-sm py-0.5 font-label-caps text-label-caps uppercase rounded transition-all ${
                viewMode === 'research'
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-xs'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
              onClick={() => onToggleViewMode('research')}
            >
              Research
            </button>
          </div>

          {/* Settings Button */}
          <button
            className="w-8 h-8 rounded bg-surface-container hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer border border-surface-container-highest"
            onClick={onOpenSettings}
            title="Cài đặt tham số & Hiệu chuẩn (Settings)"
          >
            <span className="material-symbols-outlined text-[18px]">settings</span>
          </button>
        </div>
      </div>
    </header>
  )
}
