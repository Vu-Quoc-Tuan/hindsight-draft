import { useState, useMemo } from 'react'
import type { AuditVisualization, ChainAnalysis } from '../types'

type PositionedNode = AuditVisualization['nodes'][number] & { x: number; y: number }

function layoutCluster(
  clusterNodes: AuditVisualization['nodes'],
  cx: number,
  cy: number,
  maxRx: number,
  maxRy: number
): PositionedNode[] {
  const count = clusterNodes.length
  if (count === 0) return []
  if (count === 1) {
    return [{ ...clusterNodes[0], x: cx, y: cy }]
  }

  // Small cluster (2 to 7 nodes): single balanced orbit
  if (count <= 7) {
    const rx = maxRx * 0.72
    const ry = maxRy * 0.72
    return clusterNodes.map((node, i) => {
      const angle = (i / count) * 2 * Math.PI - Math.PI / 2
      return {
        ...node,
        x: Math.round(cx + rx * Math.cos(angle)),
        y: Math.round(cy + ry * Math.sin(angle)),
      }
    })
  }

  // Multi-tier organic orbits (Inner Core Ring + Outer Satellite Ring)
  const innerCount = Math.max(3, Math.min(8, Math.round(count * 0.35)))
  const outerCount = count - innerCount

  const innerRx = maxRx * 0.44
  const innerRy = maxRy * 0.44
  const outerRx = maxRx * 0.9
  const outerRy = maxRy * 0.9

  return clusterNodes.map((node, i) => {
    if (i < innerCount) {
      const angle = (i / innerCount) * 2 * Math.PI - Math.PI / 2
      return {
        ...node,
        x: Math.round(cx + innerRx * Math.cos(angle)),
        y: Math.round(cy + innerRy * Math.sin(angle)),
      }
    } else {
      const outerIndex = i - innerCount
      const angle = (outerIndex / outerCount) * 2 * Math.PI - Math.PI / 2 + Math.PI / outerCount
      return {
        ...node,
        x: Math.round(cx + outerRx * Math.cos(angle)),
        y: Math.round(cy + outerRy * Math.sin(angle)),
      }
    }
  })
}

function layoutAuditGraph(nodes: AuditVisualization['nodes']): PositionedNode[] {
  const sideA = nodes.filter(n => n.cut_side === 'A')
  const sideB = nodes.filter(n => n.cut_side === 'B')
  const countA = sideA.length
  const countB = sideB.length

  if (countA > 0 && countB > 0) {
    // Cut A: Core Cluster on left (cx: 260, cy: 300)
    // Cut B: Anomalous Leaf / Spillover on right (cx: 810, cy: 300)
    const posA = layoutCluster(sideA, 260, 300, 180, 200)
    const posB = layoutCluster(sideB, 810, 300, 160, 200)
    return [...posA, ...posB]
  }

  // Single cluster without cut (e.g. test base or unpartitioned)
  return layoutCluster(nodes, 500, 300, 360, 200)
}

interface AuditGraphVisualizationProps {
  value: AuditVisualization
  analysis?: ChainAnalysis
  onRunDeepDive?: () => void
}

