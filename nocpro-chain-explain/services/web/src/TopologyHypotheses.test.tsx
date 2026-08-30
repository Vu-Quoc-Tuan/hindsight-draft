import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TopologyHypotheses } from './TopologyHypotheses'
import type {
  DependencyScopeResult,
  DominatorResult,
  PropagationResult,
  TopologyHypothesesResult,
} from './types'

const provenance = {
  provenance_class: 'EXTERNAL_OPERATIONAL',
  provenance_subtype: 'TOPOLOGY_EXPORT',
  source_kind: 'SYNTHETIC_GROUND_TRUTH',
}

const unavailableDominator: DominatorResult = {
  status: 'UNAVAILABLE',
  reason: 'DIRECTED_TOPOLOGY_UNAVAILABLE',
  semantic: null,
  witness_resource_id: null,
  covered_resource_ids: [],
  source_ref: null,
  relation_type: null,
  ...provenance,
}

const unavailablePropagation: PropagationResult = {
  status: 'UNAVAILABLE',
  reason: 'PROPAGATION_CONFIG_INCOMPLETE',
  semantic: null,
  source_ref: null,
  relation_type: null,
  config_version: null,
  parameter_provenance: {},
  candidate_node_count: 0,
  candidate_edge_count: 0,
  iterations: 0,
  final_l1_distance: null,
  convergence_tolerance: null,
  restart_probability: null,
  seed_policy: null,
  dangling_policy: null,
  node_scores: [],
  hypotheses: [],
  ...provenance,
}

const unavailableScope: DependencyScopeResult = {
  status: 'UNAVAILABLE',
  reason: 'DEPENDENCY_SCOPE_UNAVAILABLE',
  semantic: null,
  witness_resource_id: null,
  source_ref: null,
  relation_type: null,
  observed_resource_count: null,
  scope_resource_count: null,
  intersection_count: null,
  union_count: null,
  observed_coverage: null,
  scope_precision: null,
  jaccard: null,
  missing_resource_count: null,
  extra_resource_count: null,
  max_scope_resources: null,
  max_materialized_resources: null,
  parameter_provenance: {},
  resource_details: {
    status: 'UNAVAILABLE',
    reason: 'DEPENDENCY_SCOPE_UNAVAILABLE',
    missing_resources: null,
    extra_resources: null,
  },
  ...provenance,
}

const unavailableTopology: TopologyHypothesesResult = {
  dominator: unavailableDominator,
  propagation: unavailablePropagation,
  dependency_scope: unavailableScope,
}

const availableTopology: TopologyHypothesesResult = {
  dominator: {
    ...unavailableDominator,
    status: 'AVAILABLE',
    reason: null,
    semantic: 'UNAVOIDABLE_DEPENDENCY',
    witness_resource_id: 'resource-a',
    covered_resource_ids: ['resource-a', 'resource-b'],
    source_ref: 'topology-v1',
    relation_type: 'DIRECTED_DEPENDENCY',
  },
  propagation: {
    ...unavailablePropagation,
    status: 'AVAILABLE',
    reason: null,
    semantic: 'PROPAGATION_HYPOTHESIS',
    source_ref: 'topology-v1',
    relation_type: 'DIRECTED_DEPENDENCY',
    config_version: 'propagation-v1',
    candidate_node_count: 2,
    candidate_edge_count: 1,
    iterations: 7,
    final_l1_distance: 0.0000007,
    convergence_tolerance: 0.000001,
    restart_probability: 0.2,
    seed_policy: 'ALL_SOURCE_NODES_UNIFORM',
    dangling_policy: 'REDISTRIBUTE_TO_RESTART',
    node_scores: [{ alarm_id: 'alarm-a', score: 0.62 }],
    hypotheses: [{
      source_alarm_id: 'alarm-a',
      target_alarm_id: 'alarm-b',
      score: 0.31,
      transition_probability: 1,
      temporal_delta_seconds: 3,
    }],
  },
  dependency_scope: {
    ...unavailableScope,
    status: 'AVAILABLE',
    reason: null,
    semantic: 'DEPENDENCY_SCOPE_OVERLAP_SIGNAL',
    witness_resource_id: 'resource-a',
    source_ref: 'topology-v1',
    relation_type: 'DIRECTED_DEPENDENCY',
    observed_resource_count: 3,
    scope_resource_count: 4,
    intersection_count: 2,
    union_count: 5,
    observed_coverage: 0.6667,
    scope_precision: 0.5,
    jaccard: 0.4,
    missing_resource_count: 1,
    extra_resource_count: 2,
    max_scope_resources: 100,
    max_materialized_resources: 100,
    resource_details: {
      status: 'AVAILABLE',
      reason: null,
      missing_resources: ['resource-c'],
      extra_resources: ['resource-d', 'resource-e'],
    },
  },
}

function markup(topology_hypotheses: TopologyHypothesesResult) {
  return renderToStaticMarkup(<TopologyHypotheses topology_hypotheses={topology_hypotheses} />)
}

describe('TopologyHypotheses', () => {
  it('renders the three fail-closed status cards and stable reasons', () => {
    const html = markup(unavailableTopology)

    expect(html).toContain('Topology hypotheses')
    expect(html).toContain('Unavoidable dependency annotation')
    expect(html).toContain('Propagation hypothesis score')
    expect(html).toContain('Dependency scope overlap signal')
    expect(html.match(/>UNAVAILABLE</g)).toHaveLength(3)
    expect(html).toContain('DIRECTED_TOPOLOGY_UNAVAILABLE')
    expect(html).toContain('PROPAGATION_CONFIG_INCOMPLETE')
    expect(html).toContain('DEPENDENCY_SCOPE_UNAVAILABLE')
  })

  it('separates stationary node mass from edge propagation flow and shows diagnostics', () => {
    const html = markup(availableTopology)

    expect(html).toContain('AVAILABLE')
    expect(html).toContain('Node stationary mass')
    expect(html).toContain('alarm-a')
    expect(html).toContain('Edge propagation flow')
    expect(html).toContain('alarm-a → alarm-b')
    expect(html).toContain('candidate edges')
    expect(html).toContain('0.0000007')
    expect(html).toContain('ALL_SOURCE_NODES_UNIFORM')
    expect(html).toContain('REDISTRIBUTE_TO_RESTART')
  })

  it('keeps exact scope aggregates while hiding unavailable detail lists', () => {
    const topology = {
      ...availableTopology,
      dependency_scope: {
        ...availableTopology.dependency_scope,
        resource_details: {
          status: 'UNAVAILABLE',
          reason: 'MATERIALIZATION_LIMIT_EXCEEDED',
          missing_resources: null,
          extra_resources: null,
        },
      },
    } satisfies TopologyHypothesesResult
    const html = markup(topology)

    expect(html).toContain('66.67%')
    expect(html).toContain('50%')
    expect(html).toContain('MATERIALIZATION_LIMIT_EXCEEDED')
    expect(html).not.toContain('topology-resource-list')
    expect(html).not.toContain('missing resources</')
    expect(html).not.toContain('extra resources</')
  })

  it('renders complete resource lists only when detail materialization is available', () => {
    const html = markup(availableTopology)

    expect(html).toContain('topology-resource-list')
    expect(html).toContain('Missing resources')
    expect(html).toContain('Extra resources')
    expect(html).toContain('resource-c')
    expect(html).toContain('resource-d')
  })

  it('does not introduce causal or root-cause claims', () => {
    const html = markup(availableTopology).toLowerCase()

    expect(html).not.toContain('caused')
    expect(html).not.toContain('root cause probability')
    expect(html).not.toContain('causal confidence')
  })
})
