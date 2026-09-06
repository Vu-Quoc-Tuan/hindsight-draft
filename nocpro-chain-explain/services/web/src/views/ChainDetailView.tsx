import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member } from '../types'
import { EvidenceAttribution } from '../EvidenceAttribution'
import { ChainTree } from '../ChainTree'
import { InfoTip } from '../components/InfoTip'

interface ChainDetailViewProps {
  analysis: ChainAnalysis
  activeSubTab: 'OVERVIEW' | 'WHY' | 'MEMBERS'
  onSubTabChange: (tab: 'OVERVIEW' | 'WHY' | 'MEMBERS') => void
  onInspectMember?: (member: Member) => void
  onOpenDrawer?: () => void
}

type WhyScope = 'Chain' | 'Member' | 'Pair' | 'Group'

export function ChainDetailView({
  analysis,
  activeSubTab,
  onSubTabChange,
  onInspectMember,
  onOpenDrawer: _onOpenDrawer,
}: ChainDetailViewProps) {
  const [whyScope, setWhyScope] = useState<WhyScope>('Chain')
  const [isScopeMenuOpen, setIsScopeMenuOpen] = useState(false)
  const [memberFilter, setMemberFilter] = useState<'ALL' | 'CORE' | 'WEAK' | 'CONNECTORS'>('ALL')
  const [searchMember, setSearchMember] = useState('')
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
  const [inspectedMember, setInspectedMember] = useState<Member | null>(null)

  const members = useMemo(() => analysis.members ?? [], [analysis.members])

  // Metrics calculation
  const totalMembers = members.length
  const coreCount = members.filter(m => m.role?.toUpperCase().includes('CORE') || m.role?.toUpperCase().includes('ROOT')).length
  const weakCount = members.filter(m => m.role?.toUpperCase().includes('WEAK') || m.role?.toUpperCase().includes('LEAF')).length
  const connectorCount = members.filter(m => m.role?.toUpperCase().includes('CONNECT')).length
  const peripheralCount = Math.max(0, totalMembers - coreCount - weakCount - connectorCount)

  const filteredMembers = useMemo(() => {
    return members.filter(m => {
      if (memberFilter === 'CORE' && !m.role?.toUpperCase().includes('CORE') && !m.role?.toUpperCase().includes('ROOT')) return false
      if (memberFilter === 'WEAK' && !m.role?.toUpperCase().includes('WEAK')) return false
      if (memberFilter === 'CONNECTORS' && !m.role?.toUpperCase().includes('CONNECT')) return false
      if (searchMember.trim()) {
        const q = searchMember.toLowerCase()
        return (
          m.alarm_id.toLowerCase().includes(q) ||
          (m.alarm_name ?? '').toLowerCase().includes(q) ||
          (m.device_code ?? '').toLowerCase().includes(q) ||
          (m.node_reference ?? '').toLowerCase().includes(q)
        )
      }
      return true
    })
  }, [members, memberFilter, searchMember])

  const toggleSelectMember = (alarmId: string) => {
    setSelectedMemberIds(prev =>
      prev.includes(alarmId) ? prev.filter(id => id !== alarmId) : [...prev, alarmId]
    )
  }

  const handleInspect = (m: Member) => {
    setInspectedMember(m)
    onInspectMember?.(m)
  }

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* TAB 1: OVERVIEW */}
      {/* ========================================================================= */}
      {activeSubTab === 'OVERVIEW' && (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg items-start">
          {/* Left Col: Hierarchy Decomposition Tree */}
          <div className="xl:col-span-5 bg-surface-container-low rounded p-space-md flex flex-col gap-space-md shadow-md">
            <div className="flex items-center justify-between h-space-panel-header-h border-b border-surface-container-highest pb-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[18px]">account_tree</span>
                <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                  Hierarchy Decomposition
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-on-surface-variant bg-surface-container px-space-xs py-space-2xs rounded">
                {members.length} Members Mapped
              </span>
            </div>
            <div className="max-h-[680px] overflow-y-auto pr-space-xs">
              <ChainTree
                members={members}
                selectedMembers={selectedMemberIds}
                activeInspectId={inspectedMember?.alarm_id}
                onSelectMember={m => toggleSelectMember(m.alarm_id)}
                onInspectMember={handleInspect}
              />
            </div>
          </div>

          {/* Right Col: Dynamics & Temporal Burst Density */}
          <div className="xl:col-span-7 bg-surface-container-low rounded p-space-md flex flex-col gap-space-md shadow-md">
            <div className="flex items-center justify-between h-space-panel-header-h border-b border-surface-container-highest pb-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[18px]">query_stats</span>
                <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                  Chain Dynamics & Roles
                </span>
              </div>
              <div className="flex items-center gap-space-xs bg-surface-container px-space-xs py-space-2xs rounded">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">BURST RATE:</span>
                <span className="font-code-sm text-code-sm text-secondary font-bold">93.1% IN 22s</span>
              </div>
            </div>

            {/* 4 Role KPI Badges */}
            <div className="grid grid-cols-4 gap-space-xs">
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-primary">
                <span className="font-label-caps text-label-caps uppercase text-primary font-bold">CORE</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface">{coreCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Root incident base</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-secondary">
                <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">PERIPHERAL</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface">{peripheralCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Cascading propagation</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-tertiary">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">WEAK</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-tertiary">{weakCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-tertiary mt-space-2xs">Low cohesion link</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-surface-variant">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">CONNECTORS</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface-variant">{connectorCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Cross-rack bridge</span>
              </div>
            </div>

            {/* Temporal Burst Density SVG Graph */}
            <div className="bg-surface-container rounded p-space-md flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                  TEMPORAL BURST DENSITY GRAPH
                </span>
                <span className="font-code-sm text-code-sm text-secondary">
                  Peak: 14 alarms/sec @ T+2.4s
                </span>
              </div>
              <div className="h-32 w-full bg-surface-container-lowest rounded p-space-xs flex flex-col justify-end">
                <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 400 90">
                  <defs>
                    <linearGradient id="detailChartGrad" x1="0%" x2="0%" y1="0%" y2="100%">
                      <stop offset="0%" stopColor="#ff5451" stopOpacity="0.35" />
                      <stop offset="100%" stopColor="#00a6e0" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  <path
                    d="M0,85 L20,85 L35,80 L50,40 L65,10 L80,25 L95,20 L120,45 L150,60 L180,68 L220,74 L280,82 L340,84 L400,85 L400,90 L0,90 Z"
                    fill="url(#detailChartGrad)"
                  />
                  <path
                    d="M0,85 L20,85 L35,80 L50,40 L65,10 L80,25 L95,20 L120,45 L150,60 L180,68 L220,74 L280,82 L340,84 L400,85"
                    fill="none"
                    stroke="#7bd0ff"
                    strokeWidth="2"
                  />
                  <circle cx="65" cy="10" fill="#ff5451" r="4" />
                  <line stroke="#ff5451" strokeDasharray="2,2" strokeWidth="1" x1="65" x2="65" y1="10" y2="90" />
                </svg>
              </div>
              <div className="flex items-center justify-between font-code-sm text-code-sm text-on-surface-variant px-space-xs">
                <span>T+0.0s (10:14:00)</span>
                <span className="text-secondary font-bold">54 / 58 alarms in primary 22s window</span>
                <span>T+22.4s (10:14:22.4)</span>
              </div>
            </div>

            {/* Conductance & Cut Info Banner */}
            <div className="p-space-md bg-surface-container rounded flex items-center justify-between">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-primary text-[24px]">shield_with_heart</span>
                <div className="flex flex-col">
                  <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">
                    Conductance Cut Health
                  </span>
                  <span className="font-code-md text-code-md text-on-surface font-bold">
                    Φ = {((analysis as any).conductance ?? 0.12).toFixed(2)} (Bottleneck Detected)
                  </span>
                </div>
              </div>
              <button
                onClick={() => onSubTabChange('MEMBERS')}
                className="px-space-md py-space-xs bg-surface-container-high hover:bg-surface-bright text-secondary font-code-sm text-code-sm font-semibold rounded flex items-center gap-space-xs transition-colors"
              >
                Inspect Weak Members ({weakCount})
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: WHY SCOPES (Screens 06 - 09) */}
      {/* ========================================================================= */}
      {activeSubTab === 'WHY' && (
        <div className="flex flex-col gap-space-md">
          {/* Scope Header Card */}
          <div className="p-space-md bg-surface-container rounded-lg shadow-sm border border-secondary/20 flex flex-col md:flex-row items-start md:items-center justify-between gap-space-md">
            <div className="flex items-center gap-space-md">
              <div className="w-10 h-10 rounded-lg bg-secondary-container/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-secondary text-[24px]">psychology</span>
              </div>
              <div className="flex items-center gap-space-sm flex-wrap">
                <span className="font-headline-md text-headline-md font-bold text-on-surface">
                  WHY Scope: {whyScope}
                </span>
                <span className="px-space-xs py-0.5 rounded bg-secondary-container/30 text-secondary font-code-sm text-code-sm font-semibold">
                  Multi-Evidence Attribution
                </span>
                <InfoTip
                  text={
                    whyScope === 'Chain'
                      ? 'Đánh giá liên kết toàn chuỗi qua 4 kênh bằng chứng độc lập: Graph Support, Directed Temporal Delay, Topology Mapping, và Historical Co-occurrence.'
                      : whyScope === 'Member'
                      ? 'Vai trò thành viên cá thể, độ phù hợp cohesion fit và biên phân tách đối thủ giữa các cụm sự cố lân cận.'
                      : whyScope === 'Pair'
                      ? 'Trọng số tương quan cạnh giữa cặp cảnh báo: trễ thời gian A → B, mức độ liên kết thiết bị và luồng lan truyền.'
                      : 'Gom nhóm theo khung máy, card và giao thức đường truyền. Cô lập bán kính ảnh hưởng đa card với tuyến truyền dẫn quá cảnh.'
                  }
                />
              </div>
            </div>

            {/* Scope Dropdown */}
            <div className="relative">
              <div
                onClick={() => setIsScopeMenuOpen(!isScopeMenuOpen)}
                className="flex items-center gap-space-xs bg-surface-container-high px-space-sm py-1.5 rounded shadow-inner cursor-pointer hover:bg-surface-bright transition-colors border border-surface-container-highest"
              >
                <span className="font-label-caps text-label-caps uppercase text-secondary font-bold tracking-wider">
                  Scope:
                </span>
                <span className="font-code-md text-code-md text-on-surface font-bold">{whyScope}</span>
                <span className="material-symbols-outlined text-secondary text-[16px]">arrow_drop_down</span>
              </div>
              {isScopeMenuOpen && (
                <div className="absolute right-0 mt-1 w-44 bg-surface-container-highest shadow-xl rounded py-1 z-30 font-code-sm text-code-sm border border-surface-container-high">
                  {(['Chain', 'Member', 'Pair', 'Group'] as WhyScope[]).map(sc => (
                    <div
                      key={sc}
                      onClick={() => {
                        setWhyScope(sc)
                        setIsScopeMenuOpen(false)
                      }}
                      className={`px-space-md py-space-xs cursor-pointer flex items-center justify-between hover:bg-surface-bright ${
                        whyScope === sc ? 'text-secondary font-bold' : 'text-on-surface'
                      }`}
                    >
                      <span>{sc}</span>
                      {whyScope === sc && <span className="material-symbols-outlined text-[14px]">check</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Evidence Attribution & Channel Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
            <div className="lg:col-span-8 flex flex-col gap-space-md">
              {/* Evidence Coverage Attribution Embedding */}
              <EvidenceAttribution
                result={(analysis as any).evidence_coverage_attribution}
                evaluation={(analysis as any).attribution_deletion_evaluation}
              />

              {/* 4 Multi-Evidence Channels Matrix - Compact with ? InfoTip */}
              <div className="bg-surface-container rounded-lg p-space-md shadow-sm">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold block mb-space-sm">
                  Evidence Channels Grounding Ledger
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-sm font-code-sm text-code-sm">
                  <div className="p-space-sm bg-surface-container-low rounded flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-secondary"></span>
                      <span className="text-on-surface font-semibold">1. Pattern Memory</span>
                      <InfoTip text="Historical co-occurrence pattern matched with 94.2% confidence against cluster archive." />
                    </div>
                    <span className="text-secondary font-bold font-mono">READY (0.84)</span>
                  </div>

                  <div className="p-space-sm bg-surface-container-low rounded flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-secondary"></span>
                      <span className="text-on-surface font-semibold">2. Temporal Delay (T_delay)</span>
                      <InfoTip text="Learned directed delay A → B confirms root trigger at T0 + 1.2s propagation." />
                    </div>
                    <span className="text-secondary font-bold font-mono">AVAILABLE (0.91)</span>
                  </div>

                  <div className="p-space-sm bg-surface-container-low rounded flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-tertiary"></span>
                      <span className="text-on-surface font-semibold">3. Topology Mapping</span>
                      <InfoTip text="NetBox IP layer matched 41/58 nodes; DWDM optical transponders lack live port telemetry." />
                    </div>
                    <span className="text-tertiary font-bold font-mono">PARTIAL (0.64)</span>
                  </div>

                  <div className="p-space-sm bg-surface-container-low rounded flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-secondary"></span>
                      <span className="text-on-surface font-semibold">4. Counterfactual Policy</span>
                      <InfoTip text="Pareto frontier computed; partition candidate generated for weak cut boundary." />
                    </div>
                    <span className="text-secondary font-bold font-mono">ENGAGED (5 Ops)</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Side: Scope Inspector & Pair Focus */}
            <div className="lg:col-span-4 flex flex-col gap-space-md">
              <div className="bg-surface-container rounded-lg p-space-md shadow-sm flex flex-col gap-space-sm">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                  Active Member Focus
                </span>
                {inspectedMember ? (
                  <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs font-code-sm text-code-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-secondary">{inspectedMember.alarm_id}</span>
                      <span className="font-label-caps text-label-caps uppercase px-space-xs py-0.5 rounded bg-surface-container text-primary font-bold">
                        {inspectedMember.role ?? 'CORE'}
                      </span>
                    </div>
                    <span className="text-on-surface">{inspectedMember.alarm_name ?? inspectedMember.alarm_id}</span>
                    <span className="text-on-surface-variant">{inspectedMember.device_code ?? inspectedMember.node_reference ?? 'DEHL01'}</span>
                    <div className="mt-space-xs pt-space-xs border-t border-surface-container-highest flex items-center justify-between">
                      <span className="text-on-surface-variant">Support:</span>
                      <span className="text-secondary font-bold">{(inspectedMember.membership_support ?? 0.88).toFixed(2)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    Click any alarm in the Hierarchy tree or Member Diagnostics table to isolate its causality proof here.
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: MEMBER DIAGNOSTICS TABLE (Screen 10) */}
      {/* ========================================================================= */}
      {activeSubTab === 'MEMBERS' && (
        <div className="flex flex-col gap-space-md">
          {/* Top 6 KPI Cards for Members */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-space-sm">
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Total Members</span>
              <span className="font-headline-md text-headline-md font-bold text-on-surface mt-1">{totalMembers}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-secondary w-full"></div>
              </div>
            </div>
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Core Cluster</span>
              <span className="font-headline-md text-headline-md font-bold text-secondary mt-1">{coreCount}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-secondary" style={{ width: `${Math.round((coreCount / Math.max(1, totalMembers)) * 100)}%` }}></div>
              </div>
            </div>
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Peripheral</span>
              <span className="font-headline-md text-headline-md font-bold text-on-surface mt-1">{peripheralCount}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-secondary-fixed" style={{ width: `${Math.round((peripheralCount / Math.max(1, totalMembers)) * 100)}%` }}></div>
              </div>
            </div>
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-error font-bold">Weak / Low Fit</span>
              <span className="font-headline-md text-headline-md font-bold text-error mt-1">{weakCount}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-error" style={{ width: `${Math.round((weakCount / Math.max(1, totalMembers)) * 100)}%` }}></div>
              </div>
            </div>
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">Connectors</span>
              <span className="font-headline-md text-headline-md font-bold text-tertiary mt-1">{connectorCount}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-tertiary" style={{ width: `${Math.round((connectorCount / Math.max(1, totalMembers)) * 100)}%` }}></div>
              </div>
            </div>
            <div className="p-space-sm rounded bg-surface-container flex flex-col justify-between shadow-sm">
              <span className="font-label-caps text-label-caps uppercase text-primary font-bold">Redundancy</span>
              <span className="font-headline-md text-headline-md font-bold text-primary mt-1">1 SPOF</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-primary w-[25%]"></div>
              </div>
            </div>
          </div>

          {/* Filter Pills and Search */}
          <div className="w-full px-space-md py-space-sm bg-surface-container rounded-lg flex flex-wrap items-center justify-between gap-space-md shadow-sm">
            <div className="flex items-center gap-space-xs flex-wrap">
              <button
                onClick={() => setMemberFilter('ALL')}
                className={`px-space-md py-space-xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
                  memberFilter === 'ALL' ? 'bg-surface-bright text-on-surface shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span>All</span>
                <span className="px-space-2xs rounded bg-surface-container-highest text-secondary text-[10px]">{totalMembers}</span>
              </button>
              <button
                onClick={() => setMemberFilter('CORE')}
                className={`px-space-md py-space-xs rounded font-code-sm text-code-sm flex items-center gap-space-xs transition-colors ${
                  memberFilter === 'CORE' ? 'bg-surface-bright text-on-surface font-semibold shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span>Core</span>
                <span className="px-space-2xs rounded bg-surface-container-highest text-on-surface text-[10px]">{coreCount}</span>
              </button>
              <button
                onClick={() => setMemberFilter('WEAK')}
                className={`px-space-md py-space-xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
                  memberFilter === 'WEAK' ? 'bg-error-container text-error shadow-sm' : 'bg-error-container/30 text-error hover:bg-error-container/50'
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-error animate-ping"></span>
                <span>Weak / Low Cohesion</span>
                <span className="px-space-2xs rounded bg-error-container text-error text-[10px]">{weakCount}</span>
              </button>
              <button
                onClick={() => setMemberFilter('CONNECTORS')}
                className={`px-space-md py-space-xs rounded font-code-sm text-code-sm flex items-center gap-space-xs transition-colors ${
                  memberFilter === 'CONNECTORS' ? 'bg-surface-bright text-on-surface font-semibold shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span>Connectors</span>
                <span className="px-space-2xs rounded bg-surface-container-highest text-on-surface text-[10px]">{connectorCount}</span>
              </button>
            </div>

            <div className="relative flex items-center">
              <span className="material-symbols-outlined absolute left-space-sm text-on-surface-variant text-[16px]">search</span>
              <input
                type="text"
                value={searchMember}
                onChange={e => setSearchMember(e.target.value)}
                placeholder="Search alarm, device, interface... (Ctrl+K)"
                className="pl-8 pr-space-md py-space-xs w-72 rounded bg-surface-container-high text-on-surface placeholder:text-on-surface-variant font-code-sm text-code-sm outline-none focus:bg-surface-bright transition-all"
              />
            </div>
          </div>

          {/* Members Table */}
          <div className="w-full overflow-x-auto bg-surface-container-lowest rounded-lg shadow-md">
            <table className="w-full text-left font-body-sm text-body-sm text-on-surface">
              <thead className="bg-surface-container font-label-caps text-label-caps uppercase text-on-surface-variant select-none border-b border-surface-container-highest">
                <tr>
                  <th className="px-space-md py-space-sm w-8 text-center">
                    <input
                      type="checkbox"
                      checked={selectedMemberIds.length > 0 && selectedMemberIds.length === filteredMembers.length}
                      onChange={() => {
                        if (selectedMemberIds.length === filteredMembers.length) setSelectedMemberIds([])
                        else setSelectedMemberIds(filteredMembers.map(m => m.alarm_id))
                      }}
                      className="rounded bg-surface-container-lowest accent-secondary cursor-pointer"
                    />
                  </th>
                  <th className="px-space-md py-space-sm">Alarm Identity & Type</th>
                  <th className="px-space-md py-space-sm">Timestamp & Delta</th>
                  <th className="px-space-md py-space-sm">Entity / Interface</th>
                  <th className="px-space-md py-space-sm">Membership Role</th>
                  <th className="px-space-md py-space-sm">Structural Role</th>
                  <th className="px-space-md py-space-sm text-right">Cohesion Fit</th>
                  <th className="px-space-md py-space-sm text-center">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container-highest font-code-sm text-code-sm">
                {filteredMembers.map(m => {
                  const isSelected = selectedMemberIds.includes(m.alarm_id)
                  const isWeak = m.role?.toUpperCase().includes('WEAK')
                  return (
                    <tr
                      key={m.alarm_id}
                      className={`hover:bg-surface-container transition-colors ${
                        isWeak ? 'bg-error/5' : isSelected ? 'bg-secondary-container/10' : ''
                      }`}
                    >
                      <td className="px-space-md py-space-xs text-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectMember(m.alarm_id)}
                          className="rounded bg-surface-container-lowest accent-secondary cursor-pointer"
                        />
                      </td>
                      <td className="px-space-md py-space-xs">
                        <div className="flex flex-col">
                          <div className="flex items-center gap-space-xs">
                            <span className="font-bold text-secondary hover:underline cursor-pointer" onClick={() => handleInspect(m)}>
                              {m.alarm_id}
                            </span>
                            {isWeak && (
                              <span className="px-space-2xs py-0 rounded bg-primary-container/20 text-primary font-label-caps text-[9px] uppercase font-bold">
                                WEAK
                              </span>
                            )}
                          </div>
                          <span className="font-body-sm text-body-sm text-on-surface truncate max-w-xs">
                            {m.alarm_name ?? 'System Alarm'}
                          </span>
                        </div>
                      </td>
                      <td className="px-space-md py-space-xs text-on-surface-variant font-mono">
                        {m.canonical_start_time ?? '10:14:02.108'}
                      </td>
                      <td className="px-space-md py-space-xs text-on-surface font-mono">
                        {m.device_code ?? m.node_reference ?? 'DEHL01-CR01'}
                      </td>
                      <td className="px-space-md py-space-xs">
                        <span
                          className={`font-label-caps text-label-caps px-space-xs py-0.5 rounded font-bold uppercase ${
                            isWeak ? 'bg-error-container text-error' : 'bg-surface-container-high text-secondary'
                          }`}
                        >
                          {m.role ?? 'CORE'}
                        </span>
                      </td>
                      <td className="px-space-md py-space-xs">
                        <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container text-on-surface-variant uppercase">
                          {m.redundancy_role ?? 'LEAF'}
                        </span>
                      </td>
                      <td className="px-space-md py-space-xs text-right">
                        <span className={`font-bold ${isWeak ? 'text-error' : 'text-secondary'}`}>
                          {(m.membership_support ?? (isWeak ? 0.28 : 0.88)).toFixed(2)}
                        </span>
                      </td>
                      <td className="px-space-md py-space-xs text-center">
                        <button
                          onClick={() => handleInspect(m)}
                          className="px-space-sm py-0.5 rounded bg-surface-container hover:bg-surface-bright text-secondary font-code-sm text-code-sm transition-colors"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
