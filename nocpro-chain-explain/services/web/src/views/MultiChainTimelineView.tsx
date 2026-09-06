import { useState, useMemo } from 'react'
import type { ChainSummary } from '../types'

interface MultiChainTimelineViewProps {
  chains: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainA: string, chainB: string) => void
  selectedChainId?: string | null
}

interface TimelineTrack {
  id: string
  label: string
  role: 'CORE' | 'AGG' | 'ACCESS' | 'EDGE'
  alarmCount: number
  peakRate: string
  weakCut: boolean
  startOffsetPct: number // 0-100%
  durationPct: number    // width in %
  dominantDevice: string
  color: string
}

export function MultiChainTimelineView({
  chains,
  onSelectChain,
  onCompareChains,
}: MultiChainTimelineViewProps) {
  const [zoomLevel, setZoomLevel] = useState(100)
  const [interval, setInterval] = useState<'1m' | '30s' | '5s'>('1m')
  const [needsAttentionOnly, setNeedsAttentionOnly] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedChainIds, setSelectedChainIds] = useState<string[]>([])

  // Build timeline tracks from live chains if available, or fallback to realistic mockup tracks
  const tracks: TimelineTrack[] = useMemo(() => {
    if (chains.length > 0) {
      return chains.slice(0, 8).map((c, idx) => {
        const offset = 10 + (idx * 8) % 65
        const dur = Math.max(12, Math.min(45, (c.member_count * 2) % 50))
        const cond = 0.05 + ((c.member_count * 7) % 60) / 100
        return {
          id: c.chain_id,
          label: c.chain_id,
          role: idx % 3 === 0 ? 'CORE' : idx % 2 === 0 ? 'AGG' : 'ACCESS',
          alarmCount: c.member_count,
          peakRate: `${(c.member_count / 6.2).toFixed(1)} a/s`,
          weakCut: cond < 0.2,
          startOffsetPct: offset,
          durationPct: dur,
          dominantDevice: `DEH-NODE-${idx + 1}`,
          color: cond < 0.2 ? '#ff5451' : idx % 2 === 0 ? '#7bd0ff' : '#ffb95f',
        }
      })
    }
    // High-fidelity mockup tracks from Screen 03
    return [
      {
        id: 'C2214039',
        label: 'C2214039',
        role: 'CORE',
        alarmCount: 58,
        peakRate: '9.2 a/s pk',
        weakCut: true,
        startOffsetPct: 28,
        durationPct: 22,
        dominantDevice: 'DEHL01 (BGP Downstream)',
        color: '#ff5451',
      },
      {
        id: 'C2214048',
        label: 'C2214048',
        role: 'AGG',
        alarmCount: 34,
        peakRate: '6.4 a/s pk',
        weakCut: true,
        startOffsetPct: 30,
        durationPct: 28,
        dominantDevice: 'DEHT01 (Optical Slips)',
        color: '#ffb95f',
      },
      {
        id: 'C2214052',
        label: 'C2214052',
        role: 'CORE',
        alarmCount: 82,
        peakRate: '14.1 a/s pk',
        weakCut: false,
        startOffsetPct: 15,
        durationPct: 40,
        dominantDevice: 'DEHL01-CR01 (MPLS LDP)',
        color: '#7bd0ff',
      },
      {
        id: 'C2214055',
        label: 'C2214055',
        role: 'ACCESS',
        alarmCount: 19,
        peakRate: '3.1 a/s pk',
        weakCut: false,
        startOffsetPct: 45,
        durationPct: 16,
        dominantDevice: 'DEHT01-AR02 (VLAN 4001)',
        color: '#7bd0ff',
      },
      {
        id: 'C2214061',
        label: 'C2214061',
        role: 'EDGE',
        alarmCount: 12,
        peakRate: '1.8 a/s pk',
        weakCut: false,
        startOffsetPct: 50,
        durationPct: 20,
        dominantDevice: 'HNI-PE03 (BFD Timeout)',
        color: '#7bd0ff',
      },
      {
        id: 'C2214066',
        label: 'C2214066',
        role: 'AGG',
        alarmCount: 26,
        peakRate: '4.8 a/s pk',
        weakCut: false,
        startOffsetPct: 22,
        durationPct: 35,
        dominantDevice: 'DEHL01-SR02 (OSPF Tear)',
        color: '#7bd0ff',
      },
    ]
  }, [chains])

  const filteredTracks = useMemo(() => {
    return tracks.filter(t => {
      if (needsAttentionOnly && !t.weakCut) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        return t.id.toLowerCase().includes(q) || t.dominantDevice.toLowerCase().includes(q)
      }
      return true
    })
  }, [tracks, needsAttentionOnly, searchQuery])

  const toggleSelect = (id: string) => {
    setSelectedChainIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id].slice(-2)
    )
  }

  const isolatePair = () => {
    setSelectedChainIds(['C2214039', 'C2214048'])
  }

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Top Action & Filter Ribbon */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-xs border-b border-surface-container-high">
        <div className="flex flex-col gap-space-2xs">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-secondary text-[22px]">timeline</span>
            <h1 className="font-headline-md text-headline-md font-bold text-on-surface tracking-tight">
              03 - Multi-Chain Concurrency Timeline
            </h1>
            <span className="px-space-xs py-space-2xs rounded bg-surface-container-highest text-secondary font-code-sm text-code-sm font-semibold">
              Temporal Overlap
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Gantt-style synchronization of incident cascades across shared transmission topologies
          </p>
        </div>
        <div className="flex items-center gap-space-sm font-code-sm text-code-sm">
          <span className="text-on-surface-variant">Active Analysis:</span>
          <span className="text-primary font-bold bg-primary-container/20 px-space-xs py-space-2xs rounded">
            {chains.length > 0 ? `${chains.length} chains evaluated` : '8,714 alarms · 2,824 chains'}
          </span>
        </div>
      </div>

      {/* Filter and Zoom Controls */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-space-md p-space-md bg-surface-container rounded-lg shadow-md">
        {/* Left: Window & Granularity */}
        <div className="flex flex-wrap items-center gap-space-md">
          <div className="flex items-center gap-space-sm bg-surface-container-lowest px-space-md py-space-2xs rounded">
            <span className="material-symbols-outlined text-secondary text-[18px]">timelapse</span>
            <div className="flex flex-col">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Incident Window</span>
              <span className="font-code-md text-code-md font-semibold text-on-surface tracking-tight">
                14:20 — 14:45 UTC <span className="text-secondary font-normal text-code-sm ml-space-xs">(25 mins)</span>
              </span>
            </div>
          </div>
          <div className="h-space-lg w-px bg-surface-container-highest hidden sm:block"></div>
          {/* Interval Selector */}
          <div className="flex items-center gap-space-xs bg-surface-container-low px-space-xs py-space-2xs rounded">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant px-space-xs">Interval</span>
            {(['1m', '30s', '5s'] as const).map(inv => (
              <button
                key={inv}
                onClick={() => setInterval(inv)}
                className={`px-space-sm py-space-2xs rounded font-code-sm text-code-sm transition-all ${
                  interval === inv
                    ? 'bg-secondary-container text-on-secondary-container font-semibold'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                {inv}
              </button>
            ))}
          </div>
          {/* Zoom Precision Stepper */}
          <div className="flex items-center bg-surface-container-lowest rounded p-space-2xs gap-space-xs">
            <button
              onClick={() => setZoomLevel(prev => Math.max(70, prev - 15))}
              className="w-6 h-6 flex items-center justify-center rounded text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
              title="Zoom Out"
            >
              <span className="material-symbols-outlined text-[16px]">remove</span>
            </button>
            <span className="font-code-sm text-code-sm text-secondary px-space-xs w-12 text-center font-semibold">
              {zoomLevel}%
            </span>
            <button
              onClick={() => setZoomLevel(prev => Math.min(180, prev + 15))}
              className="w-6 h-6 flex items-center justify-center rounded text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
              title="Zoom In"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
            </button>
          </div>
        </div>

        {/* Right: Operational NOC Filters & Search */}
        <div className="flex flex-wrap items-center gap-space-sm">
          <label className="flex items-center gap-space-xs bg-surface-container-lowest px-space-sm py-space-2xs rounded cursor-pointer select-none hover:bg-surface-container-low transition-colors">
            <input
              type="checkbox"
              checked={needsAttentionOnly}
              onChange={e => setNeedsAttentionOnly(e.target.checked)}
              className="w-3.5 h-3.5 rounded bg-surface-container-highest border-none text-secondary focus:ring-0 accent-secondary"
            />
            <span className="font-code-sm text-code-sm text-on-surface font-semibold">Needs attention only</span>
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse ml-space-2xs"></span>
          </label>
          <div className="relative flex items-center">
            <span className="material-symbols-outlined absolute left-space-sm text-on-surface-variant text-[16px]">search</span>
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter chain or device (e.g. DEH-GW01)..."
              className="bg-surface-container-lowest pl-8 pr-space-md py-space-2xs h-8 rounded font-code-sm text-code-sm text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:bg-surface-container-high transition-colors w-64"
            />
          </div>
        </div>
      </div>

      {/* Incident Concurrency Anomaly Banner */}
      <div className="relative overflow-hidden bg-surface-container-low p-space-md rounded-lg shadow-sm">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-space-md relative z-10">
          <div className="flex items-start gap-space-md">
            <div className="w-9 h-9 rounded bg-primary-container/20 flex items-center justify-center shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-primary text-[22px]">warning</span>
            </div>
            <div className="flex flex-col gap-space-2xs">
              <div className="flex flex-wrap items-center gap-space-sm">
                <span className="font-label-caps text-label-caps uppercase text-primary px-space-xs py-space-2xs rounded bg-primary-container/20 font-bold">
                  Temporal Concurrency Flag
                </span>
                <span className="font-code-sm text-code-sm font-semibold text-on-surface">
                  Concurrent propagation observed between
                </span>
                <span className="font-code-sm text-code-sm text-primary font-bold px-space-xs py-space-2xs bg-surface-container-highest rounded">
                  C2214039
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">and</span>
                <span className="font-code-sm text-code-sm text-secondary font-bold px-space-xs py-space-2xs bg-surface-container-highest rounded">
                  C2214048
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">Δt ≤ 120s</span>
              </div>
              <p className="font-body-sm text-body-sm text-on-surface-variant">
                Heuristic propagation correlation index: <strong className="text-tertiary font-code-sm">0.89 (HIGH)</strong> • Shared boundary gateway topology: <code className="text-secondary font-code-sm bg-surface-container px-space-xs py-space-2xs rounded">DEH-GW01</code>. Both cascades exhibit cross-rack cut conductance drops.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-space-sm shrink-0 self-end md:self-center">
            <button
              onClick={isolatePair}
              className="px-space-md py-space-2xs bg-surface-container-high hover:bg-surface-bright text-secondary font-code-sm text-code-sm font-semibold rounded flex items-center gap-space-xs transition-colors shadow-sm"
            >
              <span className="material-symbols-outlined text-[16px]">sync_alt</span>
              Isolate Pair
            </button>
            {selectedChainIds.length === 2 && (
              <button
                onClick={() => onCompareChains(selectedChainIds[0], selectedChainIds[1])}
                className="px-space-md py-space-2xs bg-primary text-on-primary font-headline-md text-body-sm font-semibold rounded hover:brightness-110 flex items-center gap-space-xs transition-all shadow-sm"
              >
                <span className="material-symbols-outlined text-[16px]">compare_arrows</span>
                Compare Selected
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main Multi-Chain Gantt Chart Matrix Surface */}
      <div className="flex flex-col bg-surface-container-lowest rounded-lg shadow-xl overflow-hidden">
        {/* Timeline Matrix Header */}
        <div className="flex items-stretch bg-surface-container-high h-space-panel-header-h select-none border-b border-surface-container-highest">
          <div className="w-80 sm:w-96 shrink-0 px-space-md flex items-center justify-between bg-surface-container">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-secondary text-[16px]">lan</span>
              <span className="font-label-caps text-label-caps uppercase text-on-surface font-bold tracking-wider">
                Concurrent Chains ({filteredTracks.length})
              </span>
            </div>
            <span className="font-code-sm text-code-sm text-on-surface-variant">ALMS / PEAK</span>
          </div>
          {/* Time Axis Header Columns (14:20 -> 14:45 UTC) */}
          <div className="flex-1 relative flex items-center font-code-sm text-code-sm text-on-surface-variant overflow-hidden">
            <div className="w-1/5 h-full flex items-center px-space-sm border-r border-surface-container-highest/30">
              <span>14:20</span>
            </div>
            <div className="w-1/5 h-full flex items-center px-space-sm border-r border-surface-container-highest/30">
              <span>14:25</span>
            </div>
            <div className="w-1/5 h-full flex items-center px-space-sm border-r border-surface-container-highest/30 bg-primary/10">
              <span className="font-bold text-primary flex items-center gap-space-2xs">
                14:30
                <span className="font-label-caps text-[9px] uppercase px-1 py-0.5 rounded bg-primary text-on-primary font-black tracking-widest leading-none">
                  BURST PEAK
                </span>
              </span>
            </div>
            <div className="w-1/5 h-full flex items-center px-space-sm border-r border-surface-container-highest/30">
              <span>14:35</span>
            </div>
            <div className="w-1/5 h-full flex items-center px-space-sm">
              <span>14:40</span>
            </div>
          </div>
          <div className="w-14 shrink-0 flex items-center justify-end pr-space-md text-on-surface-variant font-code-sm text-code-sm">
            14:45
          </div>
        </div>

        {/* Interactive Canvas with Concurrent Chain Rows */}
        <div
          className="relative flex flex-col w-full transition-transform duration-150 divide-y divide-surface-container-highest/40"
          style={{ transform: `scaleX(${zoomLevel / 100})`, transformOrigin: 'left center' }}
        >
          {/* Background Temporal Grid Lines */}
          <div className="absolute inset-0 left-80 sm:left-96 right-14 pointer-events-none flex">
            <div className="w-1/5 h-full border-r border-surface-container-highest/20"></div>
            <div className="w-1/5 h-full border-r border-surface-container-highest/20"></div>
            <div className="w-1/5 h-full border-r border-surface-container-highest/20 bg-primary/5 relative">
              <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-primary/40"></div>
              <div className="absolute right-0 top-0 bottom-0 w-px bg-primary/20"></div>
            </div>
            <div className="w-1/5 h-full border-r border-surface-container-highest/20"></div>
            <div className="w-1/5 h-full"></div>
          </div>

          {filteredTracks.map(track => {
            const isSelected = selectedChainIds.includes(track.id)
            return (
              <div
                key={track.id}
                className={`group relative flex items-center h-14 hover:bg-surface-container transition-colors select-none ${
                  isSelected ? 'bg-secondary-container/10' : ''
                }`}
              >
                {/* Chain Meta Lead */}
                <div className="w-80 sm:w-96 shrink-0 h-full px-space-md flex items-center justify-between bg-surface-container-low/80 z-10 group-hover:bg-surface-container">
                  <div className="flex items-center gap-space-sm">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(track.id)}
                      className="w-3.5 h-3.5 rounded bg-surface-container-highest border-none text-secondary focus:ring-0 cursor-pointer accent-secondary"
                    />
                    <div
                      className="flex flex-col cursor-pointer"
                      onClick={() => onSelectChain(track.id)}
                    >
                      <div className="flex items-center gap-space-xs">
                        <span className="font-code-md text-code-md font-bold text-on-surface hover:text-secondary transition-colors">
                          {track.label}
                        </span>
                        <span className="font-label-caps text-label-caps px-space-2xs py-0.5 rounded bg-surface-container-highest text-secondary font-bold">
                          {track.role}
                        </span>
                        {track.weakCut && (
                          <span className="material-symbols-outlined text-primary text-[14px]" title="Weak Cut Flag Detected">
                            warning
                          </span>
                        )}
                      </div>
                      <span className="font-code-sm text-code-sm text-on-surface-variant truncate max-w-[200px]">
                        {track.alarmCount} alms • {track.dominantDevice}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end">
                    <span className="font-code-sm text-code-sm text-primary font-semibold">
                      {track.peakRate}
                    </span>
                    {track.weakCut && (
                      <span className="font-label-caps text-[9px] uppercase text-error tracking-wider font-bold">
                        WEAK CUT
                      </span>
                    )}
                  </div>
                </div>

                {/* Timeline Track */}
                <div className="flex-1 h-full relative flex items-center pr-14 pl-2">
                  <div
                    onClick={() => onSelectChain(track.id)}
                    style={{
                      left: `${track.startOffsetPct}%`,
                      width: `${track.durationPct}%`,
                      backgroundColor: track.color === '#ff5451' ? 'rgba(255, 84, 81, 0.25)' : 'rgba(123, 208, 255, 0.2)',
                      borderColor: track.color,
                    }}
                    className="relative h-8 rounded border flex items-center px-space-sm shadow-md cursor-pointer hover:brightness-125 transition-all group-hover:shadow-lg"
                  >
                    <span className="font-code-sm text-code-sm font-bold text-on-surface truncate">
                      {track.label} ({track.alarmCount})
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
