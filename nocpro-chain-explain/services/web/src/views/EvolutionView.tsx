import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member } from '../types'
import { EvolutionPanel } from '../EvolutionPanel'
import type { RefreshTask } from '../liveUpdates'
import { InfoTip } from '../components/InfoTip'

interface EvolutionViewProps {
  analysis: ChainAnalysis
  initialTab?: 'timeline' | 'cross_snapshot'
  resourceKey?: string
  refreshEpoch?: number
  expectedSnapshotId?: string | null
  expectedSnapshotVersion?: string | null
  scheduleRefresh?: (key: string, task: RefreshTask) => boolean
  cancelRefresh?: (key: string) => void
  onLoadError?: (message: string | null) => void
}

export function EvolutionView({
  analysis,
  initialTab = 'timeline',
  resourceKey,
  refreshEpoch,
  expectedSnapshotId,
  expectedSnapshotVersion,
  scheduleRefresh,
  cancelRefresh,
  onLoadError,
}: EvolutionViewProps) {
  const [activeTab] = useState<'timeline' | 'cross_snapshot'>(initialTab)
  const [selectedAlarmId, setSelectedAlarmId] = useState<string | null>(null)
  const [hoveredAlarmId, setHoveredAlarmId] = useState<string | null>(null)

  const members: Member[] = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Chronologically sorted alarms
  const sortedAlarms = useMemo(() => {
    return [...members].sort((a, b) => {
      const timeA = a.canonical_start_time ? Date.parse(a.canonical_start_time) : 0
      const timeB = b.canonical_start_time ? Date.parse(b.canonical_start_time) : 0
      return timeA - timeB
    })
  }, [members])

  // First Observed Alarm (T0) and arrival metrics
  const { firstObservedAlarm, timeSpanSecs, alarmDeltas, dominantDevice, dominantCount } = useMemo(() => {
    const firstObserved = sortedAlarms[0] || null
    const t0 = firstObserved?.canonical_start_time ? Date.parse(firstObserved.canonical_start_time) : 0
    const last = sortedAlarms[sortedAlarms.length - 1] || null
    const tEnd = last?.canonical_start_time ? Date.parse(last.canonical_start_time) : t0

    const diffSec = Math.max(0, Math.round((tEnd - t0) / 1000))

    const deltas = sortedAlarms.map((m, idx) => {
      const t = m.canonical_start_time ? Date.parse(m.canonical_start_time) : t0
      const deltaSec = isNaN(t) ? 0 : Math.max(0, (t - t0) / 1000)
      return {
        member: m,
        stepIndex: idx + 1,
        deltaSec,
        formattedDelta: deltaSec === 0 ? '+0.00s' : `+${deltaSec.toFixed(2)}s`,
        timestamp: m.canonical_start_time
          ? new Date(m.canonical_start_time).toISOString().slice(11, 19)
          : 'N/A',
      }
    })

    // Dominant device
    const counts = new Map<string, number>()
    members.forEach(m => {
      const dev = m.device_code || m.node_reference || 'UNKNOWN'
      counts.set(dev, (counts.get(dev) || 0) + 1)
    })
    let maxDev = 'UNKNOWN'
    let maxC = 0
    counts.forEach((c, dev) => {
      if (c > maxC) {
        maxC = c
        maxDev = dev
      }
    })

    return {
      firstObservedAlarm: firstObserved,
      timeSpanSecs: diffSec,
      alarmDeltas: deltas,
      dominantDevice: maxDev,
      dominantCount: maxC,
    }
  }, [sortedAlarms, members])

  // Sparkline / SVG Growth Curve calculation
  const svgCurveData = useMemo(() => {
    const width = 840
    const height = 180
    const paddingX = 55
    const paddingY = 30

    if (alarmDeltas.length === 0) return { points: '', area: '', markers: [] }

    const maxDelta = Math.max(1, timeSpanSecs)
    const markers = alarmDeltas.map((d, idx) => {
      const x = Math.round(paddingX + (d.deltaSec / maxDelta) * (width - 2 * paddingX))
      const y = Math.round(
        height - paddingY - ((idx + 1) / Math.max(1, alarmDeltas.length)) * (height - 2 * paddingY)
      )
      return { ...d, x, y, count: idx + 1 }
    })

    const pointPairs = markers.map(m => `${m.x},${m.y}`)
    const polyline = pointPairs.join(' ')
    const firstX = markers[0]?.x || paddingX
    const lastX = markers[markers.length - 1]?.x || width - paddingX
    const polygon = `${firstX},${height - paddingY} ${polyline} ${lastX},${height - paddingY}`

    return { points: polyline, area: polygon, markers }
  }, [alarmDeltas, timeSpanSecs])

  const arrivalRate = timeSpanSecs > 0 ? (totalAlarms / timeSpanSecs).toFixed(2) : totalAlarms.toFixed(2)

  const activeAlarmId = selectedAlarmId ?? firstObservedAlarm?.alarm_id ?? alarmDeltas[0]?.member.alarm_id ?? null
  const activeIndex = alarmDeltas.findIndex(d => d.member.alarm_id === activeAlarmId)
  const activeItem = (activeIndex >= 0 ? alarmDeltas[activeIndex] : null) ?? alarmDeltas[0] ?? null
  const prevItem = activeIndex > 0 ? alarmDeltas[activeIndex - 1] : null
  const intervalFromPrevSec = prevItem ? Math.max(0, activeItem.deltaSec - prevItem.deltaSec) : 0
  const selectedMarker = svgCurveData.markers.find(m => m.member.alarm_id === activeAlarmId) ?? null

  const handlePrevStep = () => {
    if (activeIndex > 0) {
      setSelectedAlarmId(alarmDeltas[activeIndex - 1].member.alarm_id)
    }
  }

  const handleNextStep = () => {
    if (activeIndex >= 0 && activeIndex < alarmDeltas.length - 1) {
      setSelectedAlarmId(alarmDeltas[activeIndex + 1].member.alarm_id)
    }
  }

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* 1. Header & Context Strip */}
      {/* ========================================================================= */}
      <section className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#080d17] shadow-md">
        <div className="flex flex-col gap-space-sm p-space-md lg:flex-row lg:items-center lg:justify-between border-b border-[#1b273e]">
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-secondary text-[20px]">
              timeline
            </span>
            <h1 className="font-headline-md text-base font-semibold text-on-surface flex items-center gap-2">
              <span>Alarm Arrival Timeline</span>
              <InfoTip text="Trình tự xuất hiện cảnh báo theo mốc thời gian ghi nhận trong cửa sổ quan sát. Theo dõi thời điểm quan sát đầu T₀ và phân bố thời gian đến của các cảnh báo." />
            </h1>
          </div>
        </div>

        {/* Operational Metrics Bar matching ui/15 */}
        <div className="grid grid-cols-1 divide-y divide-[#1b273e] sm:grid-cols-4 sm:divide-y-0 sm:divide-x bg-[#0c1424]">
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              First Observed Alarm (T₀)
            </small>
            <strong className="font-code-sm text-xs text-secondary font-bold truncate">
              {firstObservedAlarm?.alarm_id || 'N/A'} ({firstObservedAlarm?.device_code || dominantDevice})
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Arrival Velocity
            </small>
            <strong className="font-code-sm text-xs text-on-surface font-bold">
              {totalAlarms} Alarms in {timeSpanSecs > 0 ? `${timeSpanSecs.toFixed(1)}s` : '0.0s'} ({arrivalRate}/s)
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Dominant Host Share
            </small>
            <strong className="font-code-sm text-tertiary font-bold truncate">
              {dominantDevice} ({dominantCount}/{totalAlarms}, {((dominantCount / totalAlarms) * 100).toFixed(0)}%)
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              View Focus
            </small>
            <strong className="font-code-sm text-xs text-sky-400 font-bold">
              Intra-Chain Sequence
            </strong>
          </div>
        </div>
      </section>

      {/* 2. Content */}
      {activeTab === 'cross_snapshot' ? (
        <div className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#0c1424] p-space-md shadow-md animate-fadeIn">
          <EvolutionPanel
            chainId={analysis.chain_id}
            resourceKey={resourceKey}
            refreshEpoch={refreshEpoch}
            expectedSnapshotId={expectedSnapshotId}
            expectedSnapshotVersion={expectedSnapshotVersion}
            scheduleRefresh={scheduleRefresh}
            cancelRefresh={cancelRefresh}
            onLoadError={onLoadError}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-space-md animate-fadeIn">
          {alarmDeltas.length === 0 ? (
            <div className="w-full bg-[#0c1424] rounded-xl p-space-xl border border-[#1b273e] text-center text-on-surface-variant font-code-sm">
              <span className="material-symbols-outlined text-[32px] mb-2 text-on-surface-variant">hourglass_empty</span>
              <h2 className="font-headline-md text-sm font-bold text-on-surface">
                Chronological Alarm Cascade
              </h2>
              <p className="text-xs text-on-surface-variant mt-1">
                Không có cảnh báo hoặc chuỗi không chứa mốc thời gian sự cố.
              </p>
            </div>
          ) : (
            <>
              {/* Main Interactive Trajectory Curve Container */}
              <div className="w-full bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] shadow-md flex flex-col gap-space-sm">
                <div className="flex items-center justify-between flex-wrap gap-2 pb-space-xs border-b border-[#1b273e]">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-secondary text-[20px]">
                        stacked_line_chart
                      </span>
                      <h2 className="font-headline-md text-sm font-bold text-on-surface">
                        Chronological Alarm Cascade &amp; Onset Trajectory Curve
                      </h2>
                    </div>
                    <p className="font-body-sm text-[11px] text-on-surface-variant mt-0.5">
                      Quỹ đạo lan truyền sự cố theo thời gian thực. Nhấp hoặc rê chuột vào các node trên đồ thị để kiểm tra chi tiết.
                    </p>
                  </div>

                  <div className="flex items-center gap-3 font-code-sm text-[11px] text-on-surface-variant">
                    <span className="flex items-center gap-1.5 text-emerald-400">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> Genesis T₀
                    </span>
                    <span className="flex items-center gap-1.5 text-secondary">
                      <span className="w-2.5 h-2.5 rounded-full bg-secondary"></span> Cascade Step
                    </span>
                    <span className="text-xs text-on-surface-variant border-l border-[#1b273e] pl-3">
                      Window: 0.00s → {timeSpanSecs > 0 ? `${timeSpanSecs.toFixed(1)}s` : '0.0s'} • {totalAlarms} Alarms
                    </span>
                  </div>
                </div>

                {/* SVG Graph Canvas */}
                <div className="w-full h-52 bg-[#070e1d] rounded-lg p-2 flex flex-col justify-end relative overflow-hidden border border-[#1b273e]">
                  <svg
                    className="w-full h-44 overflow-visible"
                    preserveAspectRatio="none"
                    viewBox="0 0 840 180"
                  >
                    <defs>
                      <linearGradient id="growthGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#7bd0ff" stopOpacity="0.35" />
                        <stop offset="100%" stopColor="#ff5451" stopOpacity="0.02" />
                      </linearGradient>
                    </defs>

                    {/* Horizontal Grid lines */}
                    <line x1="40" y1="35" x2="800" y2="35" stroke="#1b273e" strokeDasharray="3 3" />
                    <line x1="40" y1="80" x2="800" y2="80" stroke="#1b273e" strokeDasharray="3 3" />
                    <line x1="40" y1="125" x2="800" y2="125" stroke="#1b273e" strokeDasharray="3 3" />

                    {/* Selected Node Guideline to Axis */}
                    {selectedMarker && (
                      <>
                        <line
                          x1={selectedMarker.x}
                          y1={selectedMarker.y}
                          x2={selectedMarker.x}
                          y2={180 - 30}
                          stroke="#7bd0ff"
                          strokeWidth="1.5"
                          strokeDasharray="2 2"
                          strokeOpacity="0.8"
                        />
                        <line
                          x1={55}
                          y1={selectedMarker.y}
                          x2={selectedMarker.x}
                          y2={selectedMarker.y}
                          stroke="#7bd0ff"
                          strokeWidth="1"
                          strokeDasharray="2 2"
                          strokeOpacity="0.5"
                        />
                      </>
                    )}

                    {/* Area Polygon */}
                    {svgCurveData.area && (
                      <polygon fill="url(#growthGrad)" points={svgCurveData.area} />
                    )}

                    {/* Trajectory Polyline */}
                    {svgCurveData.points && (
                      <polyline
                        fill="none"
                        stroke="#7bd0ff"
                        strokeWidth="2.5"
                        strokeLinejoin="round"
                        points={svgCurveData.points}
                      />
                    )}

                    {/* Data Points */}
                    {svgCurveData.markers.map(m => {
                      const isGenesis = m.stepIndex === 1
                      const isSelected = m.member.alarm_id === activeAlarmId
                      const isHovered = m.member.alarm_id === hoveredAlarmId

                      return (
                        <g key={`marker-${m.member.alarm_id}`} className="transition-all duration-150">
                          {/* Active/Hover Outer Pulse Ring */}
                          {(isSelected || isHovered) && (
                            <circle
                              cx={m.x}
                              cy={m.y}
                              r="11"
                              fill="none"
                              stroke={isGenesis ? '#34d399' : '#7bd0ff'}
                              strokeWidth="2"
                              strokeDasharray={isSelected ? 'none' : '2 2'}
                              opacity={isSelected ? 1 : 0.75}
                            />
                          )}

                          {/* Center Node Circle */}
                          <circle
                            cx={m.x}
                            cy={m.y}
                            r={isSelected ? 5.5 : 4}
                            fill={isGenesis ? '#10b981' : isSelected ? '#38bdf8' : '#7bd0ff'}
                            stroke="#070e1d"
                            strokeWidth="2"
                          />

                          {/* Top Labels on Genesis & Climax */}
                          {(m.stepIndex === 1 || m.stepIndex === svgCurveData.markers.length) && (
                            <text
                              x={m.x}
                              y={m.y - 12}
                              fill={isGenesis ? '#34d399' : '#7bd0ff'}
                              fontFamily="JetBrains Mono"
                              fontSize="10"
                              fontWeight="700"
                              textAnchor={m.stepIndex === 1 ? 'start' : 'end'}
                            >
                              #{m.stepIndex} ({m.formattedDelta})
                            </text>
                          )}

                          {/* Click & Hover Hitbox for easy interaction */}
                          <circle
                            cx={m.x}
                            cy={m.y}
                            r="15"
                            fill="transparent"
                            className="cursor-pointer"
                            onClick={() => setSelectedAlarmId(m.member.alarm_id)}
                            onMouseEnter={() => setHoveredAlarmId(m.member.alarm_id)}
                            onMouseLeave={() => setHoveredAlarmId(null)}
                          >
                            <title>{`Step #${m.stepIndex}: ${m.formattedDelta} • ${m.member.alarm_id} (${m.member.device_code || dominantDevice})`}</title>
                          </circle>
                        </g>
                      )
                    })}
                  </svg>

                  {/* Time Axis Labels */}
                  <div className="flex justify-between items-center text-on-surface-variant font-code-sm text-[11px] pt-1 px-4 border-t border-[#1b273e]">
                    <span className="text-emerald-400 font-semibold">T₀: 0.00s (Cảnh báo đầu tiên / First observed)</span>
                    <span className="text-on-surface-variant">T+{((timeSpanSecs * 0.5)).toFixed(1)}s (Midpoint)</span>
                    <span className="text-tertiary font-semibold">T+{timeSpanSecs.toFixed(1)}s (Cảnh báo cuối / Last: {totalAlarms} Alarms)</span>
                  </div>
                </div>
              </div>

              {/* Interactive Alarm Node Inspector */}
              {activeItem && (
                <div className="w-full bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] shadow-xl flex flex-col gap-space-md animate-fadeIn">
                  {/* Inspector Header with Step Navigation Controls */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-space-sm border-b border-[#1b273e]">
                    <div className="flex items-center gap-space-xs flex-wrap">
                      <span
                        className={`px-2.5 py-1 font-label-caps text-xs uppercase rounded font-bold ${
                          activeItem.stepIndex === 1
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'bg-secondary/20 text-secondary border border-secondary/40'
                        }`}
                      >
                        {activeItem.stepIndex === 1 ? '★ CẢNH BÁO ĐẦU TIÊN (T₀)' : `MỐC QUAN SÁT #${activeItem.stepIndex}`}
                      </span>
                      <span className="font-code-md text-sm text-on-surface font-bold">
                        Độ lệch: {activeItem.formattedDelta}
                      </span>
                      <span className="text-on-surface-variant font-code-sm text-xs">
                        (Ghi nhận lúc {activeItem.timestamp})
                      </span>
                    </div>

                    <div className="flex items-center gap-space-xs shrink-0">
                      <button
                        type="button"
                        disabled={activeIndex <= 0}
                        onClick={handlePrevStep}
                        className="px-2.5 py-1 bg-[#15233c] hover:bg-secondary/20 hover:text-secondary disabled:opacity-30 disabled:cursor-not-allowed rounded border border-[#1b273e] text-xs font-code-sm flex items-center gap-1 cursor-pointer transition-colors"
                      >
                        <span className="material-symbols-outlined text-[15px]">arrow_back</span>
                        <span>Step trước</span>
                      </button>

                      <span className="font-code-sm text-xs text-on-surface-variant px-1 font-bold">
                        {activeItem.stepIndex} / {totalAlarms}
                      </span>

                      <button
                        type="button"
                        disabled={activeIndex >= alarmDeltas.length - 1}
                        onClick={handleNextStep}
                        className="px-2.5 py-1 bg-[#15233c] hover:bg-secondary/20 hover:text-secondary disabled:opacity-30 disabled:cursor-not-allowed rounded border border-[#1b273e] text-xs font-code-sm flex items-center gap-1 cursor-pointer transition-colors"
                      >
                        <span>Step tiếp theo</span>
                        <span className="material-symbols-outlined text-[15px]">arrow_forward</span>
                      </button>
                    </div>
                  </div>

                  {/* 4 Detail Metric Cards */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-space-sm">
                    <div className="p-3 bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col justify-between">
                      <span className="font-label-caps text-[10px] text-on-surface-variant uppercase font-bold">
                        Mã Cảnh Báo (Alarm ID)
                      </span>
                      <strong className="font-code-sm text-sm text-secondary truncate mt-1">
                        {activeItem.member.alarm_id}
                      </strong>
                      <span className="text-[11px] text-on-surface-variant line-clamp-1 mt-0.5">
                        {activeItem.member.alarm_name || activeItem.member.redundancy_role || 'Alarm Incident Event'}
                      </span>
                    </div>

                    <div className="p-3 bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col justify-between">
                      <span className="font-label-caps text-[10px] text-on-surface-variant uppercase font-bold">
                        Thiết Bị Host &amp; Vai Trò
                      </span>
                      <strong className="font-code-sm text-sm text-on-surface truncate mt-1">
                        {activeItem.member.device_code || dominantDevice}
                      </strong>
                      <div className="flex items-center gap-1 mt-0.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                            activeItem.member.role?.toUpperCase().includes('CORE')
                              ? 'bg-rose-500/20 text-rose-300'
                              : 'bg-sky-500/20 text-sky-300'
                          }`}
                        >
                          {activeItem.member.role || 'LEAF'}
                        </span>
                        <span className="text-[11px] text-on-surface-variant">Network Node</span>
                      </div>
                    </div>

                    <div className="p-3 bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col justify-between">
                      <span className="font-label-caps text-[10px] text-on-surface-variant uppercase font-bold">
                        Độ Trễ Lan Truyền (Propagation)
                      </span>
                      <strong className="font-code-sm text-sm text-amber-300 mt-1">
                        +{activeItem.deltaSec.toFixed(2)}s từ T₀
                      </strong>
                      <span className="text-[11px] text-on-surface-variant mt-0.5">
                        {activeItem.stepIndex === 1
                          ? 'Điểm xuất phát ban đầu (Genesis trigger)'
                          : intervalFromPrevSec === 0
                          ? 'Nổ đồng thời cùng step trước'
                          : `+${intervalFromPrevSec.toFixed(2)}s sau step #${prevItem?.stepIndex}`}
                      </span>
                    </div>

                    <div className="p-3 bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col justify-between">
                      <span className="font-label-caps text-[10px] text-on-surface-variant uppercase font-bold">
                        Cấu Trúc Gom Cụm
                      </span>
                      <strong className="font-code-sm text-sm text-tertiary mt-1">
                        {activeItem.member.redundancy_role || 'MEMBER_EVENT'}
                      </strong>
                      <span className="text-[11px] text-on-surface-variant mt-0.5">
                        {activeItem.member.membership_support != null
                          ? `Độ tương quan support: ${(activeItem.member.membership_support * 100).toFixed(0)}%`
                          : 'Liên kết thời gian & topo'}
                      </span>
                    </div>
                  </div>

                  {/* Quick Stepper Bar - Clickable step numbers 1..N */}
                  {totalAlarms > 1 && (
                    <div className="flex items-center gap-1 overflow-x-auto pt-1 border-t border-[#1b273e] pb-1">
                      <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold mr-1 shrink-0">
                        Nhảy nhanh đến Step:
                      </span>
                      {alarmDeltas.map(d => {
                        const isSelected = d.member.alarm_id === activeItem.member.alarm_id
                        const isGenesis = d.stepIndex === 1
                        return (
                          <button
                            key={`pill-${d.member.alarm_id}`}
                            onClick={() => setSelectedAlarmId(d.member.alarm_id)}
                            className={`px-2 py-0.5 rounded font-code-sm text-xs transition-all cursor-pointer shrink-0 border ${
                              isSelected
                                ? isGenesis
                                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 font-bold'
                                  : 'bg-secondary/20 text-secondary border-secondary font-bold'
                                : 'bg-[#080d17] text-on-surface-variant hover:text-on-surface border-[#1b273e]'
                            }`}
                            title={`Step #${d.stepIndex} (${d.formattedDelta}): ${d.member.alarm_id}`}
                          >
                            #{d.stepIndex}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
