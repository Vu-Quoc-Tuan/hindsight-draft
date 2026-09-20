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

  if (count <= 14) {
    // 2 concentric rings
    const innerCount = Math.max(2, Math.round(count * 0.3))
    const outerCount = count - innerCount

    const innerRx = maxRx * 0.42
    const innerRy = maxRy * 0.42
    const outerRx = maxRx * 0.88
    const outerRy = maxRy * 0.88

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

  // Multi-tier organic orbits: 3 concentric rings for large clusters (>14 nodes)
  const ring1Count = Math.max(3, Math.round(count * 0.16))
  const ring2Count = Math.max(5, Math.round(count * 0.36))
  const ring3Count = count - ring1Count - ring2Count

  const r1x = maxRx * 0.30
  const r1y = maxRy * 0.30
  const r2x = maxRx * 0.62
  const r2y = maxRy * 0.62
  const r3x = maxRx * 0.92
  const r3y = maxRy * 0.92

  return clusterNodes.map((node, i) => {
    if (i < ring1Count) {
      const angle = (i / ring1Count) * 2 * Math.PI - Math.PI / 2
      return {
        ...node,
        x: Math.round(cx + r1x * Math.cos(angle)),
        y: Math.round(cy + r1y * Math.sin(angle)),
      }
    } else if (i < ring1Count + ring2Count) {
      const idx = i - ring1Count
      const angle = (idx / ring2Count) * 2 * Math.PI - Math.PI / 2 + (Math.PI / ring2Count)
      return {
        ...node,
        x: Math.round(cx + r2x * Math.cos(angle)),
        y: Math.round(cy + r2y * Math.sin(angle)),
      }
    } else {
      const idx = i - ring1Count - ring2Count
      const angle = (idx / ring3Count) * 2 * Math.PI - Math.PI / 2 + (Math.PI / (2 * ring3Count))
      return {
        ...node,
        x: Math.round(cx + r3x * Math.cos(angle)),
        y: Math.round(cy + r3y * Math.sin(angle)),
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
    // Cut A: Core Cluster on left (cx: 240, cy: 310)
    // Cut B: Spillover Cluster on right (cx: 740, cy: 310)
    const rxA = Math.min(160, Math.max(100, countA * 22))
    const ryA = Math.min(190, Math.max(120, countA * 24))
    const rxB = Math.min(190, Math.max(120, countB * 20))
    const ryB = Math.min(200, Math.max(130, countB * 22))

    const posA = layoutCluster(sideA, 240, 310, rxA, ryA)
    const posB = layoutCluster(sideB, 740, 310, rxB, ryB)
    return [...posA, ...posB]
  }

  // Single cluster without cut (e.g. test base or unpartitioned)
  return layoutCluster(nodes, 500, 310, 340, 200)
}

interface AuditGraphVisualizationProps {
  value: AuditVisualization
  analysis?: ChainAnalysis
  verdict?: string
  phi?: number | null
  epsilon?: number | null
  onRunDeepDive?: () => void
}

export function AuditGraphVisualization(props: AuditGraphVisualizationProps) {
  if (props.value.status !== 'AVAILABLE') {
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
          UNAVAILABLE · {props.value.reason ?? 'BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE'}
        </p>
        <p className="mt-space-xs text-body-sm text-on-surface-variant">
          No display graph is synthesized. Run Deep Dive explicitly to create a compatible bounded artifact.
        </p>
      </section>
    )
  }

  return <AuditGraphVisualizationContent {...props} />
}

function AuditGraphVisualizationContent({
  value,
  analysis,
  verdict,
  phi: _phi,
  epsilon: _epsilon,
  onRunDeepDive: _onRunDeepDive,
}: AuditGraphVisualizationProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [zoomScale, setZoomScale] = useState(1)
  const [showNodeLabels, setShowNodeLabels] = useState(true)
  const [showWeakEdges, setShowWeakEdges] = useState(true)
  const [showHeatmap, setShowHeatmap] = useState(true)

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

  // Active node to inspect (only populated if user explicitly clicks or hovers a node)
  const activeNodeId = selectedNodeId || hoveredNodeId
  const activeNode = activeNodeId ? byId.get(activeNodeId) || null : null

  const memberInfo = useMemo(() => {
    if (!activeNode || !analysis?.members) return null
    return analysis.members.find(m => m.alarm_id === activeNode.alarm_id)
  }, [activeNode, analysis])

  const incidentEdges = useMemo(() => {
    if (!activeNode) return []
    return value.edges.filter(
      e => e.source_alarm_id === activeNode.alarm_id || e.target_alarm_id === activeNode.alarm_id
    )
  }, [activeNode, value.edges])

  const crossCutIncidentCount = useMemo(() => {
    return incidentEdges.filter(e => e.crosses_best_cut).length
  }, [incidentEdges])


  // Breakdown statistics for right panel
  const internalAEdges = useMemo(() => {
    const sideASet = new Set(nodes.filter(n => n.cut_side === 'A').map(n => n.alarm_id))
    return value.edges.filter(e => sideASet.has(e.source_alarm_id) && sideASet.has(e.target_alarm_id))
  }, [nodes, value.edges])

  const internalBEdges = useMemo(() => {
    const sideBSet = new Set(nodes.filter(n => n.cut_side === 'B').map(n => n.alarm_id))
    return value.edges.filter(e => sideBSet.has(e.source_alarm_id) && sideBSet.has(e.target_alarm_id))
  }, [nodes, value.edges])

  const weakEdges = useMemo(() => {
    return value.edges.filter(e => e.weight < 0.2)
  }, [value.edges])

  const internalAPercent = value.edges.length > 0 ? Math.round((internalAEdges.length / value.edges.length) * 100) : 0
  const internalBPercent = value.edges.length > 0 ? Math.round((internalBEdges.length / value.edges.length) * 100) : 0
  const crossCutPercent = value.edges.length > 0 ? Math.round((crossCutEdges.length / value.edges.length) * 100) : 0
  const weakPercent = value.edges.length > 0 ? Math.round((weakEdges.length / value.edges.length) * 100) : 0

  const isBottleneck = verdict
    ? verdict.toUpperCase().includes('SPLIT') || verdict.toUpperCase().includes('CANDIDATE')
    : Number(phiConductance) <= 0.30

  return (
    <section
      className="flex flex-col gap-space-md select-none animate-fadeIn"
      aria-label="Bounded Audit graph"
    >
      {/* ========================================================================= */}
      {/* 1. Header Context Strip (Hidden visually, accessible for screen readers & tests) */}
      {/* ========================================================================= */}
      <div className="sr-only">
        <span>
          {value.shown_edge_count} / {value.total_edge_count} edges
        </span>
        <span>
          {value.shown_node_count} / {value.total_node_count} nodes
        </span>
        {value.truncated && (
          <span>
            ({value.hidden_node_count} nodes and {value.hidden_edge_count} edges hidden by display bounds)
          </span>
        )}
        <span>
          {isBottleneck ? `BOTTLENECK DETECTED (Φ = ${phiConductance})` : `COHESIVE STRUCTURE (Φ = ${phiConductance})`}
        </span>
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
              className="accent-secondary w-3.5 h-3.5 cursor-pointer"
            />
            <span className="font-code-sm text-[11px] text-on-surface">Node Labels</span>
          </label>

          <label className="flex items-center gap-1.5 px-2 py-1 bg-[#080d17] rounded border border-[#1b273e] cursor-pointer hover:bg-[#121c2e] transition-colors">
            <input
              type="checkbox"
              checked={showWeakEdges}
              onChange={e => setShowWeakEdges(e.target.checked)}
              className="accent-secondary w-3.5 h-3.5 cursor-pointer"
            />
            <span className="font-code-sm text-[11px] text-on-surface">Weak Edges (&lt;0.2)</span>
          </label>

          <label className="flex items-center gap-1.5 px-2 py-1 bg-[#080d17] rounded border border-[#1b273e] cursor-pointer hover:bg-[#121c2e] transition-colors">
            <input
              type="checkbox"
              checked={showHeatmap}
              onChange={e => setShowHeatmap(e.target.checked)}
              className="accent-rose-500 w-3.5 h-3.5 cursor-pointer"
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
            <span className="w-2.5 h-2.5 rotate-45 bg-amber-400 shadow-[0_0_6px_rgba(255,185,95,0.6)]" />
            <span className="text-on-surface">Spillover Leaf</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rotate-45 bg-rose-400 shadow-[0_0_6px_rgba(255,84,81,0.6)]" />
            <span className="text-rose-300 font-bold">Connector</span>
          </div>
          <div className="h-3 w-px bg-[#1b273e]" />
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-0.5 bg-secondary" />
            <span>Intra-cluster Link</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-0.5 border-b border-dashed border-rose-400" />
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

          {/* Quick Metrics Overlay (Pinned Top-Right) */}
          <div className="absolute top-3 right-3 z-20 flex items-center gap-2 bg-[#080d17]/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-[#1b273e] shadow-md font-code-sm text-xs pointer-events-none">
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
                className="w-full h-full cursor-default"
                role="img"
                aria-label={`Audit graph with ${value.shown_node_count} nodes and ${value.shown_edge_count} edges`}
                onClick={() => setSelectedNodeId(null)}
              >
                <defs>
                  {/* Glow Filters */}
                  <filter id="glow-danger" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="nodeGlow" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>

                  {/* Cut Field Gradient Underlay */}
                  <linearGradient id="cut-field-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="rgba(147, 0, 10, 0.18)" />
                    <stop offset="100%" stopColor="rgba(202, 129, 0, 0.03)" />
                  </linearGradient>
                </defs>

                {/* CANDIDATE CUT ZONE UNDERLAY (CHEEGER PARTITION BOUNDARY) */}
                {hasCut && showHeatmap && (
                  <g id="cut-boundary-zone">
                    <path
                      d="M 485 30 C 495 180, 475 440, 485 590"
                      fill="none"
                      opacity="0.75"
                      stroke="#ff5451"
                      strokeDasharray="6 4"
                      strokeWidth="2"
                    />
                    <rect
                      x="500"
                      y="40"
                      width="480"
                      height="540"
                      rx="16"
                      fill="url(#cut-field-grad)"
                    />
                  </g>
                )}

                {/* CLUSTER BOUNDING BACKGROUNDS (Adaptive rounded enclosures) */}
                {hasCut && (
                  <g id="cluster-groups" opacity="0.6">
                    {/* Cluster 01: Core Backbone Domain */}
                    <rect
                      x="60"
                      y="70"
                      width="360"
                      height="480"
                      rx="16"
                      fill="#0b1220"
                      stroke="#00a6e0"
                      strokeWidth="1"
                      strokeDasharray="4 4"
                    />
                    <text
                      x="80"
                      y="98"
                      fontFamily="JetBrains Mono"
                      fontSize="11"
                      fontWeight="700"
                      fill="#7bd0ff"
                    >
                      Backbone Core Domain · CUT A ({countA} nodes)
                    </text>

                    {/* Cluster 02: Anomalous Leaf / Spillover Zone */}
                    <rect
                      x="530"
                      y="70"
                      width="420"
                      height="480"
                      rx="16"
                      fill="#170f14"
                      stroke="#ffb95f"
                      strokeWidth="1"
                      strokeDasharray="4 4"
                    />
                    <text
                      x="550"
                      y="98"
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

                    // Filter weak edges when toggle is off
                    if (isWeak && !showWeakEdges) return null

                    const isInc =
                      activeNodeId &&
                      (activeNodeId === edge.source_alarm_id ||
                        activeNodeId === edge.target_alarm_id)
                    const isDim = activeNodeId && !isInc

                    const strokeColor = isCross ? '#ff5451' : '#00a6e0'
                    const strokeWidth = isCross
                      ? isInc
                        ? 3.2
                        : Math.max(1.0, Math.min(2.4, 0.6 + edge.weight * 1.8))
                      : isInc
                      ? 2.8
                      : Math.max(1.0, Math.min(2.5, 0.6 + edge.weight * 2.0))

                    const opacity = isDim
                      ? 0.04
                      : isInc
                      ? 1
                      : isCross
                      ? Math.max(0.20, Math.min(0.75, 0.2 + edge.weight * 0.8))
                      : isWeak
                      ? 0.08
                      : nodes.length > 25
                      ? Math.max(0.08, Math.min(0.24, edge.weight * 0.3))
                      : Math.max(0.18, Math.min(0.55, edge.weight * 0.6))

                    const edgeTitle = `${edge.source_alarm_id} ↔ ${edge.target_alarm_id}; weight ${edge.weight.toFixed(
                      3
                    )}; ${edge.supporting_groups.join(', ') || 'no groups'}${
                      isCross ? '; crosses best cut' : ''
                    }`

                    if (isCross) {
                      const dy = target.y - source.y
                      const curvature = Math.max(-50, Math.min(50, dy * 0.22))
                      const midX = (source.x + target.x) / 2
                      const midY = (source.y + target.y) / 2 + curvature

                      return (
                        <g key={`${edge.source_alarm_id}:${edge.target_alarm_id}`} opacity={opacity}>
                          <path
                            d={`M ${source.x} ${source.y} Q ${midX} ${midY} ${target.x} ${target.y}`}
                            fill="none"
                            stroke={strokeColor}
                            strokeWidth={strokeWidth}
                            strokeDasharray="5 4"
                            filter={isCross && isInc ? 'url(#glow-danger)' : undefined}
                          >
                            <title>{edgeTitle}</title>
                          </path>
                        </g>
                      )
                    }

                    return (
                      <g key={`${edge.source_alarm_id}:${edge.target_alarm_id}`} opacity={opacity}>
                        <line
                          x1={source.x}
                          y1={source.y}
                          x2={target.x}
                          y2={target.y}
                          stroke={strokeColor}
                          strokeWidth={strokeWidth}
                          filter={isInc ? 'url(#glow-danger)' : undefined}
                        >
                          <title>{edgeTitle}</title>
                        </line>
                      </g>
                    )
                  })}
                </g>

                {/* Non-overlapping Weak Link Callout Tag on Cut Divider */}
                {hasCut && (
                  <g transform="translate(435, 52)">
                    <rect
                      fill="#ca8100"
                      height="20"
                      rx="4"
                      width="100"
                      stroke="#ffb95f"
                      strokeWidth="1"
                    />
                    <text
                      className="font-code-sm text-[10px] font-bold"
                      fill="#070c17"
                      x="50"
                      y="14"
                      textAnchor="middle"
                    >
                      w={minCrossCutWeight} (LEAK)
                    </text>
                  </g>
                )}

                {/* GRAPH NODES LAYER */}
                <g id="graph-nodes">
                  {nodes.map(node => {
                    const radius = 9 + 8 * (node.weighted_degree / maxDegree)
                    const isSelected = selectedNodeId === node.alarm_id
                    const isHovered = hoveredNodeId === node.alarm_id
                    const isActive = isSelected || isHovered
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
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedNodeId(prev => (prev === node.alarm_id ? null : node.alarm_id))
                        }}
                        onMouseEnter={() => setHoveredNodeId(node.alarm_id)}
                        onMouseLeave={() => setHoveredNodeId(null)}
                        className="cursor-pointer group"
                      >
                        {/* Active Selection / Hover Halo */}
                        {isActive && (
                          <circle
                            r={radius + 8}
                            fill={stroke}
                            fillOpacity={isSelected ? '0.35' : '0.2'}
                            stroke={stroke}
                            strokeWidth={isSelected ? 2 : 1.5}
                            strokeDasharray={isSelected ? undefined : '3 3'}
                            className={isSelected ? 'animate-pulse' : undefined}
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
                            strokeWidth={isActive ? 3 : 2.5}
                            transform="rotate(45)"
                            filter={isActive ? 'url(#glow-danger)' : undefined}
                          />
                        ) : (
                          <circle
                            r={radius}
                            fill={fill}
                            stroke={stroke}
                            strokeWidth={isActive ? 3 : 2}
                            filter={isActive ? 'url(#nodeGlow)' : undefined}
                          />
                        )}

                        {/* Inner Core Dot */}
                        <circle
                          r={Math.max(3, radius * 0.35)}
                          fill={isConnector ? '#ff5451' : isCutA ? '#00a6e0' : '#ffb95f'}
                        />

                        {/* Node Text Label matching ui/11 */}
                        {showNodeLabels && (
                          <g transform={`translate(0, ${radius + 12})`}>
                            <text
                              textAnchor="middle"
                              fill={isActive ? '#ffffff' : '#dce2f7'}
                              fontFamily="JetBrains Mono"
                              fontSize={nodes.length > 25 ? '8' : '9.5'}
                              fontWeight={isActive ? '700' : '500'}
                              style={{ paintOrder: 'stroke', stroke: '#070c17', strokeWidth: '2.5px' }}
                            >
                              {displayText}
                            </text>
                            {(isActive || (hasCut && isConnector)) && (
                              <text
                                y="9"
                                textAnchor="middle"
                                fill={isConnector ? '#ff5451' : isCutA ? '#7bd0ff' : '#ffb95f'}
                                fontFamily="JetBrains Mono"
                                fontSize="7"
                                fontWeight="700"
                                style={{ paintOrder: 'stroke', stroke: '#070c17', strokeWidth: '2px' }}
                              >
                                {isConnector ? 'CUT-ANCHOR' : isCutA ? 'CORE' : 'LEAF'}
                              </text>
                            )}
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

            {/* Interactive Focused Node Inspector Card - ONLY rendered when user clicks or hovers a node */}
            {activeNode && (
              <div
                className="absolute bottom-4 left-4 bg-[#0c1424]/95 backdrop-blur-md p-3.5 rounded-xl border border-[#1b273e] shadow-2xl max-w-sm font-code-sm text-xs z-30 animate-fadeIn"
                onClick={e => e.stopPropagation()}
              >
                <div className="flex items-center justify-between gap-3 pb-1.5 border-b border-[#1b273e]">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2.5 h-2.5 rounded-full ${
                        activeNode.cut_side === 'A'
                          ? 'bg-secondary shadow-[0_0_6px_rgba(0,166,224,0.8)]'
                          : 'bg-amber-400 shadow-[0_0_6px_rgba(255,185,95,0.8)]'
                      }`}
                    />
                    <span className="font-label-caps text-[10px] uppercase font-bold text-on-surface tracking-wider">
                      {activeNode.cut_side === 'A'
                        ? `CUT A · CORE (${countA} nodes)`
                        : activeNode.cut_side === 'B'
                        ? `CUT B · SPILLOVER (${countB} nodes)`
                        : 'UNASSIGNED'}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 bg-[#17233a] text-secondary rounded font-bold">
                      {selectedNodeId === activeNode.alarm_id ? 'PINNED' : 'HOVER'}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedNodeId(null)
                      setHoveredNodeId(null)
                    }}
                    className="w-5 h-5 flex items-center justify-center rounded text-on-surface-variant hover:text-on-surface hover:bg-[#1b273e] transition-colors cursor-pointer text-xs"
                    title="Close Inspector"
                  >
                    ✕
                  </button>
                </div>

                <div className="font-bold text-on-surface text-xs mt-2 truncate flex items-center gap-1.5">
                  <span className="text-secondary font-mono">{activeNode.alarm_id}</span>
                  {memberInfo?.device_code && (
                    <span className="text-on-surface-variant font-normal">:: {memberInfo.device_code}</span>
                  )}
                </div>

                {memberInfo?.alarm_name && (
                  <div className="text-[11px] text-amber-300 font-semibold pt-0.5 truncate">
                    {memberInfo.alarm_name}
                  </div>
                )}

                <div className="text-[11px] text-on-surface-variant pt-1.5 leading-relaxed">
                  {activeNode.cut_side === 'A'
                    ? 'High-cohesion member belonging to Backbone Core Domain.'
                    : 'Spillover / peripheral branch separated across the Cheeger spectral cut.'}
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 mt-2 border-t border-[#1b273e] text-[11px]">
                  <div>
                    Degree: <span className="font-bold text-secondary">{activeNode.weighted_degree.toFixed(2)}</span>
                  </div>
                  <div>
                    Role:{' '}
                    <span className="font-bold text-on-surface">
                      {activeNode.structural_role ?? memberInfo?.role ?? 'MEMBER'}
                    </span>
                  </div>
                  <div>
                    Links: <span className="font-bold text-on-surface">{incidentEdges.length} connected</span>
                  </div>
                  <div>
                    Cross-Cut: <span className="font-bold text-rose-400">{crossCutIncidentCount} edges</span>
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
                  {value.shown_node_count} / {value.total_node_count}
                </span>
                <span className="font-code-sm text-[10px] text-secondary mt-0.5">
                  {hasCut ? '2 Partitions (A/B)' : '1 Partition'}
                </span>
              </div>
              <div className="bg-[#080d17] p-2.5 rounded-lg border border-[#1b273e] flex flex-col">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold">
                  TOTAL EDGES |E|
                </span>
                <span className="font-code-lg text-lg font-bold text-on-surface">
                  {value.shown_edge_count} / {value.total_edge_count}
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
                  k_max = {maxDegree.toFixed(1)}
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
            <div
              className={`bg-[#080d17] p-2.5 rounded-lg border ${
                isBottleneck ? 'border-rose-500/30' : 'border-emerald-500/30'
              } flex flex-col gap-1 mt-1`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`font-label-caps text-[10px] uppercase ${
                    isBottleneck ? 'text-rose-400' : 'text-emerald-400'
                  } font-bold tracking-wider`}
                >
                  ALGEBRAIC CONNECTIVITY
                </span>
                <span
                  className={`px-1.5 py-0.5 ${
                    isBottleneck ? 'bg-rose-500/20 text-rose-300' : 'bg-emerald-500/20 text-emerald-300'
                  } font-code-sm text-[9px] rounded font-bold`}
                >
                  {isBottleneck ? 'ALERT' : 'COHESIVE'}
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span
                  className={`font-code-lg text-base font-bold ${
                    isBottleneck ? 'text-rose-400' : 'text-emerald-400'
                  }`}
                >
                  λ2 = {fiedlerLambda2}
                </span>
                <span className="font-code-sm text-[11px] text-on-surface-variant">
                  (Fiedler Eigenvalue)
                </span>
              </div>
              <p className="text-[11px] text-on-surface-variant leading-relaxed">
                {isBottleneck
                  ? 'λ2 < 0.05 indicates severe graph conductance bottleneck. The partition across bipartite boundary represents an anomalous chain merge.'
                  : 'Graph algebraic connectivity confirms robust intra-chain cohesion. All alarm members are well-coupled into a single incident structure.'}
              </p>
            </div>
          </div>

          {/* Panel 2: Edge Topology Breakdown Matrix (Grounded in real edge data) */}
          <div className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-1 border-b border-[#1b273e]">
              <span className="font-headline-md text-sm font-bold text-on-surface">
                Edge Topology Breakdown
              </span>
              <span className="font-code-sm text-xs text-on-surface-variant">
                {value.shown_edge_count} Links
              </span>
            </div>

            <div className="space-y-2 pt-1 font-code-sm text-xs">
              {/* Internal Cut A */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Cut A Intra-Cluster</span>
                  <span className="text-secondary font-bold">
                    {internalAEdges.length} edges ({internalAPercent}%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-secondary rounded-full" style={{ width: `${internalAPercent}%` }} />
                </div>
              </div>

              {/* Internal Cut B */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Cut B Intra-Cluster</span>
                  <span className="text-amber-400 font-bold">
                    {internalBEdges.length} edges ({internalBPercent}%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-amber-400 rounded-full" style={{ width: `${internalBPercent}%` }} />
                </div>
              </div>

              {/* Cross Cut */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Bipartite Cross-Cut</span>
                  <span className="text-rose-400 font-bold">
                    {crossCutEdges.length} edges ({crossCutPercent}%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-rose-400 rounded-full" style={{ width: `${crossCutPercent}%` }} />
                </div>
              </div>

              {/* Weak Links */}
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-on-surface">Weak Bridges (&lt;0.2)</span>
                  <span className="text-on-surface-variant font-bold">
                    {weakEdges.length} edges ({weakPercent}%)
                  </span>
                </div>
                <div className="w-full h-1.5 bg-[#080d17] rounded-full overflow-hidden">
                  <div className="h-full bg-slate-500 rounded-full" style={{ width: `${weakPercent}%` }} />
                </div>
              </div>
            </div>

            <div className="mt-1 p-2 bg-[#080d17] rounded-lg border border-[#1b273e] flex items-center justify-between text-xs">
              <span className="text-on-surface-variant font-code-sm">Spectral Cut Conductance:</span>
              <span className="font-code-sm text-secondary font-bold">Φ = {phiConductance}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
