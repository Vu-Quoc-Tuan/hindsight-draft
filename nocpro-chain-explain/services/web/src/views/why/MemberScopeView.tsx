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
  const [roleFilter, setRoleFilter] = useState<'ALL' | 'CORE' | 'CONNECTOR' | 'PERIPHERAL' | 'INSUFFICIENT_DATA'>('ALL')

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
          ? role.includes('CORE') || role.includes('ROOT')
          : roleFilter === 'CONNECTOR'
          ? role.includes('CONNECTOR')
          : roleFilter === 'PERIPHERAL'
          ? role.includes('PERIPHERAL') || role.includes('LEAF') || role.includes('WEAK')
          : role.includes('INSUFFICIENT')

      return matchesSearch && matchesRole
    })
  }, [members, searchQuery, roleFilter])

  // Active member helpers
  const roleName = (activeMember?.role ?? 'PERIPHERAL').toUpperCase()
  const isCore = roleName.includes('CORE') || roleName.includes('ROOT')
  const isConnector = roleName.includes('CONNECTOR')
  const isInsufficient = roleName.includes('INSUFFICIENT')

  const defaultPartner = members.find(m => m.alarm_id !== activeMember?.alarm_id)?.alarm_id

  return (
    <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md animate-fadeIn">
      {/* ========================================================================= */}
      {/* LEFT COLUMN: Member List within Chain (4 cols) */}
      {/* ========================================================================= */}
      <section className="xl:col-span-4 flex flex-col gap-space-sm">
        <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] flex flex-col gap-space-sm shadow-sm">
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

          {/* Search Bar */}
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
          <div className="flex items-center gap-1 font-label-caps text-[10px] uppercase overflow-x-auto pb-0.5">
            <button
              onClick={() => setRoleFilter('ALL')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                roleFilter === 'ALL'
                  ? 'bg-secondary text-on-secondary font-bold'
                  : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'
              }`}
            >
              All ({members.length})
            </button>
            <button
              onClick={() => setRoleFilter('CORE')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                roleFilter === 'CORE'
                  ? 'bg-primary text-on-primary font-bold'
                  : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Core
            </button>
            <button
              onClick={() => setRoleFilter('CONNECTOR')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                roleFilter === 'CONNECTOR'
                  ? 'bg-secondary text-on-secondary font-bold'
                  : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Connector
            </button>
            <button
              onClick={() => setRoleFilter('PERIPHERAL')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                roleFilter === 'PERIPHERAL'
                  ? 'bg-tertiary text-on-tertiary font-bold'
                  : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Periph
            </button>
            <button
              onClick={() => setRoleFilter('INSUFFICIENT_DATA')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                roleFilter === 'INSUFFICIENT_DATA'
                  ? 'bg-amber-400 text-slate-950 font-bold'
                  : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Insuff
            </button>
          </div>
        </div>

        {/* Member Cards List */}
        <div className="flex flex-col gap-space-xs max-h-[640px] overflow-y-auto pr-1">
          {filteredMembers.map((member) => {
            const isSelected = activeMember?.alarm_id === member.alarm_id
            const mRole = (member.role ?? '').toUpperCase()
            const mIsCore = mRole.includes('CORE') || mRole.includes('ROOT')
            const mIsConnector = mRole.includes('CONNECTOR')
            const mIsInsuff = mRole.includes('INSUFFICIENT')

            return (
              <article
                key={member.alarm_id}
                onClick={() => setInspectedMember(member)}
                className={`p-space-sm rounded-lg border transition-all cursor-pointer relative overflow-hidden ${
                  isSelected
                    ? 'bg-[#0e1728] border-secondary shadow-md ring-1 ring-secondary/40'
                    : 'bg-surface-container hover:bg-[#0c1424] border-[#1b273e]'
                }`}
              >
                {isSelected && <div className="absolute left-0 top-0 bottom-0 w-1 bg-secondary"></div>}
                <div className="flex items-center justify-between">
                  <span className={`font-code-md text-xs font-bold ${isSelected ? 'text-secondary' : 'text-on-surface'}`}>
                    {member.alarm_id}
                  </span>
                  <span
                    className={`px-1.5 py-0.2 text-[9px] font-bold uppercase rounded font-code-sm ${
                      mIsCore
                        ? 'bg-primary/20 text-primary border border-primary/30'
                        : mIsConnector
                        ? 'bg-secondary/20 text-secondary border border-secondary/30'
                        : mIsInsuff
                        ? 'bg-amber-400/20 text-amber-300 border border-amber-400/30'
                        : 'bg-surface-container-highest text-on-surface-variant'
                    }`}
                  >
                    {member.role || 'PERIPHERAL'}
                  </span>
                </div>

                <div className="mt-1 flex flex-col">
                  <span className="font-body-sm text-xs text-on-surface font-medium truncate" title={member.alarm_name ?? ''}>
                    {member.alarm_name || 'Unnamed Alarm'}
                  </span>
                  <span className="font-code-sm text-[11px] text-on-surface-variant truncate">
                    {member.device_code ?? member.node_reference ?? 'No Host'} · {member.canonical_start_time ? member.canonical_start_time.slice(11, 19) : 'T0'}
                  </span>
                </div>

                <div className="mt-2 pt-1.5 border-t border-[#151f33] flex items-center justify-between text-on-surface-variant font-code-sm text-[11px]">
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[13px] text-secondary">bolt</span>
                    Support: <strong className="text-on-surface">{member.membership_support !== null ? member.membership_support.toFixed(2) : '—'}</strong>
                  </span>
                  <span>Cov: <strong className="text-sky-400">{(member.availability_coverage * 100).toFixed(0)}%</strong></span>
                  <span className="text-secondary font-semibold">Groups: {member.computable_groups}</span>
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
                          : isConnector
                          ? 'bg-secondary/20 text-secondary border border-secondary/40'
                          : isInsufficient
                          ? 'bg-amber-400/20 text-amber-300 border border-amber-400/40'
                          : 'bg-surface-container-highest text-on-surface-variant border border-[#1b273e]'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">
                        {isCore ? 'crisis_alert' : isConnector ? 'alt_route' : 'travel_explore'}
                      </span>
                      {activeMember.role}
                    </span>
                    <span className="font-code-sm text-xs text-on-surface-variant">
                      Timestamp: {activeMember.canonical_start_time || 'N/A'}
                    </span>
                  </div>
                  <p className="font-body-md text-sm text-secondary font-medium flex items-center gap-2 mt-1">
                    <span className="material-symbols-outlined text-[18px]">router</span>
                    {activeMember.alarm_name || 'Alarm'} on <strong className="text-on-surface">{activeMember.device_code ?? activeMember.node_reference ?? 'N/A'}</strong>
                  </p>
                </div>

                {/* 3 Codified Role Badges */}
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      ROLE
                      <InfoTip text="Vai trò được phân bổ dựa trên kiểm định độ dẫn cắt và trọng số liên kết nội tại." />
                    </span>
                    <span className={`font-code-md text-xs font-bold flex items-center gap-1 mt-0.5 ${isCore ? 'text-primary' : 'text-secondary'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${isCore ? 'bg-primary' : 'bg-secondary'}`}></span>
                      {activeMember.role}
                    </span>
                  </div>

                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      REDUNDANCY
                      <InfoTip text="Tính độc nhất của sự cố: UNIQUE (độc nhất) hoặc REDUNDANT (dư thừa từ cùng gốc lỗi)." />
                    </span>
                    <span className="font-code-md text-xs font-bold text-tertiary flex items-center gap-1 mt-0.5">
                      <span className="material-symbols-outlined text-[13px]">shield</span>
                      {activeMember.redundancy_role || 'UNIQUE'}
                    </span>
                  </div>

                  <div className="bg-[#080d17] px-3 py-1.5 rounded border border-[#1b273e] flex flex-col items-center">
                    <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold flex items-center gap-1">
                      EVIDENCE GROUPS
                      <InfoTip text="Số lượng nhóm kênh chứng cứ có thể tính toán được cho cảnh báo này." />
                    </span>
                    <span className="font-code-md text-xs font-bold text-sky-400 flex items-center gap-1 mt-0.5">
                      <span className="material-symbols-outlined text-[13px]">fact_check</span>
                      {activeMember.computable_groups} Groups
                    </span>
                  </div>
                </div>
              </div>

              {/* 4 Real Metrics Overview Banner */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60">
                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Membership Support
                    <InfoTip text="Điểm số hỗ trợ thành viên thực tế đo được từ các kênh liên kết." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-secondary mt-0.5">
                    {activeMember.membership_support !== null ? activeMember.membership_support.toFixed(3) : 'Unindexed'}
                  </span>
                  <span className="text-[10px] text-on-surface-variant">
                    {activeMember.membership_support !== null && activeMember.membership_support >= 0.7 ? 'Strong Affinity' : 'Moderate'}
                  </span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Availability Coverage
                    <InfoTip text="Tỷ lệ bao phủ kênh dữ liệu thực tế thỏa mãn điều kiện khả dụng." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-on-surface mt-0.5">
                    {(activeMember.availability_coverage * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-primary font-semibold">Data Channel Gate</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Competitor Margins
                    <InfoTip text="Số lượng chuỗi đối thủ được so sánh độ gắn kết." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-primary mt-0.5">
                    {activeMember.margins?.length ?? 0} Evaluated
                  </span>
                  <span className="text-[10px] text-on-surface-variant">Rival Chain Delta</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Representativeness
                    <InfoTip text="Mức độ đại diện cho toàn bộ chuỗi." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-secondary flex items-center gap-1 mt-0.5">
                    {activeMember.representativeness !== null ? activeMember.representativeness.toFixed(3) : '—'}
                  </span>
                  <span className="text-[10px] text-on-surface-variant">Global Prototype</span>
                </div>
              </div>
            </div>

            {/* REAL GROUP FITS DIMENSIONS (100% Dynamic from activeMember.group_fits) */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[20px]">analytics</span>
                  <h3 className="font-headline-md text-sm font-bold text-on-surface">
                    Evidence Fit Dimensions ({activeMember.group_fits?.length ?? 0} Evaluated Channels)
                  </h3>
                  <InfoTip text="Các chiều bằng chứng cụ thể giải thích vì sao cảnh báo này thuộc về chuỗi sự cố này." />
                </div>
                <span className="bg-secondary/15 text-secondary px-2.5 py-0.5 rounded font-code-sm text-xs font-semibold">
                  Chain: {analysis.chain_id}
                </span>
              </div>

              {activeMember.group_fits && activeMember.group_fits.length > 0 ? (
                <div className="flex flex-col gap-space-xs font-code-sm text-xs">
                  {activeMember.group_fits.map((gf, idx) => {
                    const tagTitle =
                      gf.derivation_tag === 'device' ? 'Device Hardware Co-location'
                      : gf.derivation_tag === 'card' ? 'Interface & Linecard Locality'
                      : gf.derivation_tag === 'site' ? 'Physical Site Co-location'
                      : gf.derivation_tag === 'semantic' ? 'Semantic Textual Alignment'
                      : gf.derivation_tag === 'temporal_burst' ? 'Temporal Burst Concurrency'
                      : gf.derivation_tag === 'temporal_delay' ? 'Directional Latency Delay'
                      : gf.derivation_tag === 'dependency_hop' ? 'Physical Topology Hop'
                      : gf.derivation_tag.includes('topology-capability-unavailable') ? 'Upstream Topology Gate'
                      : gf.derivation_tag

                    const isAvailable = gf.fit !== null && typeof gf.fit === 'number'
                    const unavailReason = gf.unavailable_reasons ? Object.values(gf.unavailable_reasons)[0] : null

                    return (
                      <div key={`${gf.derivation_tag}-${idx}`} className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <strong className="text-on-surface font-semibold text-xs">{tagTitle}</strong>
                            <span className="text-[10px] text-on-surface-variant font-mono">({gf.derivation_tag})</span>
                          </div>
                          {isAvailable ? (
                            <span className={`px-2 py-0.2 rounded text-[10px] font-bold uppercase font-code-sm ${
                              gf.fit! >= 0.8 ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                              gf.fit! >= 0.4 ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30' :
                              'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            }`}>
                              Fit: {(gf.fit! * 100).toFixed(0)}%
                            </span>
                          ) : (
                            <span className="bg-slate-700/30 text-slate-400 border border-slate-700/50 px-2 py-0.2 rounded text-[10px] font-bold uppercase font-code-sm">
                              UNAVAILABLE
                            </span>
                          )}
                        </div>

                        {isAvailable ? (
                          <div className="flex items-center gap-3">
                            <div className="flex-1 bg-[#151f33] h-1.5 rounded-full overflow-hidden">
                              <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${gf.fit! * 100}%` }}></div>
                            </div>
                            <span className="text-on-surface-variant text-[11px] shrink-0">
                              Score: <strong className="text-on-surface">{gf.fit!.toFixed(4)}</strong>
                            </span>
                          </div>
                        ) : unavailReason ? (
                          <p className="text-[11px] text-on-surface-variant bg-[#0c1424] px-2 py-1 rounded border border-[#1b273e]/60">
                            Reason: <span className="text-amber-300/90">{unavailReason}</span>
                          </p>
                        ) : null}

                        <div className="flex items-center gap-2 text-[10px] text-on-surface-variant">
                          <span>Channels:</span>
                          <div className="flex items-center gap-1 flex-wrap">
                            {gf.channels.map(ch => (
                              <span key={ch} className="bg-surface-container px-1.5 py-0.2 rounded text-secondary border border-[#1b273e]">
                                {ch}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-xs text-on-surface-variant bg-[#080d17] p-4 rounded border border-dashed border-[#1b273e] text-center">
                  No individual derivation fits available for this member.
                </p>
              )}
            </div>

            {/* REAL COMPETITOR DISPLACEMENT MARGINS */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[20px]">compare</span>
                  <h3 className="font-headline-md text-sm font-bold text-on-surface">
                    Competitor Displacement Margins ({activeMember.margins?.length ?? 0} Rival Chains Evaluated)
                  </h3>
                  <InfoTip text="Khoảng cách vượt trội (Margin) của cảnh báo này khi thuộc chuỗi hiện tại so với các chuỗi đối thủ lân cận." />
                </div>
              </div>

              {activeMember.margins && activeMember.margins.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-xs font-code-sm text-xs">
                  {activeMember.margins.map((m, idx) => (
                    <div key={`${m.compared_chain_id}-${idx}`} className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex items-center justify-between">
                      <div className="flex flex-col">
                        <span className="font-semibold text-on-surface flex items-center gap-1">
                          <span className="material-symbols-outlined text-secondary text-[14px]">arrow_right_alt</span>
                          vs Chain C{m.compared_chain_id}
                        </span>
                        <span className="text-[10px] text-on-surface-variant">
                          {m.computable_groups} Evidence Groups Evaluated
                        </span>
                      </div>
                      <div className="flex flex-col items-end">
                        <span className="text-primary font-bold text-sm">
                          {m.margin !== null ? `+${m.margin.toFixed(3)} Δ` : '—'}
                        </span>
                        <span className="text-[9px] text-emerald-400 font-medium">Optimal Partition</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-on-surface-variant bg-[#080d17] p-3 rounded border border-dashed border-[#1b273e] text-center">
                  No overlapping competitor chains identified in the current snapshot partition.
                </p>
              )}
            </div>

            {/* Bottom Scope Navigation & Pair Comparison */}
            <div className="pt-2 border-t border-[#1b273e] flex flex-wrap items-center justify-between gap-space-xs text-xs font-code-sm">
              <button
                type="button"
                onClick={() => onSwitchScope('Chain')}
                className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-semibold transition-colors cursor-pointer flex items-center gap-1"
              >
                ← Back to Chain Scope
              </button>
              {defaultPartner && (
                <button
                  type="button"
                  onClick={() => onComparePair(activeMember.alarm_id, defaultPartner)}
                  className="px-3 py-1 rounded bg-secondary/15 hover:bg-secondary/25 text-secondary border border-secondary/40 font-code-sm text-xs font-bold flex items-center gap-1.5 cursor-pointer transition-colors"
                >
                  <span className="material-symbols-outlined text-[15px]">compare_arrows</span>
                  Compare with {defaultPartner} →
                </button>
              )}
            </div>
          </>
        ) : (
          <div className="bg-surface-container rounded-lg p-space-xl border border-dashed border-[#1b273e] text-center flex flex-col items-center justify-center">
            <span className="material-symbols-outlined text-4xl text-on-surface-variant mb-2">person_search</span>
            <p className="font-body-md text-on-surface font-semibold">Select a member from the left list to inspect evidence dossier.</p>
          </div>
        )}
      </section>
    </div>
  )
}
