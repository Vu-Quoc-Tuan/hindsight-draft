import { useState } from 'react'
import type { ChainAnalysis } from '../types'
import type { MutationSpec } from '../components/OperatorValidationModal'

interface AuditStructureViewProps {
  analysis: ChainAnalysis
  onSelectCutCandidate?: (candidateId: string) => void
  onOpenValidationModal?: (spec?: MutationSpec) => void
}

type AuditTab = 'GRAPH' | 'CUTS' | 'ATTRIBUTION'

interface NodeSpectralDetail {
  id: string
  name: string
  type: string
  badge: string
  desc: string
  degree: number
  degradation: string
}

const NODE_DETAILS: Record<string, NodeSpectralDetail> = {
  'ALM-99210014': {
    id: 'ALM-99210014',
    name: 'ALM-99210014',
    type: 'Interface Drop',
    badge: 'WEAK SPUR',
    desc: 'Conductance leakage across bipartite split. Spectral cut score > 94.2% confidence for branch detachment.',
    degree: 3,
    degradation: '91.4%',
  },
  'ALM-99210088': {
    id: 'ALM-99210088',
    name: 'ALM-99210088',
    type: 'Leaf Alert',
    badge: 'ISOLATED LEAK',
    desc: 'Spillover alarm detected in downstream access leaf. Weak conductance coupling with core ring.',
    degree: 2,
    degradation: '86.7%',
  },
  'ALM-99210019': {
    id: 'ALM-99210019',
    name: 'ALM-99210019',
    type: 'BGP Flap Transient',
    badge: 'ANOMALY LEAF',
    desc: 'Peripheral session reset caused by cut boundary decoupling across L2 boundary.',
    degree: 2,
    degradation: '72.0%',
  },
  'ALM-99210102': {
    id: 'ALM-99210102',
    name: 'ALM-99210102',
    type: 'Edge Transit Loss',
    badge: 'ISOLATED LEAK',
    desc: 'Marginal alarm on downstream access tail with negligible modularity impact on core root.',
    degree: 1,
    degradation: '68.5%',
  },
  'DEHT01-PE03': {
    id: 'DEHT01-PE03',
    name: 'DEHT01-PE03',
    type: 'Transit Cut Anchor',
    badge: 'BRIDGE ROUTER',
    desc: 'Cut anchor node connecting transit aggregation with anomalous leaf zone via trunk E16/0/2.',
    degree: 4,
    degradation: '45.1%',
  },
  'DEHT01-AR01': {
    id: 'DEHT01-AR01',
    name: 'DEHT01-AR01',
    type: 'Aggregation 1',
    badge: 'BRIDGE ROUTER',
    desc: 'Inter-chassis bridge router receiving trunk E16/0/2 with normalized weight 0.87.',
    degree: 3,
    degradation: '32.4%',
  },
  'DEHT01-AR02': {
    id: 'DEHT01-AR02',
    name: 'DEHT01-AR02',
    type: 'Aggregation 2',
    badge: 'BRIDGE ROUTER',
    desc: 'Secondary aggregation node routing inter-chassis traffic towards access ring.',
    degree: 3,
    degradation: '34.1%',
  },
  'DEHT02-SW01': {
    id: 'DEHT02-SW01',
    name: 'DEHT02-SW01',
    type: 'Access Switch',
    badge: 'BRIDGE ROUTER',
    desc: 'Downstream access switch under secondary aggregation ring.',
    degree: 2,
    degradation: '28.0%',
  },
  'DEHL01-CR01': {
    id: 'DEHL01-CR01',
    name: 'DEHL01-CR01',
    type: 'Core Root Switch',
    badge: 'CORE ROOT',
    desc: 'Primary root of failure chain. High conductance core cluster with 42 strongly connected alarms.',
    degree: 6,
    degradation: '99.8%',
  },
  'DEHL01-CR02': {
    id: 'DEHL01-CR02',
    name: 'DEHL01-CR02',
    type: 'BGP Peer Router',
    badge: 'CORE CLUSTER',
    desc: 'BGP peering node in core domain with high conductance weight (w=0.98). Part of primary failure propagation.',
    degree: 4,
    degradation: '92.1%',
  },
  'DEHL02-CR01': {
    id: 'DEHL02-CR01',
    name: 'DEHL02-CR01',
    type: 'Ingress Gateway',
    badge: 'CORE CLUSTER',
    desc: 'Gateway routing core traffic into inter-chassis transit trunk E16/0/2.',
    degree: 5,
    degradation: '88.3%',
  },
  'DEHL02-CR02': {
    id: 'DEHL02-CR02',
    name: 'DEHL02-CR02',
    type: 'Core Ingress',
    badge: 'CORE CLUSTER',
    desc: 'Redundant ingress core router maintaining metro optical loop integrity.',
    degree: 3,
    degradation: '74.5%',
  },
  'DEHL01-DWDM': {
    id: 'DEHL01-DWDM',
    name: 'DEHL01-DWDM',
    type: 'Optical Transport Unit',
    badge: 'CORE CLUSTER',
    desc: 'L1 optical DWDM muxponder experiencing fiber link degradation.',
    degree: 2,
    degradation: '95.0%',
  },
}

