import { InfoTip } from './InfoTip'

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

export function ContextRibbon() {
  return (
    <div className="w-full bg-surface-container-lowest px-space-lg py-2 shadow-xs border-b border-surface-container-high/40 flex flex-wrap items-center justify-between gap-space-sm text-[12px] font-code-sm text-on-surface-variant">
      {/* Capability Dots – compact with ? tooltip */}
      <div className="flex flex-wrap items-center gap-space-md">
        <span className="font-label-caps uppercase text-on-surface-variant/70 text-[10px] font-bold tracking-wider">
          System Capabilities:
        </span>
        {CAPS.map((cap) => (
          <div key={cap.label} className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${statusDot[cap.status]}`}></span>
            <span>{cap.label}:</span>
            <span className={`font-semibold ${statusText[cap.status]}`}>{cap.value}</span>
            <InfoTip text={cap.tip} />
          </div>
        ))}
      </div>

      {/* Right: Live Engine Status */}
      <div className="flex items-center gap-1.5 text-on-surface-variant text-[11px]">
        <span className="flex h-2 w-2 relative">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary"></span>
        </span>
        <span className="text-on-surface font-medium">Engine Online</span>
      </div>
    </div>
  )
}
