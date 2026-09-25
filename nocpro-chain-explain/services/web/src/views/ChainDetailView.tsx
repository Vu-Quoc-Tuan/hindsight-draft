import { useEffect, useState, useMemo, lazy, Suspense } from 'react'
import { api, type ChainOverviewSnapshotContext } from '../api'
import type {
  ChainAnalysis,
  ChainOverviewCardContext,
  ChainOverviewCards,
  Job,
  Member,
  PairWhy,
} from '../types'
import type { RefreshTask } from '../liveUpdates'
import { InfoTip } from '../components/InfoTip'
import { ChainQualityCard, RepresentativeMemberCard, TopologyCoverageCard } from '../components/ChainQualityCards'
import { RecurrentAlarmHistoryPanel } from '../components/RecurrentAlarmHistoryPanel'
import { EvidenceDetails } from '../components/EvidenceDetails'
import { compactTime } from '../format'

const ChainScopeView = lazy(() => import('./why/ChainScopeView').then(m => ({ default: m.ChainScopeView })))
const MemberScopeView = lazy(() => import('./why/MemberScopeView').then(m => ({ default: m.MemberScopeView })))
const PairScopeView = lazy(() => import('./why/PairScopeView').then(m => ({ default: m.PairScopeView })))
const GroupScopeView = lazy(() => import('./why/GroupScopeView').then(m => ({ default: m.GroupScopeView })))
const AIAdvisorPanel = lazy(() => import('../AIAdvisorPanel').then(m => ({ default: m.AIAdvisorPanel })))

interface ChainDetailViewProps {
  analysis: ChainAnalysis
  job?: Job | null
  activeSubTab: 'OVERVIEW' | 'WHY' | 'MEMBERS'
  onSubTabChange: (tab: 'OVERVIEW' | 'WHY' | 'MEMBERS') => void
  onNavigateTab?: (tab: any) => void
  onInspectMember?: (member: Member) => void
  onPairContextChange?: (pair: [string, string] | null) => void
  reviewEpoch?: number
  refreshEpoch?: number
  scheduleRefresh?: (key: string, task: RefreshTask) => boolean
  cancelRefresh?: (key: string) => void
  snapshotKey?: string | null
  snapshotContext?: ChainOverviewSnapshotContext
  initialOverviewCards?: ChainOverviewCards | null
}

type WhyScope = 'Chain' | 'Member' | 'Pair' | 'Group'

function getRelativeTime(timeStr: string | null, baseTime: number | null): string {
  if (!timeStr || baseTime === null) return ''
  const t = new Date(timeStr).getTime()
  if (isNaN(t)) return ''
  const diffSec = Math.round((t - baseTime) / 1000)
  if (diffSec <= 0) return 'T₀ (+0s)'
  return `+${diffSec}s`
}

