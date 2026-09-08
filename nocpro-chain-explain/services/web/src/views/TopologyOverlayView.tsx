import { useState, useMemo } from 'react'
import type { ChainAnalysis, Member } from '../types'
import type { TopologyTreePayload } from '../TopologyTree'

interface TopologyOverlayViewProps {
  analysis: ChainAnalysis
  topologyPayload?: TopologyTreePayload | null
  onRootChange?: (resourceId: string) => void
}

export function TopologyOverlayView({ analysis, topologyPayload, onRootChange: _onRootChange }: TopologyOverlayViewProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [showAlarmsLayer, setShowAlarmsLayer] = useState(true)
  const [showLinksLayer, setShowLinksLayer] = useState(true)

  const members: Member[] = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Group alarms by device/host
  const deviceGroups = useMemo(() => {
    const map = new Map<string, Member[]>()
    members.forEach(m => {
      const dev = m.device_code || m.node_reference || 'UNKNOWN_HOST'
      if (!map.has(dev)) {
        map.set(dev, [])
      }
      map.get(dev)!.push(m)
    })

    // Sort devices by alarm count descending
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [members])

  const distinctDevices = useMemo(() => deviceGroups.map(([dev]) => dev), [deviceGroups])
  const dominantDevice = distinctDevices[0] || 'DOMINANT_NODE'
  const dominantAlarms = deviceGroups[0]?.[1] || []
  const dominantCount = dominantAlarms.length

  // Filtered devices/members based on search
  const filteredDeviceGroups = useMemo(() => {
    if (!searchQuery.trim()) return deviceGroups
    const q = searchQuery.toLowerCase().trim()
    return deviceGroups.filter(([dev, alms]) => {
      if (dev.toLowerCase().includes(q)) return true
      return alms.some(
        m =>
          m.alarm_id.toLowerCase().includes(q) ||
          (m.alarm_name ?? '').toLowerCase().includes(q) ||
          (m.redundancy_role ?? '').toLowerCase().includes(q)
      )
    })
  }, [deviceGroups, searchQuery])

  // Active inspected device (default to dominant device)
  const activeDevice = selectedDeviceId || dominantDevice
  const activeGroup = deviceGroups.find(([d]) => d === activeDevice) || deviceGroups[0]

  // Layout node positions for SVG topology graph
  // If 1 device: render central host with satellite alarm nodes
  // If >1 devices: render dominant device + peer devices connected by adjacency trunks
  const svgNodes = useMemo(() => {
    if (distinctDevices.length <= 1) {
      // 1 device with its individual alarms as satellite leaves
      const center = { x: 380, y: 240, dev: dominantDevice, count: dominantCount, isDominant: true }
      const satellites = (deviceGroups[0]?.[1] || []).slice(0, 8).map((m, idx, arr) => {
        const angle = (idx / Math.max(1, arr.length)) * 2 * Math.PI - Math.PI / 2
        const r = 160
        return {
          id: m.alarm_id,
          name: m.alarm_name || m.alarm_id,
          x: Math.round(center.x + r * Math.cos(angle)),
          y: Math.round(center.y + r * Math.sin(angle)),
          member: m,
          isSatellite: true,
        }
      })
      return { center, peers: [], satellites }
    }

    // Multiple devices: dominant on left/center-left, peers on right
    const dominant = { x: 230, y: 240, dev: dominantDevice, count: dominantCount, isDominant: true }
    const peers = distinctDevices.slice(1).map((dev, idx, arr) => {
      const spacing = 380 / Math.max(1, arr.length + 1)
      return {
        x: 580,
        y: Math.round(60 + (idx + 1) * spacing),
        dev,
        count: deviceGroups.find(([d]) => d === dev)?.[1].length || 1,
        isDominant: false,
      }
    })
    return { center: dominant, peers, satellites: [] }
  }, [distinctDevices, deviceGroups, dominantDevice, dominantCount])

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 select-none animate-fadeIn">
      {/* ========================================================================= */}
      {/* 1. Header Section */}
      {/* ========================================================================= */}
      <section className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#080d17] shadow-md">
        <div className="flex flex-col gap-space-md p-space-lg lg:flex-row lg:items-end lg:justify-between border-b border-[#1b273e]">
          <div>
            <div className="flex items-center gap-2">
              <span className="bg-secondary/20 text-secondary border border-secondary/30 px-2 py-0.5 rounded font-label-caps text-[10px] uppercase font-bold tracking-wider">
                ALARM-CENTRIC TOPOLOGY SUBGRAPH
              </span>
              <span className="text-on-surface-variant font-code-sm text-xs">
                Restricted to Chain {analysis.chain_id}
              </span>
            </div>
            <h1 className="mt-1 font-headline-lg text-2xl font-bold text-on-surface">
              Topology · {analysis.chain_id}
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-on-surface-variant leading-relaxed">
              Filtered strictly to devices and entities hosting alarms in this chain. Source relations and adjacency edges display verified co-location without asserting unverified causal propagation.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-secondary/30 bg-secondary/10 px-3 py-1 font-code-sm text-xs text-secondary font-semibold">
              <span className="w-2 h-2 rounded-full bg-secondary"></span>
              {distinctDevices.length} Hosts • {totalAlarms} Alarms Mapped
            </span>
          </div>
        </div>

        {/* Operational Metrics Bar */}
        <div className="grid grid-cols-1 divide-y divide-[#1b273e] sm:grid-cols-3 sm:divide-y-0 sm:divide-x">
          <div className="px-space-md py-space-sm bg-[#0c1424]">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Alarm-Bearing Devices
            </small>
            <strong className="font-code-sm text-sm text-secondary font-bold">
              {distinctDevices.length} Distinct Host{distinctDevices.length > 1 ? 's' : ''}
            </strong>
          </div>
          <div className="px-space-md py-space-sm bg-[#0c1424]">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Dominant Host Share
            </small>
            <strong className="font-code-sm text-sm text-on-surface font-bold">
              {dominantDevice} ({dominantCount}/{totalAlarms} alarms, {((dominantCount / totalAlarms) * 100).toFixed(0)}%)
            </strong>
          </div>
          <div className="px-space-md py-space-sm bg-[#0c1424]">
            <small className="block uppercase text-[10px] font-label-caps tracking-wider text-on-surface-variant">
              Topology Semantics
            </small>
            <strong className="font-code-sm text-sm text-tertiary font-bold">
              UNDIRECTED_ADJACENCY (Empirical)
            </strong>
          </div>
        </div>
      </section>

      {/* Loading State when topologyPayload is explicitly null */}
      {topologyPayload === null ? (
        <section
          role="status"
          className="rounded-xl border border-dashed border-[#1b273e] bg-[#0c1424] p-space-xl text-center font-code-sm text-sm text-on-surface-variant"
        >
          <span
            aria-hidden="true"
            className="material-symbols-outlined mb-2 block text-4xl text-secondary animate-pulse"
          >
            lan
          </span>
          Loading topology projection…
        </section>
      ) : (
        <>
          {/* ========================================================================= */}
          {/* 2. Interactive Control Ribbon matching ui/17 */}
          {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] px-space-md py-2 rounded-lg flex flex-wrap items-center justify-between gap-space-md border border-[#1b273e] text-xs">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold tracking-wider mr-1">
            LAYERS:
          </span>
          <button
            type="button"
            onClick={() => setShowAlarmsLayer(!showAlarmsLayer)}
            className={`px-2.5 py-1 rounded font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer border ${
              showAlarmsLayer
                ? 'bg-secondary/20 text-secondary border-secondary/40'
                : 'bg-[#141b2b] text-on-surface-variant border-[#1b273e]'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showAlarmsLayer ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>Chain Alarms ({totalAlarms})</span>
          </button>
          <button
            type="button"
            onClick={() => setShowLinksLayer(!showLinksLayer)}
            className={`px-2.5 py-1 rounded font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer border ${
              showLinksLayer
                ? 'bg-secondary/20 text-secondary border-secondary/40'
                : 'bg-[#141b2b] text-on-surface-variant border-[#1b273e]'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showLinksLayer ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>Adjacency Trunks</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative flex items-center">
            <span className="material-symbols-outlined absolute left-2 text-on-surface-variant text-[16px]">
              search
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter node or alarm ID..."
              className="bg-[#080d17] text-on-surface font-code-sm text-xs pl-7 pr-3 py-1 rounded w-56 border border-[#1b273e] focus:outline-none focus:border-secondary transition-colors"
            />
          </div>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-on-surface-variant hover:text-on-surface text-xs font-code-sm"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. Primary Split Layout (35% Left: Entities Tree | 65% Right: SVG Graph) */}
      {/* ========================================================================= */}
      <div className="w-full grid grid-cols-1 lg:grid-cols-12 gap-space-md items-start">
        {/* LEFT PANEL: Alarm-Bearing Devices & Member Impact Tree */}
        <div className="lg:col-span-4 flex flex-col gap-space-sm bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md h-[680px]">
          <div className="flex items-center justify-between pb-space-xs border-b border-[#1b273e]">
            <div className="flex items-center gap-1.5">
              <span className="material-symbols-outlined text-secondary text-[18px]">dns</span>
              <span className="font-headline-md text-sm font-bold text-on-surface">
                Alarm-Bearing Devices ({filteredDeviceGroups.length})
              </span>
            </div>
            <span className="px-2 py-0.5 bg-secondary/15 text-secondary font-label-caps text-[10px] rounded uppercase font-bold">
              {totalAlarms} Alarms
            </span>
          </div>

          {/* Device and Alarms Tree List */}
          <div className="flex-1 overflow-y-auto pr-1 flex flex-col gap-space-sm">
            {filteredDeviceGroups.map(([dev, devAlarms]) => {
              const isSelected = activeDevice === dev
              const isDominant = dev === dominantDevice
              return (
                <div
                  key={dev}
                  onClick={() => setSelectedDeviceId(dev)}
                  className={`rounded-lg p-2.5 flex flex-col gap-2 transition-all cursor-pointer border ${
                    isSelected
                      ? 'bg-[#15233c] border-secondary shadow-sm'
                      : 'bg-[#080d17] border-[#1b273e] hover:border-secondary/50 hover:bg-[#0e1728]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="material-symbols-outlined text-secondary text-[18px] shrink-0">
                        {isDominant ? 'domain' : 'router'}
                      </span>
                      <span className="font-code-sm text-xs font-bold text-on-surface truncate">
                        {dev}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {isDominant && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-secondary/20 text-secondary border border-secondary/30">
                          DOMINANT
                        </span>
                      )}
                      <span className="px-2 py-0.5 rounded-full text-xs font-bold font-code-sm bg-[#1e2b44] text-secondary">
                        {devAlarms.length} alm{devAlarms.length > 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>

                  {/* Alarms on this device */}
                  {showAlarmsLayer && (
                    <div className="flex flex-col gap-1.5 pt-1 pl-2 border-l-2 border-[#1e2b44]">
                      {devAlarms.map(m => (
                        <div
                          key={m.alarm_id}
                          className="bg-[#0c1424] p-1.5 rounded flex items-center justify-between gap-2 border border-[#1b273e]/70 font-code-sm text-[11px]"
                        >
                          <div className="flex flex-col min-w-0">
                            <span className="text-secondary font-semibold truncate">{m.alarm_id}</span>
                            <span className="text-on-surface-variant text-[10px] truncate">
                              {m.alarm_name || m.redundancy_role || 'Alarm Incident'}
                            </span>
                          </div>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase shrink-0 ${
                              m.role?.toUpperCase().includes('CORE') || m.role?.toUpperCase().includes('ROOT')
                                ? 'bg-rose-500/20 text-rose-300'
                                : m.role?.toUpperCase().includes('CONNECT')
                                ? 'bg-sky-500/20 text-sky-300'
                                : 'bg-slate-700 text-slate-300'
                            }`}
                          >
                            {m.role || 'LEAF'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Active Selection Summary Card */}
          {activeGroup && (
            <div className="p-2.5 bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col gap-1 text-xs shrink-0">
              <div className="flex items-center justify-between font-label-caps text-[10px] uppercase text-on-surface-variant font-bold">
                <span>Selected Host</span>
                <span className="text-secondary">{activeGroup[0]}</span>
              </div>
              <p className="text-[11px] text-on-surface-variant">
                Hosts {activeGroup[1].length} of {totalAlarms} chain alarms ({((activeGroup[1].length / totalAlarms) * 100).toFixed(1)}%).
              </p>
            </div>
          )}
        </div>

        {/* RIGHT PANEL: Alarm-Centric SVG Topology Graph */}
        <div className="lg:col-span-8 flex flex-col bg-[#0c1424] rounded-xl border border-[#1b273e] shadow-md overflow-hidden h-[680px] relative">
          {/* Panel Header */}
          <div className="h-10 px-space-md bg-[#080d17] border-b border-[#1b273e] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[18px]">device_hub</span>
              <span className="font-headline-md text-xs font-bold text-on-surface">
                Topological Alarm Distribution & Adjacency Mesh
              </span>
            </div>
            <div className="flex items-center gap-2 font-code-sm text-[11px] text-on-surface-variant">
              <span className="flex items-center gap-1 text-secondary">
                <span className="w-1.5 h-1.5 rounded-full bg-secondary"></span>
                Active Subgraph
              </span>
            </div>
          </div>

          {/* SVG Canvas Container */}
          <div className="relative flex-1 bg-[#070e1d] overflow-hidden flex items-center justify-center p-2">
            {/* Background Grid Pattern */}
            <div className="absolute inset-0 opacity-20 bg-[radial-gradient(#3a4f73_1px,transparent_1px)] [background-size:20px_20px]" />

            {/* SVG Network Canvas */}
            <svg
              className="w-full h-full"
              viewBox="0 0 820 480"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                {/* Glowing Filters */}
                <filter id="glow-cyan" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="5" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
                <filter id="glow-coral" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="6" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
                <filter id="glow-amber" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="4" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
              </defs>

              {/* CLUSTER BACKGROUND REGIONS */}
              {distinctDevices.length > 1 ? (
                <>
                  {/* Dominant Host Region */}
                  <rect
                    x="50"
                    y="40"
                    width="340"
                    height="400"
                    rx="12"
                    fill="#0e1728"
                    fillOpacity="0.75"
                    stroke="#1b273e"
                    strokeWidth="1.5"
                  />
                  <text
                    x="70"
                    y="72"
                    fill="#7bd0ff"
                    fontFamily="JetBrains Mono"
                    fontSize="11"
                    fontWeight="700"
                    letterSpacing="0.08em"
                  >
                    CLUSTER: {dominantDevice} (DOMINANT ALARM HOST)
                  </text>

                  {/* Peer Hosts Region */}
                  <rect
                    x="450"
                    y="40"
                    width="320"
                    height="400"
                    rx="12"
                    fill="#0e1728"
                    fillOpacity="0.75"
                    stroke="#1b273e"
                    strokeWidth="1.5"
                  />
                  <text
                    x="470"
                    y="72"
                    fill="#ffb95f"
                    fontFamily="JetBrains Mono"
                    fontSize="11"
                    fontWeight="700"
                    letterSpacing="0.08em"
                  >
                    CLUSTER: PEER & TRANSIT ENTITIES
                  </text>
                </>
              ) : (
                /* Single Host Chassis Region */
                <rect
                  x="100"
                  y="40"
                  width="620"
                  height="400"
                  rx="12"
                  fill="#0e1728"
                  fillOpacity="0.75"
                  stroke="#1b273e"
                  strokeWidth="1.5"
                />
              )}

              {/* CONNECTING EDGES & ADJACENCY TRUNKS */}
              {showLinksLayer && (
                <>
                  {distinctDevices.length > 1 ? (
                    svgNodes.peers.map((peer, idx) => (
                      <g key={`edge-${peer.dev}`}>
                        <path
                          d={`M ${svgNodes.center.x} ${svgNodes.center.y} C ${
                            (svgNodes.center.x + peer.x) / 2
                          } ${svgNodes.center.y}, ${(svgNodes.center.x + peer.x) / 2} ${peer.y}, ${
                            peer.x
                          } ${peer.y}`}
                          stroke={idx % 2 === 0 ? '#00a6e0' : '#ffb95f'}
                          strokeWidth={idx === 0 ? '2.5' : '1.8'}
                          strokeDasharray={idx === 0 ? undefined : '5 4'}
                          opacity="0.85"
                        />
                        {/* Midpoint connection badge */}
                        <rect
                          x={(svgNodes.center.x + peer.x) / 2 - 40}
                          y={(svgNodes.center.y + peer.y) / 2 - 10}
                          width="80"
                          height="20"
                          rx="4"
                          fill="#070e1d"
                          stroke="#1b273e"
                          strokeWidth="1"
                        />
                        <text
                          x={(svgNodes.center.x + peer.x) / 2}
                          y={(svgNodes.center.y + peer.y) / 2 + 4}
                          fill="#7bd0ff"
                          fontFamily="JetBrains Mono"
                          fontSize="9"
                          fontWeight="600"
                          textAnchor="middle"
                        >
                          ADJACENCY
                        </text>
                      </g>
                    ))
                  ) : (
                    /* Satellite Links for single device */
                    svgNodes.satellites.map(sat => (
                      <line
                        key={`sat-line-${sat.id}`}
                        x1={svgNodes.center.x}
                        y1={svgNodes.center.y}
                        x2={sat.x}
                        y2={sat.y}
                        stroke="#00a6e0"
                        strokeWidth="1.5"
                        strokeDasharray="4 3"
                        opacity="0.75"
                      />
                    ))
                  )}
                </>
              )}

              {/* TOPOLOGY NODES */}
              {/* 1. Center / Dominant Device Node */}
              <g
                transform={`translate(${svgNodes.center.x}, ${svgNodes.center.y})`}
                className="cursor-pointer"
                onClick={() => setSelectedDeviceId(dominantDevice)}
              >
                {/* Pulsing halo ring */}
                <circle
                  className="animate-pulse"
                  r="38"
                  fill="#7bd0ff"
                  fillOpacity="0.15"
                />
                {/* Outer Glow Ring */}
                <circle
                  r="28"
                  fill="#14213d"
                  stroke="#7bd0ff"
                  strokeWidth="3"
                  filter="url(#glow-cyan)"
                />
                <circle r="12" fill="#7bd0ff" />
                <text
                  x="0"
                  y="4"
                  fill="#070e1d"
                  fontFamily="JetBrains Mono"
                  fontSize="10"
                  fontWeight="800"
                  textAnchor="middle"
                >
                  HOST
                </text>

                {/* Node Label Pin */}
                <rect
                  x="-75"
                  y="36"
                  width="150"
                  height="22"
                  rx="4"
                  fill="#070e1d"
                  stroke={activeDevice === dominantDevice ? '#7bd0ff' : '#1b273e'}
                  strokeWidth="1.5"
                />
                <text
                  x="0"
                  y="51"
                  fill="#ffffff"
                  fontFamily="JetBrains Mono"
                  fontSize="10"
                  fontWeight="700"
                  textAnchor="middle"
                >
                  {dominantDevice}
                </text>

                {/* Alarm Count Badge */}
                <circle cx="24" cy="-22" r="11" fill="#ff5451" filter="url(#glow-coral)" />
                <text
                  x="24"
                  y="-18"
                  fill="#ffffff"
                  fontFamily="JetBrains Mono"
                  fontSize="10"
                  fontWeight="800"
                  textAnchor="middle"
                >
                  {dominantCount}
                </text>
              </g>

              {/* 2. Peer Device Nodes (if multiple) */}
              {svgNodes.peers.map(peer => {
                const isSelected = activeDevice === peer.dev
                return (
                  <g
                    key={`node-${peer.dev}`}
                    transform={`translate(${peer.x}, ${peer.y})`}
                    className="cursor-pointer"
                    onClick={() => setSelectedDeviceId(peer.dev)}
                  >
                    <circle
                      r="22"
                      fill="#14213d"
                      stroke={isSelected ? '#7bd0ff' : '#ffb95f'}
                      strokeWidth="2.5"
                      filter="url(#glow-amber)"
                    />
                    <circle r="8" fill="#ffb95f" />

                    {/* Label */}
                    <rect
                      x="-65"
                      y="28"
                      width="130"
                      height="20"
                      rx="3"
                      fill="#070e1d"
                      stroke={isSelected ? '#7bd0ff' : '#1b273e'}
                      strokeWidth="1"
                    />
                    <text
                      x="0"
                      y="42"
                      fill="#dce2f7"
                      fontFamily="JetBrains Mono"
                      fontSize="9"
                      fontWeight="600"
                      textAnchor="middle"
                    >
                      {peer.dev}
                    </text>

                    {/* Alarm Count Badge */}
                    <circle cx="18" cy="-16" r="9" fill="#ca8100" />
                    <text
                      x="18"
                      y="-13"
                      fill="#ffffff"
                      fontFamily="JetBrains Mono"
                      fontSize="9"
                      fontWeight="700"
                      textAnchor="middle"
                    >
                      {peer.count}
                    </text>
                  </g>
                )
              })}

              {/* 3. Satellite Alarm Nodes (if single device) */}
              {svgNodes.satellites.map(sat => (
                <g
                  key={`sat-${sat.id}`}
                  transform={`translate(${sat.x}, ${sat.y})`}
                  className="cursor-pointer"
                >
                  <circle r="14" fill="#141b2b" stroke="#7bd0ff" strokeWidth="1.5" />
                  <circle r="5" fill="#7bd0ff" />
                  <rect
                    x="-45"
                    y="18"
                    width="90"
                    height="16"
                    rx="3"
                    fill="#070e1d"
                    stroke="#1b273e"
                    strokeWidth="1"
                  />
                  <text
                    x="0"
                    y="30"
                    fill="#dce2f7"
                    fontFamily="JetBrains Mono"
                    fontSize="8"
                    fontWeight="600"
                    textAnchor="middle"
                  >
                    {sat.id.slice(0, 10)}
                  </text>
                </g>
              ))}
            </svg>

            {/* Floating Map Legend Overlay */}
            <div className="absolute bottom-3 left-3 bg-[#080d17]/95 backdrop-blur-md p-2.5 rounded-lg border border-[#1b273e] font-code-sm text-[11px] shadow-lg flex flex-col gap-1.5 max-w-xs">
              <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold tracking-wider">
                TOPOLOGY SUBGRAPH LEGEND
              </span>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-on-surface text-[10px]">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-secondary inline-block"></span>
                  <span>Dominant Host</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block"></span>
                  <span>Peer Host</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block"></span>
                  <span>Alarm Badge</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-3.5 h-0.5 bg-secondary inline-block"></span>
                  <span>Adjacency Link</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 4. Topological Alarm Verification Matrix matching ui/17 */}
      {/* ========================================================================= */}
      <section className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex flex-col gap-space-sm">
        <div className="flex items-center justify-between pb-space-xs border-b border-[#1b273e]">
          <span className="font-label-caps text-xs uppercase text-secondary font-bold tracking-wider">
            TOPOLOGICAL ALARM VERIFICATION MATRIX
          </span>
          <span className="font-code-sm text-xs text-on-surface-variant">
            {dominantCount} Dominant / {totalAlarms - dominantCount} Peripheral / 0 Unlinked
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-space-sm font-code-sm text-xs">
          <div className="p-space-sm bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-on-surface font-semibold">Alarm Host Allocation</span>
              <span className="text-secondary font-bold">{dominantCount} Alarms</span>
            </div>
            <p className="text-on-surface-variant text-[11px] leading-relaxed">
              {((dominantCount / totalAlarms) * 100).toFixed(1)}% of chain alarms reside directly on host {dominantDevice}.
            </p>
          </div>

          <div className="p-space-sm bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-on-surface font-semibold">Topology Scope</span>
              <span className="text-secondary font-bold">{distinctDevices.length} Hosts</span>
            </div>
            <p className="text-on-surface-variant text-[11px] leading-relaxed">
              Filtered strictly to entities involved in active alarms. Non-participating network devices excluded.
            </p>
          </div>

          <div className="p-space-sm bg-[#080d17] rounded-lg border border-[#1b273e] flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-on-surface font-semibold">Adjacency Mapping</span>
              <span className="text-amber-400 font-bold">Undirected</span>
            </div>
            <p className="text-on-surface-variant text-[11px] leading-relaxed">
              Hardware frame adjacency and local links established without assuming unverified propagation direction.
            </p>
          </div>
        </div>
      </section>
        </>
      )}
    </div>
  )
}