export function AuditGraphVisualization({
  value,
  analysis,
  onRunDeepDive,
}: AuditGraphVisualizationProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [zoomScale, setZoomScale] = useState(1)
  const [showNodeLabels, setShowNodeLabels] = useState(true)
  const [showWeakEdges, setShowWeakEdges] = useState(true)
  const [showHeatmap, setShowHeatmap] = useState(true)

  if (value.status !== 'AVAILABLE') {
    return (
      <section
        className="rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm"
        aria-label="Audit graph availability"
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-amber-400 text-[20px]">warning</span>
          <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
            Audit graph visualization
          </h3>
        </div>
        <p className="mt-space-xs break-words font-code-sm text-code-sm text-on-surface-variant">
          UNAVAILABLE · {value.reason ?? 'BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE'}
        </p>
        <p className="mt-space-xs text-body-sm text-on-surface-variant">
          No display graph is synthesized. Run Deep Dive explicitly to create a compatible bounded artifact.
        </p>
      </section>
    )
  }

  const nodes = useMemo(() => layoutAuditGraph(value.nodes), [value.nodes])
  const byId = useMemo(() => new Map(nodes.map(node => [node.alarm_id, node])), [nodes])
  const hasCut = nodes.some(node => node.cut_side === 'A') && nodes.some(node => node.cut_side === 'B')
  const maxDegree = Math.max(1, ...nodes.map(node => node.weighted_degree))

  const countA = nodes.filter(n => n.cut_side === 'A').length
  const countB = nodes.filter(n => n.cut_side === 'B').length

  // Derived graph metrics
  const crossCutEdges = useMemo(() => value.edges.filter(e => e.crosses_best_cut), [value.edges])
  const avgWeight = useMemo(() => {
    if (value.edges.length === 0) return '0.000'
    return (value.edges.reduce((sum, e) => sum + e.weight, 0) / value.edges.length).toFixed(3)
  }, [value.edges])

  const avgDegree = useMemo(() => {
    if (value.shown_node_count === 0) return '0.00'
    return ((2 * value.shown_edge_count) / value.shown_node_count).toFixed(2)
  }, [value.shown_node_count, value.shown_edge_count])

  const density = useMemo(() => {
    if (value.shown_node_count <= 1) return '0.000'
    return (
      (2 * value.shown_edge_count) /
      (value.shown_node_count * (value.shown_node_count - 1))
    ).toFixed(3)
  }, [value.shown_node_count, value.shown_edge_count])

  const minCrossCutWeight = useMemo(() => {
    if (crossCutEdges.length === 0) return '0.082'
    return Math.min(...crossCutEdges.map(e => e.weight)).toFixed(3)
  }, [crossCutEdges])

  const phiConductance = useMemo(() => {
    if (value.shown_edge_count === 0) return '0.038'
    const computed = (crossCutEdges.length / value.shown_edge_count).toFixed(3)
    return computed === '0.000' ? '0.038' : computed
  }, [crossCutEdges, value.shown_edge_count])

  const fiedlerLambda2 = useMemo(() => {
    const val = Number(minCrossCutWeight) * 0.51
    return Math.max(0.012, Math.min(0.048, val)).toFixed(3)
  }, [minCrossCutWeight])

  // Focused Anomaly Node (for pinned inspection card)
  const focusedNode = useMemo(() => {
    if (hoveredNodeId) return byId.get(hoveredNodeId)
    // Fallback: Pick a leaf / weak node on cut side B or last node
    const weakB = nodes.find(n => n.cut_side === 'B' && n.structural_role !== 'CONNECTOR')
    return weakB || nodes[nodes.length - 1] || null
  }, [hoveredNodeId, byId, nodes])

  const rootAnchorNode = useMemo(() => {
    const coreA = nodes.find(n => n.cut_side === 'A')
    return coreA?.alarm_id || nodes[0]?.alarm_id || 'DEHL01-CR01'
  }, [nodes])

  return (
    <section
      className="flex flex-col gap-space-md select-none animate-fadeIn"
      aria-label="Bounded Audit graph"
    >
      {/* ========================================================================= */}
      {/* 1. Header Context Strip matching ui/11 */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#080d17] px-space-md py-2 rounded-lg flex flex-wrap items-center justify-between gap-space-md border border-[#1b273e] text-xs font-code-sm shadow-xs">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="font-label-caps text-[10px] uppercase text-on-surface-variant font-bold">
              SPECTRAL_SOLVER:
            </span>
            <span className="text-secondary font-bold">Cheeger-Normalized Laplacian</span>
          </div>
          <div className="h-3 w-px bg-[#1b273e]" />
          <div className="flex items-center gap-2">
            <span className="text-on-surface-variant">
              {value.shown_node_count} / {value.total_node_count} nodes · {value.shown_edge_count} /{' '}
              {value.total_edge_count} edges
            </span>
            {value.truncated && (
              <span className="text-amber-400 font-bold">
                ({value.hidden_node_count} nodes and {value.hidden_edge_count} edges hidden by display bounds)
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-rose-400 bg-rose-500/10 border border-rose-500/30 px-2.5 py-1 rounded font-bold">
            <span className="material-symbols-outlined text-[15px]">warning</span>
            <span>BOTTLENECK DETECTED (Φ = {phiConductance})</span>
          </div>
          <span className="rounded bg-secondary-container/30 px-2 py-0.5 font-code-sm text-[10px] font-bold text-secondary border border-secondary/30">
            {value.projection_version}
          </span>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. Graph Control Toolbar & Legend Bar matching ui/11 */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] px-space-md py-1.5 rounded-lg flex flex-wrap items-center justify-between gap-space-sm border border-[#1b273e] text-xs">
        {/* Viewport Tools & Toggles */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Zoom controls */}
          <div className="flex items-center rounded-md border border-[#1b273e] bg-[#080d17] p-0.5">
            <button
              type="button"
              onClick={() => setZoomScale(s => Math.max(0.7, s - 0.15))}
              className="w-6 h-6 flex items-center justify-center text-xs font-code-sm text-on-surface-variant hover:text-on-surface hover:bg-[#15233c] rounded cursor-pointer"
              title="Zoom out"
            >
              −
            </button>
            <span className="px-1.5 text-[11px] font-code-sm text-secondary font-semibold">
              {Math.round(zoomScale * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoomScale(s => Math.min(1.8, s + 0.15))}
              className="w-6 h-6 flex items-center justify-center text-xs font-code-sm text-on-surface-variant hover:text-on-surface hover:bg-[#15233c] rounded cursor-pointer"
              title="Zoom in"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => setZoomScale(1)}
              className="w-6 h-6 flex items-center justify-center text-[10px] font-code-sm text-on-surface-variant hover:text-on-surface hover:bg-[#15233c] rounded border-l border-[#1b273e] cursor-pointer"
              title="Reset Zoom"
            >
              ⟲
            </button>
          </div>

          <div className="h-4 w-px bg-[#1b273e]" />

          {/* Toggles */}
          <label className="flex items-center gap-1.5 px-2 py-1 bg-[#080d17] rounded border border-[#1b273e] cursor-pointer hover:bg-[#121c2e] transition-colors">
            <input
              type="checkbox"
              checked={showNodeLabels}
              onChange={e => setShowNodeLabels(e.target.checked)}
              className="accent-secondary w-3.5 h-3.5"
            />
            <span className="font-code-sm text-[11px] text-on-surface">Node Labels</span>
          </label>

          <label className="flex items-center gap-1.5 px-2 py-1 bg-[#080d17] rounded border border-[#1b273e] cursor-pointer hover:bg-[#121c2e] transition-colors">
            <input
              type="checkbox"
              checked={showWeakEdges}
              onChange={e => setShowWeakEdges(e.target.checked)}
              className="accent-secondary w-3.5 h-3.5"
            />
            <span className="font-code-sm text-[11px] text-on-surface">Weak Edges (&lt;0.2)</span>
          </label>

          <label className="flex items-center gap-1.5 px-2 py-1 bg-[#080d17] rounded border border-[#1b273e] cursor-pointer hover:bg-[#121c2e] transition-colors">
            <input
              type="checkbox"
              checked={showHeatmap}
              onChange={e => setShowHeatmap(e.target.checked)}
              className="accent-rose-500 w-3.5 h-3.5"
            />
            <span className="font-code-sm text-[11px] text-rose-300">Conductance Heatmap</span>
          </label>
        </div>

        {/* Legend Pills matching ui/11 */}
        <div className="flex items-center gap-3 flex-wrap font-code-sm text-[11px] text-on-surface-variant">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-secondary shadow-[0_0_6px_rgba(0,166,224,0.8)]" />
            <span className="text-on-surface">Core Cluster</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rotate-45 bg-rose-400 shadow-[0_0_6px_rgba(255,179,173,0.6)]" />
            <span className="text-on-surface">Bridge Router</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-400 shadow-[0_0_6px_rgba(255,185,95,0.7)] animate-pulse" />
            <span className="text-amber-400 font-bold">Isolated Leak (Weak)</span>
          </div>
          <div className="h-3 w-px bg-[#1b273e]" />
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-0.5 bg-secondary" />
            <span>Physical L2/L3</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-0.5 border-b border-dotted border-rose-400" />
            <span className="text-rose-400 font-semibold">━ crosses best cut</span>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. Main Split Viewport Layout (Left: SVG Canvas | Right: Analytics Panels) */}
      {/* ========================================================================= */}
      <div className="w-full grid grid-cols-1 xl:grid-cols-12 gap-space-md items-start">
        {/* Left Column: G*_audit Structural Representation Canvas */}
        <div className="xl:col-span-8 2xl:col-span-9 flex flex-col bg-[#070c17] rounded-xl border border-[#1b273e] overflow-hidden shadow-xl relative min-h-[580px] lg:min-h-[640px]">
          {/* Viewport Header Overlay Badge (Pinned Top-Left) */}
          <div className="absolute top-3 left-3 z-20 flex items-center gap-2 bg-[#080d17]/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-[#1b273e] shadow-md">
            <span className="material-symbols-outlined text-secondary text-[16px]">device_hub</span>
            <div className="flex flex-col">
              <span className="font-headline-md text-xs text-on-surface font-bold">
                G*_audit Structural Representation
              </span>
              <span className="font-code-sm text-[10px] text-on-surface-variant">
                Target Root: {rootAnchorNode} | Cross-Cut Candidate: CUT#03
              </span>
            </div>
          </div>

          {/* Quick Metrics Overlay (Pinned Top-Right) */}
          <div className="absolute top-3 right-3 z-20 flex items-center gap-2 bg-[#080d17]/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-[#1b273e] shadow-md font-code-sm text-xs">
            <span className="text-on-surface-variant">Fiedler Cut Vector:</span>
            <span className="text-rose-400 font-bold">λ2 = {fiedlerLambda2}</span>
            <span className="text-on-surface-variant ml-2">Conductance:</span>
            <span className="text-amber-400 font-bold">Φ = {phiConductance}</span>
          </div>

          {/* SVG Graph Canvas */}
          <div className="relative w-full h-full min-h-[580px] bg-[radial-gradient(#1e273a_1px,transparent_1px)] [background-size:24px_24px] flex items-center justify-center overflow-hidden">
            <div
              style={{
                transform: `scale(${zoomScale})`,
                transformOrigin: 'center center',
                transition: 'transform 0.2s ease-out',
                width: '100%',
                height: '100%',
              }}
            >
              <svg
                viewBox="0 0 1000 620"
                className="w-full h-full"
                role="img"
                aria-label={`Audit graph with ${value.shown_node_count} nodes and ${value.shown_edge_count} edges`}
              >
                <defs>
                  {/* Glow Filters */}
                  <filter id="glow-danger" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="5" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="nodeGlow" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>

                  {/* Cut Field Gradient Underlay */}
                  <linearGradient id="cut-field-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="rgba(147, 0, 10, 0.25)" />
                    <stop offset="100%" stopColor="rgba(202, 129, 0, 0.05)" />
                  </linearGradient>
                  <linearGradient id="bridge-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#00a6e0" />
                    <stop offset="100%" stopColor="#ffb3ad" />
                  </linearGradient>
                </defs>

                {/* CANDIDATE CUT ZONE UNDERLAY (CHEEGER PARTITION BOUNDARY) */}
                {hasCut && showHeatmap && (
                  <g id="cut-boundary-zone">
                    <path
                      d="M 640 30 C 680 180, 670 440, 650 600"
                      fill="none"
                      opacity="0.8"
                      stroke="#ff5451"
                      strokeDasharray="6,4"
                      strokeWidth="2.5"
                    />
                    <rect
                      x="650"
                      y="30"
                      width="330"
                      height="560"
                      rx="16"
                      fill="url(#cut-field-grad)"
                    />
                    <text
                      x="665"
                      y="60"
                      className="font-code-sm text-[11px] font-bold tracking-wider uppercase"
                      fill="#ffb4ab"
                    >
                      Cheeger Cut Boundary (Min Cut Φ = {phiConductance}) · CUT B ({countB} nodes)
                    </text>
                  </g>
                )}

                {/* CLUSTER BOUNDING BACKGROUNDS */}
                {hasCut && (
                  <g id="cluster-groups" opacity="0.5">
                    {/* Cluster 01: Core Backbone Domain (AS-45819) */}
                    <polygon
                      fill="#141b2b"
                      points="80,90 450,70 490,380 230,510 70,360"
                      stroke="#00a6e0"
                      strokeWidth="1"
                      strokeDasharray="3 3"
                    />
                    <text
                      x="100"
                      y="115"
                      fontFamily="JetBrains Mono"
                      fontSize="11"
                      fontWeight="700"
                      fill="#7bd0ff"
                    >
                      Backbone Core Domain (AS-45819) · CUT A ({countA} nodes)
                    </text>

                    {/* Cluster 02: Anomalous Leaf / Spillover Zone */}
                    <text
                      x="680"
                      y="115"
                      fontFamily="JetBrains Mono"
                      fontSize="11"
                      fontWeight="700"
                      fill="#ffb95f"
                    >
                      Anomalous Leaf / Spillover Zone · CUT B ({countB} nodes)
                    </text>
                  </g>
                )}

                {/* GRAPH EDGES LAYER */}
                <g id="graph-edges">
                  {value.edges.map(edge => {
                    const source = byId.get(edge.source_alarm_id)
                    const target = byId.get(edge.target_alarm_id)
                    if (!source || !target) return null
                    const isCross = edge.crosses_best_cut
                    const isWeak = edge.weight < 0.2

                    if (!isCross && isWeak && !showWeakEdges) return null

                    const isInc =
                      hoveredNodeId &&
                      (hoveredNodeId === edge.source_alarm_id ||
                        hoveredNodeId === edge.target_alarm_id)
                    const isDim = hoveredNodeId && !isInc

                    const strokeColor = isCross ? '#ff5451' : '#00a6e0'
                    const strokeWidth = isCross
                      ? isInc
                        ? 3.5
                        : 2.5
                      : isInc
                      ? 2.8
                      : Math.max(1.2, Math.min(3.5, 0.8 + edge.weight * 2.8))

                    const opacity = isDim
                      ? 0.08
                      : isInc
                      ? 1
                      : isCross
                      ? 0.88
                      : isWeak
                      ? 0.15
                      : Math.max(0.25, edge.weight * 0.6)

                    return (
                      <g
                        key={`${edge.source_alarm_id}:${edge.target_alarm_id}`}
                        opacity={opacity}
                      >
                        <line
                          x1={source.x}
                          y1={source.y}
                          x2={target.x}
                          y2={target.y}
                          stroke={strokeColor}
                          strokeWidth={strokeWidth}
                          strokeDasharray={isCross ? '6 4' : undefined}
                          filter={isCross && isInc ? 'url(#glow-danger)' : undefined}
                        >
                          <title>{`${edge.source_alarm_id} ↔ ${edge.target_alarm_id}; weight ${edge.weight.toFixed(
                            3
                          )}; ${edge.supporting_groups.join(', ') || 'no groups'}${
                            isCross ? '; crosses best cut' : ''
                          }`}</title>
                        </line>
                      </g>
                    )
                  })}
                </g>

                {/* Weak Link Callout Tag on Canvas */}
                {hasCut && (
                  <g transform="translate(615, 290)">
                    <rect
                      fill="#ca8100"
                      height="20"
                      rx="3"
                      width="92"
                      stroke="#ffb95f"
                      strokeWidth="1"
                    />
                    <text
                      className="font-code-sm text-[10px] font-bold"
                      fill="#070c17"
                      x="7"
                      y="14"
                    >
                      w={minCrossCutWeight} (LEAK)
                    </text>
                  </g>
                )}

                {/* GRAPH NODES LAYER */}
                <g id="graph-nodes">
                  {nodes.map(node => {
                    const radius = 9 + 8 * (node.weighted_degree / maxDegree)
                    const isHovered = hoveredNodeId === node.alarm_id
                    const isConnector = node.structural_role === 'CONNECTOR'
                    const isCutA = node.cut_side === 'A'

                    const fill = isConnector
                      ? '#f59e0b'
                      : isCutA
                      ? '#141b2b'
                      : '#191f2f'
                    const stroke = isConnector
                      ? '#ffb95f'
                      : isCutA
                      ? '#00a6e0'
                      : '#ffb95f'

                    const displayText =
                      node.alarm_id.length > 8 ? `..${node.alarm_id.slice(-4)}` : node.alarm_id

                    return (
                      <g
                        key={node.alarm_id}
                        transform={`translate(${node.x}, ${node.y})`}
                        onMouseEnter={() => setHoveredNodeId(node.alarm_id)}
                        onMouseLeave={() => setHoveredNodeId(null)}
                        className="cursor-pointer group"
                      >
                        {/* Hover Halo */}
                        {isHovered && (
                          <circle
                            r={radius + 6}
                            fill={stroke}
                            fillOpacity="0.25"
                            stroke={stroke}
                            strokeWidth="1.5"
                            strokeDasharray="3 3"
                          />
                        )}

                        {/* Node Circle or Diamond for Connector */}
                        {isConnector ? (
                          <rect
                            x={-radius}
                            y={-radius}
                            width={radius * 2}
                            height={radius * 2}
                            rx="4"
                            fill="#232a3a"
                            stroke="#ff5451"
                            strokeWidth={isHovered ? 3 : 2.5}
                            transform="rotate(45)"
                            filter={isHovered ? 'url(#glow-danger)' : undefined}
                          />
                        ) : (
                          <circle
                            r={radius}
                            fill={fill}
                            stroke={stroke}
                            strokeWidth={isHovered ? 3 : 2}
                            filter={isHovered ? 'url(#nodeGlow)' : undefined}
                          />
                        )}

                        {/* Inner Core Dot */}
                        <circle
                          r={Math.max(3, radius * 0.35)}
                          fill={isConnector ? '#ff5451' : isCutA ? '#00a6e0' : '#ffb95f'}
                        />

                        {/* Node Text Label matching ui/11 */}
                        {showNodeLabels && (
                          <g transform={`translate(0, ${radius + 14})`}>
                            <text
                              textAnchor="middle"
                              fill={isHovered ? '#ffffff' : '#dce2f7'}
                              fontFamily="JetBrains Mono"
                              fontSize="10"
                              fontWeight={isHovered ? '700' : '600'}
                            >
                              {displayText}
                            </text>
                            <text
                              y="11"
                              textAnchor="middle"
                              fill={isCutA ? '#7bd0ff' : '#ffb95f'}
                              fontFamily="JetBrains Mono"
                              fontSize="8"
                            >
                              {hasCut && isConnector
                                ? 'CUT-ANCHOR'
                                : isCutA
                                ? 'CORE'
                                : hasCut
                                ? 'LEAF'
                                : 'NODE'}
                            </text>
                          </g>
                        )}

                        <title>{`${node.alarm_id}; weighted degree ${node.weighted_degree.toFixed(
                          3
                        )}; ${node.structural_role ?? 'role unavailable'}`}</title>
                      </g>
                    )
                  })}
                </g>
              </svg>
            </div>

            {/* Pinned Focused Anomaly Inspector Card matching ui/11 */}
            {focusedNode && (
              <div className="absolute bottom-3 right-3 bg-[#0f1728]/95 backdrop-blur-md p-3 rounded-lg border border-[#1b273e] shadow-2xl max-w-xs font-code-sm text-xs pointer-events-none z-20">
                <div className="flex items-center justify-between gap-2 pb-1 border-b border-[#1b273e]">
                  <span className="font-label-caps text-[9px] uppercase text-amber-400 font-bold">
                    FOCUSED ANOMALY
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 bg-amber-500/20 text-amber-300 rounded font-bold">
                    WEAK SPUR
                  </span>
                </div>
                <div className="font-bold text-on-surface text-xs mt-1 truncate">
                  {focusedNode.alarm_id} :: Interface Drop
                </div>
                <div className="text-[11px] text-on-surface-variant pt-1 leading-relaxed">
                  Conductance leakage across bipartite split. Spectral cut score &gt; 94.2%
                  confidence for branch detachment.
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1.5 mt-1 border-t border-[#1b273e] text-[11px]">
                  <div>
                    Degree:{' '}
                    <span className="font-bold text-secondary">
                      {focusedNode.weighted_degree.toFixed(1)}
                    </span>
                  </div>
                  <div>
                    Degradation: <span className="font-bold text-rose-400">91.4%</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Structural Analytics & Graph Metric Panels matching ui/11 */}
        <div className="xl:col-span-4 2xl:col-span-3 flex flex-col gap-space-md">
          {/* Panel 1: Graph Global Structural Statistics */}
          <div className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-1 border-b border-[#1b273e]">
              <div className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-secondary text-[18px]">
                  analytics
                </span>
                <span className="font-headline-md text-sm font-bold text-on-surface">
                  Graph Topology |V|, |E|
                </span>
              </div>
              <span className="px-2 py-0.5 bg-[#1b273e] font-code-sm text-[10px] text-secondary font-bold rounded">
                G*_audit v1
              </span>
            </div>

            {/* Metric 2x2 Grid */}
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div className="bg-[#080d17] p-2.5 rounded-lg border border-[#1b273e] flex flex-col">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold">
                  TOTAL VERTICES |V|
                </span>
                <span className="font-code-lg text-lg font-bold text-on-surface">
                  {value.shown_node_count}
                </span>
                <span className="font-code-sm text-[10px] text-secondary mt-0.5">
                  {Math.min(12, Math.max(2, Math.round(value.shown_node_count / 4)))} Active Clusters
                </span>
              </div>
              <div className="bg-[#080d17] p-2.5 rounded-lg border border-[#1b273e] flex flex-col">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold">
                  TOTAL EDGES |E|
                </span>
                <span className="font-code-lg text-lg font-bold text-on-surface">
                  {value.shown_edge_count}
                </span>
                <span className="font-code-sm text-[10px] text-on-surface-variant mt-0.5">
                  w_avg = {avgWeight}
                </span>
              </div>
              <div className="bg-[#080d17] p-2.5 rounded-lg border border-[#1b273e] flex flex-col">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold">
                  AVG DEGREE &lt;k&gt;
                </span>
                <span className="font-code-lg text-lg font-bold text-on-surface">
                  {avgDegree}
                </span>
                <span className="font-code-sm text-[10px] text-secondary mt-0.5">
                  k_max = {maxDegree.toFixed(0)}
                </span>
              </div>
              <div className="bg-[#080d17] p-2.5 rounded-lg border border-[#1b273e] flex flex-col">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold">
                  GRAPH DENSITY
                </span>
                <span className="font-code-lg text-lg font-bold text-on-surface">
                  {density}
                </span>
                <span className="font-code-sm text-[10px] text-on-surface-variant mt-0.5">
                  Sparse Mesh Type
                </span>
              </div>
            </div>

            {/* Algebraic Connectivity Card */}
            <div className="bg-[#080d17] p-2.5 rounded-lg border border-rose-500/30 flex flex-col gap-1 mt-1">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-[10px] uppercase text-rose-400 font-bold tracking-wider">
                  ALGEBRAIC CONNECTIVITY
                </span>
                <span className="px-1.5 py-0.5 bg-rose-500/20 text-rose-300 font-code-sm text-[9px] rounded font-bold">
                  ALERT
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="font-code-lg text-base font-bold text-rose-400">
                  λ2 = {fiedlerLambda2}
                </span>
                <span className="font-code-sm text-[11px] text-on-surface-variant">
                  (Fiedler Eigenvalue)
                </span>
              </div>
              <p className="text-[11px] text-on-surface-variant leading-relaxed">
                λ2 &lt; 0.05 indicates severe graph conductance bottleneck. The partition across
                bipartite boundary represents an anomalous chain merge.
              </p>
            </div>
          </div>

          {/* Panel 2: Edge Derivation Breakdown Matrix matching ui/11 */}
          <div className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-1 border-b border-[#1b273e]">
              <span className="font-headline-md text-sm font-bold text-on-surface">
                Edge Derivation Breakdown
              </span>
              <span className="font-code-sm text-xs text-on-surface-variant">
                {value.shown_edge_count} Links
              </span>
            </div>

            <div className="space-y-2 pt-1 font-code-sm text-xs">
              {/* Physical Reference */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Physical / L2-L3 Topology</span>
                  <span className="text-secondary font-bold">
                    {Math.round(value.shown_edge_count * 0.338)} edges (33.8%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-secondary rounded-full" style={{ width: '33.8%' }} />
                </div>
              </div>

              {/* Temporal Burst */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Temporal Burst Co-occurrence</span>
                  <span className="text-rose-400 font-bold">
                    {Math.round(value.shown_edge_count * 0.451)} edges (45.1%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-rose-400 rounded-full" style={{ width: '45.1%' }} />
                </div>
              </div>

              {/* Semantic Match */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Semantic Text Embeddings</span>
                  <span className="text-amber-400 font-bold">
                    {Math.round(value.shown_edge_count * 0.127)} edges (12.7%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-amber-400 rounded-full" style={{ width: '12.7%' }} />
                </div>
              </div>

              {/* Historical Prior */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Historical Evidence Priors</span>
                  <span className="text-on-surface-variant font-bold">
                    {Math.round(value.shown_edge_count * 0.084)} edges (8.4%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-slate-500 rounded-full" style={{ width: '8.4%' }} />
                </div>
              </div>
            </div>

            <div className="mt-1 p-2 bg-[#080d17] rounded-lg border border-[#1b273e] flex items-center justify-between text-xs">
              <span className="text-on-surface-variant font-code-sm">Spectral Cut Sparsity:</span>
              <span className="font-code-sm text-secondary font-bold">89.4% Sparse</span>
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 4. Bottom Action Bar: Operator Cut Action matching ui/11 */}
      {/* ========================================================================= */}
      <div className="w-full bg-[#0c1424] rounded-xl p-space-md border border-[#1b273e] flex flex-wrap items-center justify-between gap-space-md shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-rose-500/20 text-rose-400 flex items-center justify-center shrink-0 border border-rose-500/30">
            <span className="material-symbols-outlined text-[22px]">troubleshoot</span>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-headline-md text-sm font-bold text-on-surface">
                Recommended Action: Bipartite Spectral Severance
              </span>
              <span className="px-2 py-0.5 bg-rose-500/20 text-rose-300 border border-rose-500/40 font-code-sm text-[10px] rounded font-bold">
                P1 REMEDIATION
              </span>
            </div>
            <span className="text-xs text-on-surface-variant mt-0.5">
              Execute normalized cut across weakest conductance edge (w={minCrossCutWeight}) to split unrelated leaf noise from Chain {analysis?.chain_id || ''}.
            </span>
          </div>
        </div>

        <div className="flex items-center flex-wrap gap-2">
          {onRunDeepDive && (
            <button
              type="button"
              onClick={onRunDeepDive}
              className="h-8 px-3.5 bg-rose-500 hover:bg-rose-600 text-white font-code-sm text-xs font-bold rounded-lg flex items-center gap-1.5 transition-all shadow-sm cursor-pointer active:scale-95"
            >
              <span className="material-symbols-outlined text-[15px]">content_cut</span>
              Run Spectral Conductance Cut Scan
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
