import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AIAdvisorPanel } from './AIAdvisorPanel'
import { shouldForceCohesionRefresh } from './api'
import type { CohesionNarrativeView } from './types'

const cohesion: CohesionNarrativeView = {
  chain_id: 'CHAIN-VN-001',
  narrative: 'Chuỗi có mẫu liên tầng: cảnh báo giao thức xuất hiện trước, sau đó mới có cảnh báo quang trên thiết bị kế cận.',
  model: 'DETERMINISTIC_EVIDENCE',
  provider_status: 'NOT_CONFIGURED',
  context: {
    chain: { chain_id: 'CHAIN-VN-001', alarm_count: 10, duration_seconds: 30, is_singleton: false },
    alarm_summary: { top_alarm_types: [['Link Down', 10]], network_classes: [], device_types: [], devices: ['R1', 'R2'] },
    why: { strong_views: [], partial_views: [], top_descriptors: [] },
    topology: {
      mapped: 10,
      total: 10,
      mapped_device_count: 2,
      total_device_count: 2,
      device_mapping_ratio: 1,
      resource_types: [],
      dependency_verified: false,
      connected_pair_count: 1,
      pair_total: 1,
    },
    audit: { status: 'EVALUATED', candidate_cut: false, conductance: 0.4 },
    recommendations: { status: 'NO_RECOMMENDATION', count: 0, split_recommended: false },
    quality_assessment: {
      method: 'HEURISTIC_V1',
      status: 'EVALUATED',
      stars: 4,
      label: 'Khá vững',
      reasons: ['2/2 thiết bị đã nằm trong topology.'],
      available_dimension_count: 5,
    },
  },
}

describe('AIAdvisorPanel', () => {
  it('forces regeneration only for an explicit reload, not a prior review epoch', () => {
    expect(shouldForceCohesionRefresh(0)).toBe(false)
    expect(shouldForceCohesionRefresh(1)).toBe(true)
  })
  it('renders only the short grounded investigation insight', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel chainId="CHAIN-VN-001" initialCohesion={cohesion} />,
    )

    expect(html).toContain('Nhận định điều tra chuỗi')
    expect(html).not.toContain('Chuỗi có mẫu liên tầng')
    expect(html).toContain('Chưa có văn bản AI từ provider')
    expect(html).toContain('AI chưa khả dụng')
    expect(html).not.toContain('Analytical findings')
    expect(html).not.toContain('Khuyến nghị vận hành NOC')
    expect(html).not.toContain('Counterfactual Review')
  })

  it('shows an AI-assisted badge without exposing provider credentials', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialCohesion={{ ...cohesion, model: 'mistral-large', provider_status: 'OK' }}
      />,
    )

    expect(html).toContain('AI hỗ trợ')
    expect(html).toContain('mistral-large')
    expect(html).not.toContain('AI_API_KEY')
  })

  it('keeps the previous insight visible while a review refresh runs', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialCohesion={{ ...cohesion, narrative: 'Output AI hiện tại.', model: 'test-model', provider_status: 'OK' }}
        reviewEpoch={1}
      />,
    )

    expect(html).toContain('Output AI hiện tại.')
    expect(html).not.toContain('Đang tổng hợp nhận định…')
  })
})
