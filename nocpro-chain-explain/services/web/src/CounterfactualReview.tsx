import { useEffect, useState } from 'react'

import { api, ApiError } from './api'
import { percent } from './format'
import type {
  CounterfactualCandidate,
  CounterfactualJob,
  CounterfactualMetricVector,
  CounterfactualOperation,
  OperatorFeedback,
} from './types'

const metricLabels: Array<[keyof CounterfactualMetricVector, string]> = [
  ['weak_member_count', 'Weak members'],
  ['minimum_membership_support', 'Minimum support'],
  ['evidence_union_coverage', 'Evidence coverage'],
  ['component_count', 'Components'],
  ['audit_conductance', 'Conductance'],
  ['audit_verdict_severity', 'Audit severity'],
  ['eligible_external_contradiction_count', 'Contradictions'],
]

function metricValue(name: keyof CounterfactualMetricVector, vector: CounterfactualMetricVector | null) {
  const metric = vector?.[name]
  if (!metric || metric.availability !== 'AVAILABLE' || metric.value == null) return '⊥'
  if (['minimum_membership_support', 'evidence_union_coverage'].includes(name)) return percent(metric.value)
  return Number.isInteger(metric.value) ? String(metric.value) : metric.value.toFixed(3)
}

function evidenceString(candidate: CounterfactualCandidate, key: string): string | undefined {
  const value = candidate.operation_specific_evidence?.[key]
  return typeof value === 'string' ? value : undefined
}

function evidenceStrings(candidate: CounterfactualCandidate, key: string): string[] | undefined {
  const value = candidate.operation_specific_evidence?.[key]
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : undefined
}

