interface ContextRibbonProps {
  datasetName?: string
  snapshotId?: string
  totalAlarms?: number
  totalChains?: number
  singletonsCount?: number
  topologyChainsCount?: number
}

export function ContextRibbon({
  datasetName = 'IT_SERVICES',
  snapshotId = 'S102 / v1',
  totalAlarms = 8714,
  totalChains = 2824,
  singletonsCount = 2072,
  topologyChainsCount = 611,
}: ContextRibbonProps) {
  return (
    <div className="w-full bg-surface-container-lowest px-space-lg py-space-sm shadow-md border-b border-surface-container-high/40">
      <div className="flex flex-wrap items-center justify-between gap-space-md">
        {/* Left: Dataset & Specifiers */}
        <div className="flex flex-wrap items-center gap-space-md">
          <div className="flex items-center gap-space-xs bg-surface-container px-space-sm py-space-2xs rounded border border-surface-container-highest">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">DATASET</span>
            <span className="font-code-sm text-code-sm text-secondary font-bold">{datasetName}</span>
          </div>
          <div className="flex items-center gap-space-xs bg-surface-container px-space-sm py-space-2xs rounded border border-surface-container-highest">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">SNAPSHOT</span>
            <span className="font-code-sm text-code-sm text-primary font-bold">{snapshotId}</span>
          </div>
          <div className="flex items-center gap-space-xs text-on-surface-variant font-code-sm text-code-sm">
            <span className="material-symbols-outlined text-secondary text-[15px]">analytics</span>
            <span className="text-on-surface font-semibold">{totalAlarms.toLocaleString()} alarms</span>
            <span>•</span>
            <span className="text-on-surface font-semibold">{totalChains.toLocaleString()} chains</span>
            <span>•</span>
            <span className="text-tertiary font-semibold">{singletonsCount.toLocaleString()} singletons</span>
          </div>
        </div>

        {/* Right: Live System Status Indicator */}
        <div className="flex items-center gap-space-sm font-code-sm text-code-sm text-on-surface-variant">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary"></span>
          </span>
          <span className="text-on-surface font-medium">NOC Ingest Engine Online</span>
          <span className="text-surface-container-highest">|</span>
          <span>Buffer Lag: &lt;12ms</span>
        </div>
      </div>

      {/* System Capability Strip */}
      <div className="mt-space-sm pt-space-xs border-t border-surface-container/60 flex flex-wrap items-center gap-space-md font-code-sm text-[12px] text-on-surface-variant">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">
          System Capabilities:
        </span>
        <div className="flex items-center gap-1.5" title="Mô hình tương đồng lịch sử và bộ nhớ chuỗi">
          <span className="w-2 h-2 rounded-full bg-secondary"></span>
          <span>Pattern Memory:</span>
          <span className="text-on-surface font-semibold">Available</span>
        </div>
        <div className="flex items-center gap-1.5" title="Phân tích độ gần thời gian cửa sổ trượt (khống chế O(N))">
          <span className="w-2 h-2 rounded-full bg-secondary"></span>
          <span>Temporal Proximity:</span>
          <span className="text-on-surface font-semibold">Available (Window 15m)</span>
        </div>
        <div className="flex items-center gap-1.5" title="Ánh xạ topo mạng IP và tầng dịch vụ CNTT">
          <span className="w-2 h-2 rounded-full bg-tertiary"></span>
          <span>Topology Mapping:</span>
          <span className="text-tertiary font-semibold">Partial ({topologyChainsCount} Chains)</span>
        </div>
        <div className="flex items-center gap-1.5" title="Xác thực đồ thị phụ thuộc nghiệp vụ">
          <span className="w-2 h-2 rounded-full bg-secondary"></span>
          <span>Dependency Direction:</span>
          <span className="text-on-surface font-semibold">Service Graph</span>
        </div>
        <div className="flex items-center gap-1.5" title="Chế độ bảo vệ an toàn khi chưa có nhãn ground-truth">
          <span className="w-2 h-2 rounded-full bg-outline"></span>
          <span>Counterfactual Policy:</span>
          <span className="text-on-surface-variant font-semibold">Safe Baseline (SYNTHETIC_ONLY)</span>
        </div>
      </div>
    </div>
  )
}
