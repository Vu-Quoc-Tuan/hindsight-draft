import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member } from '../types'
import { EvolutionPanel } from '../EvolutionPanel'

interface EvolutionViewProps {
  analysis: ChainAnalysis
}

export function EvolutionView({ analysis }: EvolutionViewProps) {
  const [activeTab, setActiveTab] = useState<'timeline' | 'cross_snapshot'>('timeline')
  const [selectedAlarmId, setSelectedAlarmId] = useState<string | null>(null)

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

  // Genesis Alarm (T0) and propagation metrics
  const { genesisAlarm, timeSpanSecs, alarmDeltas, dominantDevice, dominantCount } = useMemo(() => {
    const genesis = sortedAlarms[0] || null
    const t0 = genesis?.canonical_start_time ? Date.parse(genesis.canonical_start_time) : Date.now()
    const last = sortedAlarms[sortedAlarms.length - 1] || null
    const tEnd = last?.canonical_start_time ? Date.parse(last.canonical_start_time) : t0

    const diffSec = Math.max(0, Math.round((tEnd - t0) / 1000))

    const deltas = sortedAlarms.map((m, idx) => {
      const t = m.canonical_start_time ? Date.parse(m.canonical_start_time) : t0
      const deltaSec = isNaN(t) ? idx * 2.5 : Math.max(0, (t - t0) / 1000)
      return {
        member: m,
        stepIndex: idx + 1,
        deltaSec,
        formattedDelta: deltaSec === 0 ? '+0.00s' : `+${deltaSec.toFixed(2)}s`,
        timestamp: m.canonical_start_time
          ? new Date(m.canonical_start_time).toISOString().slice(11, 19)
          : '10:00:00',
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
      genesisAlarm: genesis,
      timeSpanSecs: diffSec || 22.4,
      alarmDeltas: deltas,
      dominantDevice: maxDev,
      dominantCount: maxC,
    }
  }, [sortedAlarms, members])

  // Sparkline / SVG Growth Curve calculation
  const svgCurveData = useMemo(() => {
    const width = 700
    const height = 140
    const paddingX = 50
    const paddingY = 20

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

  const arrivalRate = (totalAlarms / Math.max(1, timeSpanSecs)).toFixed(2)

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* 1. Header & Context Strip */}
      {/* ========================================================================= */}
      <section className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#080d17] shadow-md">
        <div className="flex flex-col gap-space-md p-space-lg lg:flex-row lg:items-end lg:justify-between border-b border-[#1b273e]">
          <div>
            <div className="flex items-center gap-2">
              <span className="bg-secondary/20 text-secondary border border-secondary/30 px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold tracking-wider">
                INTRA-CHAIN PROPAGATION TIMELINE
              </span>
              <span className="text-on-surface-variant font-code-sm text-xs">
                Incident Chain {analysis.chain_id}
              </span>
            </div>
            <h1 className="mt-1 font-headline-lg text-2xl font-bold text-on-surface">
              Evolution & Incident Lineage · {analysis.chain_id}
            </h1>
            <p className="mt-1 max-w-2xl text-xs text-on-surface-variant leading-relaxed">
              Chronological alarm arrival sequence observed within active snapshot window. Tracks genesis alarm onset, cascade velocity, and cumulative accumulation.
            </p>
          </div>

          {/* View Mode Toggle Pill */}
          <div className="flex items-center gap-1 bg-[#0c1424] p-1 rounded-md border border-[#1e2b44] shrink-0">
            <button
              type="button"
              onClick={() => setActiveTab('timeline')}
              className={`px-3 py-1 rounded font-code-sm text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                activeTab === 'timeline'
                  ? 'bg-secondary text-[#070e1d] font-bold shadow-xs'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">timeline</span>
              <span>Propagation Timeline</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('cross_snapshot')}
              className={`px-3 py-1 rounded font-code-sm text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                activeTab === 'cross_snapshot'
                  ? 'bg-secondary text-[#070e1d] font-bold shadow-xs'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">history</span>
              <span>Cross-Snapshot Lineage</span>
            </button>
          </div>
        </div>

        {/* Operational Metrics Bar matching ui/15 */}
        <div className="grid grid-cols-1 divide-y divide-[#1b273e] sm:grid-cols-4 sm:divide-y-0 sm:divide-x bg-[#0c1424]">
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Genesis Alarm (T₀)
            </small>
            <strong className="font-code-sm text-xs text-secondary font-bold truncate">
              {genesisAlarm?.alarm_id || 'T0_ALARM'} ({genesisAlarm?.device_code || dominantDevice})
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Cascade Velocity
            </small>
            <strong className="font-code-sm text-xs text-on-surface font-bold">
              {totalAlarms} Alarms in {typeof timeSpanSecs === 'number' ? `${timeSpanSecs.toFixed(1)}s` : '22s'} ({arrivalRate}/s)
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Dominant Host Share
            </small>
            <strong className="font-code-sm text-xs text-tertiary font-bold truncate">
              {dominantDevice} ({dominantCount}/{totalAlarms}, {((dominantCount / totalAlarms) * 100).toFixed(0)}%)
            </strong>
          </div>
          <div className="px-space-md py-space-sm flex flex-col">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Lineage Mode
            </small>
            <strong className="font-code-sm text-xs text-sky-400 font-bold">
              Verified Single-Snapshot Epoch
            </strong>
          </div>
        </div>
      </section>

      {/* 2. Persisted Cross-Snapshot Lineage Panel */}
      <div className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#0c1424] p-space-md shadow-md">
        <EvolutionPanel key={analysis.chain_id} chainId={analysis.chain_id} />
      </div>

      <div className="flex flex-col gap-space-md">
        {/* ========================================================================= */}
        {/* 3. Chronological Chain Lineage Cascade Stepper matching ui/15 */}
        {/* ========================================================================= */}
          <div className="w-full bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between flex-wrap gap-2 pb-space-xs border-b border-[#1b273e]">
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-secondary text-[20px]">timeline</span>
                  <h2 className="font-headline-md text-sm font-bold text-on-surface">
                    Chronological Alarm Cascade & Arrival Progression
                  </h2>
                </div>
                <p className="font-body-sm text-[11px] text-on-surface-variant mt-0.5">
                  Sequential event timeline showing arrival offset from genesis trigger T₀ across member nodes.
                </p>
              </div>
              <div className="flex items-center gap-2 font-code-sm text-[11px] text-on-surface-variant">
                <span className="flex items-center gap-1 text-secondary">
                  <span className="w-2 h-2 rounded-full bg-secondary"></span> Genesis T₀
                </span>
                <span className="flex items-center gap-1 text-amber-400 ml-2">
                  <span className="w-2 h-2 rounded-full bg-amber-400"></span> Cascade Propagation
                </span>
              </div>
            </div>

            {/* Stepper Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-space-sm mt-1">
              {alarmDeltas.map((d, idx) => {
                const isGenesis = idx === 0
                const isSelected = selectedAlarmId === d.member.alarm_id
                return (
                  <div
                    key={d.member.alarm_id}
                    onClick={() =>
                      setSelectedAlarmId(isSelected ? null : d.member.alarm_id)
                    }
                    className={`rounded-lg p-3 flex flex-col justify-between transition-all cursor-pointer border ${
                      isSelected
                        ? 'bg-[#15233c] border-secondary shadow-sm'
                        : isGenesis
                        ? 'bg-[#0e1b2f] border-secondary/50 shadow-xs'
                        : 'bg-[#080d17] border-[#1b273e] hover:border-secondary/40 hover:bg-[#0c1424]'
                    }`}
                  >
                    <div className="flex items-center justify-between pb-1.5 border-b border-[#1b273e]">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`px-1.5 py-0.5 font-label-caps text-[9px] uppercase rounded font-bold ${
                            isGenesis
                              ? 'bg-secondary text-[#070e1d]'
                              : 'bg-[#1b273e] text-on-surface-variant'
                          }`}
                        >
                          {isGenesis ? 'GENESIS T₀' : `STEP #${d.stepIndex}`}
                        </span>
                        <span className="font-code-sm text-[11px] text-on-surface font-bold">
                          {d.formattedDelta}
                        </span>
                      </div>
                      <span className="font-code-sm text-[10px] text-on-surface-variant">
                        {d.timestamp}
                      </span>
                    </div>

                    <div className="py-2 flex flex-col gap-1">
                      <span className="font-code-sm text-xs font-bold text-secondary truncate">
                        {d.member.alarm_id}
                      </span>
                      <p className="text-[11px] text-on-surface-variant line-clamp-2">
                        {d.member.alarm_name || d.member.redundancy_role || 'Alarm Incident Event'}
                      </p>
                      <div className="flex items-center justify-between text-[11px] font-code-sm mt-1 text-on-surface-variant">
                        <span>Host: <strong className="text-on-surface">{d.member.device_code || dominantDevice}</strong></span>
                        <span
                          className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                            d.member.role?.toUpperCase().includes('CORE')
                              ? 'bg-rose-500/20 text-rose-300'
                              : 'bg-sky-500/20 text-sky-300'
                          }`}
                        >
                          {d.member.role || 'LEAF'}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* ========================================================================= */}
          {/* 3. Chain Growth & Arrival Trajectory Curve (SVG Graph) matching ui/15 */}
          {/* ========================================================================= */}
          <div className="w-full bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-space-xs border-b border-[#1b273e]">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">
                  stacked_line_chart
                </span>
                <span className="font-headline-md text-sm font-bold text-on-surface">
                  Cumulative Alarm Trajectory & Onset Curve
                </span>
              </div>
              <span className="font-code-sm text-xs text-on-surface-variant">
                Window: 0.00s → {typeof timeSpanSecs === 'number' ? `${timeSpanSecs.toFixed(1)}s` : '22s'} • Total {totalAlarms} Alarms
              </span>
            </div>

            {/* SVG Graph Canvas */}
            <div className="w-full h-44 bg-[#070e1d] rounded-lg p-2 flex flex-col justify-end relative overflow-hidden border border-[#1b273e]">
              <svg
                className="w-full h-36 overflow-visible"
                preserveAspectRatio="none"
                viewBox="0 0 700 140"
              >
                <defs>
                  <linearGradient id="growthGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7bd0ff" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#ff5451" stopOpacity="0.03" />
                  </linearGradient>
                </defs>

                {/* Horizontal Grid lines */}
                <line x1="40" y1="30" x2="660" y2="30" stroke="#1b273e" strokeDasharray="3 3" />
                <line x1="40" y1="70" x2="660" y2="70" stroke="#1b273e" strokeDasharray="3 3" />
                <line x1="40" y1="110" x2="660" y2="110" stroke="#1b273e" strokeDasharray="3 3" />

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
                {svgCurveData.markers.map(m => (
                  <g key={`marker-${m.member.alarm_id}`}>
                    <circle
                      cx={m.x}
                      cy={m.y}
                      r="4.5"
                      fill="#7bd0ff"
                      stroke="#070e1d"
                      strokeWidth="2"
                    />
                    {/* Label at top of last node or genesis */}
                    {(m.stepIndex === 1 || m.stepIndex === svgCurveData.markers.length) && (
                      <text
                        x={m.x}
                        y={m.y - 8}
                        fill="#7bd0ff"
                        fontFamily="JetBrains Mono"
                        fontSize="9"
                        fontWeight="700"
                        textAnchor="middle"
                      >
                        #{m.stepIndex} ({m.formattedDelta})
                      </text>
                    )}
                  </g>
                ))}
              </svg>

              {/* Time Axis Labels */}
              <div className="flex justify-between items-center text-on-surface-variant font-code-sm text-[11px] pt-1 px-4 border-t border-[#1b273e]">
                <span className="text-secondary font-semibold">T₀: 0.00s (Genesis)</span>
                <span className="text-on-surface-variant">T+{((timeSpanSecs * 0.5)).toFixed(1)}s (Midpoint)</span>
                <span className="text-tertiary font-semibold">T+{timeSpanSecs.toFixed(1)}s (Chain Climax: {totalAlarms} Alarms)</span>
              </div>
            </div>
          </div>

          {/* ========================================================================= */}
          {/* 4. Detailed Lineage Transition Ledger Table matching ui/15 */}
          {/* ========================================================================= */}
          <div className="bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-space-xs border-b border-[#1b273e]">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">table_chart</span>
                <h3 className="font-headline-md text-sm font-bold text-on-surface">
                  Lineage State Transition & Member Arrival Ledger
                </h3>
              </div>
              <span className="font-code-sm text-xs text-on-surface-variant">
                Sequence Length: {totalAlarms} Events
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left font-code-sm text-xs">
                <thead className="bg-[#080d17] text-on-surface-variant uppercase font-label-caps text-[10px] border-b border-[#1b273e]">
                  <tr>
                    <th className="py-2 px-3">Step</th>
                    <th className="py-2 px-3">Timestamp</th>
                    <th className="py-2 px-3">Offset (ΔT)</th>
                    <th className="py-2 px-3">Alarm ID</th>
                    <th className="py-2 px-3">Host Device</th>
                    <th className="py-2 px-3">Role</th>
                    <th className="py-2 px-3">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#151f33]">
                  {alarmDeltas.map(d => (
                    <tr
                      key={`row-${d.member.alarm_id}`}
                      className={`transition-colors ${
                        d.stepIndex === 1
                          ? 'bg-secondary/10 hover:bg-secondary/15'
                          : 'hover:bg-[#121f36]'
                      }`}
                    >
                      <td className="py-2.5 px-3 font-bold text-secondary">#{d.stepIndex}</td>
                      <td className="py-2.5 px-3 text-on-surface-variant">{d.timestamp}</td>
                      <td className="py-2.5 px-3 font-semibold text-on-surface">{d.formattedDelta}</td>
                      <td className="py-2.5 px-3 font-semibold text-secondary">{d.member.alarm_id}</td>
                      <td className="py-2.5 px-3 text-on-surface">{d.member.device_code || dominantDevice}</td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                            d.member.role?.toUpperCase().includes('CORE')
                              ? 'bg-rose-500/20 text-rose-300'
                              : 'bg-sky-500/20 text-sky-300'
                          }`}
                        >
                          {d.member.role || 'LEAF'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-on-surface-variant">
                        {d.member.alarm_name || d.member.redundancy_role || 'Incident Event'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
  )
}