export function AuditStructureView({
  analysis: _analysis,
  onOpenValidationModal,
}: AuditStructureViewProps) {
  const [activeTab, setActiveTab] = useState<AuditTab>('GRAPH')
  const [zoomLevel, setZoomLevel] = useState(100)
  const [showLabels, setShowLabels] = useState(true)
  const [showWeakEdges, setShowWeakEdges] = useState(true)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedCutIndex, setSelectedCutIndex] = useState(0)
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  const candidateCuts = [
    {
      id: 'CUT-01',
      plane: 'DEHL01-CR01 ↔ DEHT01-AR02',
      conductance: 0.038,
      subchainA: 'DEHL01 Core Cluster (42 alms)',
      subchainB: 'DEHT01 Access Tail (16 alms)',
      modularityGain: '+0.142',
      status: 'RECOMMENDED (MIN-CUT)',
    },
    {
      id: 'CUT-02',
      plane: 'DEHL01-SR02 ↔ HNI-PE03',
      conductance: 0.115,
      subchainA: 'DEHL01 Backbone (50 alms)',
      subchainB: 'HNI Edge Transit (8 alms)',
      modularityGain: '+0.088',
      status: 'SECONDARY ALTERNATIVE',
    },
    {
      id: 'CUT-03',
      plane: 'VLAN 4001 Gateway Fission',
      conductance: 0.245,
      subchainA: 'L3 Core Routing (54 alms)',
      subchainB: 'L2 Access Leaf (4 alms)',
      modularityGain: '+0.031',
      status: 'MARGINAL (LOW BENEFIT)',
    },
  ]

  const activeCut = candidateCuts[selectedCutIndex]
  const focusedNode = selectedNodeId ? (NODE_DETAILS[selectedNodeId] ?? null) : null

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Subheader & Context Controls */}
      {/* Sub-navigation Tabs Bar */}
      <div className="w-full bg-surface-container-lowest px-space-md py-space-xs rounded-lg shadow-sm flex items-center justify-between gap-space-md">
        {/* Mode Selector Tab Switcher */}
        <div className="flex items-center bg-surface-container-low p-1 rounded-lg gap-1">
          <button
            onClick={() => setActiveTab('GRAPH')}
            className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              activeTab === 'GRAPH'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">schema</span>
            <span>G*_audit Graph</span>
          </button>
          <button
            onClick={() => setActiveTab('CUTS')}
            className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              activeTab === 'CUTS'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">content_cut</span>
            <span>Candidate Cuts ({candidateCuts.length})</span>
          </button>
          <button
            onClick={() => setActiveTab('ATTRIBUTION')}
            className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              activeTab === 'ATTRIBUTION'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">account_tree</span>
            <span>Attribution Curves</span>
          </button>
        </div>

        {activeTab !== 'CUTS' ? (
          <button
            onClick={() => setActiveTab('CUTS')}
            className="px-3 py-1.5 bg-secondary-container/30 hover:bg-secondary-container/50 text-secondary border border-secondary/40 font-code-sm text-xs font-semibold rounded-md flex items-center gap-1.5 shadow-xs transition-colors cursor-pointer"
            title="Chuyển sang xem 3 phương án cắt chuỗi sự cố (Candidate Cuts)"
          >
            <span className="material-symbols-outlined text-[15px]">tune</span>
            <span>Inspect Candidate Cuts (3 Options)</span>
          </button>
        ) : (
          <span className="px-2.5 py-1 bg-surface-container text-on-surface-variant font-code-sm text-xs rounded border border-surface-container-highest">
            Candidate Cuts Active
          </span>
        )}
      </div>

      {/* ========================================================================= */}
      {/* SCREEN 11: G*_audit GRAPH INSPECTION (Matches Rich Topology & Spectral Cut) */}
      {/* ========================================================================= */}
      {activeTab === 'GRAPH' && (
        <div className="flex flex-col gap-space-md">
          {/* Viewport Toolbar with Controls and Legend matching Image 2 */}
          <div className="w-full bg-[#0d1527] border border-slate-800/80 px-space-md py-space-xs rounded-lg flex flex-wrap items-center justify-between gap-space-sm shadow-md">
            {/* Left: Zoom & View Options */}
            <div className="flex items-center gap-space-sm flex-wrap">
              {/* Zoom controls: + 100% - restart fit */}
              <div className="flex items-center bg-slate-900 border border-slate-800 rounded p-0.5">
                <button
                  onClick={() => setZoomLevel(prev => Math.min(180, prev + 15))}
                  className="w-6 h-6 flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors cursor-pointer"
                  title="Zoom In"
                >
                  <span className="material-symbols-outlined text-[15px]">add</span>
                </button>
                <span className="font-code-sm text-xs text-slate-200 px-1 font-semibold w-11 text-center select-none">
                  {zoomLevel}%
                </span>
                <button
                  onClick={() => setZoomLevel(prev => Math.max(50, prev - 15))}
                  className="w-6 h-6 flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors cursor-pointer"
                  title="Zoom Out"
                >
                  <span className="material-symbols-outlined text-[15px]">remove</span>
                </button>
                <button
                  onClick={() => setZoomLevel(100)}
                  className="w-6 h-6 flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors ml-0.5 cursor-pointer"
                  title="Reset Zoom"
                >
                  <span className="material-symbols-outlined text-[14px]">restart_alt</span>
                </button>
                <button
                  onClick={() => setZoomLevel(100)}
                  className="w-6 h-6 flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors cursor-pointer"
                  title="Fit to Screen"
                >
                  <span className="material-symbols-outlined text-[14px]">fit_screen</span>
                </button>
              </div>

              <div className="h-4 w-px bg-slate-800" />

              {/* Checkboxes: Node Labels, Weak Edges (<0.2), Conductance Heatmap */}
              <label className="flex items-center gap-1.5 px-2 py-1 bg-slate-900/80 hover:bg-slate-800/80 rounded cursor-pointer transition-colors border border-slate-800/50">
                <input
                  type="checkbox"
                  checked={showLabels}
                  onChange={e => setShowLabels(e.target.checked)}
                  className="accent-cyan-400 w-3.5 h-3.5 cursor-pointer"
                />
                <span className="font-code-sm text-xs text-slate-300">Node Labels</span>
              </label>

              <label className="flex items-center gap-1.5 px-2 py-1 bg-slate-900/80 hover:bg-slate-800/80 rounded cursor-pointer transition-colors border border-slate-800/50">
                <input
                  type="checkbox"
                  checked={showWeakEdges}
                  onChange={e => setShowWeakEdges(e.target.checked)}
                  className="accent-amber-400 w-3.5 h-3.5 cursor-pointer"
                />
                <span className="font-code-sm text-xs text-slate-300">Weak Edges (&lt;0.2)</span>
              </label>

              <label className="flex items-center gap-1.5 px-2 py-1 bg-slate-900/80 hover:bg-slate-800/80 rounded cursor-pointer transition-colors border border-slate-800/50">
                <input
                  type="checkbox"
                  checked={showHeatmap}
                  onChange={e => setShowHeatmap(e.target.checked)}
                  className="accent-cyan-400 w-3.5 h-3.5 cursor-pointer"
                />
                <span className="font-code-sm text-xs text-slate-300">Conductance Heatmap</span>
              </label>
            </div>

            {/* Right: Legend Items matching Image 2 */}
            <div className="flex items-center gap-3 text-xs font-code-sm text-slate-400 flex-wrap">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block"></span>
                <span className="text-slate-300">Core Cluster</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rotate-45 bg-pink-400 inline-block"></span>
                <span className="text-slate-300">Bridge Router</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full border border-amber-400 bg-amber-500/40 inline-block"></span>
                <span className="text-slate-300">Isolated Leak (Weak)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3.5 h-0.5 bg-cyan-400 inline-block"></span>
                <span className="text-slate-300">Physical L2/L3</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3.5 h-0.5 border-b border-dotted border-slate-300 inline-block"></span>
                <span className="text-slate-300">Temporal Sync</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3.5 h-0.5 bg-slate-400 inline-block"></span>
                <span className="text-slate-300">Multi-Chassis</span>
              </span>
            </div>
          </div>

          {/* SVG Graph Viewport Canvas */}
          <div className="w-full bg-[#070c17] border border-slate-800 rounded-lg p-space-md flex flex-col items-center justify-center overflow-hidden shadow-2xl min-h-[580px] relative">
            {/* Overlay Graph Header (Top of Canvas) matching Image 2 */}
            <div className="absolute top-4 left-4 right-4 z-10 flex items-start justify-between pointer-events-none">
              <div className="flex items-center gap-2 pointer-events-auto">
                <div className="w-7 h-7 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                  <span className="material-symbols-outlined text-[16px]">hub</span>
                </div>
                <div className="flex flex-col">
                  <span className="font-code-sm text-sm font-bold text-slate-100 tracking-tight">
                    G*_audit Structural Representation
                  </span>
                  <span className="font-code-sm text-[11px] text-slate-400">
                    Target Root: <strong className="text-cyan-400 font-semibold">DEHL01-CR01</strong> | Cross-Cut Candidate: <strong className="text-amber-400 font-semibold">{activeCut.id}</strong>
                    <span className="text-slate-500 ml-2 hidden sm:inline">• Click any node to inspect anomaly</span>
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 font-code-sm text-xs bg-slate-900/90 border border-slate-800 px-3 py-1.5 rounded-lg shadow-lg pointer-events-auto">
                <span className="text-slate-400">Fiedler Cut Vector:</span>
                <span className="text-cyan-300 font-bold">λ₂ = 0.0423</span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-400">Conductance:</span>
                <span className="text-amber-400 font-bold">Φ = 0.038</span>
              </div>
            </div>

            {/* The Interactive SVG Graph */}
            <svg
              className="w-full h-[520px] transition-transform duration-200 select-none"
              style={{ transform: `scale(${zoomLevel / 100})` }}
              viewBox="0 0 960 500"
            >
              <defs>
                {/* Grid Pattern */}
                <pattern id="audit-grid" width="24" height="24" patternUnits="userSpaceOnUse">
                  <circle cx="2" cy="2" r="1" fill="rgba(148, 163, 184, 0.07)" />
                </pattern>

                {/* Markers for directed arrows */}
                <marker id="arrow-cyan" viewBox="0 0 10 10" refX="16" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />
                </marker>
                <marker id="arrow-pink" viewBox="0 0 10 10" refX="16" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#f472b6" />
                </marker>
                <marker id="arrow-gold" viewBox="0 0 10 10" refX="16" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#ca8a04" />
                </marker>

                {/* Subtle glow filter */}
                <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
              </defs>

              {/* Background Grid */}
              <rect
                width="960"
                height="500"
                fill="url(#audit-grid)"
                onClick={() => setSelectedNodeId(null)}
                className="cursor-default"
              />

              {/* ============================================================= */}
              {/* CLUSTER 1: BACKBONE CORE DOMAIN (Shaded Polygon & Edges) */}
              {/* ============================================================= */}
              {showHeatmap && (
                <g className="transition-opacity duration-300">
                  <polygon
                    points="60,110 240,50 420,85 460,225 385,345 180,365 50,235"
                    fill="rgba(14, 165, 233, 0.06)"
                    stroke="rgba(56, 189, 248, 0.25)"
                    strokeWidth="1.5"
                    strokeDasharray="4 3"
                  />
                  <text
                    x="85"
                    y="75"
                    fill="#38bdf8"
                    opacity="0.5"
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="11"
                    fontWeight="700"
                    letterSpacing="0.04em"
                  >
                    Backbone Core Domain (~45819)
                  </text>
                </g>
              )}

              {/* Core Links with weights w: 0.98, 0.94, 0.89, 0.92 */}
              <g stroke="#0284c7" strokeWidth="2">
                <line x1="150" y1="205" x2="290" y2="130" markerEnd="url(#arrow-cyan)" />
                <line x1="290" y1="130" x2="380" y2="155" markerEnd="url(#arrow-cyan)" />
                <line x1="380" y1="155" x2="335" y2="305" markerEnd="url(#arrow-cyan)" />
                <line x1="335" y1="305" x2="185" y2="325" markerEnd="url(#arrow-cyan)" />
                <line x1="185" y1="325" x2="150" y2="205" strokeDasharray="3 2" strokeOpacity="0.6" />
              </g>

              {/* Edge Weight Badges within Core */}
              {showLabels && (
                <g fontFamily="JetBrains Mono, monospace" fontSize="9" fill="#7dd3fc" fontWeight="600">
                  <text x="205" y="150">w: 0.98</text>
                  <text x="330" y="130">w: 0.94</text>
                  <text x="365" y="240">w: 0.89</text>
                  <text x="250" y="325">w: 0.92</text>
                </g>
              )}

              {/* ============================================================= */}
              {/* CLUSTER 2: INTER-CHASSIS TRANSIT (Bridge Routers & Aggregation) */}
              {/* ============================================================= */}
              {showHeatmap && (
                <g className="transition-opacity duration-300">
                  <polygon
                    points="425,140 540,160 620,235 580,385 480,440 425,345"
                    fill="rgba(244, 114, 182, 0.05)"
                    stroke="rgba(244, 114, 182, 0.25)"
                    strokeWidth="1.5"
                    strokeDasharray="4 3"
                  />
                  <text
                    x="440"
                    y="155"
                    fill="#f472b6"
                    opacity="0.5"
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="11"
                    fontWeight="700"
                    letterSpacing="0.04em"
                  >
                    Inter-chassis Transit
                  </text>
                </g>
              )}

              {/* Inter-Cluster Trunk Edge (Core to Transit) */}
              <line x1="380" y1="155" x2="510" y2="235" stroke="#94a3b8" strokeWidth="2" />
              {showLabels && (
                <g transform="translate(440, 185)">
                  <rect x="-8" y="-12" width="124" height="16" rx="3" fill="#0f172a" stroke="#334155" strokeWidth="1" />
                  <text x="0" y="0" fill="#cbd5e1" fontFamily="JetBrains Mono, monospace" fontSize="9" fontWeight="700">
                    E16/0/2 [Trunk w: 0.87]
                  </text>
                </g>
              )}

              {/* Transit internal edges */}
              <line x1="510" y1="235" x2="510" y2="360" stroke="#f472b6" strokeWidth="2" markerEnd="url(#arrow-pink)" />
              <line x1="510" y1="235" x2="605" y2="275" stroke="#f472b6" strokeWidth="2" strokeOpacity="0.8" />
              <line x1="510" y1="360" x2="605" y2="275" stroke="#f472b6" strokeWidth="2" strokeOpacity="0.8" />
              <line x1="510" y1="360" x2="545" y2="440" stroke="#64748b" strokeWidth="1.5" strokeDasharray="3 3" />

              {/* ============================================================= */}
              {/* CHEEGER CUT BOUNDARY & SPILLOVER ZONE (Curved Boundary & Leak Edge) */}
              {/* ============================================================= */}
              {showHeatmap && (
                <rect
                  x="650"
                  y="65"
                  width="290"
                  height="405"
                  rx="16"
                  fill="rgba(35, 10, 15, 0.45)"
                  stroke="rgba(239, 68, 68, 0.25)"
                  strokeWidth="1"
                />
              )}

              {/* Cheeger Cut Dashed Curve Line */}
              <path
                d="M 635,65 Q 655,255 685,465"
                stroke="#ef4444"
                strokeWidth="2.5"
                strokeDasharray="6 4"
              />
              <text
                x="655"
                y="90"
                fill="#ef4444"
                fontFamily="JetBrains Mono, monospace"
                fontSize="10"
                fontWeight="800"
                letterSpacing="0.05em"
              >
                CHEEGER CUT BOUNDARY (MIN CUT Φ = 0.038)
              </text>

              {/* Weak Leak Edge Crossing Cut Boundary (PE03 -> ALM-99210014) */}
              <g className={`transition-opacity duration-300 ${showWeakEdges ? 'opacity-100' : 'opacity-20'}`}>
                <line
                  x1="605"
                  y1="275"
                  x2="740"
                  y2="295"
                  stroke="#f59e0b"
                  strokeWidth="2.5"
                  strokeDasharray="5 3"
                />
                {/* Yellow Callout Pill w=0.082 (LEAK) directly on the edge */}
                <g transform="translate(645, 264)">
                  <rect
                    width="96"
                    height="20"
                    rx="4"
                    fill="#eab308"
                    stroke="#ca8a04"
                    strokeWidth="1"
                  />
                  <text
                    x="48"
                    y="14"
                    fill="#000000"
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="10"
                    fontWeight="900"
                    textAnchor="middle"
                  >
                    w=0.082 (LEAK)
                  </text>
                </g>
              </g>

              {/* Anomalous Leaf Interconnects */}
              <g stroke="#ca8a04" strokeWidth="1.5" strokeDasharray="3 2" strokeOpacity="0.7">
                <line x1="715" y1="175" x2="825" y2="190" />
                <line x1="715" y1="175" x2="740" y2="295" />
                <line x1="740" y1="295" x2="795" y2="400" />
              </g>

              {/* Title of Anomalous Leaf Zone */}
              <text
                x="740"
                y="110"
                fill="#fb923c"
                opacity="0.65"
                fontFamily="JetBrains Mono, monospace"
                fontSize="11"
                fontWeight="700"
              >
                Anomalous Leaf / Spillover Zone
              </text>

              {/* ============================================================= */}
              {/* CORE DOMAIN NODES */}
              {/* ============================================================= */}

              {/* 1. DEHL01-CR01 (Incident Core Root) */}
              <g
                transform="translate(150, 205)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHL01-CR01' ? null : 'DEHL01-CR01')
                }}
              >
                <circle r={selectedNodeId === 'DEHL01-CR01' ? '30' : '26'} fill="rgba(14, 165, 233, 0.15)" stroke="#38bdf8" strokeWidth={selectedNodeId === 'DEHL01-CR01' ? 2 : 1} strokeDasharray="4 2" />
                <circle r="18" fill="#0f172a" stroke="#00f0ff" strokeWidth="2.5" filter="url(#glow-cyan)" />
                <circle r="7" fill="#00f0ff" className="animate-pulse" />
                {showLabels && (
                  <>
                    <text x="-40" y="38" fill="#e0f2fe" fontFamily="JetBrains Mono, monospace" fontSize="11" fontWeight="700">
                      DEHL01-CR01
                    </text>
                    <text x="-34" y="52" fill="#38bdf8" fontFamily="JetBrains Mono, monospace" fontSize="9" fontWeight="700">
                      CORE (ROOT)
                    </text>
                  </>
                )}
              </g>

              {/* 2. DEHL01-CR02 */}
              <g
                transform="translate(290, 130)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHL01-CR02' ? null : 'DEHL01-CR02')
                }}
              >
                {selectedNodeId === 'DEHL01-CR02' && (
                  <circle r="19" fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <circle r="13" fill="#0f172a" stroke="#38bdf8" strokeWidth="2" />
                <circle r="4" fill="#38bdf8" />
                {showLabels && (
                  <>
                    <text x="-35" y="-18" fill="#e0f2fe" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="600">
                      DEHL01-CR02
                    </text>
                    <text x="-32" y="-6" fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="8">
                      BGP PEER 02
                    </text>
                  </>
                )}
              </g>

              {/* 3. DEHL02-CR01 */}
              <g
                transform="translate(380, 155)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHL02-CR01' ? null : 'DEHL02-CR01')
                }}
              >
                {selectedNodeId === 'DEHL02-CR01' && (
                  <circle r="19" fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <circle r="13" fill="#0f172a" stroke="#38bdf8" strokeWidth="2" />
                <circle r="4" fill="#38bdf8" />
                {showLabels && (
                  <>
                    <text x="-32" y="-18" fill="#e0f2fe" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="600">
                      DEHL02-CR01
                    </text>
                    <text x="-30" y="-6" fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="8">
                      INGRESS GW
                    </text>
                  </>
                )}
              </g>

              {/* 4. DEHL02-CR02 */}
              <g
                transform="translate(335, 305)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHL02-CR02' ? null : 'DEHL02-CR02')
                }}
              >
                {selectedNodeId === 'DEHL02-CR02' && (
                  <circle r="18" fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <circle r="12" fill="#0f172a" stroke="#38bdf8" strokeWidth="2" />
                <circle r="4" fill="#38bdf8" />
                {showLabels && (
                  <text x="-35" y="26" fill="#e0f2fe" fontFamily="JetBrains Mono, monospace" fontSize="10">
                    DEHL02-CR02
                  </text>
                )}
              </g>

              {/* 5. DEHL01-DWDM */}
              <g
                transform="translate(185, 325)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHL01-DWDM' ? null : 'DEHL01-DWDM')
                }}
              >
                {selectedNodeId === 'DEHL01-DWDM' && (
                  <circle r="17" fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <circle r="11" fill="#0f172a" stroke="#38bdf8" strokeWidth="1.5" />
                <circle r="3" fill="#38bdf8" />
                {showLabels && (
                  <text x="-36" y="24" fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="9">
                    DEHL01-DWDM
                  </text>
                )}
              </g>

              {/* ============================================================= */}
              {/* TRANSIT DOMAIN NODES (Diamond Bridge Routers) */}
              {/* ============================================================= */}

              {/* DEHT01-AR01 */}
              <g
                transform="translate(510, 235)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHT01-AR01' ? null : 'DEHT01-AR01')
                }}
              >
                {selectedNodeId === 'DEHT01-AR01' && (
                  <polygon points="0,-18 18,0 0,18 -18,0" fill="none" stroke="#f472b6" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <polygon points="0,-12 12,0 0,12 -12,0" fill="#1e1b4b" stroke="#f472b6" strokeWidth="2" />
                <circle r="3" fill="#f43f5e" />
                {showLabels && (
                  <>
                    <text x="-35" y="-18" fill="#fbcfe8" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="600">
                      DEHT01-AR01
                    </text>
                    <text x="-32" y="-6" fill="#f472b6" fontFamily="JetBrains Mono, monospace" fontSize="8">
                      AGGREGATION 1
                    </text>
                  </>
                )}
              </g>

              {/* DEHT01-AR02 */}
              <g
                transform="translate(510, 360)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHT01-AR02' ? null : 'DEHT01-AR02')
                }}
              >
                {selectedNodeId === 'DEHT01-AR02' && (
                  <polygon points="0,-18 18,0 0,18 -18,0" fill="none" stroke="#f472b6" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <polygon points="0,-12 12,0 0,12 -12,0" fill="#1e1b4b" stroke="#f472b6" strokeWidth="2" />
                <circle r="3" fill="#f43f5e" />
                {showLabels && (
                  <>
                    <text x="-35" y="24" fill="#fbcfe8" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="600">
                      DEHT01-AR02
                    </text>
                    <text x="-32" y="36" fill="#f472b6" fontFamily="JetBrains Mono, monospace" fontSize="8">
                      AGGREGATION 2
                    </text>
                  </>
                )}
              </g>

              {/* DEHT01-PE03 (CUT ANCHOR DIAMOND) */}
              <g
                transform="translate(605, 275)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHT01-PE03' ? null : 'DEHT01-PE03')
                }}
              >
                <polygon points="0,-22 22,0 0,22 -22,0" fill="none" stroke="#fb7185" strokeWidth={selectedNodeId === 'DEHT01-PE03' ? 2 : 1} strokeDasharray="3 2" />
                <polygon points="0,-16 16,0 0,16 -16,0" fill="#450a0a" stroke="#fb7185" strokeWidth="2.5" />
                <circle r="4" fill="#fb7185" />
                {showLabels && (
                  <>
                    <text x="-35" y="30" fill="#fecdd3" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="700">
                      DEHT01-PE03
                    </text>
                    <text x="-30" y="42" fill="#fb7185" fontFamily="JetBrains Mono, monospace" fontSize="8" fontWeight="700">
                      CUT ANCHOR
                    </text>
                  </>
                )}
              </g>

              {/* DEHT02-SW01 */}
              <g
                transform="translate(545, 440)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'DEHT02-SW01' ? null : 'DEHT02-SW01')
                }}
              >
                {selectedNodeId === 'DEHT02-SW01' && (
                  <circle r="15" fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeDasharray="3 2" />
                )}
                <circle r="9" fill="#0f172a" stroke="#94a3b8" strokeWidth="1.5" />
                <circle r="3" fill="#94a3b8" />
                {showLabels && (
                  <text x="-35" y="20" fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="9">
                    DEHT02-SW01
                  </text>
                )}
              </g>

              {/* ============================================================= */}
              {/* ANOMALOUS LEAF ZONE NODES (Golden Dashed Circles) */}
              {/* ============================================================= */}

              {/* ALM-99210019 */}
              <g
                transform="translate(715, 175)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'ALM-99210019' ? null : 'ALM-99210019')
                }}
              >
                {selectedNodeId === 'ALM-99210019' && (
                  <circle r="22" fill="rgba(245, 158, 11, 0.2)" stroke="#fbbf24" strokeWidth="1.5" />
                )}
                <circle r="16" fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="3 3" />
                <circle r="5" fill="#f59e0b" />
                {showLabels && (
                  <text x="-35" y="-12" fill="#fde68a" fontFamily="JetBrains Mono, monospace" fontSize="9">
                    ALM-99210019
                  </text>
                )}
              </g>

              {/* ALM-99210088 (LEAF ALERT) */}
              <g
                transform="translate(825, 190)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'ALM-99210088' ? null : 'ALM-99210088')
                }}
              >
                {selectedNodeId === 'ALM-99210088' && (
                  <circle r="22" fill="rgba(245, 158, 11, 0.2)" stroke="#fbbf24" strokeWidth="1.5" />
                )}
                <circle r="16" fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="3 3" />
                <circle r="5" fill="#f59e0b" />
                {showLabels && (
                  <>
                    <text x="-35" y="-12" fill="#fde68a" fontFamily="JetBrains Mono, monospace" fontSize="9">
                      ALM-99210088
                    </text>
                    <text x="-32" y="24" fill="#fbbf24" fontFamily="JetBrains Mono, monospace" fontSize="8" fontWeight="700">
                      LEAF ALERT
                    </text>
                  </>
                )}
              </g>

              {/* ALM-99210014 (LOW CONDUCTANCE - FOCUSED ANOMALY) */}
              <g
                transform="translate(740, 295)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'ALM-99210014' ? null : 'ALM-99210014')
                }}
              >
                {/* Glowing double amber halo */}
                <circle r={selectedNodeId === 'ALM-99210014' ? '30' : '26'} fill="rgba(245, 158, 11, 0.15)" stroke="#f59e0b" strokeWidth={selectedNodeId === 'ALM-99210014' ? 2.5 : 2} strokeDasharray="4 3" />
                <circle r="14" fill="#78350f" stroke="#fbbf24" strokeWidth="2.5" />
                <circle r="5" fill="#fbbf24" />
                {showLabels && (
                  <>
                    <text x="-38" y="38" fill="#fef3c7" fontFamily="JetBrains Mono, monospace" fontSize="10" fontWeight="700">
                      ALM-99210014
                    </text>
                    <text x="-42" y="50" fill="#f59e0b" fontFamily="JetBrains Mono, monospace" fontSize="8" fontWeight="700">
                      LOW CONDUCTANCE
                    </text>
                  </>
                )}
              </g>

              {/* ALM-99210102 */}
              <g
                transform="translate(795, 400)"
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNodeId(selectedNodeId === 'ALM-99210102' ? null : 'ALM-99210102')
                }}
              >
                {selectedNodeId === 'ALM-99210102' && (
                  <circle r="20" fill="rgba(148, 163, 184, 0.2)" stroke="#94a3b8" strokeWidth="1.5" />
                )}
                <circle r="14" fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeDasharray="3 2" />
                <circle r="4" fill="#94a3b8" />
                {showLabels && (
                  <text x="-35" y="22" fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="9">
                    ALM-99210102
                  </text>
                )}
              </g>
            </svg>

            {/* FLOATING OVERLAY CARD: FOCUSED ANOMALY (Only shown when a node is clicked) */}
            {focusedNode && (
              <div className="absolute bottom-4 right-4 w-80 bg-slate-900/95 backdrop-blur-md border border-amber-500/40 rounded-lg p-3 shadow-2xl flex flex-col gap-1.5 text-slate-200 z-10 animate-fadeIn">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-code-sm text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
                      FOCUSED ANOMALY
                    </span>
                    <span className="px-2 py-0.5 bg-amber-500/20 text-amber-300 font-code-sm text-[10px] font-bold rounded">
                      {focusedNode.badge}
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setSelectedNodeId(null)
                    }}
                    className="text-slate-400 hover:text-white p-0.5 rounded hover:bg-slate-800 transition-colors cursor-pointer"
                    title="Close"
                  >
                    <span className="material-symbols-outlined text-[15px]">close</span>
                  </button>
                </div>
                <div className="font-code-sm text-sm font-bold text-white flex items-center gap-1.5">
                  <span className="text-amber-100">{focusedNode.name}</span>
                  <span className="text-slate-500 font-normal">::</span>
                  <span className="text-amber-300">{focusedNode.type}</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed font-sans">
                  {focusedNode.desc}
                </p>
                <div className="flex items-center justify-between pt-1.5 border-t border-slate-800 font-code-sm text-xs text-slate-400">
                  <span>Degree: <strong className="text-cyan-300 font-semibold">{focusedNode.degree}</strong></span>
                  <span>Degradation: <strong className="text-rose-400 font-semibold">{focusedNode.degradation}</strong></span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SCREEN 12: CANDIDATE CUTS */}
      {/* ========================================================================= */}
      {activeTab === 'CUTS' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
          {/* Left Col: Cut Candidate List */}
          <div className="lg:col-span-5 flex flex-col gap-space-sm">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
              Synthesized Cut Planes ({candidateCuts.length})
            </span>
            {candidateCuts.map((cut, idx) => (
              <div
                key={cut.id}
                onClick={() => setSelectedCutIndex(idx)}
                className={`p-space-md rounded-lg flex flex-col gap-space-xs cursor-pointer transition-all border ${
                  selectedCutIndex === idx
                    ? 'bg-surface-container border-secondary shadow-md'
                    : 'bg-surface-container-low border-transparent hover:bg-surface-container'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-code-md text-code-md font-bold text-on-surface">{cut.id}</span>
                  <span
                    className={`font-label-caps text-label-caps uppercase px-space-xs py-0.5 rounded font-bold ${
                      idx === 0 ? 'bg-primary-container/20 text-primary' : 'bg-surface-container text-on-surface-variant'
                    }`}
                  >
                    {cut.status}
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">{cut.plane}</span>
                <div className="flex items-center justify-between pt-space-2xs text-code-sm font-code-sm border-t border-surface-container-highest">
                  <span className="text-on-surface-variant">Conductance:</span>
                  <span className="text-primary font-bold">{cut.conductance.toFixed(3)}</span>
                  <span className="text-on-surface-variant">Gain:</span>
                  <span className="text-secondary font-bold">{cut.modularityGain}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Right Col: Selected Cut Deep-Dive */}
          <div className="lg:col-span-7 bg-surface-container rounded-lg p-space-md flex flex-col gap-space-md shadow-md">
            <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[20px]">content_cut</span>
                <span className="font-headline-md text-headline-md font-bold text-on-surface">
                  Cut Specification: {activeCut.id}
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-primary font-bold">
                Conductance Φ = {activeCut.conductance.toFixed(3)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-space-sm font-code-sm text-code-sm">
              <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">Subchain A (Left)</span>
                <span className="text-on-surface font-semibold">{activeCut.subchainA}</span>
                <span className="text-on-surface-variant text-body-sm">Retains upstream root failure context.</span>
              </div>
              <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">Subchain B (Right)</span>
                <span className="text-on-surface font-semibold">{activeCut.subchainB}</span>
                <span className="text-on-surface-variant text-body-sm">Isolates downstream access cascade.</span>
              </div>
            </div>

            <div className="bg-surface-container-low p-space-sm rounded flex flex-col gap-space-xs">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                Disconnected Bridge Edges
              </span>
              <div className="font-mono text-code-sm text-on-surface space-y-1">
                <div className="flex justify-between p-1 bg-surface-container rounded">
                  <span>ALM-47933130 ↔ ALM-99210014</span>
                  <span className="text-error font-bold">Weight: 0.11</span>
                </div>
                <div className="flex justify-between p-1 bg-surface-container rounded">
                  <span>DEHL01-GW01::Gi0/1 ↔ DEHT01-SW01::Gi0/2</span>
                  <span className="text-error font-bold">Weight: 0.08</span>
                </div>
              </div>
            </div>

            {/* Feedback Banner */}
            {actionFeedback && (
              <div className="p-space-sm bg-secondary-container/20 border border-secondary/40 rounded flex items-center justify-between text-body-sm animate-fadeIn">
                <div className="flex items-center gap-space-xs text-secondary font-medium">
                  <span className="material-symbols-outlined text-[18px]">info</span>
                  <span>{actionFeedback}</span>
                </div>
                <button
                  onClick={() => setActionFeedback(null)}
                  className="text-on-surface-variant hover:text-on-surface cursor-pointer text-xs"
                >
                  Đóng
                </button>
              </div>
            )}

            {/* Screen 12 Action Buttons */}
            <div className="flex flex-wrap items-center justify-end gap-space-sm pt-space-xs">
              <button
                type="button"
                onClick={() =>
                  setActionFeedback(
                    `✓ Mô phỏng Sandbox (${activeCut.id}): Cô lập 98.6%, 0 gián đoạn SLA P1, Staging snapshot sẵn sàng.`
                  )
                }
                className="px-space-md py-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface font-body-md text-sm font-semibold rounded shadow-xs flex items-center gap-space-xs transition-colors cursor-pointer border border-surface-container-highest"
              >
                <span className="material-symbols-outlined text-[18px] text-secondary">play_arrow</span>
                <span>Simulate Split Sandbox</span>
              </button>

              <button
                type="button"
                onClick={() =>
                  setActionFeedback(
                    `✓ Đã ghi nhận: Giữ nguyên chuỗi, đánh dấu đồng kích hoạt hợp lệ giữa các trạm (Override Co-firing).`
                  )
                }
                className="px-space-md py-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface-variant hover:text-on-surface font-body-md text-sm rounded shadow-xs flex items-center gap-space-xs transition-colors cursor-pointer border border-surface-container-highest"
              >
                <span className="material-symbols-outlined text-[18px]">lock_reset</span>
                <span>Override as Co-firing</span>
              </button>

              {onOpenValidationModal && (
                <button
                  type="button"
                  onClick={() =>
                    onOpenValidationModal({
                      opId: `MUT-${activeCut.id}`,
                      opType: 'CHEEGER_SPECTRAL_CUT',
                      title: `Phê duyệt Nhát cắt Đồ thị ${activeCut.id}`,
                      targetSummary: `Phân tách: Subchain A (${activeCut.subchainA}) và Subchain B (${activeCut.subchainB})`,
                      detail: `Độ dẫn vết cắt Φ = ${activeCut.conductance.toFixed(3)}, Gain = ${activeCut.modularityGain}. Ngắt các liên kết cầu nối giữa DEHL01 và DEHT01.`,
                      badgeLabel: activeCut.id,
                      conductance: activeCut.conductance,
                      modularityGain: activeCut.modularityGain,
                      disconnectedEdges: [
                        'ALM-47933130 ↔ ALM-99210014 (Weight: 0.11)',
                        'DEHL01-GW01::Gi0/1 ↔ DEHT01-SW01::Gi0/2 (Weight: 0.08)',
                      ],
                      defaultNote: `Xác nhận phân tách ${activeCut.id} để cô lập nhánh phụ trợ hạ lưu DEHT01 khỏi lõi sự cố DEHL01.`,
                    })
                  }
                  className="px-space-lg py-space-xs bg-primary text-on-primary font-body-md text-sm font-bold rounded shadow-md hover:brightness-110 flex items-center gap-space-xs transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">verified</span>
                  <span>Sign-off Cut Dispatch</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SCREEN 13: ATTRIBUTION DELETION CURVES */}
      {/* ========================================================================= */}
      {activeTab === 'ATTRIBUTION' && (
        <div className="bg-surface-container rounded-lg p-space-lg flex flex-col gap-space-md shadow-md">
          <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
            <div>
              <span className="font-headline-md text-headline-md font-bold text-on-surface">
                Attribution Exact Deletion Curves
              </span>
              <p className="font-body-sm text-body-sm text-on-surface-variant mt-0.5">
                Primary vs Reverse vs Random Feature Ablation. Lower primary AUC proves superior evidence ranking.
              </p>
            </div>
            <div className="flex items-center gap-space-sm font-code-sm text-code-sm">
              <span className="text-on-surface-variant">Randomization:</span>
              <span className="text-secondary font-semibold">100 runs · seed 42</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md">
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Primary AUC</span>
              <span className="font-headline-xl text-headline-xl text-secondary font-bold my-1">0.184</span>
              <span className="font-code-sm text-code-sm text-secondary font-semibold">Superior ranking (Steep descent)</span>
            </div>
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Random Baseline AUC</span>
              <span className="font-headline-xl text-headline-xl text-on-surface font-bold my-1">0.512 ± 0.03</span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">Null hypothesis baseline</span>
            </div>
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Reverse Ablation AUC</span>
              <span className="font-headline-xl text-headline-xl text-tertiary font-bold my-1">0.824</span>
              <span className="font-code-sm text-code-sm text-tertiary font-semibold">Worst-order deletion check</span>
            </div>
          </div>

          {/* SVG Ablation Curve */}
          <div className="w-full h-56 bg-surface-container-lowest rounded p-space-md flex flex-col justify-end">
            <svg className="w-full h-44 overflow-visible" preserveAspectRatio="none" viewBox="0 0 700 160">
              {/* Grid */}
              <line x1="0" y1="30" x2="700" y2="30" stroke="#2e3545" strokeDasharray="3 3" />
              <line x1="0" y1="80" x2="700" y2="80" stroke="#2e3545" strokeDasharray="3 3" />
              <line x1="0" y1="130" x2="700" y2="130" stroke="#2e3545" strokeDasharray="3 3" />

              {/* Random line */}
              <line x1="60" y1="20" x2="640" y2="140" stroke="#4e5566" strokeWidth="2" strokeDasharray="4 4" />

              {/* Reverse line */}
              <polyline points="60,20 200,25 350,35 500,60 640,140" fill="none" stroke="#ffb95f" strokeWidth="2.5" />

              {/* Primary line */}
              <polyline points="60,20 150,110 300,135 480,140 640,140" fill="none" stroke="#7bd0ff" strokeWidth="3" />
            </svg>
            <div className="flex justify-between text-code-sm font-code-sm text-on-surface-variant pt-space-xs">
              <span className="text-secondary font-bold">— Primary AUC (0.184)</span>
              <span className="text-tertiary font-semibold">— Reverse AUC (0.824)</span>
              <span className="text-on-surface-variant">--- Random Mean (0.512)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
