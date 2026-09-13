import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CounterfactualReview } from './CounterfactualReview'
import type { CounterfactualCandidate, CounterfactualJob, CounterfactualMetricVector } from './types'

const exactMetrics: CounterfactualMetricVector = {
  weak_member_count: { availability: 'AVAILABLE', value: 1, reason: null },
  minimum_membership_support: { availability: 'AVAILABLE', value: 0.41, reason: null },
  evidence_union_coverage: { availability: 'AVAILABLE', value: 0.8, reason: null },
  component_count: { availability: 'AVAILABLE', value: 2, reason: null },
  audit_conductance: { availability: 'AVAILABLE', value: 0.22, reason: null },
  audit_verdict_severity: { availability: 'AVAILABLE', value: 2, reason: null },
  eligible_external_contradiction_count: { availability: 'AVAILABLE', value: 0, reason: null },
}

const job: CounterfactualJob = {
  job_id: 'review-1',
  chain_id: 'C1',
  status: 'SUCCEEDED',
  progress_percent: 100,
  cache_hit: false,
  cache_fingerprint: '0123456789abcdef',
  identity: {
    snapshot_id: 's1', snapshot_version: '1', chain_id: 'C1',
    alarm_universe_fingerprint: 'alarms', analysis_version: 'analysis-v1',
    engine_version: 'counterfactual-p1-v1', config_version: 'synthetic-review-v1',
    tier1b_artifact_fingerprint: 'tier1b', structural_audit_artifact_fingerprint: null,
    external_validation_artifact_fingerprint: null,
  },
  result: {
    identity: {
      snapshot_id: 's1', snapshot_version: '1', chain_id: 'C1',
      alarm_universe_fingerprint: 'alarms', analysis_version: 'analysis-v1',
      engine_version: 'counterfactual-p1-v1', config_version: 'synthetic-review-v1',
      tier1b_artifact_fingerprint: 'tier1b', structural_audit_artifact_fingerprint: null,
      external_validation_artifact_fingerprint: null,
    },
    status: 'AVAILABLE',
    reason: null,
    recommendation_status: 'AVAILABLE',
    remove: {
      operation: 'REMOVE_MEMBER', status: 'AVAILABLE', reason: null, search_mode: 'BOUNDED',
      discovered_candidate_count: 2, evaluated_candidate_count: 1, rejected_candidate_count: 0,
      candidate_limit: 8,
      candidates: [{
        candidate_id: 'remove-X', operation: 'REMOVE_MEMBER', member_ids: ['X'],
        source_chain_id: null, target_chain_id: null,
        merged_chain_ids: null, merge_evidence: null,
        source_ref: 'trigger-union', status: 'BETTER_SUPPORTED', reason: null,
        edit_cost: { operation_count: 1, membership_reassignments: 1, affected_member_count: 1 },
        partition_delta: { before: [['C1', ['A', 'B', 'X']]], after: [['C1', ['A', 'B']], ['singleton:X', ['X']]] },
        before: exactMetrics,
        after: { ...exactMetrics, weak_member_count: { availability: 'AVAILABLE', value: 0, reason: null } },
        materially_improved_metrics: ['weak_member_count'],
        move_structural_facts: null,
        semantic_effects: [],
      }],
    },
    split: {
      operation: 'SPLIT_CHAIN', status: 'UNAVAILABLE', reason: 'STRUCTURAL_AUDIT_UNAVAILABLE',
      search_mode: 'NOT_RUN', discovered_candidate_count: 0, evaluated_candidate_count: 0,
      rejected_candidate_count: 0, candidate_limit: 4, candidates: [],
    },
    move: {
      operation: 'MOVE_MEMBER', status: 'UNAVAILABLE', reason: 'MOVE_POLICY_NOT_CALIBRATED',
      search_mode: 'NOT_RUN', discovered_candidate_count: 0, evaluated_candidate_count: 0,
      rejected_candidate_count: 0, candidate_limit: null, candidates: [],
    },
    merge: {
      operation: 'MERGE_CHAINS', status: 'UNAVAILABLE', reason: 'MERGE_POLICY_NOT_CALIBRATED',
      search_mode: 'NOT_RUN', discovered_candidate_count: 0, evaluated_candidate_count: 0,
      rejected_candidate_count: 0, candidate_limit: null, candidates: [],
    },
    recommendations: [],
    frontier_count_before_limit: 1,
    frontier_truncated: false,
    parameter_provenance: {},
  },
  error: null,
}

