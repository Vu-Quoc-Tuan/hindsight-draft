import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AIAdvisorPanel } from './AIAdvisorPanel'
import type { AISuggestion, CohesionNarrativeView } from './types'

const mockSuggestion: AISuggestion = {
  chain_id: 'CHAIN-VN-001',
  status: 'AVAILABLE',
  model: 'DETERMINISTIC_EVIDENCE',
  narrative: '### Evidence summary for chain CHAIN-VN-001\n- Analyzed members: 3.\n- Members classified WEAK: ALARM-1.\n> This is a deterministic rendering of persisted analysis facts.',
  grounded_claims: [
    'Chain CHAIN-VN-001 contains 3 analyzed members.',
    '1 member is classified WEAK: ALARM-1.',
  ],
  disclaimer: 'ADR-0024: deterministic evidence only.',
  provider_status: 'NOT_CONFIGURED',
  review_status: 'AVAILABLE',
  recommendation_status: 'NO_CLEAR_ALTERNATIVE',
}

describe('AIAdvisorPanel', () => {
  it('renders deterministic grounded facts with a clear fallback state', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel chainId="CHAIN-VN-001" initialSuggestion={mockSuggestion} />,
    )

    expect(html).toContain('ADR-0024 Grounded Narrative')
    expect(html).toContain('Deterministic fallback')
    expect(html).toContain('Not configured')
    expect(html).toContain('Evidence summary for chain CHAIN-VN-001')
    expect(html).toContain('Analyzed members: 3.')
    expect(html).toContain('Members classified WEAK: ALARM-1.')
    expect(html).toContain('Mệnh đề bằng chứng xác minh (Grounded Claims)')
    expect(html).toContain('Chain CHAIN-VN-001 contains 3 analyzed members.')
    expect(html).toContain('1 member is classified WEAK: ALARM-1.')
    expect(html).toContain('ADR-0024: deterministic evidence only.')
    expect(html).not.toContain('Root-cause')
    expect(html).not.toContain('Thông báo nhà cung cấp LLM')
  })

  it('shows successful server-side AI rendering without exposing credentials', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialSuggestion={{
          ...mockSuggestion,
          model: 'mistral-large',
          provider_status: 'OK',
          narrative: 'Grounded AI-rendered narrative.',
        }}
      />,
    )

    expect(html).toContain('AI-assisted')
    expect(html).toContain('mistral-large')
    expect(html).toContain('Grounded AI-rendered narrative.')
    expect(html).not.toContain('AI_API_KEY')
    expect(html).not.toContain('test-secret')
  })

  it('renders invalid provider configuration as a safe deterministic fallback', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialSuggestion={{
          ...mockSuggestion,
          provider_status: 'INVALID_CONFIGURATION',
        }}
      />,
    )

    expect(html).toContain('Deterministic fallback')
    expect(html).toContain('Invalid provider configuration')
    expect(html).not.toContain('AI_PROVIDER_PROTOCOL')
    expect(html).not.toContain('AI_API_KEY')
  })

  it('renders an uncalibrated safety lock as completed analysis with recommendations locked', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="6913556"
        initialSuggestion={{
          ...mockSuggestion,
          chain_id: '6913556',
          recommendation_status: 'UNAVAILABLE',
          review_reason: 'COUNTERFACTUAL_POLICY_NOT_CALIBRATED',
          narrative:
            '### Tóm tắt bằng chứng cho chuỗi 6913556\n- Số lượng cảnh báo: 26.\n\n### Đề xuất tối ưu hóa chuỗi (Counterfactual)\n- **Chế độ an toàn mặc định (Chính sách Counterfactual chưa hiệu chuẩn trên dữ liệu thực)**: Đã ghi nhận phương án can thiệp thử nghiệm. Tuy nhiên, hệ thống đang tạm khóa đề xuất tự động.\n  - *Vì sao đề xuất này tốt hơn*: Chuỗi hiện tại ghép lỏng lẻo 2 phân cụm.\n  - *Phương án thử nghiệm*: Đề xuất phân tách chuỗi 6913556 thành 2 chuỗi con\n  - *Chỉ số cải thiện*: Min Support: 48.8% → 65.0% (+16.2%).\n> Bản tóm tắt xác định.',
        }}
      />,
    )

    expect(html).toContain('Counterfactual đã phân tích xong')
    expect(html).toContain('đề xuất tự động đang bị khóa')
    expect(html).toContain('COUNTERFACTUAL_POLICY_NOT_CALIBRATED')
    expect(html).not.toContain('Biên Pareto Tối Ưu')
    expect(html).not.toContain('[Xác thực Pareto]:')
  })

  it('renders structured analytical findings with evidence and limitations', () => {
    const cohesion = {
      chain_id: 'CHAIN-VN-001',
      narrative: 'Tóm tắt quan sát.',
      model: 'DETERMINISTIC_EVIDENCE',
      context: {
        chain: { chain_id: 'CHAIN-VN-001', alarm_count: 3, duration_seconds: 30, is_singleton: false },
        alarm_summary: { top_alarm_types: [['Link Down', 2]], network_classes: [], device_types: [], devices: ['R1'] },
        why: { strong_views: [], partial_views: [], top_descriptors: [] },
        topology: { mapped: 0, total: 3, resource_types: [], dependency_verified: false },
        audit: { status: 'NOT_EVALUATED', candidate_cut: false, conductance: null },
        recommendations: { split_recommended: false },
        analytical_findings: [{
          finding_id: 'TEMPORAL_ONSET_ORDERING',
          kind: 'DERIVED',
          status: 'AVAILABLE',
          title: 'Temporal onset ordering',
          claim: 'Dữ liệu xác lập thứ tự quan sát.',
          evidence: ['Link Down xuất hiện lúc 08:53:58.'],
          limitations: ['CAUSAL_DIRECTION_UNVERIFIED'],
          confidence_basis: 'CANONICAL_START_TIME_ORDERING',
        }],
      },
    } as CohesionNarrativeView

    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialSuggestion={mockSuggestion}
        initialCohesion={cohesion}
      />,
    )

    expect(html).toContain('Analytical Findings')
    expect(html).toContain('Dữ liệu xác lập thứ tự quan sát.')
    expect(html).toContain('Link Down xuất hiện lúc 08:53:58.')
    expect(html).toContain('DERIVED')
    expect(html).toContain('CAUSAL_DIRECTION_UNVERIFIED')
  })
})
