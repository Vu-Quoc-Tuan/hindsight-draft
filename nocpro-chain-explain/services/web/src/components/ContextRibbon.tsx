import { useState } from 'react'

/**
 * Tiny tooltip: renders a `?` circle that shows a popup on hover/click.
 */
function InfoTip({ text }: { text: string }) {
  const [visible, setVisible] = useState(false)

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onClick={(e) => { e.stopPropagation(); setVisible((v) => !v) }}
    >
      <span className="w-4 h-4 rounded-full bg-surface-container-highest/70 text-on-surface-variant flex items-center justify-center text-[10px] font-bold cursor-help select-none hover:bg-surface-container-highest hover:text-on-surface transition-colors">
        ?
      </span>
      {visible && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-52 px-2.5 py-2 bg-surface-container-highest text-on-surface text-[11px] font-body-sm rounded-md shadow-lg border border-surface-container-high/50 z-50 leading-relaxed pointer-events-none animate-fadeIn">
          {text}
        </span>
      )}
    </span>
  )
}

type CapStatus = 'ready' | 'partial' | 'baseline'

interface CapItem {
  label: string
  status: CapStatus
  value: string
  tip: string
}

const CAPS: CapItem[] = [
  {
    label: 'Pattern Memory',
    status: 'ready',
    value: 'Available',
    tip: 'Mô hình tương đồng lịch sử và bộ nhớ chuỗi đã kích hoạt.',
  },
  {
    label: 'Temporal Proximity',
    status: 'ready',
    value: 'Window 15m',
    tip: 'Phân tích độ gần thời gian cửa sổ trượt (sliding window ΔT). Khống chế tuyến tính O(N).',
  },
  {
    label: 'Topology',
    status: 'partial',
    value: 'Partial',
    tip: 'Ánh xạ topo mạng IP và tầng dịch vụ CNTT. Chưa phủ 100% chuỗi — chỉ khả dụng khi có dữ liệu NetBox CMDB.',
  },
  {
    label: 'Dependency',
    status: 'ready',
    value: 'Service Graph',
    tip: 'Xác thực đồ thị phụ thuộc nghiệp vụ. Phân biệt IP adjacency (vô hướng) với service dependency (có hướng).',
  },
  {
    label: 'Counterfactual',
    status: 'baseline',
    value: 'Safe Baseline',
    tip: 'Chế độ bảo vệ an toàn khi chưa có nhãn ground-truth toán tử. Tham số dùng DOCUMENTED_DEFAULT, chưa calibrate từ production.',
  },
]

const statusDot: Record<CapStatus, string> = {
  ready: 'bg-secondary',
  partial: 'bg-tertiary',
  baseline: 'bg-outline',
}

const statusText: Record<CapStatus, string> = {
  ready: 'text-on-surface',
  partial: 'text-tertiary',
  baseline: 'text-on-surface-variant',
}

interface ContextRibbonProps {
  datasetName?: string
  snapshotId?: string
  totalAlarms?: number
  totalChains?: number
}

export function ContextRibbon({
  datasetName = 'IT_SERVICES',
  snapshotId = 'S102 / v1',
  totalAlarms = 8714,
  totalChains = 2824,
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
          </div>
        </div>

        {/* Right: Live Engine Status */}
        <div className="flex items-center gap-space-sm font-code-sm text-code-sm text-on-surface-variant">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary"></span>
          </span>
          <span className="text-on-surface font-medium">Engine Online</span>
        </div>
      </div>

      {/* Capability Dots – compact with ? tooltip */}
      <div className="mt-space-xs pt-space-xs border-t border-surface-container/60 flex flex-wrap items-center gap-space-md font-code-sm text-[12px] text-on-surface-variant">
        {CAPS.map((cap) => (
          <div key={cap.label} className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${statusDot[cap.status]}`}></span>
            <span>{cap.label}:</span>
            <span className={`font-semibold ${statusText[cap.status]}`}>{cap.value}</span>
            <InfoTip text={cap.tip} />
          </div>
        ))}
      </div>
    </div>
  )
}
