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
