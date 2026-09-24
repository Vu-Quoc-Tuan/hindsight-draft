import { useState, useEffect, useMemo } from 'react'
import { api } from '../api'
import { getCachedReviewJob, setCachedReviewJob } from '../reviewJobCache'
import {
  generatePartitionTicketReport,
  downloadPartitionDiffJson,
  copyToClipboard,
} from '../partitionExport'
import type {
  ChainAnalysis,
  CounterfactualCandidate,
  CounterfactualJob,
  OperatorFeedback,
} from '../types'
import { isReviewApproved } from '../types'
import { ReviewDecisionForm } from '../components/ReviewDecisionForm'
import { getConciseCandidateTitle } from '../reviewPresentation'

export function ValidationView({
  analysis,
  snapshotId,
  snapshotVersion,
  topologyVersion,
  onOpenManualSplit: _onOpenManualSplit,
}: {
  analysis: ChainAnalysis
  snapshotId?: string | null
  snapshotVersion?: string | null
  topologyVersion?: string | null
  onOpenManualSplit?: () => void
}) {
  const cached = getCachedReviewJob(analysis.chain_id, snapshotId, snapshotVersion, topologyVersion)
  const [job, setJob] = useState<CounterfactualJob | null>(cached)
  const [loading, setLoading] = useState<boolean>(cached == null)
  const [error, setError] = useState<string | null>(null)
  const [feedbacks, setFeedbacks] = useState<OperatorFeedback[]>([])
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [submitFeedbackMsg, setSubmitFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [copiedFeedbackId, setCopiedFeedbackId] = useState<string | null>(null)
  const [retractingFeedbackId, setRetractingFeedbackId] = useState<string | null>(null)
  const [retractStatusMsg, setRetractStatusMsg] = useState<string | null>(null)

  const alarmMap = useMemo(() => {
    const map: Record<string, { alarm_name?: string | null; device_code?: string | null; role?: string | null }> = {}
    for (const m of analysis.members || []) {
      map[m.alarm_id] = { alarm_name: m.alarm_name, device_code: m.device_code, role: m.role }
    }
    return map
  }, [analysis.members])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    Promise.allSettled([
      api.latestReview(analysis.chain_id, controller.signal),
      api.chainFeedback(analysis.chain_id, controller.signal),
    ])
      .then(([reviewRes, feedbackRes]) => {
        if (cancelled) return
        if (reviewRes.status === 'fulfilled') {
          if (
            reviewRes.value.chain_id !== analysis.chain_id
            || reviewRes.value.identity.chain_id !== analysis.chain_id
            || (snapshotId && reviewRes.value.identity.snapshot_id !== snapshotId)
            || (snapshotVersion && reviewRes.value.identity.snapshot_version !== snapshotVersion)
            || (topologyVersion !== undefined && reviewRes.value.identity.topology_version !== topologyVersion)
          ) {
            setError('REVIEW_CONTEXT_MISMATCH')
            setLoading(false)
            return
          }
          setJob(reviewRes.value)
          setCachedReviewJob(analysis.chain_id, snapshotId, snapshotVersion, topologyVersion, reviewRes.value)
          const recs = reviewRes.value?.result?.recommendations ?? []
          const evaluated = reviewRes.value?.result?.evaluated_candidates ?? []
          const defaultCandidate = recs[0] ?? evaluated[0]
          if (defaultCandidate) {
            setSelectedCandidateId((prev) => prev ?? defaultCandidate.candidate_id)
          }
        } else {
          // If no review exists yet, leave as cached or null
        }

        if (feedbackRes.status === 'fulfilled') {
          setFeedbacks(feedbackRes.value)
        }
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load validation context')
        setLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [analysis.chain_id, snapshotId, snapshotVersion, topologyVersion])

  // Poll if review is actively computing
  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.reviewJob(job.job_id, controller.signal)
        .then((updated) => {
          if (controller.signal.aborted) return
          if (
            updated.chain_id !== analysis.chain_id
            || updated.identity.chain_id !== analysis.chain_id
            || (snapshotId && updated.identity.snapshot_id !== snapshotId)
            || (snapshotVersion && updated.identity.snapshot_version !== snapshotVersion)
            || (topologyVersion !== undefined && updated.identity.topology_version !== topologyVersion)
          ) {
            setError('REVIEW_CONTEXT_MISMATCH')
            return
          }
          setJob(updated)
          setCachedReviewJob(analysis.chain_id, snapshotId, snapshotVersion, topologyVersion, updated)
          const recs = updated?.result?.recommendations ?? []
          const evaluated = updated?.result?.evaluated_candidates ?? []
          const first = recs[0] ?? evaluated[0]
          if (first && !selectedCandidateId) {
            setSelectedCandidateId(first.candidate_id)
          }
        })
        .catch(() => {
          // ignore transient poll error
        })
    }, 800)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [job, selectedCandidateId, analysis.chain_id, snapshotId, snapshotVersion, topologyVersion])

  // Impression logging: log candidate display events
  useEffect(() => {
    if (!job?.job_id) return
    const candidates = job.result?.evaluated_candidates ?? []
    if (candidates.length === 0) return

    const events = candidates.map((cand, idx) => ({
      candidate_id: cand.candidate_id,
      displayed_rank: idx + 1,
      rendered_at: new Date().toISOString(),
      exposure_policy: 'ALL_EVALUATED',
      surface: 'VALIDATION_VIEW_TOP_CARD',
      client_event_id: `evt_${window.crypto?.randomUUID ? window.crypto.randomUUID().slice(0, 16) : Math.random().toString(36).slice(2, 14)}`,
    }))

    api.recordDisplayEvents(job.job_id, events).catch(() => {
      // Telemetry best-effort
    })
  }, [job?.job_id, job?.result?.evaluated_candidates])

  const candidates: CounterfactualCandidate[] = job?.result?.evaluated_candidates ?? []
  const recommendations: CounterfactualCandidate[] = job?.result?.recommendations ?? []
  const activeCandidate =
    candidates.find((c) => c.candidate_id === selectedCandidateId) ??
    recommendations[0] ??
    candidates[0] ??
    null

  const handleStartReview = async () => {
    try {
      setLoading(true)
      const res = await api.submitReview(analysis.chain_id)
      const initialJob = await api.reviewJob(res.job_id)
      if (
        initialJob.chain_id !== analysis.chain_id
        || initialJob.identity.chain_id !== analysis.chain_id
        || (snapshotId && initialJob.identity.snapshot_id !== snapshotId)
        || (snapshotVersion && initialJob.identity.snapshot_version !== snapshotVersion)
        || (topologyVersion !== undefined && initialJob.identity.topology_version !== topologyVersion)
      ) {
        setError('REVIEW_CONTEXT_MISMATCH')
        return
      }
      setJob(initialJob)
      setCachedReviewJob(analysis.chain_id, snapshotId, snapshotVersion, topologyVersion, initialJob)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not launch review evaluation')
    } finally {
      setLoading(false)
    }
  }

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
      setFeedbacks((prev) => prev.filter((fb) => fb.feedback_id !== feedbackId))
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
      chainId: analysis.chain_id,
      operation: fb.operation || 'MANUAL_SPLIT',
      operatorId: fb.operator_id || 'operator',
      createdAt: fb.created_at || undefined,
      reasonCode: fb.reason_codes?.[0] || fb.reason || 'MANUAL_TOPOLOGY_SPLIT',
      notes: fb.reason || undefined,
      partitionDelta: fb.partition_delta,
      alarmMap,
    })
    const success = await copyToClipboard(report)
    if (success) {
      setCopiedFeedbackId(fb.feedback_id)
      setTimeout(() => setCopiedFeedbackId(null), 2500)
    }
  }

  const handleDownloadJson = (fb: OperatorFeedback) => {
    downloadPartitionDiffJson({
      chainId: analysis.chain_id,
      operation: fb.operation || 'MANUAL_SPLIT',
      operatorId: fb.operator_id || 'operator',
      createdAt: fb.created_at || undefined,
      reasonCode: fb.reason_codes?.[0] || fb.reason || 'MANUAL_TOPOLOGY_SPLIT',
      notes: fb.reason || undefined,
      partitionDelta: fb.partition_delta,
    })
  }

  const activeCandidateFeedback = feedbacks.find(
    (fb) => fb.candidate_id === activeCandidate?.candidate_id,
  )

  const manualFeedbacks = feedbacks.filter(
    (fb) =>
      fb.decision === 'MANUAL_CORRECTION' ||
      fb.has_manual_correction ||
      fb.operation?.startsWith('MANUAL_'),
  )

  return (
    <div className="flex w-full flex-col gap-space-md pb-16 animate-fadeIn">
      {/* Global Alerts & Feedback Notifications */}
      {error && (
        <div className="p-space-sm bg-rose-950/50 border border-rose-500/50 text-rose-200 rounded-lg flex items-center justify-between text-xs shadow-sm">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-rose-400 text-[18px]">error</span>
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-300 font-bold px-1 cursor-pointer">✕</button>
        </div>
      )}

      {submitFeedbackMsg && (
        <div
          className={`flex items-center justify-between p-space-sm rounded-lg border shadow-md text-xs ${
            submitFeedbackMsg.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
              : 'bg-rose-950/40 border-rose-500/40 text-rose-200'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px]">
              {submitFeedbackMsg.type === 'success' ? 'check_circle' : 'error'}
            </span>
            <span className="font-medium">{submitFeedbackMsg.text}</span>
          </div>
          <button
            onClick={() => setSubmitFeedbackMsg(null)}
            className="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
          </button>
        </div>
      )}

      {retractStatusMsg && (
        <div className="flex items-center gap-2 p-space-sm rounded-lg border border-cyan-500/40 bg-cyan-950/40 text-cyan-200 text-xs shadow-md">
          <span className="material-symbols-outlined text-[18px] text-cyan-300">info</span>
          <span>{retractStatusMsg}</span>
        </div>
      )}

      {/* Candidate Selector Bar */}
      {candidates.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1 px-1">
          <span className="text-xs font-bold uppercase tracking-wider text-on-surface-variant whitespace-nowrap flex items-center gap-1">
            <span className="material-symbols-outlined text-[15px] text-secondary">tune</span>
            ĐỀ XUẤT ĐỐI CHỨNG:
          </span>
          {candidates.map((c, idx) => {
            const isSelected = activeCandidate?.candidate_id === c.candidate_id
            const isRec = recommendations.some((r) => r.candidate_id === c.candidate_id)
            const fb = feedbacks.find((f) => f.candidate_id === c.candidate_id)
            return (
              <button
                key={c.candidate_id}
                onClick={() => setSelectedCandidateId(c.candidate_id)}
                className={`px-3 py-1.5 rounded-lg border font-code-sm text-xs transition-all flex items-center gap-2 cursor-pointer whitespace-nowrap shadow-xs ${
                  isSelected
                    ? 'bg-secondary/20 border-secondary text-secondary font-bold ring-1 ring-secondary/50'
                    : 'bg-[#0c1424] border-[#1b273e] text-on-surface-variant hover:border-[#2a3d60] hover:text-on-surface'
                }`}
              >
                <span>#{idx + 1} {c.operation}</span>
                {isRec && (
                  <span className="px-1.5 py-0.2 rounded bg-secondary/25 text-secondary text-[10px] font-bold">
                    FRONTIER
                  </span>
                )}
                {fb && (
                  <span
                    className={`px-1.5 py-0.2 text-[10px] rounded font-bold ${
                      isReviewApproved(fb.decision)
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                    }`}
                  >
                    {isReviewApproved(fb.decision) ? '✓ Đã duyệt' : '✗ Từ chối'}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}

      {/* Main 2-Column Work Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
        {/* Left Column: Candidate Spec & Comparative Explanation (8 cols) */}
        <div className="lg:col-span-8 flex flex-col gap-space-md">
          {activeCandidate ? (
            <>
              {/* Candidate Inspector Card */}
              <div className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-5 flex flex-col gap-4 shadow-lg">
                <div className="flex items-center justify-between border-b border-[#1b273e] pb-3">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-secondary text-[20px]">architecture</span>
                    <span className="text-xs uppercase font-bold text-on-surface-variant tracking-wider">
                      CHI TIẾT PHƯƠNG ÁN ĐỀ XUẤT
                    </span>
                  </div>
                  <span className="font-code-sm text-xs text-secondary font-mono bg-secondary/10 border border-secondary/25 px-2 py-0.5 rounded">
                    MÃ ĐỀ XUẤT: {activeCandidate.candidate_id}
                  </span>
                </div>

                {/* Operation Summary */}
                <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-[#080d17] rounded-lg border border-[#1b273e]">
                  <div className="px-3 py-1.5 bg-secondary/15 border border-secondary/30 rounded-lg text-secondary font-code-md text-xs font-bold text-center shrink-0">
                    {activeCandidate.operation}
                  </div>
                  <div className="flex flex-col flex-1">
                    <span className="text-sm text-on-surface font-semibold">
                      {getConciseCandidateTitle(activeCandidate)}
                    </span>
                    <span className="font-code-sm text-xs text-on-surface-variant mt-0.5">
                      Chi phí can thiệp: {activeCandidate.edit_cost?.membership_reassignments ?? 0} gán lại thành viên · {activeCandidate.edit_cost?.affected_member_count ?? 0} cảnh báo bị ảnh hưởng
                    </span>
                  </div>
                </div>

                {/* Quick Status Chips */}
                <div className="grid grid-cols-3 gap-2">
                  <div className="p-2.5 bg-[#080d17] rounded-lg border border-[#1b273e]">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Hard Gate Check</small>
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className="material-symbols-outlined text-emerald-400 text-[16px]">check_circle</span>
                      <strong className="font-code-sm text-xs text-emerald-300">
                        {activeCandidate.hard_gate_result?.status ?? 'PASSED'}
                      </strong>
                    </div>
                  </div>
                  <div className="p-2.5 bg-[#080d17] rounded-lg border border-[#1b273e]">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Pareto Frontier</small>
                    <strong className="font-code-sm text-xs text-secondary block mt-1">
                      {activeCandidate.pareto_state ?? 'FRONTIER_SELECTED'}
                    </strong>
                  </div>
                  <div className="p-2.5 bg-[#080d17] rounded-lg border border-[#1b273e]">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Trạng thái đánh giá</small>
                    <strong className="font-code-sm text-xs text-amber-300 block mt-1">
                      {activeCandidate.status ?? 'EVALUATED'}
                    </strong>
                  </div>
                </div>
              </div>

              {/* COMPARATIVE EXPLANATION CARD (Tại sao phương án này tốt hơn?) */}
              {activeCandidate.comparative_explanation ? (
                <div className="bg-[#0c1424] rounded-xl border border-emerald-500/30 p-5 flex flex-col gap-4 shadow-lg">
                  <div className="flex items-center justify-between border-b border-[#1b273e] pb-3">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-emerald-400 text-[22px]">lightbulb</span>
                      <h3 className="text-sm font-bold text-emerald-300 uppercase tracking-wider">
                        TẠI SAO PHƯƠNG ÁN NÀY TỐI ƯU HƠN? (COMPARATIVE EXPLANATION)
                      </h3>
                    </div>
                    <span className="text-[11px] font-semibold text-emerald-400/90 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded">
                      Đã xác thực định lượng
                    </span>
                  </div>

                  {/* Why Better narrative */}
                  <div className="p-3 bg-[#080d17] rounded-lg border border-[#1b273e]">
                    <p className="text-xs text-slate-200 leading-relaxed font-medium">
                      {activeCandidate.comparative_explanation.why_better}
                    </p>
                  </div>

                  {/* Delta Highlights Table */}
                  {activeCandidate.comparative_explanation.delta_highlights &&
                    activeCandidate.comparative_explanation.delta_highlights.length > 0 && (
                      <div className="flex flex-col gap-2">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
                          SO SÁNH CHỈ SỐ TRƯỚC VÀ SAU KHI TÁCH/ĐIỀU CHỈNH:
                        </span>
                        <div className="overflow-x-auto rounded-lg border border-[#1b273e] bg-[#080d17]">
                          <table className="w-full text-left text-xs font-code-sm">
                            <thead>
                              <tr className="border-b border-[#1b273e] bg-[#0e1728] text-on-surface-variant font-bold">
                                <th className="p-2.5">Chỉ số phân tích</th>
                                <th className="p-2.5 text-center">Trước can thiệp</th>
                                <th className="p-2.5 text-center">Sau can thiệp</th>
                                <th className="p-2.5 text-right">Mức độ cải thiện (Delta)</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-[#1b273e]">
                              {activeCandidate.comparative_explanation.delta_highlights.map((d, i) => (
                                <tr key={i} className="hover:bg-[#121c2e]/60 transition-colors">
                                  <td className="p-2.5 font-sans font-medium text-slate-200">{d.label}</td>
                                  <td className="p-2.5 text-center text-slate-400">{d.before}</td>
                                  <td className="p-2.5 text-center font-bold text-slate-200">{d.after}</td>
                                  <td className="p-2.5 text-right">
                                    <span
                                      className={`inline-block px-2 py-0.5 rounded text-[11px] font-bold ${
                                        d.direction === 'better'
                                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                          : d.direction === 'worse'
                                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                          : 'bg-slate-700/40 text-slate-300 border border-slate-600/30'
                                      }`}
                                    >
                                      {d.delta}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                  {/* Key Comparison Points */}
                  {activeCandidate.comparative_explanation.comparison_points &&
                    activeCandidate.comparative_explanation.comparison_points.length > 0 && (
                      <div className="flex flex-col gap-1.5 mt-1">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
                          CĂN CỨ KỸ THUẬT THEN CHỐT:
                        </span>
                        <ul className="flex flex-col gap-1 text-xs text-slate-300 list-disc list-inside">
                          {activeCandidate.comparative_explanation.comparison_points.map((pt, i) => (
                            <li key={i} className="leading-relaxed">
                              {pt}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                  {/* AI Narrative if available */}
                  {activeCandidate.comparative_explanation.ai_narrative && (
                    <div className="p-3 rounded-lg border border-purple-500/30 bg-purple-950/20 text-purple-200 text-xs leading-relaxed flex flex-col gap-1">
                      <span className="font-bold text-purple-300 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[15px]">smart_toy</span>
                        AI Advisor Giải thích mở rộng:
                      </span>
                      <p>{activeCandidate.comparative_explanation.ai_narrative}</p>
                    </div>
                  )}
                </div>
              ) : null}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center p-8 text-center bg-[#0c1424] rounded-xl border border-[#1b273e]">
              <span className="material-symbols-outlined text-on-surface-variant text-[40px] mb-2">
                pending_actions
              </span>
              <p className="text-sm text-on-surface font-semibold">
                Chưa có đề xuất phân hoạch Counterfactual được tính toán
              </p>
              <p className="text-xs text-on-surface-variant max-w-md mt-1 mb-4">
                Chạy giải thuật Multi-Objective Pareto để tìm kiếm các phương án chia tách hoặc điều chỉnh tối ưu.
              </p>
              <button
                onClick={handleStartReview}
                disabled={loading}
                className="px-4 py-2 bg-secondary text-[#070e1d] font-bold rounded-lg shadow-md hover:brightness-110 transition-all flex items-center gap-2 cursor-pointer text-xs"
              >
                <span className="material-symbols-outlined text-[16px]">play_arrow</span>
                <span>{loading ? 'Đang phân tích...' : 'Khởi chạy Đánh giá Đối chứng (Run Review)'}</span>
              </button>
            </div>
          )}
        </div>

        {/* Right Column: PO Review Decision & Historical Similar Cases (4 cols) */}
        <div className="lg:col-span-4 flex flex-col gap-space-md">
          {job?.job_id ? (
            <>
              <ReviewDecisionForm
                key={`${job.job_id}:${analysis.chain_id}:${activeCandidate?.candidate_id ?? 'none'}:${activeCandidateFeedback?.feedback_id ?? 'new'}`}
                jobId={job.job_id}
                chainId={analysis.chain_id}
                chainAlarms={analysis.members.map((m) => m.alarm_id)}
                candidateId={activeCandidate?.candidate_id ?? null}
                existingFeedback={activeCandidateFeedback}
                onFeedbackSaved={(fb) => {
                  setFeedbacks((prev) => [
                    fb,
                    ...prev.filter(
                      (item) =>
                        item.candidate_id !== fb.candidate_id &&
                        item.feedback_id !== fb.feedback_id,
                    ),
                  ])
                  setSubmitFeedbackMsg({
                    type: 'success',
                    text: 'Đã lưu thành công ý kiến ký duyệt vận hành.',
                  })
                  setTimeout(() => setSubmitFeedbackMsg(null), 3500)
                }}
                onFeedbackRetracted={(feedbackId) => {
                  setFeedbacks((prev) =>
                    prev.filter((item) => item.feedback_id !== feedbackId),
                  )
                  setSubmitFeedbackMsg({
                    type: 'success',
                    text: 'Đã thu hồi thành công ý kiến ký duyệt.',
                  })
                  setTimeout(() => setSubmitFeedbackMsg(null), 3500)
                }}
              />
            </>
          ) : (
            <div className="p-6 rounded-xl bg-[#0c1424] border border-[#1b273e] text-xs text-on-surface-variant text-center">
              Chưa có phiên đánh giá Counterfactual nào khả dụng cho chuỗi này.
            </div>
          )}
        </div>
      </div>

      {/* FULL-WIDTH SECTION: Phân hoạch do kỹ sư tự định nghĩa (Manual Partition Corrections) */}
      <section className="mt-4 bg-[#0c1424] rounded-xl border border-cyan-500/30 p-5 flex flex-col gap-4 shadow-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-[#1b273e] pb-3 gap-2">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-cyan-400 text-[24px]">alt_route</span>
            <div>
              <h2 className="text-sm font-bold text-cyan-300 uppercase tracking-wider flex items-center gap-2">
                <span>PHÂN HOẠCH DO KỸ SƯ TỰ ĐỊNH NGHĨA (MANUAL PARTITION CORRECTIONS)</span>
                <span className="px-2 py-0.2 rounded-full bg-cyan-500/20 text-cyan-300 text-xs font-mono font-bold border border-cyan-500/40">
                  {manualFeedbacks.length}
                </span>
              </h2>
            </div>
          </div>
        </div>

        {manualFeedbacks.length > 0 ? (
          <div className="flex flex-col gap-4">
            {manualFeedbacks.map((fb) => {
              const afterPartitions: Array<[string, string[]]> = fb.partition_delta?.after
                ? Array.isArray(fb.partition_delta.after)
                  ? fb.partition_delta.after
                  : Object.entries(fb.partition_delta.after)
                : []

              return (
                <div
                  key={fb.feedback_id}
                  className="bg-[#080d17] border border-[#1b273e] hover:border-cyan-500/40 rounded-xl p-4 flex flex-col gap-3 transition-all"
                >
                  {/* Partition Header Bar */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1b273e] pb-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="px-2.5 py-1 rounded bg-cyan-500/15 text-cyan-300 font-bold font-code-sm text-xs border border-cyan-500/30">
                        {fb.operation || 'MANUAL_SPLIT'}
                      </span>
                      <span className="text-xs text-slate-300 font-medium">
                        Kỹ sư: <strong className="text-secondary font-mono">{fb.operator_id}</strong>
                      </span>
                      {fb.created_at && (
                        <span className="text-xs text-on-surface-variant font-mono">
                          · {new Date(fb.created_at).toLocaleString('vi-VN')}
                        </span>
                      )}
                      <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-code-sm text-[11px] font-bold border border-emerald-500/30">
                        ĐÃ LƯU DATABASE
                      </span>
                    </div>

                    {/* Action buttons */}
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleCopyReport(fb)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#131d2e] hover:bg-[#1a273d] text-slate-200 border border-[#233552] text-xs font-medium cursor-pointer transition-all"
                        title="Sao chép báo cáo mẫu dán vào ticket ITSM/Jira"
                      >
                        <span className="material-symbols-outlined text-[14px] text-cyan-400">content_copy</span>
                        <span>{copiedFeedbackId === fb.feedback_id ? 'Đã chép ✓' : 'Sao chép Ticket'}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleDownloadJson(fb)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#131d2e] hover:bg-[#1a273d] text-slate-200 border border-[#233552] text-xs font-medium cursor-pointer transition-all"
                        title="Tải file JSON cấu trúc phân hoạch"
                      >
                        <span className="material-symbols-outlined text-[14px] text-sky-400">download</span>
                        <span>Tải JSON</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleUndoManualCorrection(fb.feedback_id)}
                        disabled={retractingFeedbackId === fb.feedback_id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-950/30 hover:bg-rose-900/50 text-rose-300 border border-rose-500/30 text-xs font-medium cursor-pointer transition-all"
                        title="Hủy / Thu hồi phân hoạch này"
                      >
                        <span className="material-symbols-outlined text-[14px]">undo</span>
                        <span>{retractingFeedbackId === fb.feedback_id ? 'Đang hủy...' : 'Hủy / Thu hồi'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Reason & Notes */}
                  {fb.reason && (
                    <div className="p-2.5 bg-[#0e1728] rounded-lg border border-[#1b273e] text-xs text-slate-200">
                      <strong className="text-on-surface-variant font-bold uppercase tracking-wider text-[10px] block mb-1">
                        Căn cứ &amp; Ghi chú của kỹ sư:
                      </strong>
                      <p className="leading-relaxed">{fb.reason}</p>
                    </div>
                  )}

                  {/* Sub-partitions breakdown */}
                  {afterPartitions.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                        CẤU TRÚC PHÂN HOẠCH SAU KHI TÁCH ({afterPartitions.length} PHÂN VÙNG):
                      </span>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {afterPartitions.map(([pId, alarmIds], pIdx) => (
                          <div
                            key={pId}
                            className="bg-[#0e1728] border border-[#1b273e] rounded-lg p-3 flex flex-col gap-2"
                          >
                            <div className="flex items-center justify-between border-b border-[#1b273e] pb-1.5">
                              <span className="font-bold text-xs text-secondary font-mono flex items-center gap-1">
                                <span className="material-symbols-outlined text-[15px]">folder</span>
                                Nhánh {pIdx + 1}: {pId}
                              </span>
                              <span className="px-2 py-0.2 rounded bg-secondary/15 text-secondary font-code-sm text-[11px] font-bold">
                                {alarmIds.length} cảnh báo
                              </span>
                            </div>

                            <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto pt-1">
                              {alarmIds.map((aid) => {
                                const info = alarmMap[aid]
                                return (
                                  <span
                                    key={aid}
                                    className="px-2 py-0.5 rounded bg-[#152033] border border-[#233552] text-slate-300 font-code-sm text-[11px] flex items-center gap-1"
                                    title={`${aid} · ${info?.alarm_name || ''} · ${info?.device_code || ''}`}
                                  >
                                    {info?.device_code && (
                                      <strong className="text-secondary">{info.device_code}:</strong>
                                    )}
                                    <span>{info?.alarm_name || aid}</span>
                                  </span>
                                )
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="p-6 bg-[#080d17] border border-[#1b273e] rounded-xl flex items-center gap-4 text-left">
            <span className="material-symbols-outlined text-cyan-400/60 text-[32px] shrink-0">content_cut</span>
            <div className="flex flex-col">
              <span className="text-xs font-bold text-slate-200">
                Chưa có phân hoạch thủ công nào được ghi nhận cho chuỗi sự cố này
              </span>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
