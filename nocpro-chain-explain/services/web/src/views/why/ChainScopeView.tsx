import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type { ChainAnalysis, CohesionNarrativeView, Member, WhyScope } from '../../types'
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
}: ChainScopeViewProps) {
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null)
  const [showDescriptors, setShowDescriptors] = useState(false)
  const [narrativeData, setNarrativeData] = useState<CohesionNarrativeView | null>(null)
  const [loadedChainId, setLoadedChainId] = useState<string | null>(null)
  const loadingNarrative = loadedChainId !== analysis.chain_id

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

  const members = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Dynamic Device Dominance Analysis - honestly handling missing devices
  const { dominantDevice, dominantCount, dominantPct, unassignedCount } = useMemo(() => {
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
    dominantCount > 0,
    timeSpanSecs !== null,
    dominantCount > 0,
    descriptors.length > 0,
    false, // delay unindexed
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
                dominantCount > 0 ? 'bg-secondary/15 text-secondary' : 'bg-surface-container-high/40 text-on-surface-variant'
              }`}>
                {dominantCount > 0 ? 'Observed' : 'Unassigned'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {dominantCount > 0
                ? `Dominant topological anchor observed. Alarm dispatch concentrates on ${dominantDevice}.`
                : 'No topological anchor assigned across alarms in this chain.'}
            </p>

            {/* Metric Breakdown Visual */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Target Host: <span className="text-on-surface font-semibold">{dominantDevice || 'Unassigned'}</span>
                </span>
                <span className="text-secondary font-bold">{dominantPct}% Coverage</span>
              </div>
              {/* High-contrast Gauge */}
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${dominantPct}%` }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>{dominantCount} of {totalAlarms} Alarms</span>
                <span>{Math.max(0, totalAlarms - dominantCount)} Other Alarms{unassignedCount > 0 ? ` (${unassignedCount} unassigned)` : ''}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className={`flex items-center gap-1 ${dominantCount > 0 ? 'text-secondary' : 'text-on-surface-variant'}`}>
              <span className="material-symbols-outlined text-[14px]">{dominantCount > 0 ? 'check_circle' : 'help'}</span>
              {dominantCount > 0 ? 'Observed' : 'Unassigned'}
            </span>
            <span className="text-on-surface font-semibold">Anchor: {dominantDevice || 'Unassigned'}</span>
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
                {timeSpanSecs === null ? 'Indeterminate' : 'Observed'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {timeSpanSecs === null
                ? 'Insufficient timestamp telemetry to evaluate temporal burst clustering.'
                : `Observed arrival span. ${burstCount} of ${totalAlarms} alarms fired within a ${typeof timeSpanSecs === 'number' ? timeSpanSecs.toFixed(1) : timeSpanLabel}s window.`}
            </p>

            {/* SVG Sparkline & Window Details */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Onset: <span className="text-on-surface font-semibold">{timeSpanSecs !== null ? `${startLabel} (T+0s)` : 'N/A'}</span>
                </span>
                <span className="text-secondary font-bold">
                  {burstPct !== null ? `${burstPct}% Window Cluster` : 'N/A'}
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
                  Window: {typeof timeSpanSecs === 'number' ? `${timeSpanSecs.toFixed(1)}s` : timeSpanLabel} ({startLabel} → {endLabel})
                </span>
                <span>Arrival Rate: {arrivalRate !== null ? `${arrivalRate}/s` : 'N/A'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-secondary">
              <span className="material-symbols-outlined text-[14px]">bolt</span>
              {timeSpanSecs !== null ? (timeSpanSecs <= 60 ? 'Micro-Burst Observed' : 'Extended Span') : 'No Timing Data'}
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
                {dominantCount > 0 ? 'Observed' : 'Unassigned'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {dominantCount > 0
                ? `Direct host co-location. Alarms share common physical network element hosting on ${dominantDevice}.`
                : 'No common physical network element hosting identified.'}
            </p>

            {/* Linecard Slot Breakdown */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">Same-Host Alarms</span>
                <span className="text-secondary font-bold">{dominantCount} / {totalAlarms} Alarms</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${dominantPct}%` }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Sub-slot: Not Indexed</span>
                <span>Host: {dominantDevice || 'Unassigned'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-secondary">
              <span className="material-symbols-outlined text-[14px]">view_in_ar</span> Host Co-location
            </span>
            <span className="text-on-surface font-semibold">Host Affinity: {dominantPct}%</span>
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
                  ? 'Unavailable'
                  : 'Not Evaluated'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {descriptors.length > 0
                ? `Recurrent pattern across historical mining. Demonstrates empirical coupling with ${descriptors.length} mined contrastive rule(s).`
                : 'Historical co-occurrence rules not evaluated or unavailable for this alarm combination.'}
            </p>

            {/* Historical Matrix Card */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Mined Rules: <span className="text-on-surface font-semibold">{descriptors.length} Rules</span>
                </span>
                <span className="text-tertiary font-bold">Lift: {histLift ? `${histLift}x` : 'N/A'}</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div
                  className="bg-tertiary h-full rounded-full transition-all"
                  style={{ width: descriptors.length > 0 ? `${Math.min(100, Math.round((descriptors[0]?.coverage || 0) * 100))}%` : '0%' }}
                ></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Baseline: 1.0</span>
                <span>Confidence: {histConfidence ? `${histConfidence}%` : 'N/A'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-tertiary">
              <span className="material-symbols-outlined text-[14px]">auto_graph</span>
              {descriptors.length > 0 ? 'Grounded Rules' : 'No Grounded Rules'}
            </span>
            <span className="text-on-surface font-semibold">
              {descriptors.length > 0 ? `Rules: ${descriptors.length}` : 'FDR: Not Evaluated'}
            </span>
          </div>
        </div>

        {/* DIM 05: Temporal Delay */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-5' ? null : 'dim-5')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-5'
              ? 'bg-[#18263f] border-tertiary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-tertiary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-tertiary text-[18px]">timelapse</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 05: Temporal Delay</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                isDelayUnavailable ? 'bg-surface-container-high/40 text-on-surface-variant' : 'bg-tertiary/15 text-tertiary'
              }`}>
                {isDelayUnavailable ? 'Unavailable' : 'Not Evaluated'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {isDelayUnavailable
                ? 'Pairwise delay propagation telemetry is unavailable in current configuration.'
                : 'Pairwise temporal delay telemetry not indexed for full chain path.'}
            </p>

            {/* Delay Metric Box */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">
                  Resolved Pairs: <span className="text-on-surface font-semibold">{isDelayUnavailable ? 'Unavailable' : 'Not Indexed'}</span>
                </span>
                <span className="text-tertiary font-bold">Indexing: N/A</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-tertiary h-full rounded-full transition-all" style={{ width: '0%' }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Known Delay: Not Indexed</span>
                <span>Telemetry GAP: Unindexed</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-tertiary">
              <span className="material-symbols-outlined text-[14px]">warning</span> Telemetry Gap
            </span>
            <span className="text-on-surface font-semibold">Propagation: Not Evaluated</span>
          </div>
        </div>

        {/* DIM 06: Topology Mapping */}
        <div
          onClick={() => setSelectedCardId(selectedCardId === 'dim-6' ? null : 'dim-6')}
          className={`rounded-xl p-space-md shadow flex flex-col justify-between cursor-pointer transition-all border ${
            selectedCardId === 'dim-6'
              ? 'bg-[#18263f] border-tertiary'
              : 'bg-[#0e1728] border-[#1b273e] hover:border-tertiary/40 hover:bg-[#121d33]'
          }`}
        >
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-tertiary text-[18px]">hub</span>
                <span className="font-code-md text-sm text-on-surface font-bold">DIM 06: Topology Mapping</span>
              </div>
              <span className={`px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold ${
                isTopoUnavailable ? 'bg-surface-container-high/40 text-on-surface-variant' : 'bg-secondary/15 text-secondary'
              }`}>
                {isTopoUnavailable ? 'Unavailable' : 'Available'}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {isTopoUnavailable
                ? 'Physical topology graph traversal is unavailable in current configuration.'
                : 'Physical IP Core and optical topology mapping.'}
            </p>

            {/* Topology Ring Representation */}
            <div className="flex flex-col gap-1.5 bg-[#080d17] p-space-sm rounded-lg border border-[#1b273e]/60 font-code-sm text-xs">
              <div className="flex items-center justify-between">
                <span className="text-on-surface-variant">Core Graph Map</span>
                <span className="text-tertiary font-bold">{isTopoUnavailable ? 'Unavailable' : 'Available'}</span>
              </div>
              <div className="w-full bg-[#151f33] h-2 rounded-full overflow-hidden flex">
                <div className="bg-secondary h-full rounded-full transition-all" style={{ width: isTopoUnavailable ? '0%' : '100%' }}></div>
              </div>
              <div className="flex justify-between items-center font-label-caps text-[10px] text-on-surface-variant">
                <span>Adjacency: {isTopoUnavailable ? 'Not Evaluated' : 'Mapped'}</span>
                <span>Layer 1/3: {isTopoUnavailable ? 'Unverified' : 'Verified'}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-2 border-t border-[#1b273e] flex items-center justify-between text-on-surface-variant font-code-sm text-xs">
            <span className="flex items-center gap-1 text-on-surface-variant">
              <span className="material-symbols-outlined text-[14px]">link_off</span> Topology Capability
            </span>
            <span className="text-on-surface font-semibold">Capability: {isTopoUnavailable ? 'Unavailable' : 'Available'}</span>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 4. Multi-dimensional Evidence Synthesis Table matching screen.png */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] rounded-xl p-space-md shadow-md flex flex-col gap-space-md border border-[#1b273e]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[20px]">tune</span>
            <h2 className="font-headline-md text-sm font-bold text-on-surface">
              Evidence Dimension Weightings &amp; Chain Fit
            </h2>
            <InfoTip text="Bảng tổng hợp trọng số chứng cứ đa chiều và mức độ đóng góp vào tính gắn kết của toàn bộ chuỗi." />
          </div>
          <div className="flex items-center gap-2 font-code-sm text-xs text-on-surface-variant">
            <span className="w-2 h-2 rounded-full bg-secondary"></span>
            <span>{evaluatedCount} Evaluated / Observed</span>
            <span className="w-2 h-2 rounded-full bg-tertiary ml-2"></span>
            <span>{6 - evaluatedCount} Unindexed / Unavailable</span>
          </div>
        </div>

        {/* Data Matrix Table */}
        <div className="w-full overflow-x-auto rounded-lg border border-[#1b273e]">
          <table className="w-full text-left font-body-sm text-xs">
            <thead className="bg-[#080d17] font-label-caps text-[10px] uppercase text-on-surface-variant border-b border-[#1b273e]">
              <tr>
                <th className="p-3">Evidence Dimension</th>
                <th className="p-3">Dimension Hypothesis</th>
                <th className="p-3 text-center">Observed Ratio</th>
                <th className="p-3 text-right">Confidence Level</th>
                <th className="p-3 text-right">Chain Unity Impact</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f33] font-code-sm text-xs">
              {/* Row 1: Entity Reference */}
              <tr className="hover:bg-[#121f36] transition-colors bg-[#0a101f]/50">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[16px]">dns</span>
                  Entity Reference
                </td>
                <td className="p-3 text-on-surface-variant">
                  Single-device origin accounts for majority of alarms
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  {dominantCount} / {totalAlarms} ({dominantPct}%)
                </td>
                <td className="p-3 text-right text-secondary font-bold">{dominantCount > 0 ? 'OBSERVED' : 'UNASSIGNED'}</td>
                <td className="p-3 text-right text-secondary font-bold">{dominantCount > 0 ? 'Primary Anchor' : '—'}</td>
              </tr>

              {/* Row 2: Temporal Synchronization */}
              <tr className="hover:bg-[#121f36] transition-colors">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[16px]">timer</span>
                  Temporal Synchronization
                </td>
                <td className="p-3 text-on-surface-variant">
                  Synchronous cluster within observed time window
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  {burstCount !== null ? `${burstCount} / ${totalAlarms} (${burstPct}%)` : 'N/A'}
                </td>
                <td className="p-3 text-right text-secondary font-bold">
                  {timeSpanSecs !== null ? 'OBSERVED' : 'INDETERMINATE'}
                </td>
                <td className="p-3 text-right text-secondary font-bold">
                  {timeSpanSecs !== null ? 'Temporal Cluster' : '—'}
                </td>
              </tr>

              {/* Row 3: Device Evidence */}
              <tr className="hover:bg-[#121f36] transition-colors bg-[#0a101f]/50">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[16px]">developer_board</span>
                  Device Evidence
                </td>
                <td className="p-3 text-on-surface-variant">
                  Hardware co-location on dominant device host
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  {dominantCount} / {totalAlarms} ({dominantPct}%)
                </td>
                <td className="p-3 text-right text-secondary font-bold">{dominantCount > 0 ? 'OBSERVED' : 'UNASSIGNED'}</td>
                <td className="p-3 text-right text-secondary font-bold">{dominantCount > 0 ? 'Host Co-location' : '—'}</td>
              </tr>

              {/* Row 4: Historical Co-occurrence */}
              <tr className="hover:bg-[#121f36] transition-colors">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-tertiary text-[16px]">history_edu</span>
                  Historical Co-occurrence
                </td>
                <td className="p-3 text-on-surface-variant">
                  Significant co-firing above background baseline
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  {histLift ? `Lift = ${histLift}x` : 'N/A'}
                </td>
                <td className="p-3 text-right text-tertiary font-bold">
                  {descriptors.length > 0 ? 'GROUNDED' : unavailableCaps.some(c => c.includes('HISTORICAL')) ? 'UNAVAILABLE' : 'NOT_EVALUATED'}
                </td>
                <td className="p-3 text-right text-tertiary font-bold">
                  {descriptors.length > 0 ? 'Rule Grounded' : '—'}
                </td>
              </tr>

              {/* Row 5: Temporal Delay */}
              <tr className="hover:bg-[#121f36] transition-colors bg-[#0a101f]/50">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-tertiary text-[16px]">timelapse</span>
                  Temporal Delay (T_del)
                </td>
                <td className="p-3 text-on-surface-variant">
                  Observed temporal sequence matched against empirical baseline
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  Not Indexed
                </td>
                <td className="p-3 text-right text-tertiary font-bold">
                  {isDelayUnavailable ? 'UNAVAILABLE' : 'NOT_INDEXED'}
                </td>
                <td className="p-3 text-right text-tertiary font-bold">—</td>
              </tr>

              {/* Row 6: Topology Mapping */}
              <tr className="hover:bg-[#121f36] transition-colors">
                <td className="p-3 font-semibold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-tertiary text-[16px]">hub</span>
                  Topology Mapping
                </td>
                <td className="p-3 text-on-surface-variant">
                  Physical IP Core Adjacency graph traversal verification
                </td>
                <td className="p-3 text-center text-on-surface font-semibold">
                  {isTopoUnavailable ? 'Unavailable' : 'Available'}
                </td>
                <td className="p-3 text-right text-tertiary font-bold">
                  {isTopoUnavailable ? 'UNAVAILABLE' : 'AVAILABLE'}
                </td>
                <td className="p-3 text-right text-tertiary font-bold">
                  {isTopoUnavailable ? '—' : 'Graph Adjacency'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
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
                Evidence Synthesis: {evaluatedCount} of 6 dimensions evaluated.
              </span>
              {narrativeData?.model && (
                <span className="text-[10px] font-code-sm px-2 py-0.5 rounded bg-[#16233b] border border-[#223352] text-secondary">
                  {narrativeData.model === 'DETERMINISTIC_EVIDENCE' ? 'Deterministic Evidence' : `AI: ${narrativeData.model}`}
                </span>
              )}
            </div>
            {loadingNarrative ? (
              <div className="h-4 w-3/4 bg-surface-container-high/40 animate-pulse rounded my-1" />
            ) : (
              <p className="font-body-sm text-xs text-on-surface-variant leading-relaxed">
                {narrativeData?.narrative || (
                  analysis.singleton
                    ? 'Chuỗi này chỉ chứa 1 cảnh báo duy nhất đã quan sát. Phân tích gắn kết đa thành viên và lan truyền không áp dụng.'
                    : `Chuỗi ${analysis.chain_id} chứa ${totalAlarms} cảnh báo đã quan sát. Kiểm tra cấu trúc Tier-2 chưa được thực hiện.`
                )}
              </p>
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
              <span>Machine-Learned Contrastive Descriptors ({descriptors.length} Rules Grounded)</span>
            </span>
            <div className="flex items-center gap-1 font-code-sm text-[11px] text-secondary">
              <span>{showDescriptors ? 'Hide Details' : 'Show Details'}</span>
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
                    <th className="p-2">Kind</th>
                    <th className="p-2">Label / Rule</th>
                    <th className="p-2 text-right">Coverage</th>
                    <th className="p-2 text-right">Global Prec.</th>
                    <th className="p-2 text-right">Local Prec.</th>
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
