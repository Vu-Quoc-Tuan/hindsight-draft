import { useState } from 'react'

import { HindsightLogo } from './HindsightLogo'

type DatasetProfile = 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'

const DATASET_PROFILES: Record<DatasetProfile, { label: string; icon: string; description: string }> = {
  IP_NETWORK: { label: 'IP Network', icon: 'hub', description: 'Undirected adjacency navigation from the IP topology dataset.' },
  IT_SERVICES: { label: 'IT Services', icon: 'dns', description: 'Directed source-relation navigation; dependency semantics remain unverified.' },
  ALARM_ONLY: { label: 'Alarm only', icon: 'notifications_active', description: 'No topology projection is available for this profile.' },
}

interface NocHeaderProps {
  datasetName: string
  snapshotId: string
  currentView: string
  onNavigate: (view: string) => void
  onOpenSettings: () => void
  onChangeDatasetProfile?: (profile: DatasetProfile) => void
}

export function NocHeader({ datasetName, snapshotId, currentView, onNavigate, onOpenSettings, onChangeDatasetProfile }: NocHeaderProps) {
  const [isSelectorOpen, setSelectorOpen] = useState(false)
  const activeProfile: DatasetProfile = datasetName in DATASET_PROFILES ? datasetName as DatasetProfile : 'ALARM_ONLY'

  return (
    <header style={{ backgroundColor: '#070e1d' }} className="sticky top-0 z-30 w-full border-b border-surface-container-high/60 shadow-[0_1px_8px_rgba(0,0,0,0.45)]">
      <div className="flex min-h-16 w-full flex-wrap items-center justify-between gap-space-sm px-space-md py-space-xs lg:px-space-lg">
        <div className="flex min-w-0 items-center gap-space-md">
          <button className="flex min-w-0 items-center gap-space-sm text-left group" onClick={() => onNavigate('snapshot-overview')} title="Hindsight — evidence-backed alarm-chain analysis">
            <HindsightLogo size={36} />
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-[17px] font-extrabold tracking-tight group-hover:text-primary">Hindsight</span>
                <span className="rounded border border-primary/25 bg-primary/15 px-1.5 py-0.5 font-code-sm text-[10px] font-bold uppercase tracking-wider text-primary">NOCPRO</span>
              </span>
              <span className="hidden truncate font-code-sm text-[11px] text-on-surface-variant sm:block">Evidence-backed alarm-chain analysis</span>
            </span>
          </button>
          <span className="hidden h-6 w-px bg-surface-container-highest md:block" />
          <div className="relative hidden lg:block">
            <button onClick={() => setSelectorOpen(open => !open)} className="flex max-w-[360px] items-center gap-1.5 rounded-md border border-[#22314d] bg-[#0f1728] px-2.5 py-1 font-code-sm text-xs text-on-surface hover:border-[#344870] hover:bg-[#152238]" aria-expanded={isSelectorOpen} title="Choose the topology navigation profile">
              <span className="material-symbols-outlined text-[15px] text-secondary">{DATASET_PROFILES[activeProfile].icon}</span>
              <span className="font-bold text-secondary">{DATASET_PROFILES[activeProfile].label}</span>
              <span className="text-[#3c4e6e]">/</span>
              <span className="truncate font-semibold text-primary">{snapshotId}</span>
              <span className="material-symbols-outlined text-[15px] text-on-surface-variant">{isSelectorOpen ? 'arrow_drop_up' : 'arrow_drop_down'}</span>
            </button>
            {isSelectorOpen && (
              <>
                <button className="fixed inset-0 z-40 cursor-default bg-black/25" aria-label="Close profile selector" onClick={() => setSelectorOpen(false)} />
                <div className="absolute left-0 top-full z-50 mt-1.5 w-[min(330px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-[#24324d] bg-[#0c1322] shadow-[0_20px_40px_-8px_rgba(0,0,0,0.95)]">
                  <div className="border-b border-[#1b273e] px-3 py-2">
                    <p className="font-code-sm text-[11px] font-bold uppercase tracking-wider">Topology dataset profile</p>
                    <p className="mt-1 text-[10px] text-on-surface-variant">This changes relation navigation only. Snapshot identity remains backend-controlled.</p>
                  </div>
                  <div className="space-y-1 p-2">
                    {(Object.keys(DATASET_PROFILES) as DatasetProfile[]).map(profile => {
                      const item = DATASET_PROFILES[profile]
                      const selected = profile === activeProfile
                      return (
                        <button key={profile} className={`flex w-full items-start gap-2 rounded-lg border p-2 text-left ${selected ? 'border-secondary/60 bg-[#162842]' : 'border-[#1b273e] bg-[#0e1728] hover:border-[#2d3e5e]'}`} onClick={() => { onChangeDatasetProfile?.(profile); setSelectorOpen(false) }}>
                          <span className="material-symbols-outlined text-[18px] text-secondary">{item.icon}</span>
                          <span className="min-w-0"><span className="block font-code-sm text-xs font-bold">{item.label}</span><span className="mt-0.5 block text-[10px] text-on-surface-variant">{item.description}</span></span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
        <nav className="order-3 flex w-full items-center gap-space-xs overflow-x-auto lg:order-none lg:w-auto" aria-label="Snapshot navigation">
          {([['snapshot-overview', 'Overview'], ['chains-explorer', 'Chains Explorer'], ['multi-chain-timeline', 'Timeline'], ['compare-chains', 'Compare']] as const).map(([view, label]) => (
            <button key={view} className={`shrink-0 rounded px-space-sm py-1 font-code-sm text-code-sm transition-all ${currentView === view ? 'bg-surface-container-high font-semibold text-secondary' : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'}`} onClick={() => onNavigate(view)}>{label}</button>
          ))}
        </nav>
        <button className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-surface-container-highest bg-surface-container text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface" onClick={onOpenSettings} title="Analysis settings" aria-label="Analysis settings">
          <span className="material-symbols-outlined text-[18px]">settings</span>
        </button>
      </div>
    </header>
  )
}
