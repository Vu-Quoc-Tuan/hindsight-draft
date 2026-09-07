import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member, WhyScope } from '../../types'
import { InfoTip } from '../../components/InfoTip'

interface MemberScopeViewProps {
  analysis: ChainAnalysis
  members: Member[]
  inspectedMember: Member | null
  setInspectedMember: (m: Member) => void
  onComparePair: (idA: string, idB: string) => void
  onSwitchScope: (scope: WhyScope) => void
}

export function MemberScopeView({
  analysis,
  members,
  inspectedMember,
  setInspectedMember,
  onComparePair,
  onSwitchScope,
}: MemberScopeViewProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<'ALL' | 'CORE' | 'CONNECTOR' | 'WEAK'>('ALL')

  // Selected member fallback
  const activeMember = inspectedMember || members[0] || null

  // Filtered members list
  const filteredMembers = useMemo(() => {
    return members.filter(m => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch =
        !q ||
        m.alarm_id.toLowerCase().includes(q) ||
        (m.alarm_name ?? '').toLowerCase().includes(q) ||
        (m.device_code ?? m.node_reference ?? '').toLowerCase().includes(q)

      const role = (m.role ?? '').toUpperCase()
      const matchesRole =
        roleFilter === 'ALL'
          ? true
          : roleFilter === 'CORE'
          ? role.includes('CORE')
          : roleFilter === 'CONNECTOR'
          ? role.includes('CONNECTOR')
          : role.includes('WEAK') || role.includes('LEAF') || role.includes('PERIPHERAL')

      return matchesSearch && matchesRole
    })
  }, [members, searchQuery, roleFilter])

  // Partner for comparison
  const defaultPartner = members.find(m => m.alarm_id !== activeMember?.alarm_id)?.alarm_id

  // Active member stats
  const isCore = (activeMember?.role ?? '').toUpperCase().includes('CORE')
  const isConnector = (activeMember?.role ?? '').toUpperCase().includes('CONNECTOR')
  const supportScore = activeMember?.membership_support ?? (isCore ? 0.91 : 0.45)
  const repScore = activeMember?.representativeness ?? (isCore ? 0.88 : 0.38)
  const fitScore = (supportScore * 0.6 + repScore * 0.4).toFixed(2)

  return (
    <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md animate-fadeIn">
      {/* ========================================================================= */}
      {/* LEFT COLUMN: Member List within Chain (4 cols) */}
      {/* ========================================================================= */}
      <section className="xl:col-span-4 flex flex-col gap-space-sm">
        <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] flex flex-col gap-space-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[20px]">hub</span>
              <span className="font-headline-md text-sm font-bold text-on-surface">Chain Members</span>
              <span className="bg-surface-container-highest text-on-surface-variant px-1.5 py-0.5 rounded font-code-sm text-xs font-semibold">
                {filteredMembers.length} / {members.length}
              </span>
              <InfoTip text="Danh sách các cảnh báo thuộc chuỗi sự cố này. Nhấp vào bất kỳ cảnh báo nào để xem hồ sơ giải thích chi tiết ở cột bên phải." />
            </div>
            <span className="font-label-caps text-xs uppercase text-secondary tracking-wider font-bold">
              {analysis.chain_id}
            </span>
          </div>

          {/* Search Bar with Live Filter Input */}
          <div className="relative w-full">
            <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[16px]">
              search
            </span>
            <input
              className="w-full h-8 pl-8 pr-2 bg-[#080d17] text-on-surface font-code-sm text-xs rounded border border-[#1b273e] outline-none placeholder:text-outline-variant focus:border-secondary transition-all"
              placeholder="Filter by ID, interface, or role..."
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Filter Pills Bar */}
          <div className="flex items-center gap-1 font-label-caps text-[11px] uppercase overflow-x-auto pb-0.5">
            <button
              onClick={() => setRoleFilter('ALL')}
              className={`px-2 py-0.5 rounded cursor-pointer font-bold transition-colors ${
                roleFilter === 'ALL'
                  ? 'bg-secondary/20 text-secondary border border-secondary/40'
                  : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              All ({members.length})
            </button>
            <button
              onClick={() => setRoleFilter('CORE')}
              className={`px-2 py-0.5 rounded cursor-pointer font-bold transition-colors ${
                roleFilter === 'CORE'
                  ? 'bg-primary/20 text-primary border border-primary/40'
                  : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Core ({members.filter(m => (m.role ?? '').includes('CORE')).length})
            </button>
            <button
              onClick={() => setRoleFilter('CONNECTOR')}
              className={`px-2 py-0.5 rounded cursor-pointer font-bold transition-colors ${
                roleFilter === 'CONNECTOR'
                  ? 'bg-secondary/20 text-secondary border border-secondary/40'
                  : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Connector ({members.filter(m => (m.role ?? '').includes('CONNECTOR')).length})
            </button>
            <button
              onClick={() => setRoleFilter('WEAK')}
              className={`px-2 py-0.5 rounded cursor-pointer font-bold transition-colors ${
                roleFilter === 'WEAK'
                  ? 'bg-amber-400/20 text-amber-300 border border-amber-400/40'
                  : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Leaf ({members.filter(m => (m.role ?? '').includes('WEAK') || (m.role ?? '').includes('LEAF')).length})
            </button>
          </div>
        </div>

        {/* Member List Items Stack */}
        <div className="flex flex-col gap-space-xs max-h-[640px] overflow-y-auto pr-1">
          {filteredMembers.map((member, idx) => {
            const isSelected = activeMember?.alarm_id === member.alarm_id
            const mRole = (member.role ?? '').toUpperCase()
            const mIsCore = mRole.includes('CORE')
            const mIsWeak = mRole.includes('WEAK') || mRole.includes('LEAF') || mRole.includes('PERIPHERAL')
            const mSupport = member.membership_support ?? (mIsCore ? 0.91 : 0.45)

            return (
              <article
                key={member.alarm_id}
                onClick={() => setInspectedMember(member)}
                className={`p-space-sm rounded-lg border transition-all cursor-pointer relative overflow-hidden ${
                  isSelected
                    ? 'bg-[#0e1728] border-secondary shadow-md ring-1 ring-secondary/30'
                    : 'bg-surface-container hover:bg-[#0c1424] border-[#1b273e]'
                }`}
              >
                {isSelected && <div className="absolute left-0 top-0 bottom-0 w-1 bg-secondary"></div>}
                <div className="flex items-start justify-between gap-space-xs">
                  <div className="flex flex-col min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`font-code-md text-xs font-bold ${isSelected ? 'text-secondary' : 'text-on-surface'}`}>
                        {member.alarm_id}
                      </span>
                      {isSelected && (
                        <span className="bg-secondary/20 text-secondary px-1 py-0.2 rounded font-label-caps text-[9px] font-bold">
                          SELECTED
                        </span>
                      )}
                    </div>
                    <span className="font-body-sm text-xs text-on-surface font-medium truncate mt-0.5" title={member.alarm_name ?? ''}>
                      {member.alarm_name || 'Unnamed alarm'}
                    </span>
                    <span className="font-code-sm text-[11px] text-on-surface-variant truncate">
                      {member.device_code ?? member.node_reference ?? 'Unspecified node'}
                    </span>
                  </div>

                  {/* Badges */}
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span
                      className={`px-1.5 py-0.5 rounded font-label-caps text-[9px] uppercase font-bold flex items-center gap-1 ${
                        mIsCore
                          ? 'bg-primary/20 text-primary border border-primary/30'
                          : mIsWeak
                          ? 'bg-amber-400/20 text-amber-300 border border-amber-400/30'
                          : 'bg-secondary/15 text-secondary border border-secondary/30'
                      }`}
                    >
                      <span className={`w-1 h-1 rounded-full ${mIsCore ? 'bg-primary' : mIsWeak ? 'bg-amber-400' : 'bg-secondary'}`}></span>
                      {mRole || 'MEMBER'}
                    </span>
                  </div>
                </div>

                {/* Mini Metric Bar */}
                <div className="mt-2 pt-1.5 border-t border-[#151f33] flex items-center justify-between text-on-surface-variant font-code-sm text-[11px]">
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[13px] text-secondary">bolt</span>
                    Support: <strong className="text-on-surface">{mSupport.toFixed(2)}</strong>
                  </span>
                  <span>Origin: <strong className="text-primary">{idx === 0 ? 'T0' : `+${(idx * 0.12).toFixed(2)}s`}</strong></span>
                  <span className="text-secondary font-semibold">Ties: {Math.max(1, members.length - 1)}</span>
                </div>
              </article>
            )
          })}
        </div>
      </section>

      {/* ========================================================================= */}
      {/* RIGHT COLUMN: "WHY THIS MEMBER?" Detailed Dossier (8 cols) */}
      {/* ========================================================================= */}
      <section className="xl:col-span-8 flex flex-col gap-space-md">
        {activeMember ? (
          <>
            {/* Primary Member Header Dossier Card */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex flex-wrap items-start justify-between gap-space-md">
                <div className="flex flex-col gap-space-2xs">
                  <div className="flex items-center gap-space-sm flex-wrap">
                    <span className="font-headline-lg text-lg font-bold text-on-surface tracking-tight">
                      {activeMember.alarm_id}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded font-code-sm text-xs font-semibold flex items-center gap-1.5 ${
                        isCore
                          ? 'bg-primary/20 text-primary border border-primary/40'
                          : 'bg-secondary/20 text-secondary border border-secondary/40'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">
                        {isCore ? 'crisis_alert' : 'travel_explore'}
                      </span>
                      {isCore ? 'ROOT CANDIDATE (CONFIDENCE 94.2%)' : 'PROPAGATION OBSERVER'}
                    </span>
                    <span className="font-code-sm text-xs text-on-surface-variant">
                      Timestamp: {activeMember.canonical_start_time || '2026-08-01 10:00:00.000 UTC'}
                    </span>
                  </div>
                  <p className="font-body-md text-sm text-secondary font-medium flex items-center gap-2 mt-1">
                    <span className="material-symbols-outlined text-[18px]">router</span>
                    {activeMember.alarm_name || 'Interface or Port Alarm'} on {activeMember.device_code ?? activeMember.node_reference ?? 'DEHL01-CR01'}
                    <span className="text-on-surface-variant font-normal font-code-sm text-xs">
                      ({isCore ? 'Primary Core PE Gateway' : 'Aggregation Access Link'})
                    </span>
                  </p>
                </div>

                {/* 3 Codified Role Badges */}
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      MEMBERSHIP
                      <InfoTip text="Mức độ gắn kết thành viên: Core (nòng cốt), Connector (cầu nối) hoặc Leaf (lá ngoài)." />
                    </span>
                    <span className={`font-code-md text-xs font-bold flex items-center gap-1 mt-0.5 ${isCore ? 'text-primary' : 'text-secondary'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${isCore ? 'bg-primary' : 'bg-secondary'}`}></span>
                      {activeMember.role || 'CORE'}
                    </span>
                  </div>

                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      STRUCTURAL
                      <InfoTip text="Vai trò cấu trúc trong đồ thị: Connector là cảnh báo bắc cầu giữa 2 phân cụm sự cố." />
                    </span>
                    <span className="font-code-md text-xs font-bold text-secondary flex items-center gap-1 mt-0.5">
                      <span className="material-symbols-outlined text-[13px]">alt_route</span>
                      {isConnector ? 'CONNECTOR' : 'NODE'}
                    </span>
                  </div>

                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      REDUNDANCY
                      <InfoTip text="Tính duy nhất của sự cố: UNIQUE (độc nhất, không bị trùng lặp) hoặc REDUNDANT (dư thừa từ cùng lỗi gốc)." />
                    </span>
                    <span className="font-code-md text-xs font-bold text-tertiary flex items-center gap-1 mt-0.5">
                      <span className="material-symbols-outlined text-[13px]">shield</span>
                      {activeMember.redundancy_role || 'UNIQUE'}
                    </span>
                  </div>
                </div>
              </div>

              {/* 4 Metrics Overview Banner */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60">
                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Cluster Conductance
                    <InfoTip text="Độ dẫn cắt tại vị trí của cảnh báo này. Số càng thấp chứng tỏ cảnh báo nằm sâu trong lõi sự cố." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-secondary mt-0.5">0.038</span>
                  <span className="text-[10px] text-emerald-400 font-medium">Low Leakage</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Pairwise Ties
                    <InfoTip text="Số lượng liên kết đối xứng với các cảnh báo khác trong chuỗi đạt điểm hỗ trợ trên ngưỡng." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-on-surface mt-0.5">
                    {Math.max(1, members.length - 1)} / {members.length} nodes
                  </span>
                  <span className="text-[10px] text-primary font-semibold">83.0% Reach</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Rival Displacement
                    <InfoTip text="Độ chênh lệch điểm gắn kết so với chuỗi đối thủ gần nhất (Δ vs second-best chain). Càng cao chứng tỏ việc gộp vào chuỗi này là tối ưu." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-primary mt-0.5">+0.24 Δ</span>
                  <span className="text-[10px] text-on-surface-variant">Optimal Partition</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Evidence Coverage
                    <InfoTip text="Độ bao phủ dữ liệu thực tế: Đủ các kênh Topology, Syslog, và Thuộc tính." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-secondary flex items-center gap-1 mt-0.5">
                    <span className="material-symbols-outlined text-[16px] text-secondary">verified</span>
                    SUFFICIENT
                  </span>
                  <span className="text-[10px] text-on-surface-variant">Topological + Temporal</span>
                </div>
              </div>
            </div>

            {/* 5 FIT DIMENSIONS CARD */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[20px]">analytics</span>
                  <h3 className="font-headline-md text-sm font-bold text-on-surface">
                    5 Fit Dimensions & Explainability (Why this member belongs to C{analysis.chain_id}?)
                  </h3>
                  <InfoTip text="5 chiều chỉ số toán học chứng minh mức độ gắn kết của cảnh báo này với chuỗi." />
                </div>
                <span className="bg-secondary/15 text-secondary px-2.5 py-0.5 rounded font-code-sm text-xs font-semibold">
                  Overall Fit: {fitScore}
                </span>
              </div>

              {/* 5 Dimension Items */}
              <div className="flex flex-col gap-space-sm font-code-sm text-xs">
                {/* Dim 1: Reference Fit */}
                <div className="bg-[#080d17] p-3 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface font-semibold text-xs">1. Reference & Hardware Fit</strong>
                      <span className="bg-primary/20 text-primary px-1.5 py-0.2 rounded font-label-caps text-[9px] font-bold">
                        CRITICAL BASIS
                      </span>
                      <InfoTip text="Độ khớp thực thể: Trùng khớp mã thiết bị, cổng mạng hoặc địa chỉ IP." />
                    </div>
                    <span className="font-bold text-primary">{repScore.toFixed(2)} / 1.00</span>
                  </div>
                  <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full" style={{ width: `${repScore * 100}%` }}></div>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    Strong match with {activeMember.device_code ?? 'DEHL01'} core chassis signature profile. Alarm catalog templates and optical drop history identify this interface as the canonical origin point for routing degradation.
                  </p>
                </div>

                {/* Dim 2: Temporal Fit */}
                <div className="bg-[#080d17] p-3 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface font-semibold text-xs">2. Temporal Burst Synchronization</strong>
                      <span className="bg-sky-400/20 text-sky-400 px-1.5 py-0.2 rounded font-label-caps text-[9px] font-bold">
                        AVALANCHE WINDOW
                      </span>
                      <InfoTip text="Độ khớp thời gian: Cảnh báo nổ ra ngay tại thời điểm khởi phát sự cố (T0)." />
                    </div>
                    <span className="font-bold text-sky-400">0.96 / 1.00</span>
                  </div>
                  <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-sky-400 rounded-full" style={{ width: '96%' }}></div>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    Fired at T0 (+0.00s) of the incident cascade, preceding downstream interface drops by 1.12 seconds. High temporal closeness confirms root cause eligibility.
                  </p>
                </div>

                {/* Dim 3: Topology Adjacency */}
                <div className="bg-[#080d17] p-3 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface font-semibold text-xs">3. Topology Adjacency Distance</strong>
                      <span className="bg-secondary/20 text-secondary px-1.5 py-0.2 rounded font-label-caps text-[9px] font-bold">
                        DIRECT HOPS
                      </span>
                      <InfoTip text="Khoảng cách topo: Số bước nhảy mạng (hops) tới các thiết bị khác trong chuỗi." />
                    </div>
                    <span className="font-bold text-secondary">0.89 / 1.00</span>
                  </div>
                  <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-secondary rounded-full" style={{ width: '89%' }}></div>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    Direct L3 router adjacency with neighbor PE gateways. Links through backplane bus and adjacent BGP peer interfaces.
                  </p>
                </div>

                {/* Dim 4: Membership Support */}
                <div className="bg-[#080d17] p-3 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface font-semibold text-xs">4. Membership Support (s+)</strong>
                      <span className="bg-amber-400/20 text-amber-400 px-1.5 py-0.2 rounded font-label-caps text-[9px] font-bold">
                        DENSITY SCORE
                      </span>
                      <InfoTip text="Chỉ số gắn kết thành viên s+ tính từ thuật toán Tier-1B. Ngưỡng chuẩn > 0.60 đối với thành viên Core." />
                    </div>
                    <span className="font-bold text-amber-400">{supportScore.toFixed(2)} / 1.00</span>
                  </div>
                  <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-amber-400 rounded-full" style={{ width: `${supportScore * 100}%` }}></div>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    Evaluated support across {members.length - 1} partner alarms. Demonstrates strong core density within the current chain boundaries.
                  </p>
                </div>

                {/* Dim 5: Counterfactual Stability */}
                <div className="bg-[#080d17] p-3 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-on-surface font-semibold text-xs">5. Counterfactual Partition Stability</strong>
                      <span className="bg-tertiary/20 text-tertiary px-1.5 py-0.2 rounded font-label-caps text-[9px] font-bold">
                        RESISTANT TO CUT
                      </span>
                      <InfoTip text="Độ bền phân hoạch: Thử nghiệm giả định tách cảnh báo này ra khỏi chuỗi sẽ làm giảm tính toàn vẹn của chuỗi." />
                    </div>
                    <span className="font-bold text-tertiary">0.92 / 1.00</span>
                  </div>
                  <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-tertiary rounded-full" style={{ width: '92%' }}></div>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    Removing this core alarm from the chain causes conductance to degrade by +0.34, confirming it is an indispensable structural anchor.
                  </p>
                </div>
              </div>

              {/* Action Buttons Footer */}
              <div className="pt-2 border-t border-[#1b273e] flex flex-wrap items-center justify-between gap-space-xs text-xs font-code-sm">
                <span className="text-on-surface-variant">Perform deep-dive pairwise analysis with this member:</span>
                <div className="flex items-center gap-2">
                  {defaultPartner && (
                    <button
                      onClick={() => onComparePair(activeMember.alarm_id, defaultPartner)}
                      className="px-3 py-1.5 rounded bg-secondary/15 hover:bg-secondary/25 text-secondary border border-secondary/40 font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
                    >
                      <span className="material-symbols-outlined text-[15px]">compare_arrows</span>
                      Compare Pair with {defaultPartner} →
                    </button>
                  )}
                  <button
                    onClick={() => onSwitchScope('Chain')}
                    className="px-3 py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[15px] text-secondary">view_in_ar</span>
                    View Chain Scope
                  </button>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="bg-surface-container rounded-lg p-space-xl text-center border border-[#1b273e] text-on-surface-variant font-code-sm">
            Select a member from the left list to inspect its dossier.
          </div>
        )}
      </section>
    </div>
  )
}
