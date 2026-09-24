import { useEffect, useState, useRef } from 'react'

import { api, ApiError } from './api'
import { ExplainClarityComparisonModal } from './components/ExplainClarityComparisonModal'
import { percent } from './format'
import {
  generatePartitionTicketReport,
  downloadPartitionDiffJson,
  copyToClipboard,
} from './partitionExport'
import type {
  CounterfactualCandidate,
  CounterfactualJob,
  CounterfactualMetricVector,
  CounterfactualOperation,
  OperatorFeedback,
  SimilarCaseRetrievalResult,
} from './types'
import { isReviewApproved } from './types'
import { getConciseCandidateTitle } from './reviewPresentation'
import { getCachedReviewJob, setCachedReviewJob } from './reviewJobCache'

const metricLabels: Array<[keyof CounterfactualMetricVector, string]> = [
  ['weak_member_count', 'Số cảnh báo yếu (Weak)'],
  ['minimum_membership_support', 'Độ hỗ trợ tối thiểu (Min Support)'],
  ['evidence_union_coverage', 'Độ phủ chứng cứ (Union Coverage)'],
  ['component_count', 'Số thành phần liên thông'],
  ['audit_conductance', 'Độ dẫn Conductance (Phi)'],
  ['audit_verdict_severity', 'Mức độ nghiêm trọng kiểm toán'],
  ['eligible_external_contradiction_count', 'Mâu thuẫn kiểm định'],
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
  onFeedbackRetract,
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
    supersedesFeedbackId?: string,
  ) => Promise<void>
  onFeedbackRetract?: (candidateId: string, feedbackId: string) => Promise<void>
}) {
  const status = candidate.evaluation_status ?? candidate.status ?? 'NOT_EVALUATED'
  const rejectionReason = candidate.hard_gate_result?.reason ?? candidate.reason
  const isRejected = candidate.hard_gate_result?.status === 'REJECTED'
    || status === 'HARD_GATE_REJECTED'
    || status === 'EXTERNALLY_CONTRADICTED'
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
  const [retracting, setRetracting] = useState(false)

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
    setReason(feedback?.reason ?? '')
    setShowForm(true)
    setSubmitError(null)
  }

  const handleEdit = () => {
    handleOpenForm(isReviewApproved(feedback?.decision) ? 'APPROVED' : 'REJECTED')
  }

  const handleRetract = async () => {
    if (!feedback || !onFeedbackRetract) return
    if (!window.confirm('Bạn có chắc muốn thu hồi phản hồi của phương án này? Lịch sử audit vẫn được giữ lại.')) return
    setRetracting(true)
    setSubmitError(null)
    try {
      await onFeedbackRetract(candidate.candidate_id, feedback.feedback_id)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Không thể thu hồi phản hồi')
    } finally {
      setRetracting(false)
    }
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
        feedback?.feedback_id,
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
          <strong>{memberIds.join(' · ') || (isRejected ? 'Phương án thử nghiệm đã bị loại' : 'Phương án phân hoạch')}</strong>
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
        <div><small>Hiện tại</small>{candidate.partition_delta.before.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} cảnh báo</span></p>)}</div>
        <i aria-hidden="true">→</i>
        <div><small>{isRejected ? 'Kết quả mô phỏng' : 'Đề xuất'}</small>{candidate.partition_delta.after.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} cảnh báo</span></p>)}</div>
      </div>

      {candidate.comparative_explanation ? (
        <div className="review-comparative" aria-label="Comparative explanation">
          <div className="review-comparative-summary">
            <span className="review-comparative-icon" aria-hidden="true">{isRejected ? '⊘' : '💡'}</span>
            <span>
              {(() => {
                const rawAction = candidate.comparative_explanation.summary_action || ''
                const displayAction = rawAction.includes('theo vết cắt Audit Graph')
                  ? getConciseCandidateTitle(candidate)
                  : rawAction || getConciseCandidateTitle(candidate)
                return isRejected
                  ? `Phương án thử nghiệm đã bị loại: ${displayAction.replace(/^Đề xuất\s*/i, '')}`
                  : displayAction
              })()}
            </span>
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
              <strong>{isRejected ? 'Vì sao bị loại: ' : 'Vì sao đề xuất này tốt hơn: '}</strong>
              {isRejected
                ? `${rejectionReason ?? 'HARD_GATE_REJECTED'} — ${REASON_EXPLANATIONS[rejectionReason ?? ''] ?? 'Phương án không vượt qua điều kiện an toàn hoặc ngưỡng cải thiện vật chất.'}`
                : candidate.comparative_explanation.why_better}
            </p>
            {!isRejected && candidate.comparative_explanation.comparison_points && candidate.comparative_explanation.comparison_points.length > 0 && (
              <ul className="review-comparative-points">
                {candidate.comparative_explanation.comparison_points.map((pt, i) => (
                  <li key={i}>{pt}</li>
                ))}
              </ul>
            )}
            {!isRejected && candidate.comparative_explanation.ai_narrative && (
              <div className="review-comparative-ai">
                <span className="review-comparative-ai-label">🤖 AI Phân tích chuyên sâu:</span>
                <p>{candidate.comparative_explanation.ai_narrative}</p>
              </div>
            )}
          </div>
        </div>
      ) : null}

      <div className="review-ledger" role="table" aria-label="Exact before and after metrics">
        <div className="review-ledger-head" role="row"><span>Chỉ số</span><span>Trước can thiệp</span><span>Sau can thiệp</span></div>
        {metricLabels.map(([name, label]) => (
          <div role="row" key={name}>
            <span>{label}</span>
            <span>{metricValue(name, candidate.before_metrics ?? candidate.before)}</span>
            <strong>{metricValue(name, candidate.after_metrics ?? candidate.after)}</strong>
          </div>
        ))}
      </div>

      {feedback ? (
        <div className={`review-feedback-verdict review-feedback-verdict--${isReviewApproved(feedback.decision) ? 'approved' : 'rejected'}`}>
          <div className="review-feedback-verdict-header">
            <span className="review-feedback-badge">
              {isReviewApproved(feedback.decision) ? '✓ ĐÃ CHẤP THUẬN ĐỀ XUẤT' : '✗ ĐÃ TỪ CHỐI ĐỀ XUẤT'}
            </span>
            <span className="review-feedback-operator">
              Kỹ sư: <strong>{feedback.operator_id}</strong>
            </span>
          </div>
          {feedback.reason ? <p className="review-feedback-reason">“{feedback.reason}”</p> : null}
          {onFeedbackRetract ? (
            <div className="review-feedback-actions">
              <button type="button" className="review-btn-action review-btn-approve" onClick={handleEdit} disabled={retracting}>
                ✎ Sửa đánh giá
              </button>
              <button type="button" className="review-btn-action review-btn-reject" onClick={() => void handleRetract()} disabled={retracting}>
                {retracting ? 'Đang thu hồi…' : '↩ Thu hồi'}
              </button>
            </div>
          ) : null}
        </div>
      ) : onFeedbackSubmit ? (
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
      ) : isRejected ? (
        <div className="review-feedback-non-recommended">
          <small>Phương án này đã bị hard gate loại và không phải khuyến nghị vận hành.</small>
        </div>
      ) : (
        <div className="review-feedback-non-recommended">
          <small>Chế độ xem hiện tại không mở ghi phản hồi vận hành; khi vào chế độ review, mọi phương án đã đánh giá đều có thể được chấp thuận hoặc từ chối.</small>
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
  NO_MATERIAL_IMPROVEMENT: 'Không có chỉ số nào đạt ngưỡng cải thiện đáng kể.',
  PARETO_METRIC_WORSENED: 'Ít nhất một chỉ số bị xấu đi so với trạng thái hiện tại.',
  REQUIRED_METRIC_UNAVAILABLE: 'Thiếu chỉ số bắt buộc để đánh giá phương án một cách an toàn.',
  AUDIT_SEVERITY_WORSENED: 'Mức độ nghiêm trọng của Audit Graph xấu đi sau mô phỏng.',
  EXTERNAL_CONTRADICTION: 'Phương án mâu thuẫn với evidence kiểm định bên ngoài.',
}

function OperationSection({
  operation,
  recommendationIds,
  feedbacks,
  jobId,
  onFeedbackSubmit,
  onFeedbackRetract,
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
    supersedesFeedbackId?: string,
  ) => Promise<void>
  onFeedbackRetract?: (candidateId: string, feedbackId: string) => Promise<void>
}) {
  const activeCandidates = operation.candidates.filter((candidate) => {
    const status = candidate.evaluation_status ?? candidate.status
    return candidate.hard_gate_result?.status !== 'REJECTED'
      && status !== 'HARD_GATE_REJECTED'
      && status !== 'EXTERNALLY_CONTRADICTED'
  })
  const rejectedCandidates = operation.candidates.filter((candidate) => !activeCandidates.includes(candidate))
  return (
    <section className="review-operation-section">
      <header>
        <div><p className="kicker">Thao tác giới hạn</p><h3>{operation.operation}</h3></div>
        <span className={`review-state review-state--${operation.status.toLowerCase()}`}>{operation.status}</span>
      </header>
      <dl className="review-search-diagnostics">
        <div><dt>Đã phát hiện</dt><dd>{operation.discovered_candidate_count}</dd></div>
        <div><dt>Đã đánh giá</dt><dd>{operation.evaluated_candidate_count}</dd></div>
        <div><dt>Đã loại bỏ</dt><dd>{operation.rejected_candidate_count}</dd></div>
        <div><dt>Giới hạn trần</dt><dd>{operation.candidate_limit ?? '⊥'}</dd></div>
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
        {activeCandidates.map((candidate) => (
          <CandidateCard
            key={candidate.candidate_id}
            candidate={candidate}
            recommended={recommendationIds.has(candidate.candidate_id)}
            feedback={feedbacks[candidate.candidate_id]}
            jobId={jobId}
            onFeedbackSubmit={onFeedbackSubmit}
            onFeedbackRetract={onFeedbackRetract}
          />
        ))}
        {rejectedCandidates.length > 0 ? (
          <details className="review-rejected-alternatives">
            <summary>{rejectedCandidates.length} phương án đã bị loại · xem bằng chứng hard gate</summary>
            <div className="review-candidate-list mt-2">
              {rejectedCandidates.map((candidate) => (
                <CandidateCard
                  key={candidate.candidate_id}
                  candidate={candidate}
                  recommended={false}
                  feedback={feedbacks[candidate.candidate_id]}
                  jobId={jobId}
                  onFeedbackSubmit={onFeedbackSubmit}
                  onFeedbackRetract={onFeedbackRetract}
                />
              ))}
            </div>
          </details>
        ) : null}
        {operation.status === 'AVAILABLE' && activeCandidates.length === 0 && rejectedCandidates.length === 0 ? <p className="review-empty">Không có phương án phân hoạch nào vượt qua chính sách kích hoạt.</p> : null}
      </div>
    </section>
  )
}

