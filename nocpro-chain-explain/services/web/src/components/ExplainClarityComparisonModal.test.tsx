import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ExplainClarityComparisonModal } from './ExplainClarityComparisonModal'

describe('ExplainClarityComparisonModal', () => {
  it('does not render when isOpen is false', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={false}
        onClose={() => {}}
        mode="proposals"
        jobId="job-123"
      />
    )
    expect(html).toBe('')
  })

  it('renders modal structure for proposals comparison when isOpen is true', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="proposals"
        jobId="job-123"
      />
    )
    expect(html).toContain('So Sánh Trực Diện: Đề Xuất Nào Có Lời Giải Thích Rõ Ràng &amp; Thuyết Phục Hơn?')
    expect(html).toContain('⚖️ So sánh Đề xuất Tối ưu')
    expect(html).toContain('Job: job-123')
  })

  it('renders modal structure for threshold optimization when isOpen is true', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="threshold"
        chainId="C1"
      />
    )
    expect(html).toContain('Tìm Ngưỡng Tham Số Cho Ra Lời Giải Thích Rõ Ràng &amp; Sắc Nét Nhất')
    expect(html).toContain('🎯 Tối ưu hóa Ngưỡng Explain')
    expect(html).toContain('Chain: C1')
  })

  it('renders sweep trials table with Before -> After transitions and metrics', () => {
    const mockThresholdData = {
      chain_id: 'C1',
      current_parameters: { 'role.s_weak': 0.30, 'role.c_min': 0.50 },
      optimal_parameters: { 'role.s_weak': 0.25, 'role.c_min': 0.50 },
      current_clarity_score: 65.0,
      optimal_clarity_score: 75.0,
      current_llm_score: 70.0,
      optimal_llm_score: 85.0,
      current_hybrid_score: 67.0,
      optimal_hybrid_score: 79.0,
      clarity_gain: 10.0,
      current_explanation: 'Giải thích hiện tại',
      optimal_explanation: 'Giải thích tối ưu mới',
      winner: 'Cấu hình được chọn',
      why_clearer: ['Phân định vai trò WEAK/CORE rõ ràng hơn'],
      summary_verdict: 'Cấu hình tối ưu vượt trội',
      sweep_results: [
        {
          label: 'Cấu hình hiện tại',
          parameters: { 'role.s_weak': 0.30, 'role.c_min': 0.50 },
          explanation: 'Giải thích hiện tại',
          clarity_score: 65.0,
          llm_score: 70.0,
          hybrid_score: 67.0,
          weak_count: 1,
          core_count: 1,
        },
        {
          label: 'Giảm ngưỡng weak',
          parameters: { 'role.s_weak': 0.25, 'role.c_min': 0.50 },
          explanation: 'Giải thích tối ưu mới',
          clarity_score: 75.0,
          llm_score: 85.0,
          hybrid_score: 79.0,
          weak_count: 2,
          core_count: 1,
        },
      ],
    }

    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="threshold"
        chainId="C1"
        initialThresholdData={mockThresholdData}
      />
    )

    // Check Before -> After table headers
    expect(html).toContain('s_weak (Trước → Sau)')
    expect(html).toContain('c_min (Trước → Sau)')
    expect(html).toContain('Số WEAK (Trước → Sau)')
    expect(html).toContain('Số CORE (Trước → Sau)')
    expect(html).toContain('Độ Rõ Bằng Chứng (Trước → Sau)')
    expect(html).toContain('Điểm LLM (Trước → Sau)')
    expect(html).toContain('Điểm Lai (Hybrid) (Trước → Sau)')

    // Check transition rendering: baseline has "(gốc)"
    expect(html).toContain('(gốc)')

    // Check parameter transition: 0.30 → 0.25 (-0.05)
    expect(html).toContain('0.30')
    expect(html).toContain('0.25')
    expect(html).toContain('(-0.05)')

    // Check weak count transition: 1 → 2 (+1)
    expect(html).toContain('(+1)')

    // Check unchanged parameter: (không đổi)
    expect(html).toContain('(không đổi)')

    // Check optimal card badge displays parameter transition
    expect(html).toContain('🎯 NGƯỠNG TỐI ƯU MỚI (s_weak: 0.3 → 0.25)')
  })

  it('renders single optimal card and already-optimal notice when no candidate improves score', () => {
    const alreadyOptimalData = {
      chain_id: 'C1',
      current_parameters: { 'role.s_weak': 0.30, 'role.c_min': 0.50 },
      optimal_parameters: { 'role.s_weak': 0.30, 'role.c_min': 0.50 },
      current_clarity_score: 65.0,
      optimal_clarity_score: 65.0,
      current_llm_score: 70.0,
      optimal_llm_score: 70.0,
      current_hybrid_score: 67.0,
      optimal_hybrid_score: 67.0,
      clarity_gain: 0.0,
      current_explanation: 'Lời giải thích hiện tại đã chuẩn xác nhất',
      optimal_explanation: 'Lời giải thích hiện tại đã chuẩn xác nhất',
      winner: 'Cấu hình hiện tại',
      why_clearer: ['Cấu hình hiện tại đã đạt độ rõ ràng tối ưu nhất'],
      summary_verdict: 'Cấu hình hiện tại đã tối ưu; khuyến nghị giữ nguyên tham số',
      is_already_optimal: true,
      sweep_results: [
        {
          label: 'Cấu hình hiện tại',
          parameters: { 'role.s_weak': 0.30, 'role.c_min': 0.50 },
          explanation: 'Lời giải thích hiện tại đã chuẩn xác nhất',
          clarity_score: 65.0,
          llm_score: 70.0,
          hybrid_score: 67.0,
          weak_count: 1,
          core_count: 1,
        },
        {
          label: 'Giảm ngưỡng weak',
          parameters: { 'role.s_weak': 0.25, 'role.c_min': 0.50 },
          explanation: 'Lời giải thích kém rõ ràng hơn',
          clarity_score: 60.0,
          llm_score: 65.0,
          hybrid_score: 62.0,
          weak_count: 2,
          core_count: 1,
        },
      ],
    }

    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="threshold"
        chainId="C1"
        initialThresholdData={alreadyOptimalData}
      />
    )

    // Should show single optimal card, not dual columns
    expect(html).toContain('🎯 LỜI GIẢI THÍCH HIỆN TẠI (ĐÃ TỐI ƯU NHẤT)')
    expect(html).toContain('Cấu hình hiện tại đã tối ưu')
    expect(html).toContain('✓ Đã tối ưu (Không đổi)')
    expect(html).toContain('Lời giải thích hiện tại đã chuẩn xác nhất')

    // Should NOT show "NGƯỠNG TỐI ƯU MỚI" or "Áp Dụng Ngưỡng Này Cho Chuỗi"
    expect(html).not.toContain('🎯 NGƯỠNG TỐI ƯU MỚI')
    expect(html).not.toContain('⚡ Áp Dụng Ngưỡng Này Cho Chuỗi')

    // Sweep table is still rendered so operator can verify trials
    expect(html).toContain('Các Ngưỡng Đã Thử Nghiệm (Sweep Trials)')
  })

  it('renders trigger button in RecommendationsView', async () => {
    const { RecommendationsView } = await import('../views/RecommendationsView')
    const mockAnalysis = {
      chain_id: 'C-REAL', title: 'Observed chain', member_count: 5, singleton: false,
      statistics_mode: 'EXACT', audit_graph_mode: 'DEFERRED', pair_materialization: 'LAZY', config_version: 'v1',
      graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
      descriptors: [], members: [], role_counts: {}, phase_durations: {},
    } as any

    const html = renderToStaticMarkup(<RecommendationsView analysis={mockAnalysis} />)
    expect(html).toContain('🎯 Tối Ưu Lời Giải Thích (Tìm Ngưỡng Rõ Nhất)')
  })

  it('renders trigger button in CounterfactualReview when candidates are present', async () => {
    const { CounterfactualReview } = await import('../CounterfactualReview')
    const mockJob: any = {
      job_id: 'job-test-1',
      chain_id: 'C1',
      status: 'SUCCEEDED',
      progress_percent: 100,
      cache_hit: false,
      cache_fingerprint: 'abcdef0123456789',
      identity: { snapshot_id: 's1', snapshot_version: '1' },
      result: {
        identity: { snapshot_id: 's1', snapshot_version: '1', config_version: 'v1' },
        status: 'AVAILABLE',
        recommendation_status: 'AVAILABLE',
        recommendations: [{
          candidate_id: 'cand-1',
          operation: 'REMOVE_MEMBER',
          status: 'RECOMMENDED',
          rank: 1,
        }],


        remove: {
          operation: 'REMOVE_MEMBER',
          status: 'AVAILABLE',
          candidates: [{
            candidate_id: 'cand-1',
            operation: 'REMOVE_MEMBER',
            member_ids: ['A'],
            edit_cost: { operation_count: 1, membership_reassignments: 1, affected_member_count: 1 },
            partition_delta: { before: [], after: [] },
            before: {},
            after: {},
            materially_improved_metrics: [],
            semantic_effects: [],
          }],

        },
        split: { operation: 'SPLIT_CHAIN', status: 'UNAVAILABLE', candidates: [] },
        move: { operation: 'MOVE_MEMBER', status: 'UNAVAILABLE', candidates: [] },
        merge: { operation: 'MERGE_CHAINS', status: 'UNAVAILABLE', candidates: [] },
      },


    }

    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={mockJob} readOnly={false} />)
    expect(html).toContain('⚖️ So Sánh Lời Giải Thích Giữa Các Đề Xuất')
  })
})
