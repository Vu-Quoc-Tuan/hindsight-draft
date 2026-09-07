import { useMemo } from 'react'
import type { ChainAnalysis, Member, WhyScope } from '../../types'
import { InfoTip } from '../../components/InfoTip'

interface ChainScopeViewProps {
  analysis: ChainAnalysis
  distinctDevices: string[]
  observedStart: string | null
  observedEnd: string | null
  onSwitchScope: (scope: WhyScope) => void
  onSelectMember: (member: Member) => void
}

export function ChainScopeView({
  analysis,
  distinctDevices,
  observedStart,
  observedEnd,
  onSwitchScope,
}: ChainScopeViewProps) {
  const members = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Dynamic Device Dominance Analysis
  const { dominantDevice, dominantCount, dominantPct } = useMemo(() => {
    if (members.length === 0) {
      return { dominantDevice: distinctDevices[0] || 'N/A', dominantCount: 0, dominantPct: '0.0' }
    }
    const counts = new Map<string, number>()
    members.forEach(m => {
      const dev = m.device_code || m.node_reference || 'Unknown'
      counts.set(dev, (counts.get(dev) || 0) + 1)
    })
    let maxDev = 'N/A'
    let maxCount = 0
    counts.forEach((c, dev) => {
      if (c > maxCount) {
        maxCount = c
        maxDev = dev
      }
    })
    return {
      dominantDevice: maxDev,
      dominantCount: maxCount,
      dominantPct: ((maxCount / totalAlarms) * 100).toFixed(1),
    }
  }, [members, totalAlarms, distinctDevices])

  // Dynamic Temporal Span
  const { timeSpanLabel, timeSpanSecs, startLabel, endLabel } = useMemo(() => {
    const times = members
      .map(m => m.canonical_start_time)
      .filter((t): t is string => Boolean(t))
      .map(t => Date.parse(t))
      .filter(t => !isNaN(t))
      .sort((a, b) => a - b)

    if (times.length < 2) {
      return {
        timeSpanLabel: 'Concurrent / Singleton',
        timeSpanSecs: 0,
        startLabel: observedStart ? observedStart.slice(11, 19) : 'T0',
        endLabel: observedEnd ? observedEnd.slice(11, 19) : 'T0',
      }
    }

    const diffSec = Math.max(0, Math.round((times[times.length - 1] - times[0]) / 1000))
    const formatted =
      diffSec === 0
        ? '0s (Concurrent)'
        : diffSec < 60
        ? `${diffSec}s Window`
        : `${Math.floor(diffSec / 60)}m ${diffSec % 60}s Span`

    return {
      timeSpanLabel: formatted,
      timeSpanSecs: diffSec,
      startLabel: new Date(times[0]).toISOString().slice(11, 19),
      endLabel: new Date(times[times.length - 1]).toISOString().slice(11, 19),
    }
  }, [members, observedStart, observedEnd])

  // Real Roles Breakdown
  const roleCounts = useMemo(() => {
    const counts: Record<string, number> = { ...(analysis.role_counts || {}) }
    if (Object.keys(counts).length === 0) {
      members.forEach(m => {
        const r = (m.role || 'PERIPHERAL').toUpperCase()
        counts[r] = (counts[r] || 0) + 1
      })
    }
    return counts
  }, [analysis.role_counts, members])

  const coreCount = roleCounts['CORE'] || roleCounts['ROOT'] || 0
  const connectorCount = roleCounts['CONNECTOR'] || 0
  const peripheralCount = roleCounts['PERIPHERAL'] || 0
  const insufficientCount = roleCounts['INSUFFICIENT_DATA'] || 0

  // Real Multi-Evidence Derivation Tag Aggregation
  const dimStats = useMemo(() => {
    const tagFits: Record<string, { total: number; validCount: number; unavailReason?: string }> = {}
    members.forEach(m => {
      ;(m.group_fits || []).forEach(gf => {
        const tag = gf.derivation_tag
        if (!tagFits[tag]) {
          tagFits[tag] = { total: 0, validCount: 0 }
        }
        if (gf.fit !== null && typeof gf.fit === 'number') {
          tagFits[tag].total += gf.fit
          tagFits[tag].validCount += 1
        } else if (!tagFits[tag].unavailReason && gf.unavailable_reasons) {
          const reasonKey = Object.keys(gf.unavailable_reasons)[0]
          if (reasonKey) tagFits[tag].unavailReason = gf.unavailable_reasons[reasonKey]
        }
      })
    })
    return tagFits
  }, [members])

  // Unique Alarm Names
  const uniqueAlarmNames = useMemo(() => {
    const names = new Set(members.map(m => m.alarm_name).filter(Boolean))
    return Array.from(names)
  }, [members])

  const descriptors = analysis.descriptors || []
  const unavailableCaps = analysis.graybox?.unavailable_capabilities || []

  return (
    <div className="flex flex-col gap-space-md animate-fadeIn">
      {/* Top 4 KPI Telemetry Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-space-sm">
        {/* Card 1: Graybox & Evidence Sufficiency */}
        <div className="bg-surface-container rounded-lg p-space-sm border border-secondary/20 flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-[11px] uppercase">
            <span className="flex items-center gap-1">
              Evidence Engine
              <InfoTip text="Chế độ phân tích chứng cứ Graybox/Blackbox và số lượng kênh quy tắc kiểm định đang kích hoạt." />
            </span>
            <span className="text-secondary font-bold font-code-sm">{analysis.graybox?.mode || 'BLACK_BOX'}</span>
          </div>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-code-lg text-lg font-bold text-secondary">
              {analysis.graybox?.rules ?? 0} Rules / {analysis.graybox?.pair_facts ?? 0} Facts
            </span>
            <span className="text-[10px] text-on-surface-variant font-medium">
              {unavailableCaps.length > 0 ? `${unavailableCaps.length} Gated Caps` : 'Full Coverage'}
            </span>
          </div>
        </div>

        {/* Card 2: Peak Burst & Synchronization */}
        <div className="bg-surface-container rounded-lg p-space-sm border border-secondary/20 flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-[11px] uppercase">
            <span className="flex items-center gap-1">
              Temporal Cohesion
              <InfoTip text="Khoảng thời gian phát tác giữa cảnh báo sớm nhất và trễ nhất trong chuỗi sự cố này." />
            </span>
            <span className="text-sky-400 font-bold font-code-sm">Δt = {timeSpanSecs}s</span>
          </div>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-code-lg text-lg font-bold text-sky-400">{timeSpanLabel}</span>
            <span className="text-[10px] text-sky-300 font-medium">
              {startLabel} → {endLabel}
            </span>
          </div>
        </div>

        {/* Card 3: Dominant Infrastructure Anchor */}
        <div className="bg-surface-container rounded-lg p-space-sm border border-secondary/20 flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-[11px] uppercase">
            <span className="flex items-center gap-1">
              Dominant Host Affinity
              <InfoTip text="Tỷ lệ cảnh báo tập trung vào thiết bị neo giữ nòng cốt của chuỗi." />
            </span>
            <span className="text-primary font-bold font-code-sm">{dominantPct}%</span>
          </div>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-code-lg text-lg font-bold text-primary truncate max-w-[140px]" title={dominantDevice}>
              {dominantDevice}
            </span>
            <span className="text-[10px] text-on-surface-variant font-medium">
              {dominantCount}/{totalAlarms} Alarms
            </span>
          </div>
        </div>

        {/* Card 4: Membership Roles Distribution */}
        <div className="bg-surface-container rounded-lg p-space-sm border border-secondary/20 flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between text-on-surface-variant font-label-caps text-[11px] uppercase">
            <span className="flex items-center gap-1">
              Member Roles
              <InfoTip text="Phân bổ vai trò thành viên: Core (lõi), Connector (cầu nối), Peripheral (ngoại vi), Insufficient Data (thiếu dữ liệu)." />
            </span>
            <span className="text-secondary font-bold font-code-sm">{totalAlarms} Total</span>
          </div>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-code-lg text-base font-bold text-on-surface">
              {coreCount}C · {connectorCount}Conn · {peripheralCount}P
            </span>
            <span className="text-[10px] text-amber-400 font-medium">
              {insufficientCount > 0 ? `${insufficientCount} Insuff` : 'Classified'}
            </span>
          </div>
        </div>
      </div>

      {/* 6 Multi-Evidence Attribution Dimensions (Chain Scope) */}
      <div className="flex flex-col gap-space-xs">
        <div className="flex items-center justify-between px-1">
          <h3 className="font-label-caps text-xs uppercase text-on-surface-variant font-bold flex items-center gap-1.5">
            <span className="material-symbols-outlined text-secondary text-[16px]">view_in_ar</span>
            6 Multi-Evidence Attribution Dimensions (Chain Scope)
            <InfoTip text="6 chiều bằng chứng đa tầng chứng minh vì sao toàn bộ chuỗi này lại được gộp với nhau, từ phần cứng, thời gian đến đồ thị mạng." />
          </h3>
          <span className="text-[11px] font-code-sm text-secondary">
            Analysis Method: {analysis.statistics_mode || 'Indexed Tier-1B'}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-sm">
          {/* DIM 01: Entity Reference */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-secondary text-[18px]">dns</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 01: Entity Reference</span>
                  <InfoTip text="Chiều thuộc tính thực thể: Mức độ tập trung của cảnh báo vào máy chủ / router trung tâm." />
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm ${
                  Number(dominantPct) >= 50 ? 'bg-secondary/15 text-secondary' : 'bg-surface-container-highest text-on-surface-variant'
                }`}>
                  {Number(dominantPct) >= 80 ? 'Concentrated' : Number(dominantPct) >= 50 ? 'Dominant' : 'Distributed'}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {distinctDevices.length === 1
                  ? `All ${totalAlarms} alarms originated from single hardware host ${dominantDevice}.`
                  : `Distributed across ${distinctDevices.length} devices; primary cluster centered on ${dominantDevice}.`}
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Anchor: <strong className="text-on-surface">{dominantDevice}</strong></span>
                  <span className="text-secondary font-bold">{dominantPct}% Coverage</span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${dominantPct}%` }}></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>{dominantCount} of {totalAlarms} Alarms</span>
                  <span>{totalAlarms - dominantCount} on other devices</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-secondary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">check_circle</span> Hardware Colocation
              </span>
              <span className="text-on-surface-variant">{distinctDevices.length} Device Nodes</span>
            </div>
          </div>

          {/* DIM 02: Temporal Synchronization */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-sky-400 text-[18px]">timer</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 02: Temporal Synch</span>
                  <InfoTip text="Độ đồng bộ thời gian: Nhóm cảnh báo nổ ra dồn dập trong một cửa sổ trượt hẹp." />
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm ${
                  timeSpanSecs <= 60 ? 'bg-sky-400/15 text-sky-400' : 'bg-amber-400/15 text-amber-300'
                }`}>
                  {timeSpanSecs <= 30 ? 'Synchronous' : timeSpanSecs <= 180 ? 'Burst Wave' : 'Gradual Cascade'}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {timeSpanSecs <= 60
                  ? `High-frequency avalanche: all alarms fired within ${timeSpanLabel}.`
                  : `Sequential cascade spanning ${timeSpanLabel} across observed timeline.`}
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Span: <strong className="text-on-surface">{timeSpanLabel}</strong></span>
                  <span className="text-sky-400 font-bold">{totalAlarms} Events</span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div className="bg-sky-400 h-full rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(15, 100 - timeSpanSecs * 0.5))}%` }}></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>Onset: {startLabel}</span>
                  <span>End: {endLabel}</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-sky-400 flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">bolt</span> {dimStats['temporal_burst']?.validCount ?? 0} Burst Fits
              </span>
              <span className="text-on-surface-variant">Sliding Gate: Active</span>
            </div>
          </div>

          {/* DIM 03: Component & Card Locality */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary text-[18px]">developer_board</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 03: Card Locality</span>
                  <InfoTip text="Bằng chứng phần cứng: Cùng chia sẻ card mạng (linecard), cổng quang hoặc bus nội bộ." />
                </div>
                <span className="bg-primary/15 text-primary px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm">
                  {dimStats['card']?.validCount ? `${dimStats['card'].validCount} Mapped` : 'Evaluated'}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                Linecard and interface component clustering evaluated via chassis slot derivation channels.
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Card Evidence Group</span>
                  <span className="text-primary font-bold">
                    {dimStats['card']?.validCount
                      ? `${((dimStats['card'].validCount / totalAlarms) * 100).toFixed(0)}% Match`
                      : 'Channel Evaluated'}
                  </span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div
                    className="bg-primary h-full rounded-full transition-all"
                    style={{ width: `${dimStats['card']?.validCount ? (dimStats['card'].validCount / totalAlarms) * 100 : 40}%` }}
                  ></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>Channel: E_card</span>
                  <span>Component Bus</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-primary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">view_in_ar</span> Hardware Bus
              </span>
              <span className="text-on-surface-variant">Slot Partitioning</span>
            </div>
          </div>

          {/* DIM 04: Semantic Diversity */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-amber-400 text-[18px]">text_fields</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 04: Semantic Profile</span>
                  <InfoTip text="Độ đồng nhất ngữ nghĩa: Số lượng mẫu tên cảnh báo và phân loại giao thức khác nhau." />
                </div>
                <span className="bg-amber-400/15 text-amber-400 px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm">
                  {uniqueAlarmNames.length} Signature{uniqueAlarmNames.length > 1 ? 's' : ''}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {uniqueAlarmNames.length === 1
                  ? `Uniform alarm type: "${uniqueAlarmNames[0]}" across all members.`
                  : `Multi-symptom cluster: ${uniqueAlarmNames.slice(0, 2).join(', ')}${uniqueAlarmNames.length > 2 ? ` (+${uniqueAlarmNames.length - 2} more)` : ''}.`}
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Semantic Fit Channel:</span>
                  <span className="text-amber-400 font-bold">Channel S</span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div
                    className="bg-amber-400 h-full rounded-full transition-all"
                    style={{ width: `${Math.min(100, Math.max(20, (1 / uniqueAlarmNames.length) * 100))}%` }}
                  ></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>Signatures: {uniqueAlarmNames.length}</span>
                  <span>Syntactic Overlap</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-amber-400 flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">spellcheck</span> Alarm Taxonomy
              </span>
              <span className="text-on-surface-variant">Text Embedding</span>
            </div>
          </div>

          {/* DIM 05: Temporal Delay (T_del) */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-tertiary text-[18px]">timelapse</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 05: Temporal Delay</span>
                  <InfoTip text="Phân phối trễ thời gian có hướng giữa các cặp cảnh báo. Kênh pairwise đánh giá độ trễ lan truyền." />
                </div>
                <span className="bg-tertiary/15 text-tertiary px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm">
                  {dimStats['temporal_delay']?.validCount ? 'Calculated' : 'Pairwise Only'}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {dimStats['temporal_delay']?.unavailReason
                  ? `Full-chain delay model: ${dimStats['temporal_delay'].unavailReason}. Available upon direct pair inspection.`
                  : 'Directional pairwise delay evaluated via sliding window latency gates.'}
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Channel: <strong className="text-on-surface">T_delay</strong></span>
                  <span className="text-tertiary font-bold">
                    {dimStats['temporal_delay']?.validCount ? 'Available' : 'Pair Query Mode'}
                  </span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div className="bg-tertiary h-full rounded-full" style={{ width: dimStats['temporal_delay']?.validCount ? '100%' : '35%' }}></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>Scope: Pairwise Gated</span>
                  <span>Window: 15m Horizon</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-tertiary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">tune</span> Sliding Window
              </span>
              <span className="text-on-surface-variant">Directional Δt</span>
            </div>
          </div>

          {/* DIM 06: Topology Mapping */}
          <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] hover:border-secondary/40 transition-all flex flex-col justify-between">
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-secondary text-[18px]">hub</span>
                  <span className="font-code-md text-sm text-on-surface font-bold">DIM 06: Topology Mapping</span>
                  <InfoTip text="Lớp phủ topo mạng IP & dịch vụ IT: Đánh giá cự ly số bước nhảy (hops) giữa các thiết bị cảnh báo." />
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm ${
                  unavailableCaps.some(c => c.includes('TOPOLOGY')) ? 'bg-slate-700/40 text-slate-400' : 'bg-secondary/15 text-secondary'
                }`}>
                  {unavailableCaps.some(c => c.includes('TOPOLOGY')) ? 'Gate Closed' : 'Overlay Active'}
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {unavailableCaps.some(c => c.includes('TOPOLOGY'))
                  ? 'Topology graph not loaded in current snapshot package. Graph distance bounded by entity co-location.'
                  : `${distinctDevices.length} node entity references mapped to topological adjacency overlay.`}
              </p>
              <div className="bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60 flex flex-col gap-1.5 text-xs font-code-sm">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Topology Gate:</span>
                  <span className="text-secondary font-bold">
                    {unavailableCaps.some(c => c.includes('TOPOLOGY')) ? 'NOT_LOADED' : `${distinctDevices.length} Nodes`}
                  </span>
                </div>
                <div className="w-full bg-[#151f33] h-1.5 rounded-full overflow-hidden flex">
                  <div className="bg-secondary h-full rounded-full" style={{ width: unavailableCaps.some(c => c.includes('TOPOLOGY')) ? '0%' : '100%' }}></div>
                </div>
                <div className="flex justify-between text-[10px] text-on-surface-variant">
                  <span>Channels: Dep_hop, DEP_UPSTREAM</span>
                  <span>Layer 2/3 Adjacency</span>
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-[11px] font-code-sm">
              <span className="text-secondary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">alt_route</span> Bounded Audit
              </span>
              <span className="text-on-surface-variant">{distinctDevices.length} Hosts</span>
            </div>
          </div>
        </div>
      </div>

      {/* Real Descriptor Data Matrix Table (100% Dynamic from analysis.descriptors) */}
      <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-xs">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[20px]">table_chart</span>
            <h3 className="font-headline-md text-sm font-bold text-on-surface">
              Descriptor Data Matrix ({descriptors.length} Contrastive Descriptors)
            </h3>
            <InfoTip text="Bảng mô tả đối sánh thực tế được sinh bởi thuật toán học đặc trưng (Contrastive Descriptors). Mỗi luật thể hiện thuộc tính phân biệt chuỗi này với toàn bộ sự cố còn lại." />
          </div>
          <span className="text-xs font-code-sm text-on-surface-variant">
            Filtered by FDR threshold α = 0.05
          </span>
        </div>

        {descriptors.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-code-sm text-xs">
              <thead>
                <tr className="border-b border-[#1b273e] bg-[#080d17] text-on-surface-variant uppercase text-[10px] tracking-wider">
                  <th className="p-2.5">Kind</th>
                  <th className="p-2.5">Descriptor Label / Rule</th>
                  <th className="p-2.5 text-right">Coverage</th>
                  <th className="p-2.5 text-right">Precision (Global)</th>
                  <th className="p-2.5 text-right">Precision (Local)</th>
                  <th className="p-2.5 text-right">Lift</th>
                  <th className="p-2.5 text-right">F1 Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#151f33]">
                {descriptors.map((desc, idx) => {
                  const isContrastive = desc.kind.toUpperCase() === 'CONTRASTIVE'
                  return (
                    <tr key={`${desc.label}-${idx}`} className="hover:bg-[#0f1b32] transition-colors">
                      <td className="p-2.5">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-code-sm ${
                            isContrastive
                              ? 'bg-secondary/20 text-secondary border border-secondary/30'
                              : 'bg-primary/20 text-primary border border-primary/30'
                          }`}
                        >
                          {desc.kind}
                        </span>
                      </td>
                      <td className="p-2.5 font-semibold text-on-surface">
                        <span className="text-slate-100">{desc.label}</span>
                      </td>
                      <td className="p-2.5 text-right font-semibold text-on-surface">
                        {(desc.coverage * 100).toFixed(1)}%
                      </td>
                      <td className="p-2.5 text-right font-semibold text-sky-400">
                        {(desc.precision_global * 100).toFixed(1)}%
                      </td>
                      <td className="p-2.5 text-right font-semibold text-secondary">
                        {desc.precision_local !== null ? `${(desc.precision_local * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="p-2.5 text-right font-bold text-amber-400">
                        {desc.lift !== null ? `${desc.lift.toFixed(2)}x` : '—'}
                      </td>
                      <td className="p-2.5 text-right font-bold text-emerald-400">
                        {desc.f1.toFixed(3)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-[#080d17] p-6 rounded border border-dashed border-[#1b273e] text-center flex flex-col items-center justify-center">
            <span className="material-symbols-outlined text-on-surface-variant text-3xl mb-1">filter_alt_off</span>
            <p className="font-body-md text-on-surface text-sm font-semibold">No contrastive descriptors extracted</p>
            <p className="text-xs text-on-surface-variant mt-0.5 max-w-md">
              The chain members do not exhibit differential rules meeting minimum global precision and lift criteria against the current snapshot background.
            </p>
          </div>
        )}

        {/* Quick Jump Scope Switcher */}
        <div className="pt-2 border-t border-[#1b273e] flex flex-wrap items-center justify-between gap-space-xs text-xs font-code-sm">
          <span className="text-on-surface-variant">Drill down into fine-grained evidence levels:</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onSwitchScope('Member')}
              className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-semibold transition-colors flex items-center gap-1 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[14px] text-secondary">person_search</span>
              Inspect Member Roles ({members.length}) →
            </button>
            <button
              onClick={() => onSwitchScope('Pair')}
              className="px-2.5 py-1 rounded bg-secondary/15 hover:bg-secondary/25 text-secondary border border-secondary/40 font-semibold transition-colors flex items-center gap-1 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[14px]">compare_arrows</span>
              Open Pair Matrix →
            </button>
            <button
              onClick={() => onSwitchScope('Group')}
              className="px-2.5 py-1 rounded bg-primary/15 hover:bg-primary/25 text-primary border border-primary/40 font-semibold transition-colors flex items-center gap-1 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[14px]">call_split</span>
              Analyze Subclusters →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
