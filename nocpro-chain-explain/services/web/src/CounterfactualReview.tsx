import { useEffect, useState } from 'react'

import { api, ApiError } from './api'
import { ExplainClarityComparisonModal } from './components/ExplainClarityComparisonModal'
import { percent } from './format'
import type {
  CounterfactualCandidate,
  CounterfactualJob,
  CounterfactualMetricVector,
  CounterfactualOperation,
  OperatorFeedback,
  SimilarCaseRetrievalResult,
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
  jobId,
  onFeedbackSubmit,
}: {
  candidate: CounterfactualCandidate
  recommended: boolean
  feedback?: OperatorFeedback
  jobId?: string
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

  const [showSimilarCases, setShowSimilarCases] = useState(false)
  const [loadingSimilar, setLoadingSimilar] = useState(false)
  const [similarResult, setSimilarResult] = useState<SimilarCaseRetrievalResult | null>(null)
  const [similarError, setSimilarError] = useState<string | null>(null)

  const handleToggleSimilarCases = async () => {
    const nextState = !showSimilarCases
    setShowSimilarCases(nextState)
    if (nextState && !similarResult && jobId) {
      setLoadingSimilar(true)
      setSimilarError(null)
      try {
        const res = await api.similarCases(jobId, candidate.candidate_id)
        setSimilarResult(res)
      } catch (err) {
        setSimilarError(err instanceof Error ? err.message : 'Không thể tải trường hợp tương tự')
      } finally {
        setLoadingSimilar(false)
      }
    }
  }

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

      {candidate.ranking_audit && (
        <div className="review-ranking-badge-container flex flex-wrap items-center gap-2 mt-2 px-3 py-1.5 rounded-lg bg-surface-container-low border border-surface-container-highest">
          {candidate.ranking_audit.ranking_status === 'RERANKED' ? (
            <>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                <span>🎯 XGBRanker</span>
                <span className="text-amber-100 font-mono">
                  Score: {candidate.ranking_audit.model_score !== null && candidate.ranking_audit.model_score !== undefined ? candidate.ranking_audit.model_score.toFixed(4) : 'N/A'}
                </span>
              </span>
              {candidate.displayed_rank !== undefined && candidate.displayed_rank !== null && (
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-primary/20 text-primary border border-primary/30 font-mono">
                  Hạng đề xuất: #{candidate.displayed_rank}
                </span>
              )}
              <span className="text-[11px] text-on-surface-variant font-mono">
                (Phiên bản: {candidate.ranking_audit.ranker_version ?? 'v1'}, Margin: {(candidate.ranking_audit.margin ?? 0).toFixed(4)})
              </span>
            </>
          ) : candidate.ranking_audit.ranking_status === 'ABSTAINED' ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30">
              <span>🛡️ Model Abstained: {candidate.ranking_audit.abstention_reason || 'Score under threshold'}</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium bg-surface-container-high text-on-surface-variant">
              <span>⚙️ Xếp hạng Baseline thuần định thức</span>
            </span>
          )}
        </div>
      )}

      <div className="review-partition" aria-label="Before and after partition">
        <div><small>Current</small>{candidate.partition_delta.before.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
        <i aria-hidden="true">→</i>
        <div><small>Proposed</small>{candidate.partition_delta.after.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
      </div>

      {candidate.comparative_explanation ? (
        <div className="review-comparative" aria-label="Comparative explanation">
          <div className="review-comparative-summary">
            <span className="review-comparative-icon" aria-hidden="true">💡</span>
            <span>{candidate.comparative_explanation.summary_action}</span>
          </div>

          {candidate.comparative_explanation.delta_highlights && candidate.comparative_explanation.delta_highlights.length > 0 && (
            <div className="review-comparative-deltas" aria-label="Delta highlights">
              {candidate.comparative_explanation.delta_highlights.map((d, i) => (
                <span
                  key={i}
                  className={`review-delta-chip review-delta-chip--${d.direction}`}
                  title={`${d.label}: ${d.before} → ${d.after} (${d.delta})`}
                >
                  <span className="review-delta-name">{d.label}:</span>
                  <span className="review-delta-val">{d.before} → {d.after}</span>
                  <strong className="review-delta-diff">({d.delta})</strong>
                </span>
              ))}
            </div>
          )}

          <div className="review-comparative-rationale">
            <p className="review-comparative-why">
              <strong>Vì sao đề xuất này tốt hơn: </strong>
              {candidate.comparative_explanation.why_better}
            </p>
            {candidate.comparative_explanation.comparison_points && candidate.comparative_explanation.comparison_points.length > 0 && (
              <ul className="review-comparative-points">
                {candidate.comparative_explanation.comparison_points.map((pt, i) => (
                  <li key={i}>{pt}</li>
                ))}
              </ul>
            )}
            {candidate.comparative_explanation.ai_narrative && (
              <div className="review-comparative-ai">
                <span className="review-comparative-ai-label">🤖 AI Phân tích chuyên sâu:</span>
                <p>{candidate.comparative_explanation.ai_narrative}</p>
              </div>
            )}
          </div>
        </div>
      ) : null}

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

      {jobId && (
        <div className="review-similar-cases-section mt-3 pt-2 border-t border-surface-container-highest">
          <button
            type="button"
            onClick={handleToggleSimilarCases}
            className="flex items-center justify-between w-full text-left py-1.5 px-2.5 rounded bg-surface-container-low hover:bg-surface-container transition-colors text-xs font-semibold text-secondary"
          >
            <span className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">history_edu</span>
              <span>Truy xuất trường hợp tương tự trong quá khứ (Similar Cases)</span>
              {similarResult && (
                <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-secondary/15 text-secondary border border-secondary/30 font-mono">
                  {similarResult.cross_incident_cases.length + similarResult.same_lineage_history.length} ca
                </span>
              )}
            </span>
            <span className="material-symbols-outlined text-[16px]">
              {showSimilarCases ? 'expand_less' : 'expand_more'}
            </span>
          </button>
          {showSimilarCases && (
            <div className="similar-cases-panel mt-2 p-3 rounded-lg bg-[#0a101d] border border-[#1a263d] space-y-2">
              {loadingSimilar ? (
                <div className="flex items-center gap-2 text-xs text-on-surface-variant py-2">
                  <span className="material-symbols-outlined animate-spin text-[16px] text-secondary">progress_activity</span>
                  <span>Đang tính toán độ đo tương đồng đa khối (Deterministic Multi-block Similarity)...</span>
                </div>
              ) : similarError ? (
                <p className="text-xs text-rose-400">{similarError}</p>
              ) : similarResult ? (
                <>
                  <div className="flex items-center justify-between text-[11px] text-on-surface-variant pb-1 border-b border-[#162136]">
                    <span>Trạng thái: <strong className="text-on-surface">{similarResult.retrieval_status}</strong></span>
                    <span>Ngưỡng tối thiểu: <strong className="text-on-surface font-mono">{(similarResult.min_similarity * 100).toFixed(0)}%</strong></span>
                  </div>
                  
                  {similarResult.cross_incident_cases.length === 0 && similarResult.same_lineage_history.length === 0 ? (
                    <p className="text-xs text-on-surface-variant italic py-1">
                      Chưa có tiền lệ tương đồng đủ tin cậy trong cơ sở tri thức {similarResult.reason ? `(${similarResult.reason})` : ''}.
                    </p>
                  ) : (
                    <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                      {similarResult.cross_incident_cases.map((sc) => (
                        <div key={sc.case_id} className="p-2.5 rounded border border-[#1e2d47] bg-[#0d1526] text-xs space-y-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5 font-mono text-[11px]">
                              <span className="text-primary font-bold">{sc.case_id}</span>
                              <span className="text-on-surface-variant">·</span>
                              <span className="text-on-surface-variant">{sc.review_id}</span>
                            </div>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                              sc.decision === 'APPROVE' || sc.decision === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                            }`}>
                              {sc.decision}
                            </span>
                          </div>
                          
                          <div className="flex items-center gap-3">
                            <div className="flex-1 bg-surface-container rounded-full h-1.5 overflow-hidden">
                              <div
                                className="bg-secondary h-full rounded-full"
                                style={{ width: `${Math.min(100, Math.round(sc.similarity_score * 100))}%` }}
                              />
                            </div>
                            <span className="font-mono text-[11px] font-bold text-secondary shrink-0">
                              {(sc.similarity_score * 100).toFixed(1)}% tương đồng
                            </span>
                          </div>

                          {sc.block_scores && (
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 text-[10px] text-on-surface-variant font-mono">
                              {Object.entries(sc.block_scores).map(([bName, bScore]) => {
                                const numScore = typeof bScore === 'number' ? bScore : (bScore as any)?.score ?? 0
                                return (
                                  <span key={bName} className="truncate">
                                    {bName.replace('_shape', '').replace('_pattern', '')}: {(numScore * 100).toFixed(0)}%
                                  </span>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  
                  <p className="text-[10px] text-amber-400/90 pt-1 italic">
                    ⚠️ {similarResult.disclaimer}
                  </p>
                </>
              ) : null}
            </div>
          )}
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
  COUNTERFACTUAL_POLICY_NOT_CALIBRATED: 'Chính sách Counterfactual đang ở chế độ an toàn mặc định (SYNTHETIC_ONLY) do chưa có nhãn hiệu chuẩn từ kỹ sư vận hành (Operator Ground Truth)',
  NO_CLEAR_ALTERNATIVE: 'Không có phương án phân hoạch nào vượt trội rõ rệt trên biên Pareto',
  STRUCTURAL_AUDIT_SKIPPED_SMALL_CHAIN: 'Chuỗi nhỏ (<10 cảnh báo) không áp dụng phân hoạch cấu trúc',
  COUNTERFACTUAL_CONFIG_INCOMPLETE: 'Cấu hình Counterfactual chưa hoàn tất trên baseline v1.yaml. Cần khởi động lại backend để nạp calibrated.yaml',
}

function OperationSection({
  operation,
  recommendationIds,
  feedbacks,
  jobId,
  onFeedbackSubmit,
}: {
  operation: CounterfactualOperation
  recommendationIds: Set<string>
  feedbacks: Record<string, OperatorFeedback>
  jobId?: string
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
            jobId={jobId}
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
  onNavigateToValidation,
  onOpenReviewLearning,
  onOpenManualSplit,
}: {
  chainId: string
  initialJob?: CounterfactualJob | null
  initialFeedbacks?: Record<string, OperatorFeedback>
  /** Assistant navigation may only display persisted results; it never starts Review. */
  readOnly?: boolean
  onNavigateToValidation?: () => void
  onOpenReviewLearning?: () => void
  onOpenManualSplit?: () => void
}) {
  const [job, setJob] = useState<CounterfactualJob | null>(initialJob)
  const [feedbacks, setFeedbacks] = useState<Record<string, OperatorFeedback>>(initialFeedbacks)
  const [manualFeedbacks, setManualFeedbacks] = useState<OperatorFeedback[]>([])
  const [loading, setLoading] = useState(initialJob == null)
  const [error, setError] = useState<string | null>(null)
  const [noPersistedReview, setNoPersistedReview] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [showClarityModal, setShowClarityModal] = useState(false)

  useEffect(() => {
    if (initialJob?.chain_id === chainId) return
    const controller = new AbortController()
    async function load() {
      setNoPersistedReview(false)
      setError(null)
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
          if (current.chain_id !== chainId || current.identity.chain_id !== chainId) {
            setError('REVIEW_CONTEXT_MISMATCH')
            return
          }
          setJob(current)
          setError(null)
          // Also fetch existing feedbacks for this job
          if (current.job_id) {
            api.reviewFeedback(current.job_id, controller.signal)
              .then((list) => {
                if (!controller.signal.aborted) {
                  const map: Record<string, OperatorFeedback> = {}
                  const manuals: OperatorFeedback[] = []
                  for (const fb of list) {
                    if (fb.candidate_id) {
                      map[fb.candidate_id] = fb
                    }
                    if (fb.decision === 'MANUAL_CORRECTION' || fb.has_manual_correction) {
                      manuals.push(fb)
                    }
                  }
                  setFeedbacks(map)
                  setManualFeedbacks(manuals)
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
  }, [chainId, initialJob, readOnly, reloadKey])

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
    _operatorId?: string,
    reason?: string,
  ) => {
    if (!job?.job_id) return
    const fb = await api.submitReviewFeedback(job.job_id, {
      candidate_id: candidateId,
      decision,
      reason,
    })
    setFeedbacks((prev) => ({ ...prev, [candidateId]: fb }))
  }

  if (loading && !job) return <section className="review-shell review-loading"><span /><p>Evaluating bounded alternatives…</p></section>
  if (error) return (
    <section className="review-shell review-unavailable" role="alert">
      <span>UNAVAILABLE</span>
      <h2>Counterfactual review could not be loaded.</h2>
      <p>{error}</p>
      <button
        type="button"
        onClick={() => {
          setError(null)
          setLoading(true)
          setReloadKey((k) => k + 1)
        }}
        className="mt-3 inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-secondary text-[#070e1d] font-bold text-xs hover:brightness-110 cursor-pointer transition-all shadow-sm"
      >
        <span className="material-symbols-outlined text-[16px]">refresh</span>
        <span>Thử lại (Retry)</span>
      </button>
    </section>
  )
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
    ? ['REMOVE_MEMBER', 'SPLIT_CHAIN', 'MOVE_MEMBER', 'MERGE_CHAINS', 'ADD_MEMBER']
        .map((operation) => {
          const summary = result.operation_status?.[operation]
          if (!summary) return null
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
        .filter((item): item is CounterfactualOperation => item !== null)
    : [result.remove, result.split, result.move, result.merge].filter(Boolean) as CounterfactualOperation[]
  return (
    <section className="review-shell">
      <header className="review-heading">
        <div>
          <p className="kicker">Review-only · {result.identity.engine_version}</p>
          <h2>Counterfactual chain review</h2>
          <p>Compare exact, bounded partition alternatives. This analysis does not change the NocPro grouping.</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
            {onOpenManualSplit && !readOnly && (
              <button
                type="button"
                onClick={onOpenManualSplit}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 transition-colors cursor-pointer"
                title="Tự định nghĩa phương án phân tách chuỗi sự cố thủ công"
              >
                <span className="material-symbols-outlined text-[15px]">alt_route</span>
                <span>✂️ Tự Tách Chuỗi</span>
              </button>
            )}
            {onOpenReviewLearning && (
              <button
                type="button"
                onClick={onOpenReviewLearning}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 transition-colors cursor-pointer"
                title="Xem bảng quản trị mô hình XGBRanker và active learning"
              >
                <span className="material-symbols-outlined text-[15px]">psychology</span>
                <span>🎯 XGBRanker v1 Model</span>
              </button>
            )}
            <span className={`review-state review-state--${result.recommendation_status.toLowerCase()}`}>{result.recommendation_status}</span>
          </div>
          <small>{result.identity.config_version}</small>
        </div>
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
      {result.recommendation_status === 'UNAVAILABLE' && (result.reason === 'COUNTERFACTUAL_POLICY_NOT_CALIBRATED' || result.reason === 'COUNTERFACTUAL_CONFIG_INCOMPLETE') ? (
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
            <strong>💡 Chế độ an toàn mặc định ({result.reason}):</strong>{' '}
            {result.reason === 'COUNTERFACTUAL_CONFIG_INCOMPLETE'
              ? 'Tệp cấu hình đang chạy (v1.yaml) chưa bật bộ thông số Counterfactual. Hãy tắt và bật lại dev server (`make dev`) để nạp cấu hình `calibrated.yaml` đã được hiệu chuẩn.'
              : 'Chính sách Counterfactual hiện đang chạy cấu hình mặc định (SYNTHETIC_ONLY). Do chưa có bộ nhãn phản hồi thực tế từ kỹ sư vận hành (Operator Ground Truth), hệ thống tự động khóa an toàn các đề xuất phân hoạch trên dữ liệu mạng thực tế để tránh can thiệp ngoài kiểm chứng.'}
          </div>
          {onNavigateToValidation && (
            <button
              type="button"
              onClick={onNavigateToValidation}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.375rem',
                padding: '0.375rem 0.75rem',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: '#070e1d',
                backgroundColor: '#38bdf8',
                borderRadius: '0.375rem',
                border: 'none',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>verified</span>
              <span>Đi đến Ký duyệt</span>
            </button>
          )}
        </div>
      ) : null}
      {/* Top Recommended Proposals Spotlight */}
      {result.recommendations.length > 0 ? (
        <section className="review-recommended-section" aria-label="Top recommended proposals">
          <header className="review-recommended-header">
            <div className="review-recommended-title">
              <span className="material-symbols-outlined review-recommended-star" aria-hidden="true">
                auto_awesome
              </span>
              <div>
                <h3>⭐ Đề xuất Phân hoạch Được Khuyến nghị (Top Recommended Proposals)</h3>
                <p>
                  Phương án tối ưu trên biên Pareto (tính toán chính xác Trước vs Sau). Phản hồi của kỹ sư sẽ được lưu làm căn cứ đánh giá.
                </p>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              {onOpenManualSplit && !readOnly && (
                <button
                  type="button"
                  className="action-btn"
                  onClick={onOpenManualSplit}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    backgroundColor: 'rgba(6, 182, 212, 0.15)',
                    border: '1px solid rgba(6, 182, 212, 0.4)',
                    color: '#22d3ee',
                    padding: '0.35rem 0.85rem',
                    borderRadius: '6px',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  title="Kỹ sư tự chọn các cảnh báo và định nghĩa chuỗi phân tách mới theo ý muốn"
                >
                  ✂️ Tự Tách Chuỗi Thủ Công
                </button>
              )}
              <button
                type="button"
                className="action-btn"
                onClick={() => setShowClarityModal(true)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  backgroundColor: 'rgba(56, 189, 248, 0.15)',
                  border: '1px solid rgba(56, 189, 248, 0.4)',
                  color: '#38bdf8',
                  padding: '0.35rem 0.85rem',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
                title="So sánh trực tiếp lời giải thích giữa các đề xuất để xem đề xuất nào rõ ràng và thuyết phục hơn"
              >
                ⚖️ So Sánh Lời Giải Thích Giữa Các Đề Xuất
              </button>
              <span className="review-recommended-count">
                {result.recommendations.length} đề xuất
              </span>
            </div>
          </header>
          <div className="review-candidate-list">
            {(result.evaluated_candidates ?? [])
              .filter((c) => recommendationIds.has(c.candidate_id))
              .map((candidate) => (
                <CandidateCard
                  key={`top-recommended-${candidate.candidate_id}`}
                  candidate={candidate}
                  recommended={true}
                  feedback={feedbacks[candidate.candidate_id]}
                  jobId={job.job_id}
                  onFeedbackSubmit={readOnly ? undefined : handleFeedbackSubmit}
                />
              ))}
          </div>
        </section>
      ) : result.recommendation_status === 'AVAILABLE' ? (
        <div className="review-optimal-section" role="status" aria-label="Optimal chain cohesion">
          <div className="review-optimal-icon" aria-hidden="true">✓</div>
          <div className="review-optimal-text">
            <h4>Chuỗi có độ gắn kết cao và cấu trúc thuần nhất (Optimal Partition Cohesion)</h4>
            <p>
              Toàn bộ các cảnh báo trong chuỗi đều liên kết chặt chẽ qua các mối quan hệ tô-pô mạng và chuỗi kiểm toán sự cố. Không phát hiện cảnh báo rời rạc (WEAK) hay thành phần phân mảnh. Hệ thống không khuyến nghị phân tách, loại bỏ hay di chuyển cảnh báo nào.
            </p>
            {onOpenManualSplit && !readOnly && (
              <div style={{ marginTop: '0.6rem' }}>
                <button
                  type="button"
                  onClick={onOpenManualSplit}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    backgroundColor: 'rgba(6, 182, 212, 0.15)',
                    border: '1px solid rgba(6, 182, 212, 0.4)',
                    color: '#22d3ee',
                    padding: '0.35rem 0.75rem',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                  title="Tự định nghĩa phân hoạch tách chuỗi theo nhận định kỹ sư"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>alt_route</span>
                  <span>✂️ Thiết lập phương án tách thủ công theo nhận định kỹ sư</span>
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {/* Manual Corrections Section */}
      {manualFeedbacks.length > 0 && (
        <section
          className="review-manual-corrections-section"
          style={{
            margin: '1.25rem 0',
            padding: '1rem 1.25rem',
            borderRadius: '10px',
            background: 'rgba(6, 182, 212, 0.07)',
            border: '1px solid rgba(6, 182, 212, 0.35)',
          }}
          aria-label="Manual partitions by operators"
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="material-symbols-outlined" style={{ color: '#22d3ee', fontSize: '20px' }}>
                alt_route
              </span>
              <strong style={{ color: '#e2e8f0', fontSize: '0.95rem' }}>
                Phân Hoạch Do Kỹ Sư Tự Định Nghĩa ({manualFeedbacks.length} phương án đã lưu)
              </strong>
            </div>
            <span style={{ fontSize: '0.75rem', color: '#22d3ee', fontWeight: 600 }}>
              ✓ PO-asserted Ground Truth
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {manualFeedbacks.map((fb) => (
              <div
                key={fb.feedback_id}
                style={{
                  padding: '0.75rem 1rem',
                  borderRadius: '8px',
                  background: '#070e1d',
                  border: '1px solid #1e293b',
                  fontSize: '0.8rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: 'rgba(6, 182, 212, 0.2)',
                        color: '#22d3ee',
                        fontWeight: 700,
                        fontSize: '0.75rem',
                        border: '1px solid rgba(6, 182, 212, 0.4)',
                      }}
                    >
                      {fb.operation || 'MANUAL_SPLIT'}
                    </span>
                    <span style={{ color: '#94a3b8' }}>
                      Kỹ sư: <strong style={{ color: '#f8fafc' }}>{fb.operator_id}</strong>
                    </span>
                  </div>
                  <span style={{ color: '#64748b', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                    {fb.created_at ? new Date(fb.created_at).toLocaleString() : ''}
                  </span>
                </div>
                {fb.reason && (
                  <p style={{ margin: '0.35rem 0', color: '#cbd5e1', fontStyle: 'italic' }}>
                    “{fb.reason}”
                  </p>
                )}
                {fb.partition_delta?.after && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                    {Array.isArray(fb.partition_delta.after)
                      ? fb.partition_delta.after.map(([pId, alarms]) => (
                          <div
                            key={pId}
                            style={{
                              padding: '0.3rem 0.6rem',
                              borderRadius: '4px',
                              background: '#0f172a',
                              border: '1px solid #334155',
                              fontFamily: 'monospace',
                              fontSize: '0.75rem',
                            }}
                          >
                            <span style={{ color: '#38bdf8' }}>{pId}</span>: <strong>{alarms.length} cảnh báo</strong>
                          </div>
                        ))
                      : Object.entries(fb.partition_delta.after).map(([pId, alarms]) => (
                          <div
                            key={pId}
                            style={{
                              padding: '0.3rem 0.6rem',
                              borderRadius: '4px',
                              background: '#0f172a',
                              border: '1px solid #334155',
                              fontFamily: 'monospace',
                              fontSize: '0.75rem',
                            }}
                          >
                            <span style={{ color: '#38bdf8' }}>{pId}</span>: <strong>{(alarms as unknown[]).length} cảnh báo</strong>
                          </div>
                        ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="review-operation-grid">
        {operations.map((operation) => (
          <OperationSection
            key={operation.operation}
            operation={operation}
            recommendationIds={recommendationIds}
            feedbacks={feedbacks}
            jobId={job.job_id}
            onFeedbackSubmit={readOnly ? undefined : handleFeedbackSubmit}
          />
        ))}
      </div>
      <footer className="review-provenance">
        <span>Snapshot {result.identity.snapshot_id}@{result.identity.snapshot_version}</span>
        <span>{result.frontier?.count_before_limit ?? result.frontier_count_before_limit} frontier candidates{(result.frontier?.truncated ?? result.frontier_truncated) ? ' · bounded for display' : ''}</span>
        <span>Artifact {job.cache_fingerprint.slice(0, 12)}</span>
      </footer>
      {showClarityModal && job && (
        <ExplainClarityComparisonModal
          isOpen={showClarityModal}
          onClose={() => setShowClarityModal(false)}
          mode="proposals"
          jobId={job.job_id}
        />
      )}
    </section>
  )
}
