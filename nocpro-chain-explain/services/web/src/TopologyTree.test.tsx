import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TopologyTree, type TopologyTreePayload } from './TopologyTree'

const itProjection: TopologyTreePayload = {
  status: 'AVAILABLE',
  profile: 'IT_SERVICES',
  topology_kind: 'DIRECTED_SOURCE_RELATIONS',
  direction_kind: 'SOURCE_RELATION',
  dependency_semantics: 'UNVERIFIED',
  topology: {
    availability: 'AVAILABLE', relation_model: 'DIRECTED_SOURCE_RELATIONS', direction_kind: 'SOURCE_RELATION',
    dependency_semantics: 'UNVERIFIED', navigation_mapping: 'PARTIAL_SOURCE_FIELD_EXACT', alarm_resource_mapping: 'UNAVAILABLE',
  },
  source_version: 'sha256:fixture',
  semantic_notice: 'This relation-tree projection is for navigation. It does not imply dependency, causality, ownership, or propagation direction.',
  tree: {
    resource_id: 'it:service:s1', resource_type: 'SERVICE', display_name: 'Billing', relation_type: null, source_table: null,
    hidden_child_count: 0, reference_kind: null, linked_parent_count: 0,
    children: [{
      resource_id: 'it:module:m1', resource_type: 'MODULE', display_name: 'API', relation_type: 'SERVICE_HAS_MODULE', source_table: 'service_module_server.csv',
      hidden_child_count: 0, reference_kind: null, linked_parent_count: 0,
      children: [{
        resource_id: 'it:service:s1', resource_type: 'SERVICE', display_name: 'Billing', relation_type: 'DATABASE_LINKS_SERVICE', source_table: 'database.csv',
        hidden_child_count: 0, reference_kind: 'CYCLE', linked_parent_count: 0, children: [],
      }],
    }],
  },
}

describe('TopologyTree', () => {
  it('labels directed IT data as a relation-tree projection instead of dependency', () => {
    const html = renderToStaticMarkup(<TopologyTree payload={itProjection} />)
    expect(html).toContain('Relation Tree Projection')
    expect(html).toContain('does not imply dependency, causality, ownership, or propagation direction')
    expect(html).not.toContain('Root cause')
  })

  it('renders a cycle as a reference and not another expandable branch', () => {
    const html = renderToStaticMarkup(<TopologyTree payload={itProjection} />)
    expect(html).toContain('Linked to Billing')
    expect(html).toContain('Cycle reference')
    expect(html).toContain('data-resource-id="it:service:s1"')
  })

  it('shows an explicit unavailable state rather than an empty graph', () => {
    const html = renderToStaticMarkup(<TopologyTree payload={{ status: 'UNAVAILABLE', reason: 'TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE', profile: 'ALARM_ONLY', topology_kind: 'UNAVAILABLE' }} />)
    expect(html).toContain('Topology unavailable')
    expect(html).toContain('TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE')
  })
})