export function CounterfactualLoadingView({
  progressPercent,
  status,
  error,
  message = 'Đang đánh giá các phương án phân hoạch đối chứng…',
}: {
  progressPercent?: number | null
  status?: string | null
  error?: string | null
  message?: string
}) {
  const hasPercent = typeof progressPercent === 'number' && progressPercent >= 0

  return (
    <section className="review-shell review-loading" role="status" aria-label="Đang tải Counterfactual">
      <div className="cf-loading-card">
        <div className="cf-loading-header">
          <div className="cf-loading-icon-wrap">
            <span className="material-symbols-outlined cf-loading-icon">alt_route</span>
          </div>
          <div className="cf-loading-titles">
            <h3 className="cf-loading-title">Phân tích Phân hoạch Đối chứng (Counterfactual What-If)</h3>
            <p className="cf-loading-subtitle">{status ? `Trạng thái: ${status}` : message}</p>
          </div>
        </div>

        {/* The Exact Glowing Gradient Loading Bar */}
        <div className="cf-loading-bar-track">
          <div
            className={`cf-loading-bar ${hasPercent ? 'is-determinate' : 'is-indeterminate'}`}
            style={hasPercent ? { width: `${Math.max(6, Math.min(100, progressPercent))}%` } : undefined}
          />
        </div>

        <div className="cf-loading-footer">
          <span className="cf-loading-step">
            <span className="cf-pulse-dot" />
            <span>{status || 'Đang mô phỏng đột biến REMOVE, SPLIT, MOVE, MERGE & Pareto frontier…'}</span>
          </span>
          {hasPercent && (
            <span className="cf-loading-percent">{progressPercent}%</span>
          )}
        </div>

        {error ? <small className="cf-loading-error">{error}</small> : null}
      </div>
    </section>
  )
}