function CandidateCard({
  candidate,
  recommended,
  feedback,
  onFeedbackSubmit,
}: {
  candidate: CounterfactualCandidate
  recommended: boolean
  feedback?: OperatorFeedback
  onFeedbackSubmit?: (
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    operatorId?: string,
    reason?: string,
  ) => Promise<void>
}) {
  const status = candidate.evaluation_status ?? candidate.status ?? 'NOT_EVALUATED'
  const sourceRef = candidate.debug_source_ref ?? candidate.source_ref
  const memberIds = candidate.member_ids?.length
    ? candidate.member_ids
    : evidenceString(candidate, 'alarm_id') ? [evidenceString(candidate, 'alarm_id')!] : []
  const sourceChainId = candidate.source_chain_id ?? evidenceString(candidate, 'source_chain_id')
  const targetChainId = candidate.target_chain_id ?? evidenceString(candidate, 'target_chain_id')
  const mergedChainIds = candidate.merged_chain_ids ?? evidenceStrings(candidate, 'merged_chain_ids')
  const mergeEvidence = candidate.merge_evidence ?? candidate.operation_specific_evidence?.cross_chain_evidence as { cross_audit_edge_count?: number } | undefined

  const [showForm, setShowForm] = useState(false)
  const [selectedDecision, setSelectedDecision] = useState<'APPROVED' | 'REJECTED'>('APPROVED')
  const [operatorId, setOperatorId] = useState('viettel_operator')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const handleOpenForm = (decision: 'APPROVED' | 'REJECTED') => {
    setSelectedDecision(decision)
    setShowForm(true)
    setSubmitError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!onFeedbackSubmit) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await onFeedbackSubmit(
        candidate.candidate_id,
        selectedDecision,
        operatorId,
        reason,
      )
      setShowForm(false)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Gửi phản hồi thất bại')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <article className={`review-candidate ${recommended ? 'review-candidate--recommended' : ''}`}>
      <header>
        <div>
          <span className="review-operation">{candidate.operation}</span>
          <strong>{memberIds.join(' · ') || 'Partition proposal'}</strong>
        </div>
        <span className={`review-state review-state--${status.toLowerCase()}`}>{status}</span>
      </header>
      <div className="review-partition" aria-label="Before and after partition">
        <div><small>Current</small>{candidate.partition_delta.before.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
        <i aria-hidden="true">→</i>
        <div><small>Proposed</small>{candidate.partition_delta.after.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
      </div>
      <div className="review-ledger" role="table" aria-label="Exact before and after metrics">
        <div className="review-ledger-head" role="row"><span>Metric</span><span>Before</span><span>After</span></div>
        {metricLabels.map(([name, label]) => (
          <div role="row" key={name}>
            <span>{label}</span>
            <span>{metricValue(name, candidate.before_metrics ?? candidate.before)}</span>
            <strong>{metricValue(name, candidate.after_metrics ?? candidate.after)}</strong>
          </div>
        ))}
      </div>

      {feedback ? (
        <div className={`review-feedback-verdict review-feedback-verdict--${feedback.decision.toLowerCase()}`}>
          <div className="review-feedback-verdict-header">
            <span className="review-feedback-badge">
              {feedback.decision === 'APPROVED' ? '✓ ĐÃ CHẤP THUẬN ĐỀ XUẤT' : '✗ ĐÃ TỪ CHỐI ĐỀ XUẤT'}
            </span>
            <span className="review-feedback-operator">
              Kỹ sư: <strong>{feedback.operator_id}</strong>
            </span>
          </div>
          {feedback.reason ? <p className="review-feedback-reason">“{feedback.reason}”</p> : null}
        </div>
      ) : recommended && onFeedbackSubmit ? (
        showForm ? (
          <form className="review-feedback-form" onSubmit={handleSubmit}>
            <div className="review-feedback-form-title">
              <strong>{selectedDecision === 'APPROVED' ? '✓ Xác nhận chấp thuận đề xuất' : '✗ Xác nhận từ chối đề xuất'}</strong>
              <small>Phản hồi được lưu làm dữ liệu đánh giá; không thay đổi NocPro.</small>
            </div>
            {submitError ? <div className="review-form-error">{submitError}</div> : null}
            <div className="review-form-row">
              <label htmlFor={`operator-${candidate.candidate_id}`}>Mã kỹ sư vận hành:</label>
              <input
                id={`operator-${candidate.candidate_id}`}
                name="operator_id"
                autoComplete="username"
                type="text"
                value={operatorId}
                onChange={(e) => setOperatorId(e.target.value)}
                required
              />
            </div>
            <div className="review-form-row">
              <label htmlFor={`reason-${candidate.candidate_id}`}>Ghi chú / Căn cứ đánh giá:</label>
              <textarea
                id={`reason-${candidate.candidate_id}`}
                name="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="VD: Cảnh báo thuộc cùng một tuyến truyền dẫn quang…"
                rows={2}
              />
            </div>
            <div className="review-form-actions">
              <button
                type="submit"
                className={`review-btn-submit ${selectedDecision === 'APPROVED' ? 'review-btn-submit--approve' : 'review-btn-submit--reject'}`}
                disabled={submitting}
              >
                {submitting ? 'Đang lưu…' : 'Lưu phản hồi'}
              </button>
              <button
                type="button"
                className="review-btn-cancel"
                onClick={() => setShowForm(false)}
                disabled={submitting}
              >
                Hủy
              </button>
            </div>
          </form>
        ) : (
          <div className="review-feedback-prompt">
            <span className="review-feedback-prompt-label">Phản hồi chuyên gia (Operator Feedback):</span>
            <div className="review-feedback-buttons">
              <button
                type="button"
                className="review-btn-action review-btn-approve"
                onClick={() => handleOpenForm('APPROVED')}
              >
                ✓ Chấp thuận đề xuất
              </button>
              <button
                type="button"
                className="review-btn-action review-btn-reject"
                onClick={() => handleOpenForm('REJECTED')}
              >
                ✗ Từ chối đề xuất
              </button>
            </div>
          </div>
        )
      ) : recommended ? (
        <div className="review-feedback-non-recommended">
          <small>Read-only navigation displays the persisted proposal but does not open operator-feedback controls.</small>
        </div>
      ) : (
        <div className="review-feedback-non-recommended">
          <small>Chỉ các đề xuất thuộc biên Pareto (recommendation) mới mở tiếp nhận phản hồi vận hành.</small>
        </div>
      )}

      <footer>
        <span>Exact bounded evaluation{sourceRef ? ` · ${sourceRef}` : ''}</span>
        {candidate.operation === 'MOVE_MEMBER' && sourceChainId && targetChainId ? <span>Transfer {sourceChainId} → {targetChainId}</span> : null}
        {candidate.operation === 'MERGE_CHAINS' && mergedChainIds && mergeEvidence ? <span>Merge {mergedChainIds.join(' + ')} · {mergeEvidence.cross_audit_edge_count} exact cross Audit edges</span> : null}
        {recommended && candidate.semantic_effects.includes('BECOMES_CONNECTOR') && (candidate.structural_facts ?? candidate.move_structural_facts) ? <span>Reason: becomes a connector after the move · {(candidate.structural_facts ?? candidate.move_structural_facts)!.after_blocks_supported} supported blocks</span> : null}
        <span>{candidate.materially_improved_metrics.length} material improvements</span>
      </footer>
    </article>
  )
}

const REASON_EXPLANATIONS: Record<string, string> = {
  MOVE_POLICY_NOT_CALIBRATED: 'Chưa cấu hình chính sách di chuyển thành viên (MOVE) · Sử dụng Cài đặt để hiệu chuẩn',
  MERGE_POLICY_NOT_CALIBRATED: 'Chưa cấu hình chính sách gộp chuỗi (MERGE) · Sử dụng Cài đặt để hiệu chuẩn',
  STRUCTURAL_AUDIT_UNAVAILABLE: 'Chưa có kết quả phân tích đồ thị cấu trúc (Audit Graph) cho chuỗi này',
  NO_NONTRIVIAL_SPLIT: 'Chuỗi không có điểm cắt tự nhiên đạt ngưỡng phân tách',
  COUNTERFACTUAL_POLICY_NOT_CALIBRATED: 'Tập tham số hiện tại chưa được đánh dấu hiệu chuẩn sản xuất (PRODUCTION_CALIBRATED)',
  NO_CLEAR_ALTERNATIVE: 'Không có phương án phân hoạch nào vượt trội rõ rệt trên biên Pareto',
  STRUCTURAL_AUDIT_SKIPPED_SMALL_CHAIN: 'Chuỗi nhỏ (<10 cảnh báo) không áp dụng phân hoạch cấu trúc',
}

function OperationSection({
  operation,
  recommendationIds,
  feedbacks,
  onFeedbackSubmit,
}: {
  operation: CounterfactualOperation
  recommendationIds: Set<string>
  feedbacks: Record<string, OperatorFeedback>
  onFeedbackSubmit?: (
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    operatorId?: string,
    reason?: string,
  ) => Promise<void>
}) {
  return (
    <section className="review-operation-section">
      <header>
        <div><p className="kicker">Bounded operation</p><h3>{operation.operation}</h3></div>
        <span className={`review-state review-state--${operation.status.toLowerCase()}`}>{operation.status}</span>
      </header>
      <dl className="review-search-diagnostics">
        <div><dt>discovered</dt><dd>{operation.discovered_candidate_count}</dd></div>
        <div><dt>evaluated</dt><dd>{operation.evaluated_candidate_count}</dd></div>
        <div><dt>rejected</dt><dd>{operation.rejected_candidate_count}</dd></div>
        <div><dt>limit</dt><dd>{operation.candidate_limit ?? '⊥'}</dd></div>
      </dl>
      {operation.reason && (
        <p className="review-reason" title={REASON_EXPLANATIONS[operation.reason] ?? operation.reason}>
          <span className="review-reason-code">{operation.reason}</span>
          {REASON_EXPLANATIONS[operation.reason] ? (
            <span className="review-reason-desc"> — {REASON_EXPLANATIONS[operation.reason]}</span>
          ) : null}
        </p>
      )}
      <div className="review-candidate-list">
        {operation.candidates.map((candidate) => (
          <CandidateCard
            key={candidate.candidate_id}
            candidate={candidate}
            recommended={recommendationIds.has(candidate.candidate_id)}
            feedback={feedbacks[candidate.candidate_id]}
            onFeedbackSubmit={onFeedbackSubmit}
          />
        ))}
        {operation.status === 'AVAILABLE' && operation.candidates.length === 0 ? <p className="review-empty">No bounded candidate met the trigger policy.</p> : null}
      </div>
    </section>
  )
}

export function CounterfactualReview({
  chainId,
  initialJob = null,
  initialFeedbacks = {},
  readOnly = false,
}: {
  chainId: string
  initialJob?: CounterfactualJob | null
  initialFeedbacks?: Record<string, OperatorFeedback>
  /** Assistant navigation may only display persisted results; it never starts Review. */
  readOnly?: boolean
}) {
  const [job, setJob] = useState<CounterfactualJob | null>(initialJob)
  const [feedbacks, setFeedbacks] = useState<Record<string, OperatorFeedback>>(initialFeedbacks)
  const [loading, setLoading] = useState(initialJob == null)
  const [error, setError] = useState<string | null>(null)
  const [noPersistedReview, setNoPersistedReview] = useState(false)

  useEffect(() => {
    if (initialJob?.chain_id === chainId) return
    const controller = new AbortController()
    async function load() {
      setNoPersistedReview(false)
      try {
        let current: CounterfactualJob
        try {
          current = await api.latestReview(chainId, controller.signal)
        } catch (cause) {
          if (!(cause instanceof ApiError && cause.status === 404)) throw cause
          if (readOnly) {
            if (!controller.signal.aborted) setNoPersistedReview(true)
            return
          }
          const submission = await api.submitReview(chainId)
          current = await api.reviewJob(submission.job_id, controller.signal)
        }
        if (!controller.signal.aborted) {
          setJob(current)
          // Also fetch existing feedbacks for this job
          if (current.job_id) {
            api.reviewFeedback(current.job_id, controller.signal)
              .then((list) => {
                if (!controller.signal.aborted) {
                  const map: Record<string, OperatorFeedback> = {}
                  for (const fb of list) {
                    map[fb.candidate_id] = fb
                  }
                  setFeedbacks(map)
                }
              })
              .catch(() => {
                // Ignore feedback fetch errors on fresh jobs
              })
          }
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Review unavailable')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [chainId, initialJob, readOnly])

  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.reviewJob(job.job_id, controller.signal).then(setJob).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Review polling failed')
      })
    }, 450)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [job])

  const handleFeedbackSubmit = async (
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    operatorId?: string,
    reason?: string,
  ) => {
    if (!job?.job_id) return
    const fb = await api.submitReviewFeedback(job.job_id, {
      candidate_id: candidateId,
      decision,
      operator_id: operatorId,
      reason,
    })
    setFeedbacks((prev) => ({ ...prev, [candidateId]: fb }))
  }

  if (loading && !job) return <section className="review-shell review-loading"><span /><p>Evaluating bounded alternatives…</p></section>
  if (error) return <section className="review-shell review-unavailable" role="alert"><span>UNAVAILABLE</span><h2>Counterfactual review could not be loaded.</h2><p>{error}</p></section>
  if (noPersistedReview) return (
    <section className="review-shell review-unavailable">
      <span>NOT_RUN</span>
      <h2>No persisted Counterfactual Review is available.</h2>
      <p>Assistant navigation is read-only and does not create Review jobs. Open Review directly to run the configured bounded evaluation.</p>
    </section>
  )
  if (!job) return null
  if (!job.result) return <section className="review-shell review-loading"><span>{job.progress_percent}%</span><p>{job.status}</p>{job.error ? <small>{job.error}</small> : null}</section>

  const result = job.result
  const recommendationIds = new Set(result.recommendations.map((item) => item.candidate_id))
  const operations: CounterfactualOperation[] = result.operation_status
    ? ['REMOVE_MEMBER', 'SPLIT_CHAIN', 'MOVE_MEMBER', 'MERGE_CHAINS', 'ADD_MEMBER'].map((operation) => {
        const summary = result.operation_status![operation]
        return {
          operation: operation as CounterfactualOperation['operation'],
          status: summary.status as CounterfactualOperation['status'],
          reason: summary.reason,
          search_mode: summary.search_mode as CounterfactualOperation['search_mode'],
          discovered_candidate_count: summary.candidate_count,
          evaluated_candidate_count: summary.evaluated_count,
          rejected_candidate_count: 0,
          candidate_limit: summary.ceiling,
          candidates: (result.evaluated_candidates ?? []).filter((item) => item.operation === operation),
        }
      })
    : [result.remove, result.split, result.move, result.merge]
  return (
    <section className="review-shell">
      <header className="review-heading">
        <div><p className="kicker">Review-only · {result.identity.engine_version}</p><h2>Counterfactual chain review</h2><p>Compare exact, bounded partition alternatives. This analysis does not change the NocPro grouping.</p></div>
        <div><span className={`review-state review-state--${result.recommendation_status.toLowerCase()}`}>{result.recommendation_status}</span><small>{result.identity.config_version}</small></div>
      </header>
      <div className="review-safety-notice"><strong>Proposal only</strong><span>NocPro was not changed. No candidate is applied automatically.</span></div>
      {result.reason ? (
        <p className="review-global-reason" title={REASON_EXPLANATIONS[result.reason] ?? result.reason}>
          <span className="review-reason-code">{result.reason}</span>
          {REASON_EXPLANATIONS[result.reason] ? (
            <span className="review-reason-desc"> — {REASON_EXPLANATIONS[result.reason]}</span>
          ) : null}
        </p>
      ) : null}
      {result.recommendation_status === 'UNAVAILABLE' && result.reason === 'COUNTERFACTUAL_POLICY_NOT_CALIBRATED' ? (
        <div
          className="review-calibration-hint"
          style={{
            margin: '0.75rem 1.25rem',
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-sm, 6px)',
            background: 'rgba(59, 130, 246, 0.12)',
            border: '1px solid rgba(59, 130, 246, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '1rem',
            fontSize: '0.8rem',
            color: '#93c5fd',
          }}
        >
          <div>
            <strong>💡 Chế độ an toàn:</strong> Cấu hình hiện tại chưa được đánh dấu hiệu chuẩn sản xuất. Để mở khóa toàn bộ đề xuất tối ưu, hãy vào <strong>⚙ Settings</strong> và chọn <strong>Calibrate from Database</strong> hoặc chọn profile <strong>v1-calibrated</strong>.
          </div>
        </div>
      ) : null}
      <div className="review-operation-grid">
        {operations.map((operation) => (
          <OperationSection
            key={operation.operation}
            operation={operation}
            recommendationIds={recommendationIds}
            feedbacks={feedbacks}
            onFeedbackSubmit={readOnly ? undefined : handleFeedbackSubmit}
          />
        ))}
      </div>
      <footer className="review-provenance">
        <span>Snapshot {result.identity.snapshot_id}@{result.identity.snapshot_version}</span>
        <span>{result.frontier?.count_before_limit ?? result.frontier_count_before_limit} frontier candidates{(result.frontier?.truncated ?? result.frontier_truncated) ? ' · bounded for display' : ''}</span>
        <span>Artifact {job.cache_fingerprint.slice(0, 12)}</span>
      </footer>
    </section>
  )
}
