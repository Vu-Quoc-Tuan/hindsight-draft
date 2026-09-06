import { useState } from 'react'
import { HindsightLogo } from './HindsightLogo'

type AlarmCategory = 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'

interface AlarmSnapshotItem {
  id: string
  name: string
  time: string
  alarms: string
  isLatestDb?: boolean
  tag?: string
}

const ALARM_SETS_BY_CATEGORY: Record<
  AlarmCategory,
  {
    categoryName: string
    shortLabel: string
    icon: string
    desc: string
    items: AlarmSnapshotItem[]
  }
> = {
  IP_NETWORK: {
    categoryName: 'IP_NETWORK',
    shortLabel: 'IP Network',
    icon: 'hub',
    desc: 'Hạ tầng mạng IP Core, MPLS, Router Metro',
    items: [
      {
        id: 'real_alarm_20260801',
        name: 'real_alarm_20260801',
        time: '10:00 — 12:00 UTC',
        alarms: '8,714 alarms · S102',
        isLatestDb: true,
        tag: 'Gần nhất từ PostgreSQL',
      },
      {
        id: 'real_alarm_20260802',
        name: 'real_alarm_20260802',
        time: '08:00 — 10:00 UTC',
        alarms: '9,102 alarms · S103',
        tag: 'Ca trực 02/08',
      },
      {
        id: 'ip_core_cascade_s101',
        name: 'ip_core_cascade_s101',
        time: '00:00 — 02:00 UTC',
        alarms: '12,450 alarms · S101',
        tag: 'Bão Router Core',
      },
    ],
  },
  IT_SERVICES: {
    categoryName: 'IT_SERVICES',
    shortLabel: 'IT Services',
    icon: 'dns',
    desc: 'Dịch vụ CNTT, Kubernetes, Cloud Platform',
    items: [
      {
        id: 'it_k8s_surge_20260801',
        name: 'it_k8s_surge_20260801',
        time: '09:30 — 11:30 UTC',
        alarms: '5,420 alarms · K8s',
        tag: 'Ingress 504 Gateway',
      },
      {
        id: 'it_db_failover_20260802',
        name: 'it_db_failover_20260802',
        time: '04:00 — 06:00 UTC',
        alarms: '3,180 alarms · DB',
        tag: 'Postgres Failover',
      },
      {
        id: 'it_cloud_down_s101',
        name: 'it_cloud_down_s101',
        time: '01:00 — 03:00 UTC',
        alarms: '4,890 alarms · Pods',
        tag: 'Cloud Node Drain',
      },
    ],
  },
  ALARM_ONLY: {
    categoryName: 'ALARM_ONLY',
    shortLabel: 'Alarm Only',
    icon: 'notifications_active',
    desc: 'Cảnh báo viễn thông thuần túy, không topo',
    items: [
      {
        id: 'telecom_raw_20260801',
        name: 'telecom_raw_20260801',
        time: '10:00 — 12:00 UTC',
        alarms: '15,200 alarms · Raw',
        tag: 'Raw Stream',
      },
      {
        id: 'synthetic_incident_s101',
        name: 'synthetic_incident_s101',
        time: '00:00 — 02:00 UTC',
        alarms: '8,900 alarms · Test',
        tag: 'Mô phỏng đứt cáp',
      },
    ],
  },
}

