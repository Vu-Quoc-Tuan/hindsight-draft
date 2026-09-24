import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type { ChainAnalysis, CohesionNarrativeView, Job, Member, WhyScope } from '../../types'
import { InfoTip } from '../../components/InfoTip'


interface ChainScopeViewProps {
  analysis: ChainAnalysis
  job?: Job | null
  distinctDevices: string[]
  observedStart: string | null
  observedEnd: string | null
  onSwitchScope: (scope: WhyScope) => void
  onSelectMember: (member: Member) => void
}

export function ChainScopeView({
  analysis,
  job,
  distinctDevices,
  observedStart,
  observedEnd,
}: ChainScopeViewProps) {
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null)
  const [showDescriptors, setShowDescriptors] = useState(false)
  const [narrativeData, setNarrativeData] = useState<CohesionNarrativeView | null>(null)
  const [loadedChainId, setLoadedChainId] = useState<string | null>(null)
  const [expandedTraceIds, setExpandedTraceIds] = useState<Record<string, boolean>>({})
  const loadingNarrative = loadedChainId !== analysis.chain_id

  const toggleTrace = (id: string) => {
    setExpandedTraceIds(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const analyticalFindings = useMemo(
    () => narrativeData?.context?.analytical_findings || [],
    [narrativeData]
  )
  const auditContext = narrativeData?.context?.audit

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    api.cohesionNarrative(analysis.chain_id, controller.signal)
      .then(res => {
        if (!cancelled) {
          setNarrativeData(res)
          setLoadedChainId(analysis.chain_id)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadedChainId(analysis.chain_id)
        }
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [analysis.chain_id])

  // Re-trigger Cohesion Advisor when P2 finishes to incorporate full Audit conductance
  useEffect(() => {
    if (!job || job.chain_id !== analysis.chain_id || job.status !== 'SUCCEEDED') return
    const hasP2InNarrative = Boolean(narrativeData?.context?.has_p2)
    if (hasP2InNarrative) return

    let cancelled = false
    const controller = new AbortController()
    api.cohesionNarrative(analysis.chain_id, controller.signal, 'vi', true)
      .then(res => {
        if (!cancelled) {
          setNarrativeData(res)
          setLoadedChainId(analysis.chain_id)
        }
      })
      .catch(() => {})

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [analysis.chain_id, job, narrativeData?.context?.has_p2])

  const members = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Dynamic Alarm Type Dominance Analysis (DIM 01: Entity / Alarm Type Anchor)
  const { dominantAlarmName, dominantAlarmCount, dominantAlarmPct } = useMemo(() => {
    if (members.length === 0) {
      return { dominantAlarmName: null, dominantAlarmCount: 0, dominantAlarmPct: '0.0' }
    }
    const counts = new Map<string, number>()
    members.forEach(m => {
      const name = m.alarm_name
      if (name) {
        counts.set(name, (counts.get(name) || 0) + 1)
      }
    })
    let maxName: string | null = null
    let maxCount = 0
    counts.forEach((c, name) => {
      if (c > maxCount) {
        maxCount = c
        maxName = name
      }
    })
    return {
      dominantAlarmName: maxName,
      dominantAlarmCount: maxCount,
      dominantAlarmPct: totalAlarms > 0 && maxCount > 0 ? ((maxCount / totalAlarms) * 100).toFixed(1) : '0.0',
    }
  }, [members, totalAlarms])

  // Dynamic Device Dominance Analysis - honestly handling missing devices
  const { dominantDevice, dominantCount, dominantPct } = useMemo(() => {
    if (members.length === 0) {
      return { dominantDevice: distinctDevices[0] || null, dominantCount: 0, dominantPct: '0.0', unassignedCount: 0 }
    }
    const counts = new Map<string, number>()
    let unassigned = 0
    members.forEach(m => {
      const dev = m.device_code || m.node_reference
      if (!dev) {
        unassigned += 1
      } else {
        counts.set(dev, (counts.get(dev) || 0) + 1)
      }
    })
    let maxDev: string | null = null
    let maxCount = 0
    counts.forEach((c, dev) => {
      if (c > maxCount) {
        maxCount = c
        maxDev = dev
      }
    })
    if (!maxDev && distinctDevices.length > 0) {
      maxDev = distinctDevices[0]
    }
    return {
      dominantDevice: maxDev,
      dominantCount: maxCount,
      dominantPct: totalAlarms > 0 && maxCount > 0 ? ((maxCount / totalAlarms) * 100).toFixed(1) : '0.0',
      unassignedCount: unassigned,
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
        timeSpanLabel: 'N/A',
        timeSpanSecs: null,
        startLabel: observedStart ? observedStart.slice(11, 19) : (times.length === 1 ? new Date(times[0]).toISOString().slice(11, 19) : 'N/A'),
        endLabel: observedEnd ? observedEnd.slice(11, 19) : (times.length === 1 ? new Date(times[0]).toISOString().slice(11, 19) : 'N/A'),
      }
    }

    const diffSec = Math.max(0, (times[times.length - 1] - times[0]) / 1000)
    const diffSecRound = Math.round(diffSec)
    const formatted =
      diffSecRound === 0
        ? '0.00s'
        : diffSecRound < 60
        ? `${diffSecRound}s`
        : `${Math.floor(diffSecRound / 60)}m ${diffSecRound % 60}s`

    return {
      timeSpanLabel: formatted,
      timeSpanSecs: diffSec,
      startLabel: new Date(times[0]).toISOString().slice(11, 19),
      endLabel: new Date(times[times.length - 1]).toISOString().slice(11, 19),
    }
  }, [members, observedStart, observedEnd])

  // Derived dimensional metrics
  const descriptors = useMemo(() => analysis.descriptors || [], [analysis.descriptors])
  const unavailableCaps = useMemo(() => (analysis.graybox?.unavailable_capabilities || []).map(c => c.toUpperCase()), [analysis.graybox])
  const availability = analysis.evidence_availability || {}
  const isHistAvailable = availability.historical?.state === 'AVAILABLE'
  const isDelayUnavailable = availability.temporal_delay?.state !== 'AVAILABLE'
  const isTopoUnavailable = availability.topology?.state !== 'AVAILABLE'
  const isDepUnavailable = availability.dependency?.state !== 'AVAILABLE'

  // DIM 02: Burst arrivals (computed from real timestamps)
  const { burstCount, burstPct, arrivalRate } = useMemo(() => {
    if (timeSpanSecs === null) {
      return { burstCount: null, burstPct: null, arrivalRate: null }
    }
    const times = members
      .map(m => m.canonical_start_time)
      .filter((t): t is string => Boolean(t))
      .map(t => Date.parse(t))
      .filter(t => !isNaN(t))
      .sort((a, b) => a - b)
    if (times.length === 0) {
      return { burstCount: null, burstPct: null, arrivalRate: null }
    }
    const windowStart = times[0]
    const inBurst = times.filter(t => t - windowStart <= 60000).length
    const pct = ((inBurst / totalAlarms) * 100).toFixed(1)
    const rate = (totalAlarms / Math.max(1, timeSpanSecs)).toFixed(2)
    return {
      burstCount: inBurst,
      burstPct: pct,
      arrivalRate: rate,
    }
  }, [members, timeSpanSecs, totalAlarms])

  // DIM 04: Historical Lift
  const { histLift, histConfidence } = useMemo(() => {
    if (isHistAvailable && descriptors.length > 0) {
      const maxL = Math.max(...descriptors.map(d => d.lift || 0))
      const conf = descriptors[0].precision_global ? (descriptors[0].precision_global * 100).toFixed(1) : null
      return {
        histLift: maxL > 0 ? maxL.toFixed(2) : null,
        histConfidence: conf,
      }
    }
    return { histLift: null, histConfidence: null }
  }, [descriptors, isHistAvailable])

  // Evaluated dimensions count (truthful telemetry channels with observations)
  const evaluatedCount = [
    dominantAlarmCount > 0,
    timeSpanSecs !== null,
    dominantCount > 0 && dominantDevice !== null,
    histLift !== null,
    !isDelayUnavailable,
    !isTopoUnavailable,
  ].filter(Boolean).length

  return (
    <div className="flex flex-col gap-space-md select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* 1. Real-time Capability Status Strip matching ui/06_why_chain_scope */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#080d17] px-space-lg py-2 rounded-lg flex flex-wrap items-center justify-between gap-space-md border border-[#1b273e]/60 font-code-sm text-xs shadow-xs">
        <div className="flex items-center gap-space-xl flex-wrap">
          {/* Historical Pattern */}
          <div className="flex items-center gap-1.5">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-semibold">
              Historical Pattern:
            </span>
            <div className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${isHistAvailable ? 'bg-secondary' : 'bg-surface-container-high'}`}></span>
              <span className={`font-semibold ${isHistAvailable ? 'text-secondary' : 'text-on-surface-variant'}`}>
                {isHistAvailable ? 'Available' : 'Unavailable'}
              </span>
            </div>
          </div>

          {/* Temporal Delay */}
          <div className="flex items-center gap-1.5">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-semibold">
              Temporal Delay:
            </span>
            <div className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${!isDelayUnavailable ? 'bg-secondary' : 'bg-tertiary'}`}></span>
              <span className={`font-semibold ${!isDelayUnavailable ? 'text-secondary' : 'text-tertiary'}`}>
                {!isDelayUnavailable ? 'Available' : 'Unavailable'}
              </span>
            </div>
          </div>

          {/* Topology Mapping */}
          <div className="flex items-center gap-1.5">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-semibold">
              Topology Mapping:
            </span>
            <div className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${!isTopoUnavailable ? 'bg-secondary' : 'bg-tertiary'}`}></span>
              <span className={`font-semibold ${!isTopoUnavailable ? 'text-secondary' : 'text-tertiary'}`}>
                {!isTopoUnavailable ? 'Available' : 'Unavailable'}
              </span>
            </div>
          </div>

          {/* Dependency */}
          <div className="flex items-center gap-1.5">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-semibold">
              Dependency:
            </span>
            <div className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${!isDepUnavailable ? 'bg-secondary' : 'bg-rose-500'}`}></span>
              <span className={`font-semibold ${!isDepUnavailable ? 'text-secondary' : 'text-rose-400'}`}>
                {!isDepUnavailable ? 'Available' : 'Unverified'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-on-surface-variant">
          <span className="material-symbols-outlined text-[15px] text-secondary">verified</span>
          <span>Correlation &amp; Adjacency Calibration</span>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. Top Analysis Banner matching ui/06_why_chain_scope */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] rounded-xl p-space-lg shadow-md flex flex-col lg:flex-row justify-between lg:items-center gap-space-md border border-[#1b273e]">
        <div className="flex flex-col gap-1 max-w-3xl">
          <div className="flex items-center gap-2">
            <span className="bg-secondary/20 text-secondary border border-secondary/30 px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold tracking-wider">
              EVIDENCE COHESION
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <h1 className="font-headline-lg text-xl font-bold text-on-surface tracking-tight">
              Chain-level Cohesion Analysis: {analysis.chain_id} ({totalAlarms} Alarms)
            </h1>
            <div className="relative inline-flex items-center group">
              <button
                type="button"
                className="w-5 h-5 rounded-full bg-[#172338] border border-[#263756] text-on-surface-variant hover:text-secondary hover:border-secondary/50 flex items-center justify-center font-bold text-xs cursor-help transition-colors"
                aria-label="Cohesion methodology description"
                title="Multi-evidence synthesis evaluating alarm co-location, temporal window proximity, and device correlation without asserting unverified causal ground truth."
              >
                ?
              </button>
              <div className="absolute left-0 top-full mt-2 hidden group-hover:flex flex-col z-30 w-80 p-3 rounded-lg bg-[#0b1220] border border-secondary/40 shadow-2xl text-xs text-on-surface-variant leading-relaxed backdrop-blur-md pointer-events-none">
                <div className="font-semibold text-secondary text-[11px] uppercase tracking-wider mb-1 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[14px]">info</span>
                  <span>Cohesion Methodology</span>
                </div>
                <span>
                  Multi-evidence synthesis evaluating alarm co-location, temporal window proximity, and device correlation without asserting unverified causal ground truth.
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* High Level Aggregated Stats Pill Array */}
        <div className="flex items-center gap-2 flex-wrap lg:justify-end shrink-0">
          <div className="bg-[#131c2e] px-3.5 py-2.5 rounded-lg flex flex-col items-start min-w-[110px] border border-[#1e2b44]">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-medium">Evidence Channels</span>
            <span className="font-code-lg text-base text-secondary font-bold">{evaluatedCount}/6 Evaluated</span>
          </div>
          <div className="bg-[#131c2e] px-3.5 py-2.5 rounded-lg flex flex-col items-start min-w-[110px] border border-[#1e2b44]">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-medium">Span Delta</span>
            <span className="font-code-lg text-base text-on-surface font-bold">
              {typeof timeSpanSecs === 'number' ? `${timeSpanSecs.toFixed(2)}s` : timeSpanLabel}
            </span>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. Evidence Dimensions Grid (6 Cards, 3x2) matching screen.png */}
      {/* ========================================================================= */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">
        {/* DIM 01: Entity Reference */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-1' ? null : 'dim-1')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-1'
              ? 'bg-[#18263f] border-secondary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-secondary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">dns</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 01: Entity Reference</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                dominantAlarmCount > 0 ? 'bg-secondary/15 text-secondary' : 'bg-surface-container-high/40 text-on-surface-variant'
              }`}>
                {dominantAlarmCount > 0 ? 'Đã ghi nhận' : 'Chưa gán'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {dominantAlarmCount > 0
                ? `Xác định loại thực thể/cảnh báo neo chính (Entity Anchor). Phần lớn cảnh báo trong chuỗi tập trung vào loại '${dominantAlarmName}'.`
                : 'Chưa xác định được loại cảnh báo neo chung cho các cảnh báo trong chuỗi này.'}
            </p>

            {/* Metric Breakdown Visual */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant truncate max-w-[200px]" title={dominantAlarmName || ''}>
                  Loại cảnh báo chính: <span className="text-on-surface font-semibold">{dominantAlarmName || 'Chưa gán'}</span>
                </span>
                <span className="text-secondary font-bold">{dominantAlarmPct}% Tỷ lệ</span>
              </div>
              {/* High-contrast Gauge */}
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${dominantAlarmPct}%` }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>{dominantAlarmCount} / {totalAlarms} Cảnh báo</span>
                <span>{Math.max(0, totalAlarms - dominantAlarmCount)} Cảnh báo khác</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className={`flex items-center gap-1 ${dominantAlarmCount > 0 ? 'text-secondary' : 'text-on-surface-variant'}`}>
              <span className="material-symbols-outlined text-[14px]">{dominantAlarmCount > 0 ? 'check_circle' : 'help'}</span>
              {dominantAlarmCount > 0 ? 'Đã ghi nhận' : 'Chưa gán'}
            </span>
            <span className="text-on-surface font-semibold truncate max-w-[180px]" title={dominantAlarmName || ''}>
              Thực thể neo: {dominantAlarmName || 'Chưa gán'}
            </span>
          </div>
        </div>

        {/* DIM 02: Temporal Synchronization */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-2' ? null : 'dim-2')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-2'
              ? 'bg-[#18263f] border-secondary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-secondary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">timer</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 02: Temporal Synch</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                timeSpanSecs === null
                  ? 'bg-surface-container-high/40 text-on-surface-variant'
                  : 'bg-secondary/15 text-secondary'
              }`}>
                {timeSpanSecs === null ? 'Chưa xác định' : 'Đã ghi nhận'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {timeSpanSecs === null
                ? 'Không đủ dữ liệu mốc thời gian để đánh giá độ đồng bộ và dồn cục thời gian.'
                : `Khung thời gian xuất hiện quan sát được. Có ${burstCount} / ${totalAlarms} cảnh báo phát sinh đồng bộ trong khung ${typeof timeSpanSecs === 'number' ? timeSpanSecs.toFixed(1) : timeSpanLabel}s.`}
            </p>

            {/* SVG Sparkline & Window Details */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Khởi phát: <span className="text-on-surface font-semibold">{timeSpanSecs !== null ? `${startLabel} (T+0s)` : 'N/A'}</span>
                </span>
                <span className="text-secondary font-bold">
                  {burstPct !== null ? `${burstPct}% Cụm đồng bộ` : 'N/A'}
                </span>
              </div>
              {/* Sparkline Visual of Alarms Arrival */}
              <div className="w-full h-8 flex items-end gap-1 pt-1">
                {timeSpanSecs !== null ? (
                  <>
                    <div className="flex-1 bg-[#1a2942] h-1 rounded-sm"></div>
                    <div className="flex-1 bg-[#1a2942] h-2.5 rounded-sm"></div>
                    <div className="flex-1 bg-secondary h-7 rounded-sm"></div>
                    <div className="flex-1 bg-secondary h-6 rounded-sm"></div>
                    <div className="flex-1 bg-secondary h-4.5 rounded-sm"></div>
                    <div className="flex-1 bg-[#1a2942] h-2 rounded-sm"></div>
                    <div className="flex-1 bg-[#1a2942] h-1 rounded-sm"></div>
                    <div className="flex-1 bg-[#1a2942] h-1 rounded-sm"></div>
                  </>
                ) : (
                  <div className="w-full h-1 bg-[#1a2942] rounded-sm"></div>
                )}
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>
                  Khung giờ: {typeof timeSpanSecs === 'number' ? `${timeSpanSecs.toFixed(1)}s` : timeSpanLabel} ({startLabel} → {endLabel})
                </span>
                <span>Tần suất đến: {arrivalRate !== null ? `${arrivalRate}/s` : 'N/A'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-secondary">
              <span className="material-symbols-outlined text-[14px]">bolt</span>
              {timeSpanSecs !== null ? (timeSpanSecs <= 60 ? 'Đột biến dồn cục (Micro-Burst)' : 'Khoảng trôi kéo dài') : 'Không có dữ liệu thời gian'}
            </span>
            <span className="text-on-surface font-semibold">
              {typeof timeSpanSecs === 'number' ? `ΔT Max = ${timeSpanSecs.toFixed(2)}s` : 'ΔT = N/A'}
            </span>
          </div>
        </div>

        {/* DIM 03: Device Hardware */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-3' ? null : 'dim-3')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-3'
              ? 'bg-[#18263f] border-secondary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-secondary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">developer_board</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 03: Device Hardware</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                dominantCount > 0 ? 'bg-secondary/15 text-secondary' : 'bg-surface-container-high/40 text-on-surface-variant'
              }`}>
                {dominantCount > 0 ? 'Đã ghi nhận' : 'Chưa gán'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {dominantCount > 0
                ? `Cùng vị trí phần cứng (Host co-location). Các cảnh báo cùng chia sẻ phần tử thiết bị mạng vật lý ${dominantDevice}.`
                : 'Chưa phát hiện phần tử mạng vật lý chung được chia sẻ giữa các cảnh báo.'}
            </p>

            {/* Linecard Slot Breakdown */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">Cảnh báo cùng Host</span>
                <span className="text-secondary font-bold">{dominantCount} / {totalAlarms} Cảnh báo</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${dominantPct}%` }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Khe cắm phụ: Chưa đánh chỉ mục</span>
                <span>Host: {dominantDevice || 'Chưa gán'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-secondary">
              <span className="material-symbols-outlined text-[14px]">view_in_ar</span> Cùng vị trí thiết bị (Co-location)
            </span>
            <span className="text-on-surface font-semibold">Tỷ lệ cùng Host: {dominantPct}%</span>
          </div>
        </div>

        {/* DIM 04: Historical Co-occurrence */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-4' ? null : 'dim-4')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-4'
              ? 'bg-[#18263f] border-tertiary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-tertiary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-tertiary text-[18px]">history_edu</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 04: Historical Co-occ.</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                descriptors.length > 0
                  ? 'bg-secondary/15 text-secondary'
                  : unavailableCaps.some(c => c.includes('HISTORICAL'))
                  ? 'bg-surface-container-high/40 text-on-surface-variant'
                  : 'bg-tertiary/15 text-tertiary'
              }`}>
                {descriptors.length > 0
                  ? 'Grounded'
                  : unavailableCaps.some(c => c.includes('HISTORICAL'))
                  ? 'Chưa nạp CSDL'
                  : 'Chưa đánh giá'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {totalAlarms <= 1
                ? 'Chuỗi đơn lẻ (1 cảnh báo): Không áp dụng đánh giá đồng xuất hiện trong lịch sử.'
                : descriptors.length > 0
                ? `Mẫu hình lặp lại trong lịch sử. Thể hiện sự liên kết thực nghiệm với ${descriptors.length} quy tắc tương phản.`
                : unavailableCaps.some(c => c.includes('HISTORICAL'))
                ? 'Mô hình quy tắc đồng xuất hiện lịch sử chưa nạp CSDL hoặc chưa được kích hoạt.'
                : 'Chưa đủ dữ liệu lịch sử (Support < 5) để sinh quy tắc đồng xuất hiện với Lift > 1 cho tổ hợp này.'}
            </p>

            {/* Historical Matrix Card */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Mined Rules: <span className="text-on-surface font-semibold">{totalAlarms <= 1 ? 'N/A (Singleton)' : `${descriptors.length} Rules`}</span>
                </span>
                <span className="text-tertiary font-bold">Lift: {totalAlarms <= 1 ? 'N/A' : histLift ? `${histLift}x` : 'N/A'}</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div
                  className="bg-tertiary h-full rounded-full transition-all"
                  style={{ width: descriptors.length > 0 ? `${Math.min(100, Math.round((descriptors[0]?.coverage || 0) * 100))}%` : '0%' }}
                ></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Baseline: 1.0</span>
                <span>Confidence: {totalAlarms <= 1 ? 'N/A' : histConfidence ? `${histConfidence}%` : 'N/A'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-tertiary">
              <span className="material-symbols-outlined text-[14px]">auto_graph</span>
              {totalAlarms <= 1
                ? 'Chuỗi đơn lẻ'
                : histLift
                ? 'Grounded Rules'
                : unavailableCaps.some(c => c.includes('HISTORICAL'))
                ? 'CSDL chưa nạp'
                : 'Chưa đủ dữ liệu sinh luật'}
            </span>
            <span className="text-on-surface font-semibold">
              {totalAlarms <= 1
                ? 'Không áp dụng'
                : histLift
                ? `Rules: ${descriptors.length}`
                : unavailableCaps.some(c => c.includes('HISTORICAL'))
                ? 'Chưa kết nối CSDL lịch sử'
                : 'Chưa đủ tần suất (Support < 5)'}
            </span>
          </div>
        </div>

        {/* DIM 05: Temporal Delay */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-5' ? null : 'dim-5')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-5'
              ? 'bg-[#18263f] border-secondary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-secondary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">timelapse</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 05: Temporal Delay</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                totalAlarms <= 1
                  ? 'bg-surface-container-high/40 text-on-surface-variant'
                  : 'bg-secondary/15 text-secondary'
              }`}>
                {totalAlarms <= 1 ? 'Chuỗi đơn lẻ (N/A)' : 'Đo theo cặp'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {totalAlarms <= 1
                ? 'Chuỗi đơn lẻ (1 cảnh báo): Không có cặp cảnh báo để đo độ trễ lan truyền.'
                : 'Độ trễ thời gian được đo chính xác theo từng cặp cảnh báo (A → B). Vui lòng xem phân phối delay tại tab Pair WHY.'}
            </p>

            {/* Delay Metric Box */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Phương thức: <span className="text-on-surface font-semibold">{totalAlarms <= 1 ? 'N/A (Singleton)' : 'Đo theo cặp (Pair WHY)'}</span>
                </span>
                <span className="text-secondary font-bold">{totalAlarms <= 1 ? 'N/A' : 'Pairwise'}</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: totalAlarms <= 1 ? '0%' : '100%' }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>{totalAlarms <= 1 ? 'Độ trễ: N/A' : 'Chi tiết: Tab Pair WHY'}</span>
                <span>{totalAlarms <= 1 ? 'Chuỗi 1 alarm' : 'Phân phối Histogram/KDE'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-secondary">
              <span className="material-symbols-outlined text-[14px]">tune</span> Phân tích theo cặp
            </span>
            <span className="text-on-surface font-semibold">{totalAlarms <= 1 ? 'Không áp dụng' : 'Khả dụng tại Pair WHY'}</span>
          </div>
        </div>

        {/* DIM 06: Topology Mapping */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-6' ? null : 'dim-6')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-6'
              ? 'bg-[#18263f] border-secondary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-secondary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">hub</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 06: Topology Mapping</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                isTopoUnavailable ? 'bg-surface-container-high/40 text-on-surface-variant' : 'bg-secondary/15 text-secondary'
              }`}>
                {isTopoUnavailable ? 'Chưa khả dụng' : 'Khả dụng'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {isTopoUnavailable
                ? 'Đồ thị topo mạng IP Core chưa khả dụng trong cấu hình hiện tại.'
                : 'Ánh xạ topo vật lý IP Core: các thiết bị router/switch đã được kết nối và xác thực trên đồ thị mạng.'}
            </p>

            {/* Topology Ring Representation */}
            {(() => {
              const topoMapped = narrativeData?.context?.topology?.mapped ?? 0
              const topoTotal = narrativeData?.context?.topology?.total || totalAlarms
              const topoPct = topoTotal > 0 && !isTopoUnavailable ? Math.round((topoMapped / topoTotal) * 100) : (isTopoUnavailable ? 0 : 100)
              return (
                <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Đồ thị IP Core</span>
                    <span className="text-secondary font-bold">
                      {isTopoUnavailable ? 'Chưa kết nối' : `${topoPct}% Core Mapped (${topoMapped}/${topoTotal})`}
                    </span>
                  </div>
                  <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                    <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${isTopoUnavailable ? 0 : topoPct}%` }}></div>
                  </div>
                  <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                    <span>Tính kề vật lý: {isTopoUnavailable ? 'Chưa kề' : 'Đã map IP Core'}</span>
                    <span>Khoảng cách hop: {isTopoUnavailable ? 'N/A' : (narrativeData?.context?.topology?.max_path_hops ? `Tối đa ${narrativeData.context.topology.max_path_hops} hops` : 'Xem tại Pair WHY')}</span>
                  </div>
                </div>
              )
            })()}
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-on-surface-variant">
              <span className="material-symbols-outlined text-[14px]">link_off</span> Đồ thị Topo
            </span>
            <span className="text-on-surface font-semibold">Khả năng phân tích: {isTopoUnavailable ? 'Chưa khả dụng' : 'Khả dụng'}</span>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 4. Analytical Findings Ledger (Direct from Cohesion Advisor)             */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] rounded-xl p-space-md shadow-md flex flex-col gap-space-md border border-[#1b273e]">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[20px]">insights</span>
            <h2 className="font-headline-md text-sm font-bold text-on-surface">
              Các phát hiện phân tích cốt lõi (Analytical Findings)
            </h2>
            <InfoTip text="Các phát hiện phân tích chuyên sâu trích xuất từ dữ liệu thực tế và thuật toán Cohesion Advisor: Diễn tiến thời gian (T0/Wave offsets), Ngữ cảnh Topology transit hops, và Kết luận kiểm định ranh giới Audit Graph (conductance Φ / ε)." />
          </div>
          <div className="flex items-center gap-2 font-code-sm text-xs text-on-surface-variant flex-wrap">
            <span className="px-2.5 py-1 rounded bg-[#151f33] text-secondary font-semibold border border-[#1b273e] flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-secondary"></span>
              <span>{analyticalFindings.length} Phát hiện trích xuất</span>
            </span>
            {auditContext?.status === 'EVALUATED' && (
              <span className="px-2.5 py-1 rounded bg-emerald-950/40 text-emerald-300 font-semibold border border-emerald-800/40 flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px]">verified</span>
                <span>
                  Audit: Φ = {typeof auditContext.conductance === 'number' ? auditContext.conductance.toFixed(3) : '—'}{' '}
                  {auditContext.candidate_cut ? '≤' : '>'} ε = {typeof auditContext.epsilon === 'number' ? auditContext.epsilon.toFixed(3) : '—'}{' '}
                  ({auditContext.candidate_cut ? 'Cần tách' : 'Gắn kết mạnh, Không tách'})
                </span>
              </span>
            )}
          </div>
        </div>

        {/* Analytical Findings Cards */}
        {loadingNarrative ? (
          <div className="p-8 text-center text-on-surface-variant font-code-sm text-xs rounded-lg border border-[#1b273e] bg-[#080d17]/60">
            <div className="flex flex-col items-center justify-center gap-2">
              <span className="material-symbols-outlined animate-spin text-secondary text-[24px]">progress_activity</span>
              <span>Đang tải các phát hiện phân tích từ Cohesion Advisor...</span>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-md">
            {/* CARD 1: TEMPORAL PROGRESSION */}
            {(() => {
              const temporalFinding = analyticalFindings.find(f => f.finding_id === 'TEMPORAL_PROGRESSION')
              const isExpanded = Boolean(expandedTraceIds['TEMPORAL'])
              const evidenceList = temporalFinding?.evidence || []
              return (
                <div className="bg-[#091120] rounded-lg border border-[#1b273e] p-space-md flex flex-col justify-between transition-all hover:border-purple-500/40">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-1.5 rounded-md bg-purple-950/40 text-purple-300 border border-purple-800/60 flex items-center justify-center">
                          <span className="material-symbols-outlined text-[17px] text-purple-400">schedule</span>
                        </div>
                        <span className="font-bold text-on-surface text-xs">Diễn tiến thời gian</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold font-code-sm bg-purple-500/15 text-purple-300 border border-purple-500/30">
                          <span className="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
                          DERIVED
                        </span>
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold font-code-sm bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          HIGH
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-on-surface font-semibold leading-relaxed mt-1">
                      {temporalFinding?.claim || `Chuỗi cảnh báo bắt đầu lúc ${observedStart || '—'} và kết thúc lúc ${observedEnd || '—'}.`}
                    </p>

                    <div className="flex items-start gap-1.5 text-[10px] text-amber-300/90 font-code-sm bg-amber-500/10 px-2 py-1 rounded border border-amber-500/20 leading-relaxed">
                      <span className="material-symbols-outlined text-[13px] shrink-0 mt-0.5 text-amber-400">info</span>
                      <span>Chưa kiểm định hướng nhân quả • Cảnh báo sớm nhất chưa chắc là nguyên nhân gốc</span>
                    </div>

                    {evidenceList.length > 0 && (
                      <div className="mt-1 flex flex-col gap-1.5">
                        <button
                          type="button"
                          onClick={() => toggleTrace('TEMPORAL')}
                          className="flex items-center justify-between w-full text-[11px] font-code-sm text-secondary hover:text-secondary/80 py-1 px-2 rounded bg-[#0e1728] border border-[#1b273e] transition-colors"
                        >
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[14px]">
                              {isExpanded ? 'expand_less' : 'expand_more'}
                            </span>
                            <span>{isExpanded ? 'Thu gọn dấu vết' : `Xem dấu vết thời gian (${evidenceList.length} mốc)`}</span>
                          </span>
                        </button>
                        {isExpanded && (
                          <div className="flex flex-col gap-1 pl-1 max-h-48 overflow-y-auto pr-1">
                            {evidenceList.map((ev, idx) => (
                              <div key={idx} className="flex items-start gap-1.5 text-[11px] font-code-sm bg-[#080d17] p-1.5 rounded border border-[#1b273e]/60 text-slate-300">
                                <span className="text-secondary select-none font-bold">›</span>
                                <span className="break-words">{ev}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })()}

            {/* CARD 2: SHARED TOPOLOGY CONTEXT */}
            {(() => {
              const topoFinding = analyticalFindings.find(f => f.finding_id === 'SHARED_TOPOLOGY_CONTEXT')
              const domFinding = analyticalFindings.find(f => f.finding_id === 'TOPOLOGY_DOMINATOR_WITNESS')
              const propFinding = analyticalFindings.find(f => f.finding_id === 'TOPOLOGY_PROPAGATION_FLOW')
              const domData = narrativeData?.context?.tier2_p2?.dominator
              const propData = narrativeData?.context?.tier2_p2?.propagation
              const isExpanded = Boolean(expandedTraceIds['TOPO'])
              const evidenceList = [
                ...(topoFinding?.evidence || []),
                ...(domFinding?.evidence || []),
                ...(propFinding?.evidence || []),
              ]
              return (
                <div className="bg-[#091120] rounded-lg border border-[#1b273e] p-space-md flex flex-col justify-between transition-all hover:border-cyan-500/40">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-1.5 rounded-md bg-cyan-950/40 text-cyan-300 border border-cyan-800/60 flex items-center justify-center">
                          <span className="material-symbols-outlined text-[17px] text-cyan-400">hub</span>
                        </div>
                        <span className="font-bold text-on-surface text-xs">Ngữ cảnh Topology</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold font-code-sm bg-purple-500/15 text-purple-300 border border-purple-500/30">
                          <span className="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
                          DERIVED
                        </span>
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold font-code-sm bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          HIGH
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-on-surface font-semibold leading-relaxed mt-1">
                      {topoFinding?.claim || 'Ánh xạ topo vật lý/IT: các thiết bị đã được định vị trên đồ thị mạng hạ tầng.'}
                    </p>

                    {/* Dominator Witness Badge (Tier-2 P2) */}
                    {(domFinding || domData?.witness_resource_id) && (
                      <div className="flex items-center gap-1.5 text-[11px] text-purple-300 font-code-sm bg-purple-950/40 px-2 py-1 rounded border border-purple-800/50">
                        <span className="material-symbols-outlined text-[13px] text-purple-400 shrink-0">shield</span>
                        <span className="font-bold">Dominator:</span>
                        <span className="truncate">{domData?.witness_resource_id || domFinding?.claim}</span>
                        {domData?.covered_resource_ids && (
                          <span className="text-[10px] text-purple-400 ml-auto">({domData.covered_resource_ids.length} resources)</span>
                        )}
                      </div>
                    )}

                    {/* Propagation Flow Chip (Tier-2 P2) */}
                    {(propFinding || (propData?.hypotheses && propData.hypotheses.length > 0)) && (
                      <div className="flex items-center gap-1.5 text-[11px] text-cyan-300 font-code-sm bg-cyan-950/30 px-2 py-1 rounded border border-cyan-800/40">
                        <span className="material-symbols-outlined text-[13px] text-cyan-400 shrink-0">route</span>
                        <span className="truncate">{propFinding?.claim || `Lan truyền RWR: ${propData?.hypotheses?.length} giả thuyết luồng`}</span>
                      </div>
                    )}

                    <div className="flex items-start gap-1.5 text-[10px] text-amber-300/90 font-code-sm bg-amber-500/10 px-2 py-1 rounded border border-amber-500/20 leading-relaxed">
                      <span className="material-symbols-outlined text-[13px] shrink-0 mt-0.5 text-amber-400">info</span>
                      <span>Kết nối transit không đồng nghĩa với quan hệ phụ thuộc nhân quả</span>
                    </div>

                    {evidenceList.length > 0 && (
                      <div className="mt-1 flex flex-col gap-1.5">
                        <button
                          type="button"
                          onClick={() => toggleTrace('TOPO')}
                          className="flex items-center justify-between w-full text-[11px] font-code-sm text-secondary hover:text-secondary/80 py-1 px-2 rounded bg-[#0e1728] border border-[#1b273e] transition-colors"
                        >
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[14px]">
                              {isExpanded ? 'expand_less' : 'expand_more'}
                            </span>
                            <span>{isExpanded ? 'Thu gọn dấu vết' : `Xem chi tiết đường transit (${evidenceList.length} mục)`}</span>
                          </span>
                        </button>
                        {isExpanded && (
                          <div className="flex flex-col gap-1 pl-1 max-h-48 overflow-y-auto pr-1">
                            {evidenceList.map((ev, idx) => (
                              <div key={idx} className="flex items-start gap-1.5 text-[11px] font-code-sm bg-[#080d17] p-1.5 rounded border border-[#1b273e]/60 text-slate-300">
                                <span className="text-secondary select-none font-bold">›</span>
                                <span className="break-words">{ev}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })()}

            {/* CARD 3: AUDIT COHESION (P2) */}
            {(() => {
              const isDeepDiveRunning = job?.status === 'QUEUED' || job?.status === 'RUNNING'
              const auditFinding = analyticalFindings.find(f => f.finding_id === 'AUDIT_COHESION')
              const isEvaluated = auditContext?.status === 'EVALUATED' || Boolean(auditFinding)
              const isExpanded = Boolean(expandedTraceIds['AUDIT'])

              if (isDeepDiveRunning) {
                return (
                  <div className="bg-[#091120] rounded-lg border border-secondary/40 p-space-md flex flex-col justify-center items-center text-center gap-3">
                    <span className="material-symbols-outlined animate-spin text-secondary text-[28px]">progress_activity</span>
                    <div className="flex flex-col gap-1">
                      <span className="font-bold text-on-surface text-xs">Đang kiểm định ranh giới Audit qua P2...</span>
                      <span className="text-[11px] font-code-sm text-on-surface-variant">
                        Tính toán độ dẫn vết cắt conductance Φ và kiểm định ranh giới tách chuỗi
                      </span>
                    </div>
                  </div>
                )
              }

              if (isEvaluated) {
                const overMergeFinding = analyticalFindings.find(f => f.finding_id === 'OVER_MERGE_EVALUATION')
                const overMergeData = narrativeData?.context?.tier2_p2?.over_merge
                const evidenceList = [
                  ...(auditFinding?.evidence || []),
                  ...(overMergeFinding?.evidence || []),
                ]
                const isCut = (auditContext?.candidate_cut ?? false) || Boolean(overMergeData?.structural_separation)
                return (
                  <div className={`bg-[#091120] rounded-lg border p-space-md flex flex-col justify-between transition-all ${
                    isCut ? 'border-amber-500/40 hover:border-amber-500' : 'border-emerald-500/40 hover:border-emerald-500'
                  }`}>
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className={`p-1.5 rounded-md flex items-center justify-center ${
                            isCut ? 'bg-amber-950/40 text-amber-300 border border-amber-800/60' : 'bg-emerald-950/40 text-emerald-300 border border-emerald-800/60'
                          }`}>
                            <span className="material-symbols-outlined text-[17px]">{isCut ? 'call_split' : 'verified'}</span>
                          </div>
                          <span className="font-bold text-on-surface text-xs">Kiểm định Audit Graph</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold font-code-sm ${
                            isCut ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                          }`}>
                            {isCut ? 'CẦN TÁCH' : 'GẮN KẾT MẠNH'}
                          </span>
                        </div>
                      </div>

                      <p className="text-xs text-on-surface font-semibold leading-relaxed mt-1">
                        {auditFinding?.claim || (isCut
                          ? 'Phát hiện vết cắt có độ dẫn thấp; chuỗi có dấu hiệu over-merge và có thể tách thành 2 sự cố.'
                          : 'Độ dẫn vết cắt conductance lớn hơn ngưỡng epsilon; các cảnh báo gắn kết mạnh, không cần tách chuỗi.'
                        )}
                      </p>

                      {/* Over-merge Warning Chip (Tier-2 P2) */}
                      {overMergeData?.structural_separation && (
                        <div className="flex items-center gap-1.5 text-[11px] text-amber-300 font-code-sm bg-amber-950/40 px-2 py-1 rounded border border-amber-800/50">
                          <span className="material-symbols-outlined text-[13px] text-amber-400 shrink-0">warning</span>
                          <span className="font-bold">Over-Merge ({overMergeData.strength}):</span>
                          <span className="truncate">{overMergeData.narrative || overMergeFinding?.claim}</span>
                        </div>
                      )}

                      <div className="flex items-start gap-1.5 text-[10px] text-slate-300/80 font-code-sm bg-slate-800/30 px-2 py-1 rounded border border-slate-700/40 leading-relaxed">
                        <span className="material-symbols-outlined text-[13px] shrink-0 mt-0.5 text-slate-400">account_tree</span>
                        <span>Audit Graph đo độ gắn kết bằng chứng thực tế, không phải topology vật lý.</span>
                      </div>

                      {evidenceList.length > 0 && (
                        <div className="mt-1 flex flex-col gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleTrace('AUDIT')}
                            className="flex items-center justify-between w-full text-[11px] font-code-sm text-secondary hover:text-secondary/80 py-1 px-2 rounded bg-[#0e1728] border border-[#1b273e] transition-colors"
                          >
                            <span className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-[14px]">
                                {isExpanded ? 'expand_less' : 'expand_more'}
                              </span>
                              <span>{isExpanded ? 'Thu gọn dấu vết' : `Xem chi tiết kiểm định (${evidenceList.length} mục)`}</span>
                            </span>
                          </button>
                          {isExpanded && (
                            <div className="flex flex-col gap-1 pl-1 max-h-48 overflow-y-auto pr-1">
                              {evidenceList.map((ev, idx) => (
                                <div key={idx} className="flex items-start gap-1.5 text-[11px] font-code-sm bg-[#080d17] p-1.5 rounded border border-[#1b273e]/60 text-slate-300">
                                  <span className="text-secondary select-none font-bold">›</span>
                                  <span className="break-words">{ev}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              }

              return (
                <div className="bg-[#091120] rounded-lg border border-[#1b273e] p-space-md flex flex-col justify-between">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-1.5 rounded-md bg-slate-800/40 text-slate-400 border border-slate-700/60 flex items-center justify-center">
                          <span className="material-symbols-outlined text-[17px]">verified</span>
                        </div>
                        <span className="font-bold text-on-surface text-xs">Kiểm định Audit Graph (P2)</span>
                      </div>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold font-code-sm bg-slate-500/15 text-slate-400 border border-slate-500/30">
                        CHƯA CHẠY
                      </span>
                    </div>
                    <p className="text-xs text-on-surface-variant leading-relaxed mt-1">
                      Chưa có kết quả kiểm định ranh giới Audit. Chạy Deep Dive tại tab Cấu trúc hoặc Topology để kiểm tra over-merge.
                    </p>
                  </div>
                </div>
              )
            })()}
          </div>
        )}
      </div>

      {/* ========================================================================= */}
      {/* 5. Bottom Section: Limitations & Evidence Cohesion Callout Box */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] rounded-xl p-space-md flex items-center gap-space-md shadow-md border border-[#1b273e]">
        {/* Limitations & Cohesion Statement */}
        <div className="flex items-start gap-3 w-full">
          <div className="p-2 bg-tertiary/20 text-tertiary rounded-lg flex items-center justify-center mt-0.5 shrink-0">
            <span className="material-symbols-outlined text-[20px]">
              {narrativeData?.model && narrativeData.model !== 'DETERMINISTIC_EVIDENCE' ? 'auto_awesome' : 'info'}
            </span>
          </div>
          <div className="flex flex-col gap-1.5 w-full">
            <div className="flex items-center gap-2 flex-wrap justify-between">
              <span className="font-headline-md text-sm font-bold text-on-surface">
                Tổng hợp chứng cứ: Đã đánh giá {evaluatedCount}/6 chiều quan sát.
              </span>
              {narrativeData?.model && (
                <span className="text-[10px] font-code-sm px-2 py-0.5 rounded bg-[#16233b] border border-[#223352] text-secondary">
                  {narrativeData.model === 'DETERMINISTIC_EVIDENCE' ? 'Chứng cứ xác định (Deterministic)' : `AI: ${narrativeData.model}`}
                </span>
              )}
            </div>
            {loadingNarrative ? (
              <div className="h-4 w-3/4 bg-surface-container-high/40 animate-pulse rounded my-1" />
            ) : (
              <div className="flex flex-col gap-2">
                <p className="font-body-sm text-xs text-on-surface-variant leading-relaxed">
                  {narrativeData?.narrative?.trim() || (
                    narrativeData
                      ? `Provider chưa trả về văn bản AI (${narrativeData.provider_status ?? 'UNAVAILABLE'}). Các số liệu và evidence xác định vẫn hiển thị ở những phần bên dưới.`
                      : 'Chưa có nhận định AI từ provider.'
                  )}
                </p>
                {narrativeData?.context?.operational_insights?.actionable_takeaway && (
                  <div className="flex items-start gap-2 p-2 rounded bg-cyan-950/40 border border-cyan-800/60 text-xs text-cyan-200">
                    <span className="material-symbols-outlined text-[16px] text-cyan-400 shrink-0 mt-0.5">tips_and_updates</span>
                    <div className="flex-1 leading-snug">
                      <strong className="text-cyan-300 mr-1">Khuyến nghị vận hành NOC:</strong>
                      <span>{narrativeData.context.operational_insights.actionable_takeaway}</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 6. Optional: Model Descriptors Diagnostic Ledger (Collapsible) */}
      {/* ========================================================================= */}
      {descriptors.length > 0 && (
        <div className="bg-[#080d17] rounded-xl p-space-sm border border-[#1b273e]/70 shadow-xs">
          <button
            type="button"
            onClick={() => setShowDescriptors(!showDescriptors)}
            className="w-full flex items-center justify-between p-1.5 text-xs text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-2 font-semibold">
              <span className="material-symbols-outlined text-secondary text-[16px]">data_object</span>
              <span>Quy tắc tương phản từ mô hình học máy ({descriptors.length} Rules Grounded)</span>
            </span>
            <div className="flex items-center gap-1 font-code-sm text-[11px] text-secondary">
              <span>{showDescriptors ? 'Ẩn chi tiết' : 'Xem chi tiết'}</span>
              <span className="material-symbols-outlined text-[14px]">
                {showDescriptors ? 'expand_less' : 'expand_more'}
              </span>
            </div>
          </button>

          {showDescriptors && (
            <div className="mt-2 pt-2 border-t border-[#1b273e] overflow-x-auto">
              <table className="w-full text-left font-code-sm text-xs">
                <thead>
                  <tr className="border-b border-[#1b273e] bg-[#0c1424] text-on-surface-variant uppercase text-[10px] tracking-wider">
                    <th className="p-2">Phân loại</th>
                    <th className="p-2">Nhãn quy tắc (Rule)</th>
                    <th className="p-2 text-right">Độ bao phủ</th>
                    <th className="p-2 text-right">Độ cx toàn cục</th>
                    <th className="p-2 text-right">Độ cx cục bộ</th>
                    <th className="p-2 text-right">Lift</th>
                    <th className="p-2 text-right">F1</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#151f33]">
                  {descriptors.map((desc, idx) => (
                    <tr key={`${desc.label}-${idx}`} className="hover:bg-[#111c30] transition-colors">
                      <td className="p-2">
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-secondary/20 text-secondary border border-secondary/30">
                          {desc.kind}
                        </span>
                      </td>
                      <td className="p-2 text-on-surface font-medium">{desc.label}</td>
                      <td className="p-2 text-right text-on-surface">{(desc.coverage * 100).toFixed(1)}%</td>
                      <td className="p-2 text-right text-sky-400">{(desc.precision_global * 100).toFixed(1)}%</td>
                      <td className="p-2 text-right text-secondary">
                        {desc.precision_local !== null ? `${(desc.precision_local * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="p-2 text-right font-bold text-amber-400">
                        {desc.lift !== null ? `${desc.lift.toFixed(2)}x` : '—'}
                      </td>
                      <td className="p-2 text-right font-bold text-emerald-400">{desc.f1.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
