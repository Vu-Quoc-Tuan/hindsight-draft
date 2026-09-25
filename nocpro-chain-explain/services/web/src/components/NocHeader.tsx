import { useState, useMemo } from 'react'

import { HindsightLogo } from './HindsightLogo'

export type DatasetProfile = 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'

export interface HeaderSnapshotItem {
  snapshot_id: string
  snapshot_version?: string | null
  name: string
  profile: DatasetProfile
  alarm_count: number
  chain_count: number
  description: string
  badge: string
  available?: boolean
  unavailable_reason?: string | null
}

const DATASET_PROFILES: Record<DatasetProfile, { label: string; icon: string; description: string; color: string }> = {
  IP_NETWORK: {
    label: 'IP Network',
    icon: 'hub',
    description: 'Undirected adjacency navigation from the IP topology dataset.',
    color: 'text-cyan-400 border-cyan-500/40 bg-cyan-500/10',
  },
  IT_SERVICES: {
    label: 'IT Services',
    icon: 'dns',
    description: 'Directed source-relation navigation; dependency semantics remain unverified.',
    color: 'text-purple-400 border-purple-500/40 bg-purple-500/10',
  },
  ALARM_ONLY: {
    label: 'Alarm only',
    icon: 'notifications_active',
    description: 'Pure alarm correlation; no topology projection available for this profile.',
    color: 'text-amber-400 border-amber-500/40 bg-amber-500/10',
  },
}

interface NocHeaderProps {
  datasetName: string
  snapshotId: string
  currentView: string
  onNavigate: (view: string) => void
  onOpenSettings?: () => void
  onChangeDatasetProfile?: (profile: DatasetProfile) => void
  snapshots?: HeaderSnapshotItem[]
  onSelectSnapshot?: (snapshotId: string, profile: DatasetProfile, snapshotVersion?: string | null) => void
  onUploadSnapshotFile?: (file: File) => void
  onOpenReviewLearning?: () => void
  onOpenLearning?: (tab?: 'engine' | 'ranker') => void
}