interface NocHeaderProps {
  datasetName: string
  snapshotId: string
  currentView: string
  onNavigate: (view: string) => void
  onOpenSettings: () => void
  onChangeDatasetProfile?: (profile: 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES') => void
  onChangeSnapshot?: (snapshot: string) => void
}

export function NocHeader({
  datasetName,
  snapshotId,
  currentView,
  onNavigate,
  onOpenSettings,
  onChangeDatasetProfile,
  onChangeSnapshot,
}: NocHeaderProps) {
  const [isSelectorOpen, setSelectorOpen] = useState(false)
  const [userSelectedCategory, setUserSelectedCategory] = useState<AlarmCategory | null>(null)

  const activeCategory: AlarmCategory = userSelectedCategory ?? (
    (datasetName as AlarmCategory) in ALARM_SETS_BY_CATEGORY
      ? (datasetName as AlarmCategory)
      : 'IP_NETWORK'
  )

  return (
    <header
      style={{ backgroundColor: '#070e1d' }}
      className="sticky top-0 w-full z-30 shadow-[0_1px_8px_rgba(0,0,0,0.45)] border-b border-surface-container-high/60"
    >
      <div className="h-16 w-full px-space-lg flex items-center justify-between">
        {/* Left: Brand, Snapshot Info, and Metrics */}
        <div className="flex items-center gap-space-md">
          <div
            className="flex items-center gap-space-sm cursor-pointer group"
            onClick={() => onNavigate('snapshot-overview')}
            title="Hindsight - See the bigger picture behind alarm chains"
          >
            <HindsightLogo size={36} />
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-headline-md text-[17px] font-extrabold text-on-surface leading-tight tracking-tight group-hover:text-primary transition-colors">
                  Hindsight
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-primary/15 text-primary border border-primary/25 tracking-wider uppercase font-code-sm">
                  NOCPRO
                </span>
              </div>
              <span className="font-code-sm text-[11px] text-on-surface-variant font-medium tracking-tight">
                See the bigger picture behind alarm chains
              </span>
            </div>
          </div>

          <span className="h-6 w-px bg-surface-container-highest ml-space-xs hidden md:block" />

          {/* Dataset & Snapshot Selector Dropdown */}
          <div className="relative hidden lg:block">
            <button
              onClick={() => setSelectorOpen(!isSelectorOpen)}
              className={`flex items-center gap-1.5 font-code-sm text-xs px-2.5 py-1 rounded-md border transition-all cursor-pointer select-none ${
                isSelectorOpen
                  ? 'bg-[#14223b] border-secondary text-on-surface shadow-[0_0_8px_rgba(56,189,248,0.25)] ring-1 ring-secondary/30'
                  : 'bg-[#0f1728] hover:bg-[#152238] border-[#22314d] hover:border-[#344870] text-on-surface'
              }`}
              title="Chọn tập cảnh báo cần khảo sát"
            >
              <span className="material-symbols-outlined text-[15px] text-secondary">
                {ALARM_SETS_BY_CATEGORY[activeCategory]?.icon || 'hub'}
              </span>
              <span className="text-secondary font-bold tracking-tight">{datasetName}</span>
              <span className="text-[#3c4e6e] font-light">/</span>
              <span className="text-primary font-semibold tracking-tight">{snapshotId}</span>
              {snapshotId === 'real_alarm_20260801' && (
                <span
                  className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5"
                  title="Gần nhất từ PostgreSQL"
                />
              )}
              <span className="material-symbols-outlined text-[15px] text-on-surface-variant ml-0.5">
                {isSelectorOpen ? 'arrow_drop_up' : 'arrow_drop_down'}
              </span>
            </button>

            {/* Click-outside backdrop */}
            {isSelectorOpen && (
              <div
                className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[0.5px]"
                onClick={() => setSelectorOpen(false)}
              />
            )}

            {/* Compact 2-tier Alarm Scope Selector Popover */}
            {isSelectorOpen && (
              <div
                style={{ backgroundColor: '#0c1322' }}
                className="absolute top-full left-0 mt-1.5 w-[330px] border border-[#24324d] rounded-xl shadow-[0_20px_40px_-8px_rgba(0,0,0,0.95)] z-50 flex flex-col overflow-hidden animate-scaleUp text-on-surface"
              >
                {/* Popover Header */}
                <div
                  style={{ backgroundColor: '#070c17' }}
                  className="px-3 py-2 border-b border-[#1b273e] flex items-center justify-between"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[15px] text-secondary">tune</span>
                    <span className="font-code-sm text-[11px] uppercase tracking-wider font-bold text-on-surface">
                      Tập Cảnh Báo Khảo Sát
                    </span>
                  </div>
                  <button
                    onClick={() => setSelectorOpen(false)}
                    className="text-on-surface-variant hover:text-on-surface text-sm cursor-pointer px-1"
                  >
                    ✕
                  </button>
                </div>

                <div className="p-2.5 flex flex-col gap-2">
                  {/* Tier 1: 3 Category Segmented Tabs */}
                  <div className="grid grid-cols-3 gap-1 p-0.5 bg-[#070c17] rounded-lg border border-[#1b273e]">
                    {(['IP_NETWORK', 'IT_SERVICES', 'ALARM_ONLY'] as const).map((cat) => {
                      const isCatActive = activeCategory === cat
                      return (
                        <button
                          key={cat}
                          onClick={() => setUserSelectedCategory(cat)}
                          className={`py-1.5 px-1 rounded-md text-center transition-all cursor-pointer flex flex-col items-center gap-0.5 ${
                            isCatActive
                              ? 'bg-[#14243b] text-secondary font-bold shadow-sm border border-secondary/40'
                              : 'text-on-surface-variant hover:text-on-surface hover:bg-[#0e1728]'
                          }`}
                        >
                          <span className="material-symbols-outlined text-[15px]">
                            {ALARM_SETS_BY_CATEGORY[cat].icon}
                          </span>
                          <span className="text-[10px] font-code-sm truncate max-w-full">
                            {ALARM_SETS_BY_CATEGORY[cat].shortLabel}
                          </span>
                        </button>
                      )
                    })}
                  </div>

                  <div className="px-1 text-[10px] text-on-surface-variant/80 italic">
                    {ALARM_SETS_BY_CATEGORY[activeCategory].desc}
                  </div>

                  {/* Tier 2: Dãy alarm của loại đang chọn */}
                  <div className="flex flex-col gap-1 mt-0.5">
                    <div className="flex items-center justify-between text-[10px] font-label-caps uppercase text-on-surface-variant px-1">
                      <span>Dãy alarm ({ALARM_SETS_BY_CATEGORY[activeCategory].shortLabel})</span>
                      <span className="text-secondary font-code-sm font-semibold">
                        {ALARM_SETS_BY_CATEGORY[activeCategory].items.length} tập
                      </span>
                    </div>

                    {ALARM_SETS_BY_CATEGORY[activeCategory].items.map((item) => {
                      const isSelected = snapshotId === item.id && datasetName === activeCategory
                      return (
                        <button
                          key={item.id}
                          onClick={() => {
                            onChangeDatasetProfile?.(activeCategory)
                            onChangeSnapshot?.(item.id)
                            setSelectorOpen(false)
                            setUserSelectedCategory(null)
                          }}
                          style={{ backgroundColor: isSelected ? '#162842' : '#0e1728' }}
                          className={`p-2 rounded-lg text-left flex items-center justify-between gap-2 border transition-all cursor-pointer ${
                            isSelected
                              ? 'border-secondary/60 shadow-[0_0_8px_rgba(56,189,248,0.2)] ring-1 ring-secondary/30'
                              : 'border-[#1b273e] hover:bg-[#142036] hover:border-[#2d3e5e]'
                          }`}
                        >
                          <div className="flex flex-col min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className={`font-code-sm text-xs font-bold truncate ${isSelected ? 'text-secondary' : 'text-on-surface'}`}>
                                {item.name}
                              </span>
                              {item.isLatestDb && (
                                <span className="text-[9px] font-code-sm px-1 py-0.2 rounded bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30 flex items-center gap-1">
                                  <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
                                  PostgreSQL
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-on-surface-variant font-code-sm mt-0.5">
                              {item.time} · {item.alarms}
                            </span>
                          </div>

                          <div className="shrink-0">
                            {isSelected ? (
                              <span className="material-symbols-outlined text-[16px] text-secondary font-bold">
                                check_circle
                              </span>
                            ) : (
                              <span className="w-3.5 h-3.5 rounded-full border border-[#2d3e5e] block" />
                            )}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Popover Footer */}
                <div
                  style={{ backgroundColor: '#070c17' }}
                  className="px-3 py-1.5 border-t border-[#1b273e] flex items-center justify-between text-[10px] text-on-surface-variant font-code-sm"
                >
                  <span className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span>Mặc định nạp tập mới nhất từ DB</span>
                  </span>
                  <span className="text-secondary font-bold">NOCPRO</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center: Global Navigation Links (Snapshot Level Only: 01 Overview, 02 Chains, 03 Timeline, 04 Compare) */}
        <nav className="flex items-center gap-space-xs">
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all cursor-pointer ${
              currentView === 'snapshot-overview'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('snapshot-overview')}
          >
            Overview
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all cursor-pointer ${
              currentView === 'chains-explorer'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('chains-explorer')}
          >
            Chains Explorer
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all cursor-pointer ${
              currentView === 'multi-chain-timeline'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('multi-chain-timeline')}
          >
            Timeline
          </button>
          <button
            className={`px-space-sm py-1 font-code-sm text-code-sm rounded transition-all cursor-pointer ${
              currentView === 'compare-chains'
                ? 'bg-surface-container-high text-secondary font-semibold shadow-sm'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
            onClick={() => onNavigate('compare-chains')}
          >
            Compare
          </button>
        </nav>

        {/* Right: Settings */}
        <div className="flex items-center gap-space-sm">
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
