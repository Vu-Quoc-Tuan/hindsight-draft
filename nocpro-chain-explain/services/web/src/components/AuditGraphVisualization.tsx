import type { AuditVisualization } from '../types'

type PositionedNode = AuditVisualization['nodes'][number] & { x: number; y: number }

function distribute(
  nodes: AuditVisualization['nodes'],
  xStart: number,
  xEnd: number,
): PositionedNode[] {
  const columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length)))
  const rows = Math.max(1, Math.ceil(nodes.length / columns))
  return nodes.map((node, index) => ({
    ...node,
    x: xStart + ((index % columns) + 0.5) * ((xEnd - xStart) / columns),
    y: 42 + (Math.floor(index / columns) + 0.5) * (276 / rows),
  }))
}

function layoutNodes(nodes: AuditVisualization['nodes']): PositionedNode[] {
  const sideA = nodes.filter(node => node.cut_side === 'A')
  const sideB = nodes.filter(node => node.cut_side === 'B')
  if (sideA.length > 0 && sideB.length > 0) {
    return [...distribute(sideA, 20, 330), ...distribute(sideB, 390, 700)]
  }
  return distribute(nodes, 20, 700)
}

export function AuditGraphVisualization({ value }: { value: AuditVisualization }) {
  if (value.status !== 'AVAILABLE') {
    return (
      <section className="rounded-lg border border-surface-container-highest bg-surface-container p-space-md shadow-sm" aria-label="Audit graph availability">
        <h3 className="font-headline-md text-headline-md font-bold">Audit graph visualization</h3>
        <p className="mt-space-xs break-words font-code-sm text-code-sm text-on-surface-variant">
          UNAVAILABLE · {value.reason ?? 'BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE'}
        </p>
        <p className="mt-space-xs text-body-sm text-on-surface-variant">
          No display graph is synthesized. Run Deep Dive explicitly to create a compatible bounded artifact.
        </p>
      </section>
    )
  }

  const nodes = layoutNodes(value.nodes)
  const byId = new Map(nodes.map(node => [node.alarm_id, node]))
  const hasCut = nodes.some(node => node.cut_side === 'A') && nodes.some(node => node.cut_side === 'B')
  const maxDegree = Math.max(1, ...nodes.map(node => node.weighted_degree))

  return (
    <section className="overflow-hidden rounded-lg border border-surface-container-highest bg-surface-container shadow-sm" aria-label="Bounded Audit graph">
      <div className="flex flex-wrap items-start justify-between gap-space-sm border-b border-surface-container-highest p-space-md">
        <div>
          <h3 className="font-headline-md text-headline-md font-bold">Bounded Audit graph</h3>
          <p className="mt-space-2xs text-body-sm text-on-surface-variant">
            {value.shown_node_count} / {value.total_node_count} nodes · {value.shown_edge_count} / {value.total_edge_count} edges
          </p>
        </div>
        <span className="rounded-full bg-secondary-container px-space-sm py-space-xs font-code-sm text-code-sm text-on-secondary-container">
          {value.projection_version}
        </span>
      </div>

      <div className="overflow-x-auto p-space-sm">
        <svg viewBox="0 0 720 360" className="h-auto min-w-[620px] w-full" role="img" aria-label={`Audit graph with ${value.shown_node_count} nodes and ${value.shown_edge_count} edges`}>
          {hasCut && (
            <>
              <rect x="10" y="18" width="330" height="322" rx="16" className="fill-primary/5 stroke-primary/20" />
              <rect x="380" y="18" width="330" height="322" rx="16" className="fill-secondary/5 stroke-secondary/20" />
              <text x="28" y="38" className="fill-primary text-[12px] font-semibold">CUT A</text>
              <text x="398" y="38" className="fill-secondary text-[12px] font-semibold">CUT B</text>
            </>
          )}
          {value.edges.map(edge => {
            const source = byId.get(edge.source_alarm_id)
            const target = byId.get(edge.target_alarm_id)
            if (!source || !target) return null
            return (
              <line
                key={`${edge.source_alarm_id}:${edge.target_alarm_id}`}
                x1={source.x} y1={source.y} x2={target.x} y2={target.y}
                strokeWidth={Math.max(1, Math.min(5, 1 + edge.weight * 3))}
                className={edge.crosses_best_cut ? 'stroke-error/70' : 'stroke-outline/40'}
              >
                <title>{`${edge.source_alarm_id} ↔ ${edge.target_alarm_id}; weight ${edge.weight.toFixed(3)}; ${edge.supporting_groups.join(', ') || 'no groups'}`}</title>
              </line>
            )
          })}
          {nodes.map(node => {
            const radius = 7 + 8 * (node.weighted_degree / maxDegree)
            return (
              <g key={node.alarm_id} transform={`translate(${node.x} ${node.y})`}>
                <circle
                  r={radius}
                  className={node.structural_role === 'CONNECTOR' ? 'fill-tertiary stroke-on-tertiary' : node.cut_side === 'B' ? 'fill-secondary stroke-on-secondary' : 'fill-primary stroke-on-primary'}
                  strokeWidth="2"
                />
                <text y={radius + 14} textAnchor="middle" className="fill-on-surface text-[11px] font-medium">
                  {node.alarm_id.length > 16 ? `${node.alarm_id.slice(0, 14)}…` : node.alarm_id}
                </text>
                <title>{`${node.alarm_id}; weighted degree ${node.weighted_degree.toFixed(3)}; ${node.structural_role ?? 'role unavailable'}`}</title>
              </g>
            )
          })}
        </svg>
      </div>

      <div className="flex flex-wrap gap-space-md border-t border-surface-container-highest px-space-md py-space-sm text-body-sm text-on-surface-variant">
        {hasCut && <><span>● Cut A</span><span>● Cut B</span><span className="text-error">━ crosses best cut</span></>}
        <span>Node size = weighted degree</span>
        {value.truncated && <strong>{value.hidden_node_count} nodes and {value.hidden_edge_count} edges hidden by display bounds</strong>}
      </div>
    </section>
  )
}