export function NocHeader({
  datasetName,
  snapshotId,
  currentView,
  onNavigate,
  onOpenSettings,
  onChangeDatasetProfile,
  snapshots = [],
  onSelectSnapshot,
  onUploadSnapshotFile,
  onOpenReviewLearning,
  onOpenLearning,
}: NocHeaderProps) {
  const [isSelectorOpen, setSelectorOpen] = useState(false)
  const [selectedCategoryTab, setSelectedCategoryTab] = useState<'ALL' | DatasetProfile>('ALL')

  const activeProfile: DatasetProfile = datasetName in DATASET_PROFILES ? (datasetName as DatasetProfile) : 'ALARM_ONLY'
  const [cleanActiveSnapshotId, activeSnapshotVersion] = snapshotId.split('@')

  const filteredSnapshots = useMemo(() => {
    if (selectedCategoryTab === 'ALL') return snapshots
    return snapshots.filter(item => item.profile === selectedCategoryTab)
  }, [snapshots, selectedCategoryTab])

  const counts = useMemo(() => {
    return {
      ALL: snapshots.length,
      IP_NETWORK: snapshots.filter(s => s.profile === 'IP_NETWORK').length,
      IT_SERVICES: snapshots.filter(s => s.profile === 'IT_SERVICES').length,
      ALARM_ONLY: snapshots.filter(s => s.profile === 'ALARM_ONLY').length,
    }
  }, [snapshots])

  return (
    <header style={{ backgroundColor: '#070e1d' }} className="sticky top-0 z-30 w-full border-b border-surface-container-high/60 shadow-[0_1px_8px_rgba(0,0,0,0.45)]">
      <div className="flex min-h-16 w-full flex-wrap items-center justify-between gap-space-sm px-space-md py-space-xs lg:px-space-lg">
        <div className="flex min-w-0 items-center gap-space-md">
          <button className="flex min-w-0 items-center gap-space-sm text-left group" onClick={() => onNavigate('snapshot-overview')} title="Hindsight — See the bigger picture behind alarm chains">
            <HindsightLogo size={36} />
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-[17px] font-extrabold tracking-tight group-hover:text-primary">Hindsight</span>
                <span className="rounded border border-primary/25 bg-primary/15 px-1.5 py-0.5 font-code-sm text-[10px] font-bold uppercase tracking-wider text-primary">NOCPRO</span>
              </span>
              <span className="hidden truncate font-code-sm text-[11px] text-on-surface-variant sm:block">See the bigger picture behind alarm chains</span>
            </span>
          </button>
          <span className="hidden h-6 w-px bg-surface-container-highest md:block" />
          <div className="relative hidden lg:block">
            <button
              onClick={() => setSelectorOpen(open => !open)}
              className="flex max-w-[420px] items-center gap-2 rounded-lg border border-[#22314d] bg-[#0f1728] px-3 py-1.5 font-code-sm text-xs text-on-surface transition-colors hover:border-[#344870] hover:bg-[#152238]"
              aria-expanded={isSelectorOpen}
              title="Click to select past snapshots or change topology profile"
            >
              <span className="material-symbols-outlined text-[16px] text-secondary">{DATASET_PROFILES[activeProfile].icon}</span>
              <span className="font-bold text-secondary">{DATASET_PROFILES[activeProfile].label}</span>
              <span className="text-[#3c4e6e]">/</span>
              <span className="truncate font-semibold text-primary">{snapshotId}</span>
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant">{isSelectorOpen ? 'arrow_drop_up' : 'arrow_drop_down'}</span>
            </button>

            {isSelectorOpen && (
              <>
                <button className="fixed inset-0 z-40 cursor-default bg-black/40 backdrop-blur-sm" aria-label="Close snapshot selector" onClick={() => setSelectorOpen(false)} />
                <div className="absolute left-0 top-full z-50 mt-2 w-[min(520px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-[#24324d] bg-[#0c1322] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.95)] animate-in fade-in zoom-in-95 duration-100">
                  {/* Modal Header */}
                  <div className="border-b border-[#1b273e] bg-[#0f1728] px-4 py-3 flex items-center justify-between">
                    <div>
                      <p className="font-code-sm text-xs font-bold uppercase tracking-wider text-on-surface">Snapshot & Profile Catalog</p>
                      <p className="mt-0.5 text-[11px] text-on-surface-variant">Select an observed snapshot or filter by topology dataset type</p>
                    </div>
                    <button
                      onClick={() => setSelectorOpen(false)}
                      className="rounded p-1 text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
                      aria-label="Close"
                    >
                      <span className="material-symbols-outlined text-[18px]">close</span>
                    </button>
                  </div>

                  {/* 3 Category Filter Tabs */}
                  <div className="flex border-b border-[#1b273e] bg-[#0a0f1c] px-3 pt-2 gap-1 overflow-x-auto">
                    <button
                      onClick={() => setSelectedCategoryTab('ALL')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg font-code-sm text-xs transition-colors border-t border-x ${
                        selectedCategoryTab === 'ALL'
                          ? 'border-[#24324d] bg-[#0c1322] text-secondary font-bold -mb-px'
                          : 'border-transparent text-on-surface-variant hover:text-on-surface'
                      }`}
                    >
                      <span>All</span>
                      <span className="rounded-full bg-surface-container px-1.5 py-0.2 text-[10px]">{counts.ALL}</span>
                    </button>

                    <button
                      onClick={() => setSelectedCategoryTab('IP_NETWORK')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg font-code-sm text-xs transition-colors border-t border-x ${
                        selectedCategoryTab === 'IP_NETWORK'
                          ? 'border-[#24324d] bg-[#0c1322] text-cyan-400 font-bold -mb-px'
                          : 'border-transparent text-on-surface-variant hover:text-on-surface'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">hub</span>
                      <span>IP Network</span>
                      <span className="rounded-full bg-surface-container px-1.5 py-0.2 text-[10px]">{counts.IP_NETWORK}</span>
                    </button>

                    <button
                      onClick={() => setSelectedCategoryTab('IT_SERVICES')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg font-code-sm text-xs transition-colors border-t border-x ${
                        selectedCategoryTab === 'IT_SERVICES'
                          ? 'border-[#24324d] bg-[#0c1322] text-purple-400 font-bold -mb-px'
                          : 'border-transparent text-on-surface-variant hover:text-on-surface'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">dns</span>
                      <span>IT Services</span>
                      <span className="rounded-full bg-surface-container px-1.5 py-0.2 text-[10px]">{counts.IT_SERVICES}</span>
                    </button>

                    <button
                      onClick={() => setSelectedCategoryTab('ALARM_ONLY')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg font-code-sm text-xs transition-colors border-t border-x ${
                        selectedCategoryTab === 'ALARM_ONLY'
                          ? 'border-[#24324d] bg-[#0c1322] text-amber-400 font-bold -mb-px'
                          : 'border-transparent text-on-surface-variant hover:text-on-surface'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">notifications_active</span>
                      <span>Alarm only</span>
                      <span className="rounded-full bg-surface-container px-1.5 py-0.2 text-[10px]">{counts.ALARM_ONLY}</span>
                    </button>
                  </div>

                  {/* Snapshot List */}
                  <div className="max-h-[380px] overflow-y-auto space-y-2 p-3">
                    {filteredSnapshots.length === 0 ? (
                      <div className="py-8 text-center text-on-surface-variant">
                        <span className="material-symbols-outlined text-3xl mb-1 block">inventory_2</span>
                        <p className="text-xs">No snapshots found for this category.</p>
                      </div>
                    ) : (
                      filteredSnapshots.map(item => {
                        const isActive = item.snapshot_id === cleanActiveSnapshotId && (
                          !item.snapshot_version || !activeSnapshotVersion || item.snapshot_version === activeSnapshotVersion
                        )
                        const profMeta = DATASET_PROFILES[item.profile]
                        return (
                          <div
                            key={`${item.snapshot_id}@${item.snapshot_version ?? 'unknown'}`}
                            className={`rounded-lg border p-3 text-left transition-all ${
                              isActive
                                ? 'border-secondary/80 bg-[#14233a] shadow-sm'
                                : 'border-[#1b273e] bg-[#0e1728] hover:border-[#32456c] hover:bg-[#131f33]'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span className="material-symbols-outlined text-[16px] text-secondary">{profMeta.icon}</span>
                                  <strong className="truncate font-code-sm text-xs font-bold text-on-surface">{item.name}</strong>
                                  <span className={`rounded px-1.5 py-0.2 text-[9px] font-bold uppercase border ${profMeta.color}`}>
                                    {profMeta.label}
                                  </span>
                                  <span className="rounded bg-surface-container-high px-1.5 py-0.2 text-[9px] font-code-sm text-on-surface-variant">
                                    {item.badge}
                                  </span>
                                </div>
                                <p className="mt-1 text-[11px] text-on-surface-variant line-clamp-2">{item.description}</p>
                                <div className="mt-2 flex items-center gap-3 font-code-sm text-[11px] text-on-surface-variant">
                                  <span><strong className="text-on-surface">{item.alarm_count}</strong> alarms</span>
                                  <span>•</span>
                                  <span><strong className="text-on-surface">{item.chain_count}</strong> chains</span>
                                  <span>•</span>
                                  <span className="truncate text-[10px] text-[#60769d]">{item.snapshot_id}</span>
                                </div>
                              </div>
                              <div className="shrink-0 flex flex-col items-end gap-1.5">
                                {isActive ? (
                                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/20 px-2.5 py-0.5 text-[11px] font-bold text-emerald-400 border border-emerald-500/30">
                                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                    Active
                                  </span>
                                ) : item.available === false ? (
                                  <span
                                    title={item.unavailable_reason ?? 'Snapshot source file is missing from local disk'}
                                    className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 font-code-sm text-xs font-medium text-amber-300 cursor-not-allowed"
                                  >
                                    <span className="material-symbols-outlined text-[14px]">warning</span>
                                    Unavailable
                                  </span>
                                ) : (
                                  <button
                                    onClick={() => {
                                      onChangeDatasetProfile?.(item.profile)
                                      onSelectSnapshot?.(item.snapshot_id, item.profile, item.snapshot_version)
                                      setSelectorOpen(false)
                                    }}
                                    className="rounded border border-secondary/50 bg-secondary/15 px-2.5 py-1 font-code-sm text-xs font-semibold text-secondary hover:bg-secondary hover:text-on-secondary transition-colors"
                                  >
                                    Load snapshot →
                                  </button>
                                )}
                              </div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>

                  {/* Footer with Upload Option */}
                  <div className="border-t border-[#1b273e] bg-[#0a0f1c] px-4 py-2.5 flex items-center justify-between">
                    <label className="inline-flex items-center gap-1.5 text-xs text-secondary hover:text-on-surface cursor-pointer font-code-sm transition-colors">
                      <span className="material-symbols-outlined text-[16px]">upload_file</span>
                      <span>Import custom snapshot JSON</span>
                      <input
                        type="file"
                        accept=".json"
                        className="hidden"
                        onChange={event => {
                          const file = event.target.files?.[0]
                          if (file) {
                            onUploadSnapshotFile?.(file)
                            setSelectorOpen(false)
                          }
                        }}
                      />
                    </label>
                    <span className="text-[10px] text-on-surface-variant font-code-sm">Backend-verified</span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
        <nav className="order-3 flex w-full items-center gap-space-sm overflow-x-auto lg:order-none lg:w-auto" aria-label="Main navigation">
          {([['snapshots-overview', 'Snapshots'], ['snapshot-overview', 'Overview'], ['all-chains', 'All Chains'], ['review-history', 'Lịch sử ký duyệt']] as const).map(([view, label]) => (
            <button key={view} className={`shrink-0 rounded px-space-md py-1 font-code-sm text-code-sm transition-all ${currentView === view ? 'bg-surface-container-high font-semibold text-secondary' : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'}`} onClick={() => onNavigate(view)}>{label}</button>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <button
            className="flex items-center gap-1.5 h-8 px-3 rounded border border-secondary/40 bg-secondary/10 text-secondary hover:bg-secondary/20 hover:text-primary transition-colors text-xs font-semibold cursor-pointer shadow-sm"
            onClick={() => {
              if (onOpenLearning) onOpenLearning('engine')
              else if (onOpenSettings) onOpenSettings()
              else if (onOpenReviewLearning) onOpenReviewLearning()
            }}
            title="Hindsight Learning & Calibration: Tham số động cơ & Mô hình AI"
            aria-label="Learning & Calibration"
          >
            <span className="material-symbols-outlined text-[16px]">psychology</span>
            <span className="font-code-sm font-bold">Learn</span>
          </button>
        </div>
      </div>
    </header>
  )
}