describe('CounterfactualReview', () => {
  it('renders partial operations and exact comparison without an apply control', () => {
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={job} />)

    expect(html).toContain('Counterfactual chain review')
    expect(html).toContain('REMOVE_MEMBER')
    expect(html).toContain('SPLIT_CHAIN')
    expect(html).toContain('MOVE_MEMBER')
    expect(html).toContain('MERGE_CHAINS')
    expect(html).toContain('MOVE_POLICY_NOT_CALIBRATED')
    expect(html).toContain('STRUCTURAL_AUDIT_UNAVAILABLE')
    expect(html).toContain('Exact before and after metrics')
    expect(html).toContain('Proposal only')
    expect(html).toContain('NocPro was not changed')
    expect(html.toLowerCase()).not.toContain('>apply<')
  })

  it('shows an unavailable domain result without fabricating a proposal', () => {
    const unavailable: CounterfactualJob = {
      ...job,
      result: job.result ? {
        ...job.result,
        status: 'UNAVAILABLE',
        reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE',
        recommendation_status: 'UNAVAILABLE',
        remove: { ...job.result.remove, status: 'UNAVAILABLE', reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE', candidates: [] },
        split: { ...job.result.split, reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE' },
        move: { ...job.result.move, reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE' },
        merge: { ...job.result.merge, reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE' },
      } : null,
    }
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={unavailable} />)

    expect(html).toContain('COUNTERFACTUAL_CONFIG_INCOMPLETE')
    expect(html).toContain('UNAVAILABLE')
    expect(html).not.toContain('review-ledger')
  })

  it('surfaces connector completion only for a Pareto recommendation', () => {
    const move: CounterfactualCandidate = {
      candidate_id: 'move-B', operation: 'MOVE_MEMBER' as const, member_ids: ['B'],
      source_chain_id: 'C2', target_chain_id: 'C1', source_ref: 'move-trigger:WEAK',
      merged_chain_ids: null, merge_evidence: null,
      status: 'BETTER_SUPPORTED', reason: null,
      edit_cost: { operation_count: 1, membership_reassignments: 1, affected_member_count: 3 },
      partition_delta: { before: [['C2', ['B']], ['C1', ['A', 'C']]], after: [['C1', ['A', 'B', 'C']]] },
      before: exactMetrics, after: exactMetrics, materially_improved_metrics: ['component_count'],
      move_structural_facts: {
        before_structural_role: 'NOT_APPLICABLE', after_structural_role: 'CONNECTOR',
        after_is_articulation_point: true, after_blocks_supported: 2,
      },
      semantic_effects: ['BECOMES_CONNECTOR'],
    }
    const withMove: CounterfactualJob = {
      ...job,
      result: job.result ? {
        ...job.result,
        move: { ...job.result.move, status: 'AVAILABLE', candidates: [move] },
        recommendations: [move],
      } : null,
    }
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={withMove} />)
    expect(html).toContain('Reason: becomes a connector after the move')
    expect(html).toContain('2 supported blocks')
  })

  it('renders interactive operator feedback buttons only for Pareto recommendations', () => {
    const recommendedJob: CounterfactualJob = {
      ...job,
      result: job.result
        ? {
            ...job.result,
            recommendations: [job.result.remove.candidates[0]],
          }
        : null,
    }
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={recommendedJob} />)

    expect(html).toContain('Phản hồi chuyên gia (Operator Feedback):')
    expect(html).toContain('Chấp thuận đề xuất')
    expect(html).toContain('Từ chối đề xuất')
  })

  it('restricts feedback buttons and shows notice on non-recommended candidates', () => {
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={job} />)

    expect(html).not.toContain('Phản hồi chuyên gia (Operator Feedback):')
    expect(html).not.toContain('Chấp thuận đề xuất')
    expect(html).toContain(
      'Chỉ các đề xuất thuộc biên Pareto (recommendation) mới mở tiếp nhận phản hồi vận hành.'
    )
  })

  it('keeps persisted recommendations read-only when opened by Assistant navigation', () => {
    const recommendedJob: CounterfactualJob = {
      ...job,
      result: job.result
        ? { ...job.result, recommendations: [job.result.remove.candidates[0]] }
        : null,
    }
    const html = renderToStaticMarkup(
      <CounterfactualReview chainId="C1" initialJob={recommendedJob} readOnly />,
    )

    expect(html).toContain('Read-only navigation displays the persisted proposal')
    expect(html).not.toContain('Phản hồi chuyên gia (Operator Feedback):')
    expect(html).not.toContain('Chấp thuận đề xuất')
    expect(html).not.toContain('Từ chối đề xuất')
  })

  it('renders approved operator feedback as proposal-only review data', () => {
    const approvedFeedback = {
      feedback_id: 'fb-test-01',
      job_id: 'review-1',
      chain_id: 'C1',
      candidate_id: 'remove-X',
      operation: 'REMOVE_MEMBER',
      decision: 'APPROVED' as const,
      operator_id: 'lead_engineer_viettel',
      reason: 'Đã xác minh không liên quan tuyến truyền dẫn',
      partition_delta: { before: [], after: [] },
      created_at: '2026-09-04T06:00:00Z',
    }

    const html = renderToStaticMarkup(
      <CounterfactualReview
        chainId="C1"
        initialJob={job}
        initialFeedbacks={{ 'remove-X': approvedFeedback }}
      />
    )

    expect(html).toContain('ĐÃ CHẤP THUẬN ĐỀ XUẤT')
    expect(html).toContain('lead_engineer_viettel')
    expect(html).toContain('Đã xác minh không liên quan tuyến truyền dẫn')
    expect(html).toContain('Proposal only')
    expect(html).not.toContain('gửi lệnh NocPro live')
    expect(html).not.toContain('Từ chối đề xuất')
  })

  it('renders rejected operator feedback verdict with engineer reasoning', () => {
    const rejectedFeedback = {
      feedback_id: 'fb-test-02',
      job_id: 'review-1',
      chain_id: 'C1',
      candidate_id: 'remove-X',
      operation: 'REMOVE_MEMBER',
      decision: 'REJECTED' as const,
      operator_id: 'ops_shift_lead',
      reason: 'Cảnh báo thuộc chung tuyến switch truyền dẫn',
      partition_delta: { before: [], after: [] },
      created_at: '2026-09-04T06:10:00Z',
    }

    const html = renderToStaticMarkup(
      <CounterfactualReview
        chainId="C1"
        initialJob={job}
        initialFeedbacks={{ 'remove-X': rejectedFeedback }}
      />
    )

    expect(html).toContain('ĐÃ TỪ CHỐI ĐỀ XUẤT')
    expect(html).toContain('ops_shift_lead')
    expect(html).toContain('Cảnh báo thuộc chung tuyến switch truyền dẫn')
  })

  it('renders comparative explanation block with delta highlights and operational rationale', () => {
    const jobWithComparative: CounterfactualJob = {
      ...job,
      result: job.result ? {
        ...job.result,
        remove: {
          ...job.result.remove,
          candidates: [{
            ...job.result.remove.candidates[0],
            comparative_explanation: {
              operation: 'REMOVE_MEMBER',
              summary_action: 'Đề xuất loại bỏ 1 cảnh báo (X) ra khỏi chuỗi C1',
              why_better: 'Cảnh báo X có mức độ gắn kết yếu với các thành viên còn lại.',
              comparison_points: [
                'Giảm số lượng cảnh báo lạc quẻ (WEAK) từ 1 xuống 0 (giảm 1 cảnh báo gây nhiễu).',
                'Tăng độ hỗ trợ liên kết thành viên tối thiểu từ 41.0% lên 65.0% (+24.0%).',
              ],
              delta_highlights: [
                {
                  metric_name: 'weak_member_count',
                  label: 'Cảnh báo lạc quẻ (WEAK)',
                  before: '1',
                  after: '0',
                  delta: '-1',
                  direction: 'better',
                },
                {
                  metric_name: 'minimum_membership_support',
                  label: 'Độ hỗ trợ tối thiểu (Min Support)',
                  before: '41.0%',
                  after: '65.0%',
                  delta: '+24.0%',
                  direction: 'better',
                },
              ],
              ai_narrative: 'AI đánh giá đề xuất loại bỏ phần tử nhiễu sẽ làm gọn phân vùng lỗi.',
            },
          }],
        },
      } : null,
    }

    const html = renderToStaticMarkup(
      <CounterfactualReview chainId="C1" initialJob={jobWithComparative} />
    )

    expect(html).toContain('Comparative explanation')
    expect(html).toContain('Đề xuất loại bỏ 1 cảnh báo (X) ra khỏi chuỗi C1')
    expect(html).toContain('Cảnh báo lạc quẻ (WEAK)')
    expect(html).toContain('(-1)')
    expect(html).toContain('review-delta-chip--better')
    expect(html).toContain('Vì sao đề xuất này tốt hơn:')
    expect(html).toContain('Cảnh báo X có mức độ gắn kết yếu với các thành viên còn lại.')
    expect(html).toContain('giảm 1 cảnh báo gây nhiễu')
    expect(html).toContain('AI Phân tích chuyên sâu:')
    expect(html).toContain('AI đánh giá đề xuất loại bỏ phần tử nhiễu sẽ làm gọn phân vùng lỗi.')
  })

  it('renders top recommended proposals spotlight when recommendations exist', () => {
    const recommendedJob: CounterfactualJob = {
      ...job,
      result: job.result
        ? {
            ...job.result,
            recommendations: [job.result.remove.candidates[0]],
            evaluated_candidates: [job.result.remove.candidates[0]],
          }
        : null,
    }
    const html = renderToStaticMarkup(
      <CounterfactualReview chainId="C1" initialJob={recommendedJob} />
    )

    expect(html).toContain('⭐ Đề xuất Phân hoạch Được Khuyến nghị (Top Recommended Proposals)')
    expect(html).toContain('1 đề xuất')
    expect(html).toContain('⚖️ So Sánh Lời Giải Thích Giữa Các Đề Xuất')
  })

  it('renders optimal chain cohesion banner when no recommendations are needed', () => {
    const optimalJob: CounterfactualJob = {
      ...job,
      result: job.result
        ? {
            ...job.result,
            recommendation_status: 'AVAILABLE',
            recommendations: [],
          }
        : null,
    }
    const html = renderToStaticMarkup(
      <CounterfactualReview chainId="C1" initialJob={optimalJob} />
    )

    expect(html).toContain('Chuỗi có độ gắn kết cao và cấu trúc thuần nhất (Optimal Partition Cohesion)')
    expect(html).toContain('Không phát hiện cảnh báo rời rạc (WEAK) hay thành phần phân mảnh')
  })

  it('renders XGBRanker ranking audit badge and model governance button', () => {
    const candidateWithLearning: CounterfactualCandidate = {
      ...job.result!.remove.candidates[0],
      displayed_rank: 1,
      ranking_audit: {
        ranking_status: 'RERANKED',
        model_score: 0.8842,
        margin: 0.1250,
        ranker_version: 'v1',
        abstention_reason: null,
      },
    }

    const rerankedJob: CounterfactualJob = {
      ...job,
      result: {
        ...job.result!,
        recommendations: [candidateWithLearning],
        evaluated_candidates: [candidateWithLearning],
        remove: {
          ...job.result!.remove,
          candidates: [candidateWithLearning],
        },
      },
    }

    const html = renderToStaticMarkup(
      <CounterfactualReview
        chainId="C1"
        initialJob={rerankedJob}
        onOpenReviewLearning={() => {}}
      />
    )

    expect(html).toContain('🎯 XGBRanker')
    expect(html).toContain('Score: 0.8842')
    expect(html).toContain('Hạng đề xuất: #1')
    expect(html).toContain('Phiên bản: v1')
    expect(html).toContain('XGBRanker v1 Model')
    expect(html).toContain('Truy xuất trường hợp tương tự trong quá khứ')
  })

  it('renders model abstention badge when ranking audit status is ABSTAINED', () => {
    const candidateAbstained: CounterfactualCandidate = {
      ...job.result!.remove.candidates[0],
      displayed_rank: 1,
      ranking_audit: {
        ranking_status: 'ABSTAINED',
        model_score: null,
        margin: null,
        ranker_version: 'v1',
        abstention_reason: 'Score under margin threshold',
      },
    }

    const abstainedJob: CounterfactualJob = {
      ...job,
      result: {
        ...job.result!,
        recommendations: [candidateAbstained],
        evaluated_candidates: [candidateAbstained],
        remove: {
          ...job.result!.remove,
          candidates: [candidateAbstained],
        },
      },
    }

    const html = renderToStaticMarkup(
      <CounterfactualReview chainId="C1" initialJob={abstainedJob} />
    )

    expect(html).toContain('🛡️ Model Abstained: Score under margin threshold')
  })
})


