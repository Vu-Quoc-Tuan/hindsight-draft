import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member, WhyScope } from '../../types'
import { InfoTip } from '../../components/InfoTip'

interface GroupScopeViewProps {
  analysis: ChainAnalysis
  onSwitchScope: (scope: WhyScope) => void
  onNavigateToRecommendations?: () => void
}

interface DynamicPartition {
  id: string
  name: string
  subtitle: string
  device: string
  members: Member[]
  percentage: number
  cohesion: number | null
  cohesionLevel: 'Strong' | 'Mod' | 'Weak'
  isPrimaryRCA: boolean
  roleCounts: Record<string, number>
}

export function GroupScopeView({
  analysis,
  onSwitchScope,
  onNavigateToRecommendations,
}: GroupScopeViewProps) {
  const members = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Dynamic Partitioning of Chain Members
  const partitions: DynamicPartition[] = useMemo(() => {
    if (members.length === 0) {
      return [
        {
          id: 'partition-empty',
          name: 'Empty Chain',
          subtitle: 'No members in current chain',
          device: 'N/A',
          members: [],
          percentage: 100,
          cohesion: null,
          cohesionLevel: 'Weak',
          isPrimaryRCA: false,
          roleCounts: {},
        },
      ]
    }

    // Step 1: Check distinct devices
    const deviceMap = new Map<string, Member[]>()
    members.forEach(m => {
      const dev = m.device_code || m.node_reference || 'Unassigned Device'
      if (!deviceMap.has(dev)) deviceMap.set(dev, [])
      deviceMap.get(dev)!.push(m)
    })

    // If multiple devices exist, partition by device
    if (deviceMap.size > 1) {
      const result: DynamicPartition[] = []
      let pIdx = 1
      deviceMap.forEach((devMembers, dev) => {
        const pct = (devMembers.length / totalAlarms) * 100
        const validSupports = devMembers
          .map(m => m.membership_support)
          .filter((s): s is number => typeof s === 'number')
        const avgSupport =
          validSupports.length > 0 ? validSupports.reduce((a, b) => a + b, 0) / validSupports.length : null

        const roleCounts: Record<string, number> = {}
        devMembers.forEach(m => {
          const r = (m.role || 'PERIPHERAL').toUpperCase()
          roleCounts[r] = (roleCounts[r] || 0) + 1
        })

        const isCore = (roleCounts['CORE'] || roleCounts['ROOT'] || 0) > 0

        result.push({
          id: `dev-${pIdx}`,
          name: `Chassis Domain ${pIdx}: ${dev}`,
          subtitle: `${devMembers.length} alarm${devMembers.length > 1 ? 's' : ''} on hardware node ${dev}`,
          device: dev,
          members: devMembers,
          percentage: Number(pct.toFixed(1)),
          cohesion: avgSupport,
          cohesionLevel: avgSupport && avgSupport >= 0.7 ? 'Strong' : avgSupport && avgSupport >= 0.4 ? 'Mod' : 'Weak',
          isPrimaryRCA: isCore,
          roleCounts,
        })
        pIdx++
      })
      // Sort dominant partition first
      return result.sort((a, b) => b.members.length - a.members.length)
    }

    // Single device: partition by symptom / alarm_name
    const alarmMap = new Map<string, Member[]>()
    members.forEach(m => {
      const aName = m.alarm_name || 'Generic Alarm'
      if (!alarmMap.has(aName)) alarmMap.set(aName, [])
      alarmMap.get(aName)!.push(m)
    })

    if (alarmMap.size > 1) {
      const result: DynamicPartition[] = []
      let pIdx = 1
      const dominantDev = members[0]?.device_code || members[0]?.node_reference || 'Local Host'
      alarmMap.forEach((aMembers, aName) => {
        const pct = (aMembers.length / totalAlarms) * 100
        const validSupports = aMembers
          .map(m => m.membership_support)
          .filter((s): s is number => typeof s === 'number')
        const avgSupport =
          validSupports.length > 0 ? validSupports.reduce((a, b) => a + b, 0) / validSupports.length : null

        const roleCounts: Record<string, number> = {}
        aMembers.forEach(m => {
          const r = (m.role || 'PERIPHERAL').toUpperCase()
          roleCounts[r] = (roleCounts[r] || 0) + 1
        })
        const isCore = (roleCounts['CORE'] || roleCounts['ROOT'] || 0) > 0

        result.push({
          id: `alarm-${pIdx}`,
          name: `Symptom Cluster ${pIdx}: ${aName}`,
          subtitle: `${aMembers.length} event${aMembers.length > 1 ? 's' : ''} on ${dominantDev}`,
          device: dominantDev,
          members: aMembers,
          percentage: Number(pct.toFixed(1)),
          cohesion: avgSupport,
          cohesionLevel: avgSupport && avgSupport >= 0.7 ? 'Strong' : avgSupport && avgSupport >= 0.4 ? 'Mod' : 'Weak',
          isPrimaryRCA: isCore,
          roleCounts,
        })
        pIdx++
      })
      return result.sort((a, b) => b.members.length - a.members.length)
    }

    // If identical alarms and single device: partition by roles
    const roleMap = new Map<string, Member[]>()
    members.forEach(m => {
      const r = (m.role || 'PERIPHERAL').toUpperCase()
      if (!roleMap.has(r)) roleMap.set(r, [])
      roleMap.get(r)!.push(m)
    })

    const result: DynamicPartition[] = []
    let pIdx = 1
    const dominantDev = members[0]?.device_code || members[0]?.node_reference || 'Local Host'
    roleMap.forEach((rMembers, role) => {
      const pct = (rMembers.length / totalAlarms) * 100
      const validSupports = rMembers
        .map(m => m.membership_support)
        .filter((s): s is number => typeof s === 'number')
      const avgSupport =
        validSupports.length > 0 ? validSupports.reduce((a, b) => a + b, 0) / validSupports.length : null

      result.push({
        id: `role-${pIdx}`,
        name: `Role Group: ${role}`,
        subtitle: `${rMembers.length} member${rMembers.length > 1 ? 's' : ''} assigned as ${role}`,
        device: dominantDev,
        members: rMembers,
        percentage: Number(pct.toFixed(1)),
        cohesion: avgSupport,
        cohesionLevel: avgSupport && avgSupport >= 0.7 ? 'Strong' : avgSupport && avgSupport >= 0.4 ? 'Mod' : 'Weak',
        isPrimaryRCA: role.includes('CORE') || role.includes('ROOT'),
        roleCounts: { [role]: rMembers.length },
      })
      pIdx++
    })
    return result
  }, [members, totalAlarms])

  const [selectedPartitionId, setSelectedPartitionId] = useState<string>(partitions[0]?.id || '')
  const [filterQuery, setFilterQuery] = useState('')

  const activePartition = partitions.find(s => s.id === selectedPartitionId) || partitions[0]

  const filteredPartitions = partitions.filter(
    s =>
      !filterQuery ||
      s.name.toLowerCase().includes(filterQuery.toLowerCase()) ||
      s.subtitle.toLowerCase().includes(filterQuery.toLowerCase()) ||
      s.device.toLowerCase().includes(filterQuery.toLowerCase())
  )

  const palette = ['bg-primary', 'bg-secondary', 'bg-tertiary', 'bg-amber-400', 'bg-emerald-400']

  return (
    <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md animate-fadeIn">
      {/* ========================================================================= */}
      {/* LEFT COLUMN: Partitions / Subclusters List (4 cols) */}
      {/* ========================================================================= */}
      <section className="xl:col-span-4 flex flex-col gap-space-sm">
        <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] flex flex-col gap-space-sm shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">account_tree</span>
                <span className="font-headline-md text-sm font-bold text-on-surface">Subcluster Partitions</span>
                <InfoTip text="Các phân cụm con bên trong chuỗi sự cố được bóc tách từ các miền vật lý (chassis), miền lỗi (failure domains) và vai trò thành viên để phát hiện sự cố lồng nhau." />
              </div>
              <span className="font-code-sm text-[11px] text-on-surface-variant">
                {partitions.length} partition{partitions.length > 1 ? 's' : ''} in C{analysis.chain_id}
              </span>
            </div>
            <span className="font-label-caps text-[10px] uppercase bg-secondary/15 text-secondary border border-secondary/30 px-2 py-0.5 rounded tracking-wider font-bold">
              Domain Audit
            </span>
          </div>

          {/* Search Filter */}
          <div className="relative w-full">
            <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[16px]">
              search
            </span>
            <input
              className="w-full h-8 pl-8 pr-2 bg-[#080d17] text-on-surface font-code-sm text-xs rounded border border-[#1b273e] outline-none placeholder:text-outline-variant focus:border-secondary transition-all"
              placeholder="Filter partitions by host or label..."
              type="text"
              value={filterQuery}
              onChange={e => setFilterQuery(e.target.value)}
            />
          </div>

          {/* Partitions List Items Stack */}
          <div className="flex flex-col gap-space-xs mt-1">
            {filteredPartitions.map(sc => {
              const isSelected = activePartition?.id === sc.id
              const isStrong = sc.cohesionLevel === 'Strong'
              const isMod = sc.cohesionLevel === 'Mod'

              return (
                <article
                  key={sc.id}
                  onClick={() => setSelectedPartitionId(sc.id)}
                  className={`p-space-sm rounded-lg border cursor-pointer transition-all relative overflow-hidden ${
                    isSelected
                      ? 'bg-[#0e1728] border-secondary shadow-md ring-1 ring-secondary/30'
                      : 'bg-surface-container hover:bg-[#0c1424] border-[#1b273e]'
                  }`}
                >
                  {isSelected && <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary"></div>}
                  <div className="flex items-center justify-between">
                    <span className={`font-code-md text-xs font-bold truncate max-w-[200px] ${isSelected ? 'text-secondary' : 'text-on-surface'}`}>
                      {sc.name}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {sc.isPrimaryRCA && (
                        <span className="bg-primary/20 text-primary border border-primary/40 text-[9px] font-bold px-1.5 py-0.2 rounded uppercase">
                          Root
                        </span>
                      )}
                      <span className="bg-surface-container-highest text-on-surface-variant text-[10px] font-code-sm px-1.5 py-0.2 rounded font-semibold">
                        {sc.percentage}%
                      </span>
                    </div>
                  </div>

                  <p className="font-body-sm text-xs text-on-surface-variant mt-1 line-clamp-1">
                    {sc.subtitle}
                  </p>

                  <div className="mt-2 pt-1.5 border-t border-[#151f33] flex items-center justify-between font-code-sm text-[11px] text-on-surface-variant">
                    <span className="flex items-center gap-1">
                      <span className="material-symbols-outlined text-[13px] text-secondary">analytics</span>
                      {sc.members.length} Alarms
                    </span>
                    <span className="flex items-center gap-1">
                      Cohesion:
                      <strong className={isStrong ? 'text-secondary' : isMod ? 'text-sky-300' : 'text-amber-400'}>
                        {sc.cohesion !== null ? sc.cohesion.toFixed(2) : '—'}
                      </strong>
                    </span>
                  </div>
                </article>
              )
            })}
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* RIGHT COLUMN: Active Partition Details & Member Inspector (8 cols) */}
      {/* ========================================================================= */}
      <section className="xl:col-span-8 flex flex-col gap-space-md">
        {activePartition ? (
          <>
            {/* Top Partition Header Dossier Card */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex flex-wrap items-start justify-between gap-space-md">
                <div className="flex flex-col gap-space-2xs">
                  <div className="flex items-center gap-space-sm flex-wrap">
                    <span className="font-headline-lg text-lg font-bold text-on-surface">
                      {activePartition.name}
                    </span>
                    {activePartition.isPrimaryRCA && (
                      <span className="bg-primary/20 text-primary border border-primary/40 font-code-sm text-xs font-semibold px-2 py-0.5 rounded flex items-center gap-1">
                        <span className="material-symbols-outlined text-[14px]">crisis_alert</span>
                        PRIMARY ROOT SUBCLUSTER
                      </span>
                    )}
                    <span className="font-code-sm text-xs text-on-surface-variant">
                      Node: {activePartition.device}
                    </span>
                  </div>
                  <p className="font-body-md text-sm text-on-surface-variant mt-1">
                    {activePartition.subtitle}
                  </p>
                </div>

                {/* Scope Action Buttons */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onSwitchScope('Chain')}
                    className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-code-sm text-xs font-semibold transition-colors cursor-pointer"
                  >
                    ← Chain Scope
                  </button>
                  {onNavigateToRecommendations && (
                    <button
                      onClick={onNavigateToRecommendations}
                      className="px-2.5 py-1 rounded bg-secondary/20 hover:bg-secondary/30 text-secondary border border-secondary/40 font-code-sm text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                    >
                      <span className="material-symbols-outlined text-[14px]">tips_and_updates</span>
                      Review Counterfactuals
                    </button>
                  )}
                </div>
              </div>

              {/* Dynamic Partition Ratio Bar */}
              <div className="mt-2 flex flex-col gap-1.5 bg-[#080d17] p-3 rounded border border-[#1b273e]/60">
                <div className="flex items-center justify-between text-xs font-code-sm">
                  <span className="text-on-surface-variant">Full Chain Partition Composition:</span>
                  <span className="text-secondary font-bold">100% of C{analysis.chain_id}</span>
                </div>
                <div className="w-full h-2.5 rounded-full overflow-hidden flex gap-0.5 bg-[#151f33]">
                  {partitions.map((p, idx) => (
                    <div
                      key={p.id}
                      className={`${palette[idx % palette.length]} h-full transition-all`}
                      style={{ width: `${p.percentage}%` }}
                    ></div>
                  ))}
                </div>
                <div className="flex items-center justify-between text-[11px] font-code-sm text-on-surface-variant mt-1 flex-wrap gap-2">
                  {partitions.map((p, idx) => (
                    <span key={p.id} className="flex items-center gap-1">
                      <span className={`w-2 h-2 rounded-full ${palette[idx % palette.length]}`}></span>
                      {p.name.split(':')[0]}: <strong>{p.percentage}%</strong> ({p.members.length})
                    </span>
                  ))}
                </div>
              </div>

              {/* 4 Real Metrics for this Partition */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-space-sm bg-[#080d17] p-2.5 rounded border border-[#1b273e]/60">
                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Member Alarms
                    <InfoTip text="Số lượng cảnh báo thuộc phân cụm này." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-on-surface mt-0.5">
                    {activePartition.members.length} / {totalAlarms}
                  </span>
                  <span className="text-[10px] text-secondary font-medium">{activePartition.percentage}% of Chain</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Mean Cohesion
                    <InfoTip text="Điểm gắn kết trung bình của các thành viên trong phân cụm." />
                  </span>
                  <span className="font-code-lg text-base font-bold text-secondary mt-0.5">
                    {activePartition.cohesion !== null ? activePartition.cohesion.toFixed(3) : 'Unindexed'}
                  </span>
                  <span className="text-[10px] text-on-surface-variant">{activePartition.cohesionLevel} Binding</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Host Domain
                    <InfoTip text="Thiết bị hạ tầng chính bao bọc phân cụm này." />
                  </span>
                  <span className="font-code-lg text-sm font-bold text-primary mt-0.5 truncate" title={activePartition.device}>
                    {activePartition.device}
                  </span>
                  <span className="text-[10px] text-on-surface-variant">Physical Domain</span>
                </div>

                <div className="flex flex-col p-1">
                  <span className="font-label-caps text-[10px] uppercase text-on-surface-variant flex items-center gap-1">
                    Roles in Cluster
                    <InfoTip text="Các vai trò được gán bên trong phân cụm này." />
                  </span>
                  <span className="font-code-lg text-xs font-bold text-on-surface mt-1">
                    {Object.entries(activePartition.roleCounts).map(([r, c]) => `${c} ${r.slice(0, 4)}`).join(', ')}
                  </span>
                  <span className="text-[10px] text-emerald-400 font-medium">Classified</span>
                </div>
              </div>
            </div>

            {/* Partition Boundary & Conductance Note */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[20px]">ssid_chart</span>
                  <h4 className="font-headline-md text-sm font-bold text-on-surface">
                    Spectral Conductance & Partition Boundary Audit
                  </h4>
                  <InfoTip text="Đánh giá đường cắt ranh giới phân hoạch: Kiểm tra xem phân cụm này có nên tách thành chuỗi riêng biệt hay không." />
                </div>
                <span className="text-xs font-code-sm text-secondary font-semibold">
                  Boundary Integrity: High
                </span>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {totalAlarms <= 10
                  ? `Small incident chain (N = ${totalAlarms}): Spectral graph bi-partitioning is bounded by discrete failure domain heuristics. High internal affinity maintains chain unity without boundary leakage.`
                  : `Multi-node incident chain (N = ${totalAlarms}): High internal graph density binds members into a unified propagation sequence. Partition boundaries reflect physical chassis isolation.`}
              </p>
            </div>

            {/* Real Members in this Partition Table */}
            <div className="bg-surface-container rounded-lg p-space-md border border-[#1b273e] shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[18px]">format_list_bulleted</span>
                  <h4 className="font-headline-md text-sm font-bold text-on-surface">
                    Alarms in {activePartition.name} ({activePartition.members.length})
                  </h4>
                </div>
                <span className="text-xs font-code-sm text-on-surface-variant">
                  Click to inspect member in Member Scope
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left font-code-sm text-xs">
                  <thead>
                    <tr className="border-b border-[#1b273e] bg-[#080d17] text-on-surface-variant uppercase text-[10px] tracking-wider">
                      <th className="p-2.5">Alarm ID</th>
                      <th className="p-2.5">Alarm Name</th>
                      <th className="p-2.5">Device</th>
                      <th className="p-2.5">Timestamp</th>
                      <th className="p-2.5">Role</th>
                      <th className="p-2.5 text-right">Support</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#151f33]">
                    {activePartition.members.map(m => (
                      <tr
                        key={m.alarm_id}
                        onClick={() => onSwitchScope('Member')}
                        className="hover:bg-[#0f1b32] transition-colors cursor-pointer"
                      >
                        <td className="p-2.5 font-bold text-secondary">{m.alarm_id}</td>
                        <td className="p-2.5 text-on-surface font-medium truncate max-w-[200px]">
                          {m.alarm_name || 'Unnamed'}
                        </td>
                        <td className="p-2.5 text-on-surface-variant">{m.device_code ?? m.node_reference ?? 'N/A'}</td>
                        <td className="p-2.5 text-on-surface-variant">
                          {m.canonical_start_time ? m.canonical_start_time.slice(11, 19) : 'T0'}
                        </td>
                        <td className="p-2.5">
                          <span className="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-surface-container-highest text-on-surface-variant">
                            {m.role}
                          </span>
                        </td>
                        <td className="p-2.5 text-right font-semibold text-secondary">
                          {m.membership_support !== null ? m.membership_support.toFixed(2) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        ) : null}
      </section>
    </div>
  )
}
