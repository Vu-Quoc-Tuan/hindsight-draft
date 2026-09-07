import { useEffect, useState, useMemo } from 'react'
import { api } from '../api'
import type { ChainAnalysis, Member, PairWhy } from '../types'
import { ChainTree } from '../ChainTree'
import { InfoTip } from '../components/InfoTip'
import { ChainScopeView } from './why/ChainScopeView'
import { MemberScopeView } from './why/MemberScopeView'
import { PairScopeView } from './why/PairScopeView'
import { GroupScopeView } from './why/GroupScopeView'

interface ChainDetailViewProps {
  analysis: ChainAnalysis
  activeSubTab: 'OVERVIEW' | 'WHY' | 'MEMBERS'
  onSubTabChange: (tab: 'OVERVIEW' | 'WHY' | 'MEMBERS') => void
  onInspectMember?: (member: Member) => void
  onPairContextChange?: (pair: [string, string] | null) => void
}

type WhyScope = 'Chain' | 'Member' | 'Pair' | 'Group'

export function ChainDetailView({
  analysis,
  activeSubTab,
  onSubTabChange,
  onInspectMember,
  onPairContextChange,
}: ChainDetailViewProps) {
  const [whyScope, setWhyScope] = useState<WhyScope>('Chain')
  const [memberFilter, setMemberFilter] = useState<'ALL' | 'CORE' | 'WEAK' | 'CONNECTORS'>('ALL')
  const [searchMember, setSearchMember] = useState('')
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
  const [inspectedMember, setInspectedMember] = useState<Member | null>(null)
  const [pairWhyLoad, setPairWhyLoad] = useState<{
    requestKey: string
    payload: PairWhy | null
    reason: string | null
  } | null>(null)

  const members = useMemo(() => analysis.members ?? [], [analysis.members])

  const pairRequestKey = activeSubTab === 'WHY' && whyScope === 'Pair' && selectedMemberIds.length === 2
    ? `${analysis.chain_id}\u0000${selectedMemberIds[0]}\u0000${selectedMemberIds[1]}`
    : null
  const pairWhy = pairWhyLoad?.requestKey === pairRequestKey ? pairWhyLoad.payload : null
  const pairWhyReason = pairWhyLoad?.requestKey === pairRequestKey ? pairWhyLoad.reason : null
  const pairWhyState = !pairRequestKey
    ? 'IDLE'
    : pairWhy
      ? 'AVAILABLE'
      : pairWhyReason
        ? 'UNAVAILABLE'
        : 'LOADING'

  useEffect(() => {
    if (pairRequestKey && selectedMemberIds.length === 2) {
      onPairContextChange?.([selectedMemberIds[0], selectedMemberIds[1]])
    } else {
      onPairContextChange?.(null)
    }
  }, [onPairContextChange, pairRequestKey, selectedMemberIds])

  useEffect(() => () => {
    onPairContextChange?.(null)
  }, [onPairContextChange])

  useEffect(() => {
    if (!pairRequestKey) return
    const [alarmA, alarmB] = selectedMemberIds
    if (alarmA === alarmB) return
    const controller = new AbortController()
    api.pairWhy(analysis.chain_id, alarmA, alarmB, controller.signal).then(payload => {
      if (controller.signal.aborted) return
      if (payload.chain_id !== analysis.chain_id || payload.alarm_id_a !== alarmA || payload.alarm_id_b !== alarmB) {
        setPairWhyLoad({ requestKey: pairRequestKey, payload: null, reason: 'PAIR_WHY_CONTEXT_MISMATCH' })
        return
      }
      setPairWhyLoad({ requestKey: pairRequestKey, payload, reason: null })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setPairWhyLoad({
          requestKey: pairRequestKey,
          payload: null,
          reason: cause instanceof Error ? cause.message : 'PAIR_WHY_UNAVAILABLE',
        })
      }
    })
    return () => controller.abort()
  }, [analysis.chain_id, pairRequestKey, selectedMemberIds])

  // Metrics calculation
  const totalMembers = members.length
  const coreCount = members.filter(m => m.role?.toUpperCase().includes('CORE') || m.role?.toUpperCase().includes('ROOT')).length
  const weakCount = members.filter(m => m.role?.toUpperCase().includes('WEAK') || m.role?.toUpperCase().includes('LEAF')).length
  const connectorCount = members.filter(m => m.role?.toUpperCase().includes('CONNECT')).length
  const spofCount = members.filter(m => m.redundancy_role?.toUpperCase().includes('SPOF')).length
  const peripheralCount = Math.max(0, totalMembers - coreCount - weakCount - connectorCount)
  const observedTimes = members
    .map(member => member.canonical_start_time)
    .filter((value): value is string => value !== null)
    .sort((left, right) => Date.parse(left) - Date.parse(right))
  const observedStart = observedTimes[0] ?? null
  const observedEnd = observedTimes.at(-1) ?? null

  const distinctDevices = useMemo(() => {
    return Array.from(
      new Set(
        members
          .map(m => m.device_code ?? m.node_reference)
          .filter((v): v is string => Boolean(v))
      )
    )
  }, [members])

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
      prev.includes(alarmId) ? prev.filter(id => id !== alarmId) : [...prev.slice(-1), alarmId]
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

          {/* Right Col: persisted member facts */}
          <div className="xl:col-span-7 bg-surface-container-low rounded p-space-md flex flex-col gap-space-md shadow-md">
            <div className="flex items-center justify-between h-space-panel-header-h border-b border-surface-container-highest pb-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[18px]">query_stats</span>
                <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                  Chain members & roles
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-on-surface-variant">{analysis.statistics_mode}</span>
            </div>

            <div className="grid grid-cols-2 gap-space-xs sm:grid-cols-4">
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-primary">
                <span className="font-label-caps text-label-caps uppercase text-primary font-bold">CORE</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface">{coreCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Assigned member role</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-secondary">
                <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">PERIPHERAL</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface">{peripheralCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Assigned member role</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-tertiary">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">WEAK</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-tertiary">{weakCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-tertiary mt-space-2xs">Assigned member role</span>
              </div>
              <div className="bg-surface-container p-space-sm rounded flex flex-col items-start border-t-2 border-surface-variant">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">CONNECTORS</span>
                <div className="flex items-baseline gap-space-xs mt-space-2xs">
                  <span className="font-headline-lg text-headline-lg font-bold text-on-surface-variant">{connectorCount}</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">/{totalMembers}</span>
                </div>
                <span className="font-body-sm text-body-sm text-on-surface-variant mt-space-2xs">Assigned member role</span>
              </div>
            </div>

            <div className="rounded bg-surface-container p-space-md">
              <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Observed timestamp range</p>
              <p className="mt-space-xs font-code-sm text-code-sm text-on-surface">
                {observedStart && observedEnd ? `${observedStart} → ${observedEnd}` : 'UNAVAILABLE'}
              </p>
            </div>

            <div className="p-space-md bg-surface-container rounded flex flex-wrap items-center justify-between gap-space-sm">
              <p className="text-on-surface-variant">Structural conductance is computed only by an explicit Deep Dive.</p>
              <button
                onClick={() => onSubTabChange('MEMBERS')}
                className="px-space-md py-space-xs bg-surface-container-high hover:bg-surface-bright text-secondary font-code-sm text-code-sm font-semibold rounded flex items-center gap-space-xs transition-colors"
              >
                Inspect members
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {activeSubTab === 'WHY' && (
        <div className="flex flex-col gap-space-md">
          {/* Scope Header Card with Prominent Scope Switcher */}
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
                      ? 'Chain-level: Tổng hợp 6 chiều bằng chứng toàn diện chứng minh tính gắn kết của toàn bộ chuỗi.'
                      : whyScope === 'Member'
                      ? 'Member-level: Hồ sơ chi tiết giải thích vai trò (Core, Connector, Leaf) của từng cảnh báo trong chuỗi.'
                      : whyScope === 'Pair'
                      ? 'Pair-level: Đối sánh trực tiếp giữa 2 cảnh báo được chọn trên từng kênh trễ thời gian, topology và thuộc tính.'
                      : 'Group-level: Phân tích các phân cụm con (Subclusters A, B, C) và các đường cắt ranh giới phân hoạch.'
                  }
                />
              </div>
            </div>

            {/* Scope Switcher Pill Tabs */}
            <div className="flex items-center gap-1 bg-[#080d17] p-1 rounded-lg border border-[#1b273e]">
              {(['Chain', 'Member', 'Pair', 'Group'] as WhyScope[]).map(sc => {
                const isActive = whyScope === sc
                const icon =
                  sc === 'Chain' ? 'view_in_ar'
                  : sc === 'Member' ? 'person_search'
                  : sc === 'Pair' ? 'compare_arrows'
                  : 'account_tree'

                return (
                  <button
                    key={sc}
                    type="button"
                    onClick={() => setWhyScope(sc)}
                    className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer ${
                      isActive
                        ? 'bg-secondary text-on-secondary shadow-md'
                        : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high'
                    }`}
                  >
                    <span className="material-symbols-outlined text-[15px]">{icon}</span>
                    {sc} Scope
                  </button>
                )
              })}
            </div>
          </div>

          {/* Render Scope View */}
          {whyScope === 'Chain' && (
            <ChainScopeView
              analysis={analysis}
              distinctDevices={distinctDevices}
              observedStart={observedStart}
              observedEnd={observedEnd}
              onSwitchScope={setWhyScope}
              onSelectMember={m => {
                setInspectedMember(m)
                setWhyScope('Member')
              }}
            />
          )}

          {whyScope === 'Member' && (
            <MemberScopeView
              analysis={analysis}
              members={members}
              inspectedMember={inspectedMember}
              setInspectedMember={setInspectedMember}
              onComparePair={(idA, idB) => {
                setSelectedMemberIds([idA, idB])
                setWhyScope('Pair')
              }}
              onSwitchScope={setWhyScope}
            />
          )}

          {whyScope === 'Pair' && (
            <PairScopeView
              members={members}
              selectedMemberIds={selectedMemberIds}
              setSelectedMemberIds={setSelectedMemberIds}
              pairWhy={pairWhy}
              pairWhyState={pairWhyState}
              pairWhyReason={pairWhyReason}
              onSwitchScope={setWhyScope}
            />
          )}

          {whyScope === 'Group' && (
            <GroupScopeView
              analysis={analysis}
              onSwitchScope={setWhyScope}
            />
          )}
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
              <span className="font-headline-md text-headline-md font-bold text-primary mt-1">{spofCount}</span>
              <div className="w-full h-1 bg-surface-container-highest rounded-full mt-2">
                <div className="h-full bg-primary" style={{ width: `${Math.round((spofCount / Math.max(1, totalMembers)) * 100)}%` }}></div>
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
                            {m.alarm_name ?? 'N/A'}
                          </span>
                        </div>
                      </td>
                      <td className="px-space-md py-space-xs text-on-surface-variant font-mono">
                        {m.canonical_start_time ?? 'N/A'}
                      </td>
                      <td className="px-space-md py-space-xs text-on-surface font-mono">
                        {m.device_code ?? m.node_reference ?? 'N/A'}
                      </td>
                      <td className="px-space-md py-space-xs">
                        <span
                          className={`font-label-caps text-label-caps px-space-xs py-0.5 rounded font-bold uppercase ${
                            isWeak ? 'bg-error-container text-error' : 'bg-surface-container-high text-secondary'
                          }`}
                        >
                          {m.role || 'UNAVAILABLE'}
                        </span>
                      </td>
                      <td className="px-space-md py-space-xs">
                        <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container text-on-surface-variant uppercase">
                          {m.redundancy_role ?? 'N/A'}
                        </span>
                      </td>
                      <td className="px-space-md py-space-xs text-right">
                        <span className={`font-bold ${isWeak ? 'text-error' : 'text-secondary'}`}>
                          {m.membership_support === null ? 'N/A' : m.membership_support.toFixed(2)}
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
