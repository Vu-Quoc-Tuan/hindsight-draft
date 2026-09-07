import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AuditGraphVisualization } from './components/AuditGraphVisualization'
import type { AuditVisualization } from './types'

const base: AuditVisualization = {
  status: 'AVAILABLE',
  reason: null,
  projection_version: 'audit-visualization-v1',
  selection_strategy: 'BEST_CUT_BALANCED_WEIGHTED_DEGREE_V1',
  max_nodes: 80,
  max_edges: 160,
  total_node_count: 2,
  shown_node_count: 2,
  hidden_node_count: 0,
  total_edge_count: 1,
  shown_edge_count: 1,
  hidden_edge_count: 0,
  truncated: false,
  nodes: [
    { alarm_id: 'A-1', weighted_degree: 0.8, cut_side: 'A', structural_role: 'NON_CONNECTOR' },
    { alarm_id: 'B-1', weighted_degree: 0.8, cut_side: 'B', structural_role: 'CONNECTOR' },
  ],
  edges: [
    { source_alarm_id: 'A-1', target_alarm_id: 'B-1', weight: 0.8, supporting_groups: ['entity'], crosses_best_cut: true },
  ],
}

describe('AuditGraphVisualization', () => {
  it('renders the persisted best-cut projection and accessible evidence details', () => {
    const html = renderToStaticMarkup(<AuditGraphVisualization value={base} />)

    expect(html).toContain('Audit graph with 2 nodes and 1 edges')
    expect(html).toContain('CUT A')
    expect(html).toContain('CUT B')
    expect(html).toContain('A-1 ↔ B-1; weight 0.800; entity')
    expect(html).toContain('crosses best cut')
    expect(html).not.toMatch(/root cause|caused by|complete graph/i)
  })

  it('uses the no-cut grid and supports an available zero-edge graph', () => {
    const value: AuditVisualization = {
      ...base,
      total_edge_count: 0,
      shown_edge_count: 0,
      nodes: base.nodes.map(node => ({ ...node, cut_side: 'NONE' as const })),
      edges: [],
    }
    const html = renderToStaticMarkup(<AuditGraphVisualization value={value} />)

    expect(html).toContain('2 / 2 nodes')
    expect(html).toContain('0 / 0 edges')
    expect(html).not.toContain('CUT A')
    expect(html).toContain('<svg')
  })

  it('reports projection truncation without claiming omitted graph structure', () => {
    const value: AuditVisualization = {
      ...base,
      total_node_count: 20,
      hidden_node_count: 18,
      total_edge_count: 30,
      hidden_edge_count: 29,
      truncated: true,
    }
    const html = renderToStaticMarkup(<AuditGraphVisualization value={value} />)

    expect(html).toContain('18 nodes and 29 edges hidden by display bounds')
    expect(html).not.toMatch(/complete graph/i)
  })

  it('keeps unavailable distinct from an available graph with zero edges', () => {
    const value: AuditVisualization = {
      ...base,
      status: 'UNAVAILABLE',
      reason: 'AUDIT_ARTIFACT_NOT_AVAILABLE',
      shown_node_count: 0,
      hidden_node_count: 2,
      shown_edge_count: 0,
      hidden_edge_count: 1,
      truncated: true,
      nodes: [],
      edges: [],
    }
    const html = renderToStaticMarkup(<AuditGraphVisualization value={value} />)

    expect(html).toContain('UNAVAILABLE · AUDIT_ARTIFACT_NOT_AVAILABLE')
    expect(html).not.toContain('<svg')
  })
})