export function ChainDetailView({
  analysis,
  job,
  activeSubTab,
  onSubTabChange,
  onNavigateTab,
  onInspectMember,
  onPairContextChange,
  reviewEpoch = 0,
  refreshEpoch = 0,
  scheduleRefresh,
  cancelRefresh,
  snapshotKey = null,
  snapshotContext,
  initialOverviewCards = null,
}: ChainDetailViewProps) {
  const [whyScope, setWhyScope] = useState<WhyScope>('Chain')
  const [memberFilter, setMemberFilter] = useState<'ALL' | 'CORE' | 'WEAK' | 'CONNECTORS'>('ALL')
  const [memberViewMode, setMemberViewMode] = useState<'TABLE' | 'TREE'>('TABLE')
  const [searchMember, setSearchMember] = useState('')
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
  const [inspectedMember, setInspectedMember] = useState<Member | null>(null)
  const [pairWhyLoad, setPairWhyLoad] = useState<{
    requestKey: string
    payload: PairWhy | null
    reason: string | null
  } | null>(null)
  const [evidenceDetailsOpen, setEvidenceDetailsOpen] = useState(false)
  const [evidenceIds, setEvidenceIds] = useState<string[] | null>(null)
  const openEvidence = (ids?: string[]) => {
    setEvidenceIds(ids?.length ? ids : null)
    setEvidenceDetailsOpen(true)
  }

  const members = useMemo(() => analysis.members ?? [], [analysis.members])
  // App owns the scheduled Overview-cards read and pending retry. Keeping a
  // second request loop here could duplicate requests and race stale results.
  const cardsPayload = initialOverviewCards && initialOverviewCards.status !== 'PENDING'
    ? initialOverviewCards
    : null
  const cardsContext: ChainOverviewCardContext | null = cardsPayload?.status === 'READY'
    ? {
        representative_member: cardsPayload.representative_member,
        topology: cardsPayload.topology ?? undefined,
        quality_assessment: cardsPayload.quality_assessment ?? undefined,
        recommendations: cardsPayload.recommendations ?? undefined,
      }
    : null
  const cardsStatus = cardsPayload?.status ?? 'PENDING'

  const pairSchedulerKey = activeSubTab === 'WHY' && whyScope === 'Pair' && selectedMemberIds.length === 2
    ? JSON.stringify(['pair-why', snapshotKey, analysis.chain_id, selectedMemberIds[0], selectedMemberIds[1]])
    : null
  const pairRequestKey = pairSchedulerKey === null ? null : `${pairSchedulerKey}\u0000${refreshEpoch}`
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
    if (!pairSchedulerKey || !pairRequestKey) return
    const [alarmA, alarmB] = selectedMemberIds
    if (alarmA === alarmB) return
    const requestKey = pairRequestKey
    const task: RefreshTask = async signal => {
      try {
        const payload = await api.pairWhy(analysis.chain_id, alarmA, alarmB, signal)
        if (signal.aborted) return
        if (payload.chain_id !== analysis.chain_id || payload.alarm_id_a !== alarmA || payload.alarm_id_b !== alarmB) {
          setPairWhyLoad({ requestKey, payload: null, reason: 'PAIR_WHY_CONTEXT_MISMATCH' })
          return
        }
        setPairWhyLoad({ requestKey, payload, reason: null })
      } catch (cause: unknown) {
        if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
        setPairWhyLoad({
          requestKey,
          payload: null,
          reason: cause instanceof Error ? cause.message : 'PAIR_WHY_UNAVAILABLE',
        })
      }
    }
    if (scheduleRefresh) {
      scheduleRefresh(pairSchedulerKey, task)
      return
    }
    const controller = new AbortController()
    void task(controller.signal)
    return () => controller.abort()
  }, [analysis.chain_id, pairRequestKey, pairSchedulerKey, scheduleRefresh, selectedMemberIds])

  useEffect(() => () => {
    if (pairSchedulerKey) cancelRefresh?.(pairSchedulerKey)
  }, [cancelRefresh, pairSchedulerKey])

  // Metrics calculation
  const totalMembers = members.length
  const coreCount = members.filter(m => m.role?.toUpperCase().includes('CORE') || m.role?.toUpperCase().includes('ROOT')).length
  const weakCount = members.filter(m => m.role?.toUpperCase().includes('WEAK') || m.role?.toUpperCase().includes('LEAF')).length
  const connectorCount = members.filter(m => m.role?.toUpperCase().includes('CONNECT')).length
  const observedTimes = members
    .map(member => member.canonical_start_time)
    .filter((value): value is string => value !== null)
    .sort((left, right) => Date.parse(left) - Date.parse(right))
  const observedStart = observedTimes[0] ?? null
  const observedEnd = observedTimes.at(-1) ?? null

  const baseTime = useMemo(() => {
    if (!observedStart) return null
    const t = new Date(observedStart).getTime()
    return isNaN(t) ? null : t
  }, [observedStart])

  const durationSecs = useMemo(() => {
    if (!observedStart || !observedEnd) return null
    const s = new Date(observedStart).getTime()
    const e = new Date(observedEnd).getTime()
    if (isNaN(s) || isNaN(e) || e < s) return null
    return Math.round((e - s) / 1000)
  }, [observedStart, observedEnd])

  const durationDisplay = useMemo(() => {
    if (durationSecs === null) return 'N/A'
    if (durationSecs === 0) return 'Đồng thời (0s)'
    const m = Math.floor(durationSecs / 60)
    const s = durationSecs % 60
    if (m === 0) return `${s}s`
    return `${m}m ${s}s`
  }, [durationSecs])

  const distinctDevices = useMemo(() => {
    return Array.from(
      new Set(
        members
          .map(m => m.device_code ?? m.node_reference)
          .filter((v): v is string => Boolean(v))
      )
    )
  }, [members])

  const isTemporalBurst = useMemo(() => {
    return analysis.descriptors?.some(d => d.kind === 'temporal_burst' || d.label.toLowerCase().includes('burst')) ?? false
  }, [analysis.descriptors])

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
    setSelectedMemberIds(prev => {
      const next = new Set(prev)
      if (next.has(alarmId)) {
        next.delete(alarmId)
      } else {
        next.add(alarmId)
      }
      return Array.from(next)
    })
  }

  const handleSelectAll = () => {
    if (selectedMemberIds.length === filteredMembers.length) {
      setSelectedMemberIds([])
    } else {
      setSelectedMemberIds(filteredMembers.map(m => m.alarm_id))
    }
  }

  const handleInspect = (m: Member) => {
    setInspectedMember(m)
    onInspectMember?.(m)
  }

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* TAB 1: OVERVIEW - INCIDENT TRIAGE COCKPIT */}
      {/* ========================================================================= */}
      {activeSubTab === 'OVERVIEW' && (
        <div className="flex flex-col gap-space-lg">
          {/* TẦNG 1: EXECUTIVE KPI DECK (4 CARDS) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-space-md">
            <RepresentativeMemberCard context={cardsContext} status={cardsStatus} />

            {/* Card 2: Duration & Velocity */}
            <div className="bg-[#0b1322] border border-[#1b2b48] hover:border-secondary/50 p-space-md rounded-lg shadow-sm flex flex-col justify-between transition-all">
              <div>
                <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-xs mb-1.5">
                  <span className="flex items-center gap-1.5 text-secondary font-bold uppercase tracking-wider">
                    <span className="material-symbols-outlined text-[16px]">timer</span>
                    Thời lượng quan sát
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded font-mono text-[10px] font-bold ${
                      isTemporalBurst
                        ? 'bg-secondary/15 text-secondary border border-secondary/30'
                        : 'bg-surface-container-high text-on-surface-variant border border-surface-container-highest'
                    }`}
                  >
                    {isTemporalBurst ? 'BURST' : 'KÉO DÀI'}
                  </span>
                </div>
                <div className="flex items-baseline gap-2 mt-1">
                  <span className="font-headline-lg text-2xl font-bold text-on-surface">{durationDisplay}</span>
                  <span className="text-xs text-on-surface-variant font-mono">({totalMembers} cảnh báo)</span>
                </div>
                <p className="text-xs text-on-surface-variant font-mono mt-2">
                  {observedStart ? compactTime(observedStart) : 'N/A'} → {observedEnd ? compactTime(observedEnd) : 'N/A'}
                </p>
              </div>
              <div className="mt-3 pt-2 border-t border-[#17233a] flex items-center justify-between text-xs font-mono text-on-surface-variant">
                <span>Nhịp độ:</span>
                <span className="text-secondary font-bold">
                  {durationSecs && durationSecs > 0 ? `${(totalMembers / (durationSecs / 60)).toFixed(1)} /phút` : `${totalMembers} tức thì`}
                </span>
              </div>
            </div>

            <TopologyCoverageCard context={cardsContext} status={cardsStatus} />
            <ChainQualityCard
              context={cardsContext}
              status={cardsStatus}
              onOpenRecommendations={() => onNavigateTab?.('review')}
              onOpenEvidence={cardsStatus === 'READY' ? openEvidence : undefined}
            />
          </div>

          <RecurrentAlarmHistoryPanel
            chainId={analysis.chain_id}
            snapshotContext={snapshotContext}
            refreshEpoch={refreshEpoch}
          />

          {cardsPayload ? (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => openEvidence()}
                disabled={cardsStatus !== 'READY'}
                className="rounded border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 font-code-sm text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Mở chi tiết evidence của Overview
              </button>
            </div>
          ) : null}

          {cardsPayload ? (
            <EvidenceDetails
              chainId={analysis.chain_id}
              isOpen={evidenceDetailsOpen}
              onClose={() => {
                setEvidenceDetailsOpen(false)
                setEvidenceIds(null)
              }}
              evidenceIds={evidenceIds}
              expectedContext={{
                snapshot_id: cardsPayload.snapshot_id,
                snapshot_version: cardsPayload.snapshot_version,
                topology_version: cardsPayload.topology_version,
                analysis_identity: cardsPayload.analysis_identity ?? null,
              }}
            />
          ) : null}

          {/* TẦNG 2: short grounded explanation of the deterministic rating */}
          <div className="w-full">
            <Suspense
              fallback={
                <div className="flex h-32 items-center justify-center gap-space-sm text-on-surface-variant font-code-sm bg-surface-container-low rounded-lg p-space-md">
                  <span className="material-symbols-outlined animate-spin text-xl text-primary">progress_activity</span>
                  <span>Đang tải nhận định độ vững…</span>
                </div>
              }
            >
              <AIAdvisorPanel
                chainId={analysis.chain_id}
                analysis={analysis}
                job={job}
                onSubTabChange={onSubTabChange}
                onNavigateTab={onNavigateTab}
                reviewEpoch={reviewEpoch}
              />
            </Suspense>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {activeSubTab === 'WHY' && (
        <div className="flex flex-col gap-space-md">
          {/* WHY Scope Selector Bar (Clean, no redundant breadcrumb) */}
          <div className="w-full bg-[#080d17] px-space-md py-1.5 rounded-lg flex flex-wrap items-center justify-between gap-space-sm border border-[#1b273e] shadow-sm">
            <div className="flex items-center gap-2">
              <span className="font-label-caps text-xs uppercase text-secondary font-bold tracking-wider flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[16px]">psychology</span>
                WHY Scope: <span className="text-on-surface">{whyScope}</span>
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

            {/* Scope Switcher Buttons */}
            <div className="flex items-center gap-1 bg-[#0c1424] p-1 rounded-md border border-[#1e2b44]">
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
                    className={`px-3 py-1 rounded font-code-sm text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                      isActive
                        ? 'bg-secondary text-[#070e1d] font-bold shadow-xs'
                        : 'text-on-surface-variant hover:text-on-surface hover:bg-[#14233a]'
                    }`}
                  >
                    <span className="material-symbols-outlined text-[14px]">{icon}</span>
                    <span>{sc}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Render Scope View */}
          <Suspense
            fallback={
              <div className="flex h-48 items-center justify-center gap-space-sm text-on-surface-variant font-code-sm">
                <span className="material-symbols-outlined animate-spin text-lg text-primary">progress_activity</span>
                <span>Loading scope analysis…</span>
              </div>
            }
          >
            {whyScope === 'Chain' && (
              <ChainScopeView
                analysis={analysis}
                job={job}
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
          </Suspense>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: MEMBER DIAGNOSTICS TABLE & TREE */}
      {/* ========================================================================= */}
      {activeSubTab === 'MEMBERS' && (
        <div className="flex flex-col gap-space-md">

          {/* Filter Pills, Search and View Switcher */}
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

            <div className="flex items-center gap-3 flex-wrap">
              {/* View Switcher Toggle */}
              <div className="flex items-center gap-1 bg-[#090f1d] p-1 rounded-md border border-[#1b2b48]">
                <button
                  type="button"
                  onClick={() => setMemberViewMode('TABLE')}
                  className={`px-2.5 py-1 rounded font-code-sm text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                    memberViewMode === 'TABLE'
                      ? 'bg-secondary text-[#080d19] font-bold shadow-xs'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                  title="Xem dạng bảng phẳng chi tiết"
                >
                  <span className="material-symbols-outlined text-[14px]">table_rows</span>
                  <span>Table View</span>
                </button>

              </div>

              {/* Search Bar */}
              <div className="relative flex items-center">
                <span className="material-symbols-outlined absolute left-space-sm text-on-surface-variant text-[16px]">search</span>
                <input
                  type="text"
                  value={searchMember}
                  onChange={e => setSearchMember(e.target.value)}
                  placeholder="Search alarm, device, interface... (Ctrl+K)"
                  className="pl-8 pr-space-md py-space-xs w-64 rounded bg-surface-container-high text-on-surface placeholder:text-on-surface-variant font-code-sm text-code-sm outline-none focus:bg-surface-bright transition-all"
                />
              </div>
            </div>
          </div>


          {/* Render Mode: TABLE View */}
          {memberViewMode === 'TABLE' && (
            <div className="w-full overflow-x-auto bg-surface-container-lowest rounded-lg shadow-md border border-surface-container-highest">
              <table className="w-full text-left font-body-sm text-body-sm text-on-surface">
                <thead className="bg-surface-container font-label-caps text-label-caps uppercase text-on-surface-variant select-none border-b border-surface-container-highest">
                  <tr>
                    <th className="px-space-md py-space-sm w-8 text-center">
                      <input
                        type="checkbox"
                        checked={selectedMemberIds.length > 0 && selectedMemberIds.length === filteredMembers.length}
                        onChange={handleSelectAll}
                        className="rounded bg-surface-container-lowest accent-secondary cursor-pointer"
                      />
                    </th>
                    <th className="px-space-md py-space-sm">Alarm Identity &amp; Type</th>
                    <th className="px-space-md py-space-sm">Timestamp &amp; Delta</th>
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
                    const relTime = getRelativeTime(m.canonical_start_time, baseTime)
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
                            {(m.content || m.raw_content) && (
                              <span
                                className="text-[11px] text-slate-400 font-mono truncate max-w-md mt-0.5"
                                title={m.content || m.raw_content || ''}
                              >
                                {m.content || m.raw_content}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-space-md py-space-xs text-on-surface-variant font-mono">
                          {m.canonical_start_time ? (
                            <div className="flex flex-col">
                              <span className="text-on-surface text-xs font-bold">
                                {compactTime(m.canonical_start_time)}
                              </span>
                              {baseTime !== null && relTime ? (
                                <span
                                  className={`font-code-sm text-[11px] font-bold ${
                                    relTime === 'T₀ (+0s)'
                                      ? 'text-amber-400'
                                      : 'text-amber-400/80'
                                  }`}
                                >
                                  {relTime}
                                </span>
                              ) : null}
                            </div>
                          ) : (
                            'N/A'
                          )}
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
          )}
        </div>
      )}
    </div>
  )
}
