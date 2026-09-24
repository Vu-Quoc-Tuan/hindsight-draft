import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ChainQualityCard, RepresentativeMemberCard, TopologyCoverageCard } from './ChainQualityCards'
import type { CohesionNarrativeView } from '../types'

const context = {
  chain: { chain_id: 'C1', alarm_count: 71, duration_seconds: 30, is_singleton: false },
  alarm_summary: { top_alarm_types: [], network_classes: [], device_types: [], devices: [] },
  why: { strong_views: [], partial_views: [], top_descriptors: [] },
  topology: {
    mapped: 71,
    total: 71,
    mapped_device_count: 7,
    total_device_count: 7,
    device_mapping_ratio: 1,
    resource_types: [],
    dependency_verified: false,
    connected_pair_count: 21,
    pair_total: 21,
  },
  audit: { status: 'EVALUATED', candidate_cut: false, conductance: 0.4 },
  representative_member: {
    status: 'AVAILABLE',
    alarm_id: 'A-CORE',
    alarm_name: 'BGP peer down',
    device_code: 'RTR-01',
    role: 'CORE',
    membership_support: 0.87,
    availability_coverage: 1,
    computable_groups: 5,
    representativeness: 0.72,
    selection_semantic: 'EVIDENCE_REPRESENTATIVE_NOT_ROOT_CAUSE',
  },
  recommendations: { status: 'AVAILABLE', count: 1, split_recommended: true },
  quality_assessment: {
    method: 'HEURISTIC_V1',
    status: 'EVALUATED',
    readiness: 'READY',
    stars: 4,
    label: 'Khá vững',
    reasons: [],
    available_dimension_count: 5,
  },
} satisfies CohesionNarrativeView['context']

describe('chain quality overview cards', () => {
  it('shows distinct-device topology coverage instead of raw alarm coverage', () => {
    const html = renderToStaticMarkup(<TopologyCoverageCard context={context} />)
    expect(html).toContain('Thiết bị trong topology')
    expect(html).toContain('7/7')
    expect(html).toContain('21/21 cặp resource')
  })

  it('shows heuristic stars and the concise counterfactual result', () => {
    const html = renderToStaticMarkup(<ChainQualityCard context={context} />)
    expect(html).toContain('★★★★☆')
    expect(html).toContain('4/5')
    expect(html).toContain('Khá vững')
    expect(html).toContain('Giữ lại 1 phương án tốt hơn')
    expect(html).toContain('HEURISTIC')
    expect(html).not.toContain('Độ tin cậy')
  })

  it('distinguishes a completed locked review from a review that never ran', () => {
    const lockedContext = {
      ...context,
      recommendations: {
        status: 'UNAVAILABLE',
        count: 0,
        split_recommended: false,
        evaluation_completed: true,
        evaluated_count: 9,
        rejected_count: 7,
        reason: 'COUNTERFACTUAL_POLICY_NOT_CALIBRATED',
        calibration_status: 'SYNTHETIC_ONLY',
      },
    } satisfies CohesionNarrativeView['context']

    const html = renderToStaticMarkup(<ChainQualityCard context={lockedContext} />)
    expect(html).toContain('Đã thử 9 PA · 2 PA qua kiểm tra an toàn')
    expect(html).not.toContain('Chưa chạy so sánh phương án')
  })

  it('does not render placeholder stars when readiness is incomplete', () => {
    const partialContext = {
      ...context,
      quality_assessment: {
        method: 'HEURISTIC_V1',
        status: 'UNAVAILABLE',
        readiness: 'PARTIAL',
        stars: null,
        label: 'Chưa đủ dữ liệu để chấm',
        reasons: ['Counterfactual Review chưa hoàn tất đánh giá.'],
        reason_codes: ['REVIEW_NOT_COMPLETED'],
        available_dimension_count: 2,
      },
    } satisfies CohesionNarrativeView['context']

    const html = renderToStaticMarkup(<ChainQualityCard context={partialContext} />)
    expect(html).toContain('Chưa đủ dữ liệu để chấm')
    expect(html).toContain('Counterfactual Review chưa hoàn tất đánh giá.')
    expect(html).not.toContain('☆☆☆☆☆')
  })

  it('links an incomplete readiness reason to only its evidence IDs', () => {
    const evidenceId = `ev1_${'b'.repeat(64)}`
    const partialContext = {
      ...context,
      quality_assessment: {
        method: 'HEURISTIC_V1',
        status: 'UNAVAILABLE',
        readiness: 'PARTIAL',
        stars: null,
        label: 'Chưa đủ dữ liệu để chấm',
        reasons: ['Counterfactual Review chưa hoàn tất đánh giá.'],
        reason_codes: ['REVIEW_NOT_COMPLETED'],
        reason_evidence_ids: { REVIEW_NOT_COMPLETED: [evidenceId] },
        available_dimension_count: 2,
      },
    } satisfies CohesionNarrativeView['context']

    const html = renderToStaticMarkup(
      <ChainQualityCard context={partialContext} onOpenEvidence={() => {}} />,
    )
    expect(html).toContain('Xem evidence của lý do này (1)')
    expect(html).toContain('Mở 1 evidence cho lý do REVIEW_NOT_COMPLETED')
  })

  it('uses a CORE member as an evidence representative without calling it root cause', () => {
    const html = renderToStaticMarkup(<RepresentativeMemberCard context={context} />)
    expect(html).toContain('Thành viên evidence mạnh nhất')
    expect(html).toContain('BGP peer down')
    expect(html).toContain('RTR-01')
    expect(html).toContain('CORE')
    expect(html).toContain('Evidence:')
    expect(html).not.toContain('nguyên nhân gốc')
  })
})