export function CounterfactualReview({
  chainId,
  snapshotId,
  snapshotVersion,
  topologyVersion,
  initialJob = null,
  initialFeedbacks = {},
  readOnly = false,
  hideHeader = false,
  onNavigateToValidation: _onNavigateToValidation,
  onOpenReviewLearning,
  onOpenManualSplit,
  onReviewSucceeded,
  onFeedbackSubmit: onFeedbackSubmitOverride,
  onFeedbackRetract: onFeedbackRetractOverride,
}: {
  chainId: string
  snapshotId?: string | null
  snapshotVersion?: string | null
  topologyVersion?: string | null
  initialJob?: CounterfactualJob | null
  initialFeedbacks?: Record<string, OperatorFeedback>
  /** Hosts may explicitly request a read-only view; normal app navigation keeps review actions enabled. */
  readOnly?: boolean
  hideHeader?: boolean
  onNavigateToValidation?: () => void
  onOpenReviewLearning?: () => void
  onOpenManualSplit?: () => void
  onReviewSucceeded?: (job: CounterfactualJob) => void
  /** Optional injection for review hosts/tests; normal usage persists through the built-in API handlers. */
  onFeedbackSubmit?: (
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    operatorId?: string,
    reason?: string,
    supersedesFeedbackId?: string,
  ) => Promise<void>
  onFeedbackRetract?: (candidateId: string, feedbackId: string) => Promise<void>
}) {
  const initialJobMatchesContext = initialJob != null
    && initialJob.chain_id === chainId
    && initialJob.identity?.chain_id === chainId
    && (!snapshotId || initialJob.identity?.snapshot_id === snapshotId)
    && (!snapshotVersion || initialJob.identity?.snapshot_version === snapshotVersion)
    && (topologyVersion === undefined || initialJob.identity?.topology_version === topologyVersion)
  const cachedInitial = initialJobMatchesContext
    ? initialJob
    : getCachedReviewJob(chainId, snapshotId, snapshotVersion, topologyVersion)
  const [job, setJob] = useState<CounterfactualJob | null>(cachedInitial)
  const [feedbacks, setFeedbacks] = useState<Record<string, OperatorFeedback>>(initialFeedbacks)
  const [manualFeedbacks, setManualFeedbacks] = useState<OperatorFeedback[]>([])
  const [loading, setLoading] = useState(cachedInitial == null)
  const [error, setError] = useState<string | null>(null)
  const [noPersistedReview, setNoPersistedReview] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [showClarityModal, setShowClarityModal] = useState(false)
  const [retractingFeedbackId, setRetractingFeedbackId] = useState<string | null>(null)
  const [copiedFeedbackId, setCopiedFeedbackId] = useState<string | null>(null)
  const [retractStatusMsg, setRetractStatusMsg] = useState<string | null>(null)
  const pollRetryCountRef = useRef(0)
  const notifiedReviewJobIdRef = useRef<string | null>(null)

  const handleUndoManualCorrection = async (feedbackId: string) => {
    if (!job?.job_id) return
    if (!window.confirm('Bạn có chắc chắn muốn hủy (Undo / Retract) phương án phân hoạch này?')) {
      return
    }
    try {
      setRetractingFeedbackId(feedbackId)
      setRetractStatusMsg(null)
      await api.retractFeedback(job.job_id, feedbackId, 'Kỹ sư hủy phương án phân hoạch thủ công', {
        'X-Dev-Operator-Id': 'viettel_operator',
        'X-Dev-Operator-Role': 'PRODUCT_OWNER',
        'X-Dev-Domain-Scope': 'IP_NETWORK',
      })
      setManualFeedbacks((prev) => prev.filter((fb) => fb.feedback_id !== feedbackId))
      setFeedbacks((prev) => {
        const next = { ...prev }
        for (const [candidateId, feedback] of Object.entries(next)) {
          if (feedback.feedback_id === feedbackId) delete next[candidateId]
        }
        return next
      })
      setRetractStatusMsg('Đã hủy thành công phương án phân hoạch.')
      setTimeout(() => setRetractStatusMsg(null), 3500)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Không thể hủy phương án phân hoạch')
    } finally {
      setRetractingFeedbackId(null)
    }
  }

  const handleCopyReport = async (fb: OperatorFeedback) => {
    const report = generatePartitionTicketReport({
      chainId,
      operation: fb.operation || 'MANUAL_SPLIT',
      operatorId: fb.operator_id || 'operator',
      createdAt: fb.created_at || undefined,
      reasonCode: fb.reason_codes?.[0] || fb.reason || 'MANUAL_TOPOLOGY_SPLIT',
      notes: fb.reason || undefined,
      partitionDelta: fb.partition_delta,
    })
    const success = await copyToClipboard(report)
    if (success) {
      setCopiedFeedbackId(fb.feedback_id)
      setTimeout(() => setCopiedFeedbackId(null), 2500)
    }
  }

  const handleDownloadJson = (fb: OperatorFeedback) => {
    downloadPartitionDiffJson({
      chainId,
      operation: fb.operation || 'MANUAL_SPLIT',
      operatorId: fb.operator_id || 'operator',
      createdAt: fb.created_at || undefined,
      reasonCode: fb.reason_codes?.[0] || fb.reason || 'MANUAL_TOPOLOGY_SPLIT',
      notes: fb.reason || undefined,
      partitionDelta: fb.partition_delta,
    })
  }

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      setNoPersistedReview(false)
      setError(null)
      try {
        let current: CounterfactualJob
        if (initialJobMatchesContext && initialJob) {
          // Hosts such as the chain shell can provide the already-loaded job.
          // Still fetch its persisted feedback; previously this early-return
          // skipped that request, so edit/retract controls disappeared after
          // navigation or a refresh.
          current = initialJob
        } else {
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
        }
        if (!controller.signal.aborted) {
          if (
            current.chain_id !== chainId
            || current.identity.chain_id !== chainId
            || (snapshotId && current.identity.snapshot_id !== snapshotId)
            || (snapshotVersion && current.identity.snapshot_version !== snapshotVersion)
            || (topologyVersion !== undefined && current.identity.topology_version !== topologyVersion)
          ) {
            setError('REVIEW_CONTEXT_MISMATCH')
            return
          }
          setJob(current)
          setCachedReviewJob(chainId, snapshotId, snapshotVersion, topologyVersion, current)
          if (current.status === 'SUCCEEDED' && notifiedReviewJobIdRef.current !== current.job_id) {
            notifiedReviewJobIdRef.current = current.job_id
            onReviewSucceeded?.(current)
          }
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
  }, [chainId, snapshotId, snapshotVersion, topologyVersion, initialJob, onReviewSucceeded, readOnly, reloadKey])

  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) {
      pollRetryCountRef.current = 0
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.reviewJob(job.job_id, controller.signal)
        .then((nextJob) => {
          if (controller.signal.aborted) return
          if (
            nextJob.chain_id !== chainId
            || nextJob.identity.chain_id !== chainId
            || (snapshotId && nextJob.identity.snapshot_id !== snapshotId)
            || (snapshotVersion && nextJob.identity.snapshot_version !== snapshotVersion)
            || (topologyVersion !== undefined && nextJob.identity.topology_version !== topologyVersion)
          ) {
            setError('REVIEW_CONTEXT_MISMATCH')
            return
          }
          pollRetryCountRef.current = 0
          setJob(nextJob)
          setCachedReviewJob(chainId, snapshotId, snapshotVersion, topologyVersion, nextJob)
          if (nextJob.status === 'SUCCEEDED' && notifiedReviewJobIdRef.current !== nextJob.job_id) {
            notifiedReviewJobIdRef.current = nextJob.job_id
            onReviewSucceeded?.(nextJob)
          }
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return
          pollRetryCountRef.current += 1
          if (pollRetryCountRef.current <= 3) {
            // Transient retry while backend is computing or flushing
            setJob((prev) => (prev ? { ...prev } : prev))
          } else {
            setError(cause instanceof Error ? cause.message : 'Review polling failed')
          }
        })
    }, 450)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [chainId, snapshotId, snapshotVersion, topologyVersion, job, onReviewSucceeded])

  const handleFeedbackSubmit = async (
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    _operatorId?: string,
    reason?: string,
    supersedesFeedbackId?: string,
  ) => {
    if (!job?.job_id) return
    const payload = {
      candidate_id: candidateId,
      decision,
      reason,
    }
    const fb = supersedesFeedbackId
      ? await api.supersedeFeedback(job.job_id, supersedesFeedbackId, payload)
      : await api.submitReviewFeedback(job.job_id, payload)
    setFeedbacks((prev) => ({ ...prev, [candidateId]: fb }))
  }

  const handleFeedbackRetract = async (candidateId: string, feedbackId: string) => {
    if (!job?.job_id) return
    await api.retractFeedback(job.job_id, feedbackId, 'Người dùng thu hồi phản hồi phương án')
    setFeedbacks((prev) => {
      const next = { ...prev }
      delete next[candidateId]
      return next
    })
  }

  if (loading && !job) return (
    <CounterfactualLoadingView
      message="Đang đánh giá các phương án phân hoạch đối chứng…"
    />
  )
  if (error) return (
    <section className="review-shell review-unavailable" role="alert">
      <span>UNAVAILABLE</span>
      <h2>Không thể tải kết quả đối chứng Counterfactual.</h2>
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
        <span>Thử lại</span>
      </button>
    </section>
  )
  if (noPersistedReview) return (
    <section className="review-shell review-unavailable">
      <span>NOT_RUN</span>
      <h2>Chưa có kết quả Counterfactual được lưu trữ.</h2>
      <p>Chưa có tác vụ Review đã lưu cho chuỗi này. Hãy mở Review để chạy đánh giá các phương án phân hoạch.</p>
    </section>
  )
  if (!job) return null
  if (!job.result) return (
    <CounterfactualLoadingView
      progressPercent={job.progress_percent}
      status={job.status}
      error={job.error}
    />
  )

  const result = job.result
  const feedbackSubmit = readOnly ? undefined : (onFeedbackSubmitOverride ?? handleFeedbackSubmit)
  const feedbackRetract = readOnly ? undefined : (onFeedbackRetractOverride ?? handleFeedbackRetract)
  const recommendationIds = new Set(result.recommendations.map((item) => item.candidate_id))
  const evaluatedCandidates = result.evaluated_candidates ?? []
  const isRejectedCandidate = (candidate: CounterfactualCandidate) => {
    const status = candidate.evaluation_status ?? candidate.status
    return candidate.hard_gate_result?.status === 'REJECTED'
      || status === 'HARD_GATE_REJECTED'
      || status === 'EXTERNALLY_CONTRADICTED'
  }
  const rejectedCandidateCount = evaluatedCandidates.filter(isRejectedCandidate).length
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
            rejected_candidate_count: (result.evaluated_candidates ?? []).filter(
              (item) => item.operation === operation && isRejectedCandidate(item)
            ).length,
            candidate_limit: summary.ceiling,
            candidates: (result.evaluated_candidates ?? []).filter((item) => item.operation === operation),
          }
        })
        .filter((item): item is CounterfactualOperation => item !== null)
    : [result.remove, result.split, result.move, result.merge].filter(Boolean) as CounterfactualOperation[]
  return (
    <section className="review-shell">
      {!hideHeader && (
        <>
          <header className="review-heading">
            <div>
              <p className="kicker">Review-only · {result.identity.engine_version}</p>
              <h2>Counterfactual chain review</h2>
              <p>So sánh chính xác các phương án phân hoạch đối chứng. Phân tích này không làm thay đổi gom nhóm thực tế trên NocPro.</p>
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
                <span className={`review-state review-state--${result.recommendation_status.toLowerCase()}`}>
                  {job.status === 'SUCCEEDED' && result.recommendation_status === 'UNAVAILABLE'
                    ? 'ANALYSIS COMPLETE · RECOMMENDATION LOCKED'
                    : result.recommendation_status}
                </span>
              </div>
              <small>{result.identity.config_version}</small>
            </div>
          </header>
          <div className="review-safety-notice"><strong>Proposal only</strong><span>NocPro was not changed. Không có phương án nào được tự động áp dụng.</span></div>
        </>
      )}
      {job.status === 'SUCCEEDED' ? (
        <div className="mx-5 my-3 p-3 rounded-lg border border-[#28415f] bg-[#0b1625] text-xs text-on-surface" role="status">
          <strong>Counterfactual đã chạy xong.</strong>{' '}
          Đã đánh giá {evaluatedCandidates.length || operations.reduce((sum, item) => sum + item.evaluated_candidate_count, 0)} phương án;
          {' '}{rejectedCandidateCount || operations.reduce((sum, item) => sum + item.rejected_candidate_count, 0)} phương án đã bị loại.
          {result.recommendation_status === 'UNAVAILABLE'
            ? ' Không có khuyến nghị đủ điều kiện để trình vận hành; khóa calibration không làm mất kết quả đánh giá đã tính.'
            : ''}
        </div>
      ) : null}
      {result.reason ? (
        <p className="review-global-reason" title={REASON_EXPLANATIONS[result.reason] ?? result.reason}>
          <span className="review-reason-code">{result.reason}</span>
          {REASON_EXPLANATIONS[result.reason] ? (
            <span className="review-reason-desc"> — {REASON_EXPLANATIONS[result.reason]}</span>
          ) : null}
        </p>
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
                  Phương án tối ưu trên biên Pareto (tính toán chính xác Trước vs Sau can thiệp). Phản hồi của kỹ sư sẽ được lưu làm căn cứ đánh giá.
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
                  onFeedbackSubmit={feedbackSubmit}
                  onFeedbackRetract={feedbackRetract}
                />
              ))}
          </div>
        </section>
      ) : result.recommendation_status === 'AVAILABLE' ? (
        <div className="review-optimal-section" role="alert" aria-label="Counterfactual contract inconsistency">
          <div className="review-optimal-icon" aria-hidden="true">!</div>
          <div className="review-optimal-text">
            <h4>Kết quả không nhất quán</h4>
            <p>
              Trạng thái AVAILABLE nhưng không có recommendation. Không thể suy ra chuỗi tối ưu, thuần nhất hoặc không cần can thiệp từ contract này.
            </p>
          </div>
        </div>
      ) : result.recommendation_status === 'NO_CLEAR_ALTERNATIVE' ? (
        <div className="review-optimal-section" role="status" aria-label="Bounded counterfactual result">
          <div className="review-optimal-icon" aria-hidden="true">≈</div>
          <div className="review-optimal-text">
            <h4>Không tìm thấy phương án vượt trội rõ ràng</h4>
            <p>
              Kết luận này chỉ áp dụng cho không gian tìm kiếm hữu hạn đã đánh giá; không xác nhận tính tối ưu của chuỗi ngoài phạm vi đó.
            </p>
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
                Phân hoạch do kỹ sư tự định nghĩa ({manualFeedbacks.length} phương án đã lưu)
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
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid #1e293b' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <button
                      type="button"
                      onClick={() => handleCopyReport(fb)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        padding: '0.25rem 0.6rem',
                        borderRadius: '5px',
                        background: copiedFeedbackId === fb.feedback_id ? 'rgba(16, 185, 129, 0.2)' : 'rgba(56, 189, 248, 0.12)',
                        border: copiedFeedbackId === fb.feedback_id ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(56, 189, 248, 0.3)',
                        color: copiedFeedbackId === fb.feedback_id ? '#34d399' : '#38bdf8',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                      title="Sao chép nội dung báo cáo phân hoạch để dán vào Ticket NOC (Jira/ITSM)"
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>
                        {copiedFeedbackId === fb.feedback_id ? 'check' : 'content_copy'}
                      </span>
                      <span>{copiedFeedbackId === fb.feedback_id ? 'Đã sao chép Ticket!' : '📋 Sao chép Ticket'}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDownloadJson(fb)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        padding: '0.25rem 0.6rem',
                        borderRadius: '5px',
                        background: 'rgba(148, 163, 184, 0.12)',
                        border: '1px solid rgba(148, 163, 184, 0.3)',
                        color: '#cbd5e1',
                        fontSize: '0.75rem',
                        fontWeight: 500,
                        cursor: 'pointer',
                      }}
                      title="Tải file JSON diff đính kèm ticket"
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>download</span>
                      <span>📥 Tải JSON Diff</span>
                    </button>
                  </div>
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => handleUndoManualCorrection(fb.feedback_id)}
                      disabled={retractingFeedbackId === fb.feedback_id}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        padding: '0.25rem 0.6rem',
                        borderRadius: '5px',
                        background: 'rgba(244, 63, 94, 0.12)',
                        border: '1px solid rgba(244, 63, 94, 0.35)',
                        color: '#fb7185',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        cursor: retractingFeedbackId === fb.feedback_id ? 'not-allowed' : 'pointer',
                      }}
                      title="Hủy phương án này và rút lại khỏi danh sách nhãn duyệt"
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>undo</span>
                      <span>{retractingFeedbackId === fb.feedback_id ? 'Đang hủy...' : '↺ Hủy phương án (Undo)'}</span>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {retractStatusMsg && (
            <div style={{ marginTop: '0.75rem', padding: '0.5rem 0.75rem', borderRadius: '6px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.35)', color: '#34d399', fontSize: '0.8rem' }}>
              ✓ {retractStatusMsg}
            </div>
          )}
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
            onFeedbackSubmit={feedbackSubmit}
            onFeedbackRetract={feedbackRetract}
          />
        ))}
      </div>
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
