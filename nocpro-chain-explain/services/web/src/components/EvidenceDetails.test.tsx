import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EvidenceRecordCard } from './EvidenceDetails'
import type { EvidenceRecord } from '../types'

const identity: EvidenceRecord['analysis_identity'] = {
  identity_version: 'analysis-identity-v1',
  snapshot_id: 'snapshot-evidence',
  snapshot_version: '3',
  chain_id: 'C-EVIDENCE',
  topology_version: 'topology-v9',
  analysis_config_version: 'analysis-v2',
  review_config_version: 'review-v4',
  pipeline_version: 'DETERMINISTIC_QUALITY_V6',
  input_fingerprint: 'evidence-fingerprint',
}

function record(overrides: Partial<EvidenceRecord> = {}): EvidenceRecord {
  return {
    evidence_id: `ev1_${'a'.repeat(64)}`,
    analysis_identity: identity,
    kind: 'TOPOLOGY_PATH',
    status: 'AVAILABLE',
    statement_kind: 'DERIVED',
    source_artifact_id: 'inventory-14',
    source_fingerprint: '0123456789abcdef',
    summary: 'Pair WHY A ↔ B: 2 hop trong giới hạn 3 hop; quan hệ cấu trúc, không xác nhận chiều nhân quả.',
    reason_codes: [],
    limitations: ['STRUCTURAL_PATH_IS_NOT_CAUSAL_DIRECTION'],
    path: {
      resource_ids: ['R-A', 'R-X', 'R-B'],
      relation_types: ['IP_ADJACENCY', 'IP_ADJACENCY'],
      hop_count: 2,
      traversal_semantic: 'STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL',
      max_hops: 3,
      topology_version: 'topology-v9',
      mapping_statuses: ['EXACT', 'VERIFIED_ALIAS'],
      analysis_truncated: false,
      direction_policy: 'SOURCE_EDGE_DIRECTION_PRESERVED',
    },
    ...overrides,
  }
}

describe('EvidenceRecordCard', () => {
  it('shows the actual witness, relation per edge, identity source and non-causal semantics', () => {
    const html = renderToStaticMarkup(<EvidenceRecordCard record={record()} />)
    expect(html).toContain('R-A → R-X → R-B')
    expect(html).toContain('2/3 hop')
    expect(html).toContain('Pair WHY Dep_hop, chính sách riêng')
    expect(html).toContain('R-A — <span class="text-cyan-200">IP_ADJACENCY</span> → R-X')
    expect(html).toContain('Alias đã xác minh')
    expect(html).toContain('Tôn trọng chiều cạnh nguồn')
    expect(html).toContain('không tự xác nhận nhân quả')
    expect(html).toContain('Nguồn: inventory-14')
  })

  it('explains unavailable evidence without inventing a path', () => {
    const html = renderToStaticMarkup(<EvidenceRecordCard record={record({
      status: 'UNAVAILABLE',
      summary: 'Pair WHY A ↔ B: Dep_hop chưa có đường topology khả dụng.',
      reason_codes: ['PAIR_TOPOLOGY_PATH_UNAVAILABLE'],
      limitations: ['NO_PATH_WITHIN_BOUND_DOES_NOT_PROVE_GLOBAL_DISCONNECTION'],
      path: null,
    })} />)
    expect(html).toContain('Pair WHY A ↔ B')
    expect(html).toContain('Dep_hop không có đường khả dụng')
    expect(html).toContain('không chứng minh toàn topology bị ngắt')
    expect(html).not.toContain('R-A → R-X → R-B')
  })
})
