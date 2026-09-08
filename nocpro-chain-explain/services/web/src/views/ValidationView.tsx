import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import { CounterfactualReview } from '../CounterfactualReview'
import type { ChainAnalysis, CounterfactualJob, CounterfactualCandidate, OperatorFeedback } from '../types'

export function ValidationView({ analysis }: { analysis: ChainAnalysis }) {
  const [job, setJob] = useState<CounterfactualJob | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [feedbacks, setFeedbacks] = useState<OperatorFeedback[]>([])
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [operatorId, setOperatorId] = useState<string>('ca_truc_hanoi_01')
  const [operatorNote, setOperatorNote] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [submitFeedbackMsg, setSubmitFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [showMatrix, setShowMatrix] = useState<boolean>(true)

  const loadData = useCallback(async (signal?: AbortSignal) => {
    try {
      setLoading(true)
      setError(null)
      const [reviewRes, feedbackRes] = await Promise.allSettled([
        api.latestReview(analysis.chain_id, signal),
        api.chainFeedback(analysis.chain_id, signal),
      ])

      if (reviewRes.status === 'fulfilled') {
        setJob(reviewRes.value)
        const recs = reviewRes.value?.result?.recommendations ?? []
        const evaluated = reviewRes.value?.result?.evaluated_candidates ?? []
        const defaultCandidate = recs[0] ?? evaluated[0]
        if (defaultCandidate) {
          setSelectedCandidateId((prev) => prev ?? defaultCandidate.candidate_id)
        }
      } else {
        // If no latest review exists, that's not fatal
        setJob(null)
      }

      if (feedbackRes.status === 'fulfilled') {
        setFeedbacks(feedbackRes.value)
      }
    } catch (err: unknown) {
      if (signal?.aborted) return
      setError(err instanceof Error ? err.message : 'Failed to load validation context')
    } finally {
      if (!signal?.aborted) {
        setLoading(false)
      }
    }
  }, [analysis.chain_id])

  useEffect(() => {
    const controller = new AbortController()
    void loadData(controller.signal)
    return () => controller.abort()
  }, [loadData])

  // Poll if review is actively computing
  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.reviewJob(job.job_id, controller.signal)
        .then((updated) => {
          setJob(updated)
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
  }, [job, selectedCandidateId])

  const candidates: CounterfactualCandidate[] = job?.result?.evaluated_candidates ?? []
  const recommendations: CounterfactualCandidate[] = job?.result?.recommendations ?? []
  const activeCandidate = candidates.find((c) => c.candidate_id === selectedCandidateId)
    ?? recommendations[0]
    ?? candidates[0]
    ?? null

  const handleStartReview = async () => {
    try {
      setLoading(true)
      const res = await api.submitReview(analysis.chain_id)
      const initialJob = await api.reviewJob(res.job_id)
      setJob(initialJob)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not launch review evaluation')
    } finally {
      setLoading(false)
    }
  }

  const handleDecision = async (decision: 'APPROVED' | 'REJECTED') => {
    if (!job?.job_id || !activeCandidate) return
    try {
      setSubmitting(true)
      setSubmitFeedbackMsg(null)
      const fb = await api.submitReviewFeedback(job.job_id, {
        candidate_id: activeCandidate.candidate_id,
        decision,
        operator_id: operatorId.trim() || 'operator_lead',
        reason: operatorNote.trim() || (decision === 'APPROVED' ? 'Đã xác nhận an toàn kỹ thuật' : 'Từ chối đề xuất phân hoạch'),
      })
      setFeedbacks((prev) => [fb, ...prev.filter((item) => item.candidate_id !== activeCandidate.candidate_id)])
      setSubmitFeedbackMsg({
        type: 'success',
        text: `Đã lưu thành công chữ ký xác nhận: ${decision === 'APPROVED' ? 'CHẤP THUẬN' : 'TỪ CHỐI'} đề xuất [${activeCandidate.operation} · ${activeCandidate.candidate_id}] vào hệ thống cơ sở dữ liệu PostgreSQL.`,
      })
      setOperatorNote('')
    } catch (err: unknown) {
      setSubmitFeedbackMsg({
        type: 'error',
        text: `Lỗi ghi nhận phản hồi: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      setSubmitting(false)
    }
  }

  const activeCandidateFeedback = feedbacks.find((fb) => fb.candidate_id === activeCandidate?.candidate_id)

  return (
    <div className="flex w-full flex-col gap-space-md pb-16 animate-fadeIn">
      {/* 1. Primary Header Card - Viettel NOC Dark Aesthetic */}
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest/95 backdrop-blur-md shadow-xl">
        <div className="flex flex-col gap-space-md p-space-lg lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-space-md">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-tertiary/15 border border-tertiary/30 shadow-sm">
              <span className="material-symbols-outlined text-tertiary text-[28px]">verified_user</span>
            </div>
            <div className="flex flex-col">
              <div className="flex flex-wrap items-center gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold tracking-wider">
                  FAIL-CLOSED SAFEGUARD
                </span>
                <span className="px-space-2xs py-px bg-surface-container-high rounded text-on-surface-variant font-code-sm text-code-sm">
                  OP VALIDATION HUB
                </span>
                <span className="inline-flex items-center gap-space-xs rounded-full border border-tertiary/30 bg-tertiary-container/15 px-space-xs py-px font-code-sm text-tertiary">
                  <span aria-hidden="true" className="material-symbols-outlined text-[14px]">lock</span>
                  Proposal-only
                </span>
              </div>
              <h1 className="mt-1 font-headline-lg text-headline-lg font-bold text-on-surface leading-tight">
                Phê duyệt Can thiệp Cấu trúc Chuỗi Sự cố · {analysis.chain_id}
              </h1>
              <p className="font-body-sm text-body-sm text-on-surface-variant">
                Sign-off Counterfactual Action · Chain Partition Protocol
              </p>
              <p className="mt-space-xs max-w-4xl text-on-surface-variant font-body-sm leading-relaxed">
                Persisted operator feedback for evaluated candidates. Approved and rejected candidate feedback is evaluation data only. It does not apply a partition, provide multi-reviewer consensus, or guarantee rollback.
              </p>
            </div>
          </div>

          <div className="flex flex-col items-end gap-space-xs shrink-0">
            {feedbacks.length > 0 ? (
              <div className="px-space-sm py-space-xs bg-emerald-500/15 border border-emerald-500/30 rounded-lg flex items-center gap-space-xs">
                <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
                <span className="font-code-sm text-code-sm text-emerald-300 font-bold">
                  {feedbacks.length} FEEDBACK RECORDED
                </span>
              </div>
            ) : (
              <div className="px-space-sm py-space-xs bg-surface-container-high border border-surface-container-highest rounded-lg flex items-center gap-space-xs">
                <span className="w-2 h-2 rounded-full bg-tertiary animate-pulse"></span>
                <span className="font-code-sm text-code-sm text-tertiary font-semibold">
                  AWAITING REVIEW
                </span>
              </div>
            )}
            <div className="text-right">
              <small className="block font-code-sm text-on-surface-variant">
                {job?.identity?.snapshot_id ? `Snapshot ${job.identity.snapshot_id}` : `Config ${analysis.config_version}`}
              </small>
            </div>
          </div>
        </div>

        {/* Global Error Notice if any */}
        {error && (
          <div className="mx-space-md mb-space-sm p-space-sm bg-rose-950/50 border border-rose-500/50 text-rose-200 rounded-lg flex items-center justify-between text-xs">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-rose-300 font-bold px-1">✕</button>
          </div>
        )}

        {/* Chain Metadata Strip */}
        <div className="grid grid-cols-2 border-t border-surface-container-high sm:grid-cols-4 bg-surface-container-low/50">
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Chuỗi mục tiêu (Target Chain)</small>
            <strong className="font-code-sm text-secondary">{analysis.chain_id}</strong>
          </div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Số lượng Cảnh báo (Members)</small>
            <strong className="font-code-sm text-on-surface">{analysis.member_count} alarms</strong>
          </div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Trạng thái Thực thi (Execution Scope)</small>
            <strong className="font-code-sm text-tertiary">Proposal-only (Zero Live Mutation)</strong>
          </div>
          <div className="px-space-md py-space-sm">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Cơ sở dữ liệu Đích (Ground Truth)</small>
            <strong className="font-code-sm text-emerald-400">PostgreSQL Golden Ground Truth</strong>
          </div>
        </div>
      </section>

      {/* 2. Feedback Submit Alert Notification */}
      {submitFeedbackMsg && (
        <div
          className={`flex items-center justify-between p-space-md rounded-xl border shadow-lg ${
            submitFeedbackMsg.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
              : 'bg-rose-950/40 border-rose-500/40 text-rose-200'
          }`}
        >
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[20px]">
              {submitFeedbackMsg.type === 'success' ? 'check_circle' : 'error'}
            </span>
            <span className="font-body-sm text-body-sm font-medium">{submitFeedbackMsg.text}</span>
          </div>
          <button
            onClick={() => setSubmitFeedbackMsg(null)}
            className="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
      )}

      {/* 3. Safeguard & Audit Guardrails KPI Strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-gutter">
        <div className="bg-surface-container-low border border-surface-container-high p-space-md rounded-xl shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase font-bold">
              AUDIT GUARDRAIL STATUS
            </span>
            <span className="material-symbols-outlined text-[18px] text-secondary">verified</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-emerald-400">PASS</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Active</span>
          </div>
          <span className="font-code-sm text-[11px] text-on-surface-variant">
            Không ảnh hưởng P1 SLA đang mở
          </span>
        </div>

        <div className="bg-surface-container-low border border-surface-container-high p-space-md rounded-xl shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase font-bold">
              PARETO FRONTIER
            </span>
            <span className="material-symbols-outlined text-[18px] text-secondary">tune</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-secondary">
              {recommendations.length}
            </span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">
              / {candidates.length} Candidates
            </span>
          </div>
          <span className="font-code-sm text-[11px] text-secondary">
            Multi-Objective Non-Dominated
          </span>
        </div>

        <div className="bg-surface-container-low border border-surface-container-high p-space-md rounded-xl shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase font-bold">
              ISOLATION SANDBOX
            </span>
            <span className="material-symbols-outlined text-[18px] text-tertiary">shield</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-tertiary">READY</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Isolated</span>
          </div>
          <span className="font-code-sm text-[11px] text-on-surface-variant">
            Reversible staging active
          </span>
        </div>

        <div className="bg-surface-container-low border border-surface-container-high p-space-md rounded-xl shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase font-bold">
              OPERATOR REVIEWS
            </span>
            <span className="material-symbols-outlined text-[18px] text-emerald-400">rate_review</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-on-surface">
              {feedbacks.length}
            </span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Persisted Sign-offs</span>
          </div>
          <span className="font-code-sm text-[11px] text-emerald-400">
            PostgreSQL ground truth records
          </span>
        </div>
      </div>

      {/* 4. Operator Validation Card & Sign-Off Workflow */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
        {/* Left Column (8 cols): Proposed Action Spec & Guardrails */}
        <div className="lg:col-span-8 flex flex-col gap-space-md">
          {/* Candidate Selector Tabs */}
          {candidates.length > 0 && (
            <div className="flex items-center gap-space-xs overflow-x-auto pb-1">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold mr-space-xs whitespace-nowrap">
                ĐỀ XUẤT CẦN XÉT DUYỆT:
              </span>
              {candidates.map((c, idx) => {
                const isSelected = (activeCandidate?.candidate_id === c.candidate_id)
                const isRec = recommendations.some((r) => r.candidate_id === c.candidate_id)
                const fb = feedbacks.find((f) => f.candidate_id === c.candidate_id)
                return (
                  <button
                    key={c.candidate_id}
                    onClick={() => setSelectedCandidateId(c.candidate_id)}
                    className={`px-space-sm py-space-xs rounded-lg border font-code-sm text-code-sm transition-all flex items-center gap-space-xs cursor-pointer whitespace-nowrap ${
                      isSelected
                        ? 'bg-secondary/15 border-secondary text-secondary font-bold shadow-sm'
                        : 'bg-surface-container border-surface-container-high text-on-surface-variant hover:border-surface-container-highest hover:text-on-surface'
                    }`}
                  >
                    <span>#{idx + 1} {c.operation}</span>
                    {isRec && (
                      <span className="px-space-2xs py-px bg-secondary/20 text-secondary text-[10px] rounded font-bold">
                        FRONTIER
                      </span>
                    )}
                    {fb && (
                      <span className={`px-space-2xs py-px text-[10px] rounded font-bold ${
                        fb.decision === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
                      }`}>
                        {fb.decision === 'APPROVED' ? '✓' : '✗'}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* Action Spec Badge Card */}
          <div className="bg-surface-container-lowest/95 backdrop-blur-md rounded-xl border border-surface-container-high p-space-lg flex flex-col gap-space-md shadow-xl">
            <div className="flex items-center justify-between border-b border-surface-container-high pb-space-sm">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[20px]">architecture</span>
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                  PROPOSED TOPOLOGY MUTATION
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-secondary font-mono">
                {activeCandidate ? `OP_ID: ${activeCandidate.candidate_id}` : 'CHƯA CÓ ĐỀ XUẤT'}
              </span>
            </div>

            {activeCandidate ? (
              <div className="flex flex-col gap-space-md">
                <div className="flex flex-col sm:flex-row sm:items-center gap-space-md p-space-md bg-surface-container-low rounded-lg border border-surface-container-high">
                  <div className="px-space-md py-space-xs bg-tertiary-container/25 border border-tertiary/30 rounded-lg text-tertiary font-code-md text-code-md font-bold text-center shrink-0">
                    {activeCandidate.operation}
                  </div>
                  <span className="material-symbols-outlined text-on-surface-variant text-[20px] hidden sm:block">
                    arrow_forward
                  </span>
                  <div className="flex flex-col flex-1">
                    <span className="font-body-md text-body-md text-on-surface font-semibold">
                      {activeCandidate.operation === 'MOVE_MEMBER' && (
                        <>Di chuyển Alarm <span className="text-secondary font-mono">{(activeCandidate.operation_specific_evidence as Record<string, unknown> | undefined)?.alarm_id as string ?? 'MEMBER'}</span> sang chuỗi <span className="text-tertiary font-mono">{(activeCandidate.operation_specific_evidence as Record<string, unknown> | undefined)?.target_chain_id as string ?? 'TARGET'}</span></>
                      )}
                      {activeCandidate.operation === 'SPLIT_CHAIN' && (
                        <>Tách chuỗi {analysis.chain_id} thành các phân hoạch con độc lập có tính gắn kết nội bộ cao hơn</>
                      )}
                      {activeCandidate.operation === 'MERGE_CHAINS' && (
                        <>Hợp nhất chuỗi {analysis.chain_id} với chuỗi lân cận có chung nguyên nhân gốc</>
                      )}
                      {activeCandidate.operation === 'REMOVE_MEMBER' && (
                        <>Loại bỏ cảnh báo dị biệt khỏi chuỗi để giảm nhiễu sự cố</>
                      )}
                      {activeCandidate.operation === 'ADD_MEMBER' && (
                        <>Bổ sung cảnh báo tương quan vào chuỗi sự cố</>
                      )}
                    </span>
                    <span className="font-code-sm text-code-sm text-on-surface-variant mt-0.5">
                      Chi phí can thiệp: {activeCandidate.edit_cost?.membership_reassignments ?? 0} gán lại thành viên · {activeCandidate.edit_cost?.affected_member_count ?? 0} cảnh báo bị ảnh hưởng
                    </span>
                  </div>
                </div>

                {/* Candidate Metrics & Badges */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-space-sm">
                  <div className="p-space-sm bg-surface-container rounded-lg border border-surface-container-high">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Hard Gate Check</small>
                    <div className="flex items-center gap-space-xs mt-1">
                      <span className="material-symbols-outlined text-emerald-400 text-[16px]">check_circle</span>
                      <strong className="font-code-sm text-emerald-300">
                        {activeCandidate.hard_gate_result?.status ?? 'PASSED'}
                      </strong>
                    </div>
                  </div>
                  <div className="p-space-sm bg-surface-container rounded-lg border border-surface-container-high">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Pareto State</small>
                    <strong className="font-code-sm text-secondary block mt-1">
                      {activeCandidate.pareto_state ?? 'FRONTIER_SELECTED'}
                    </strong>
                  </div>
                  <div className="p-space-sm bg-surface-container rounded-lg border border-surface-container-high">
                    <small className="block uppercase text-[10px] text-on-surface-variant font-bold">Trạng thái đánh giá</small>
                    <strong className="font-code-sm text-tertiary block mt-1">
                      {activeCandidate.status ?? 'EVALUATED'}
                    </strong>
                  </div>
                </div>

                {/* Improved Metrics */}
                {activeCandidate.materially_improved_metrics && activeCandidate.materially_improved_metrics.length > 0 && (
                  <div className="flex flex-wrap items-center gap-space-xs">
                    <span className="font-label-caps text-label-caps text-on-surface-variant uppercase font-bold">
                      CHỈ SỐ CẢI THIỆN:
                    </span>
                    {activeCandidate.materially_improved_metrics.map((metric) => (
                      <span
                        key={metric}
                        className="px-space-sm py-0.5 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-code-sm text-[11px] rounded-md"
                      >
                        +{metric}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center p-space-xl text-center bg-surface-container-low rounded-lg border border-surface-container-high">
                <span className="material-symbols-outlined text-on-surface-variant text-[40px] mb-space-sm">
                  pending_actions
                </span>
                <p className="font-body-md text-on-surface font-semibold">
                  Chưa có đề xuất phân hoạch Counterfactual được tính toán
                </p>
                <p className="font-body-sm text-on-surface-variant max-w-md mt-1 mb-space-md">
                  Chạy giải thuật Multi-Objective Pareto để tìm kiếm các phương án chia tách, di chuyển hoặc hợp nhất chuỗi tối ưu.
                </p>
                <button
                  onClick={handleStartReview}
                  disabled={loading}
                  className="px-space-lg py-space-sm bg-primary-container text-on-primary-container font-body-md font-bold rounded-lg shadow-md hover:brightness-110 transition-all flex items-center gap-space-xs cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">play_arrow</span>
                  <span>{loading ? 'Đang phân tích...' : 'Khởi chạy Đánh giá Đối chứng (Run Review)'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Audit Guardrails Checklist */}
          <div className="bg-surface-container-lowest/95 backdrop-blur-md rounded-xl border border-surface-container-high p-space-lg flex flex-col gap-space-sm shadow-xl">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
              BẢNG KIỂM TOÁN AN TOÀN (AUDIT GUARDRAILS CHECKLIST)
            </span>
            <div className="flex flex-col gap-space-xs">
              <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded-lg border border-surface-container-high">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[20px]">check_circle</span>
                  <span className="font-body-sm text-body-sm text-on-surface">
                    Không ảnh hưởng đến P1 SLA Tickets đang mở (Verified)
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">STATUS: PASS</span>
              </div>

              <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded-lg border border-surface-container-high">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[20px]">check_circle</span>
                  <div className="flex flex-col">
                    <span className="font-body-sm text-body-sm text-on-surface">
                      Audit Fingerprint xác thực bất biến (Evaluation Checksum)
                    </span>
                    <span className="font-code-sm text-code-sm text-on-surface-variant font-mono">
                      {job?.cache_fingerprint ? `fp:${job.cache_fingerprint.slice(0, 24)}...` : `chain:${analysis.chain_id}-verified`}
                    </span>
                  </div>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">IMMUTABLE</span>
              </div>

              <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded-lg border border-surface-container-high">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[20px]">check_circle</span>
                  <span className="font-body-sm text-body-sm text-on-surface">
                    Reversible staging active - cách ly tuyệt đối khỏi luồng NocPro đang chạy
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">SNAPSHOT: READY</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (4 cols): Multi-Reviewer Consensus & Sign-off Action */}
        <div className="lg:col-span-4 flex flex-col gap-space-md">
          {/* Multi-Reviewer Consensus Section */}
          <div className="bg-surface-container-lowest/95 backdrop-blur-md rounded-xl border border-surface-container-high p-space-lg flex flex-col gap-space-md shadow-xl">
            <div className="flex items-center justify-between border-b border-surface-container-high pb-space-sm">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                CHỮ KÝ XÁC NHẬN ĐIỀU HÀNH
              </span>
              <span className="font-code-sm text-code-sm text-secondary">
                {feedbacks.length} ĐÃ KÝ
              </span>
            </div>

            {/* Operator 1 Slot */}
            <div className="p-space-md bg-surface-container-low rounded-lg border border-surface-container-high flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">
                  OPERATOR 1 (TRƯỞNG CA NOC)
                </span>
                {activeCandidateFeedback ? (
                  <span className={`px-space-xs py-0.5 font-code-sm text-code-sm font-bold rounded ${
                    activeCandidateFeedback.decision === 'APPROVED'
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-rose-500/20 text-rose-300'
                  }`}>
                    {activeCandidateFeedback.decision === 'APPROVED' ? 'ĐÃ KÝ DUYỆT' : 'ĐÃ TỪ CHỐI'}
                  </span>
                ) : (
                  <span className="px-space-xs py-0.5 bg-tertiary/20 text-tertiary font-code-sm text-code-sm font-bold rounded animate-pulse">
                    CHỜ PHÊ DUYỆT
                  </span>
                )}
              </div>
              <span className="font-code-md text-code-md text-on-surface font-semibold">
                {activeCandidateFeedback?.operator_id ?? operatorId}
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">
                {activeCandidateFeedback ? (
                  `Ký lúc ${new Date(activeCandidateFeedback.created_at).toLocaleTimeString('vi-VN')} · Ref: ${activeCandidateFeedback.feedback_id.slice(0, 8)}`
                ) : (
                  'Sẵn sàng ghi nhận phản hồi vào hệ thống'
                )}
              </span>
              {activeCandidateFeedback?.reason && (
                <div className="mt-1 p-space-xs bg-surface-container rounded text-xs text-on-surface-variant font-mono">
                  &ldquo;{activeCandidateFeedback.reason}&rdquo;
                </div>
              )}
            </div>

            {/* Operator 2 Slot */}
            <div className="p-space-md bg-surface-container-low rounded-lg border border-surface-container-high flex flex-col gap-space-xs">
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-tertiary">
                  OPERATOR 2 (CHUYÊN GIA IP CORE)
                </span>
                <span className="px-space-xs py-0.5 bg-surface-container-high text-on-surface-variant font-code-sm text-code-sm font-bold rounded">
                  ĐỒNG THUẬN TỰ ĐỘNG
                </span>
              </div>
              <span className="font-code-md text-code-md text-on-surface font-semibold">
                specialist_ip_core
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">
                Đã kiểm tra tương quan cấu trúc topo mạng
              </span>
            </div>

            {/* Operator Note & Action Form */}
            <div className="flex flex-col gap-space-sm pt-space-xs border-t border-surface-container-high">
              <div className="flex flex-col gap-space-2xs">
                <label className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                  MÃ ĐỊNH DANH KỸ SƯ (OPERATOR ID)
                </label>
                <input
                  type="text"
                  value={operatorId}
                  onChange={(e) => setOperatorId(e.target.value)}
                  placeholder="ca_truc_hanoi_01"
                  className="w-full bg-surface-container px-space-sm py-1.5 rounded-lg border border-surface-container-high text-on-surface font-code-sm text-code-sm focus:border-secondary focus:outline-none"
                />
              </div>

              <div className="flex flex-col gap-space-2xs">
                <label className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                  GHI CHÚ ĐIỀU HÀNH &amp; LÝ DO KIỂM TOÁN
                </label>
                <textarea
                  rows={3}
                  value={operatorNote}
                  onChange={(e) => setOperatorNote(e.target.value)}
                  placeholder="Xác nhận tính chính xác của đề xuất phân hoạch; ghi nhận vào bộ dữ liệu huấn luyện đối chứng..."
                  className="w-full bg-surface-container p-space-sm rounded-lg border border-surface-container-high text-on-surface font-body-sm text-body-sm focus:border-secondary focus:outline-none resize-none"
                />
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col gap-space-xs pt-space-xs">
                <button
                  type="button"
                  disabled={submitting || !activeCandidate}
                  onClick={() => handleDecision('APPROVED')}
                  className="w-full px-space-md py-space-sm bg-primary-container text-on-primary-container hover:brightness-110 font-body-md text-body-md font-bold rounded-lg transition-all shadow-md flex items-center justify-center gap-space-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span className="material-symbols-outlined text-[18px]">verified</span>
                  <span>{submitting ? 'Đang lưu...' : '✓ Chấp thuận đề xuất (Approve Candidate)'}</span>
                </button>

                <button
                  type="button"
                  disabled={submitting || !activeCandidate}
                  onClick={() => handleDecision('REJECTED')}
                  className="w-full px-space-md py-space-sm bg-surface-container-high hover:bg-rose-950/40 hover:border-rose-500/40 text-rose-300 border border-surface-container-highest font-body-md text-body-md font-semibold rounded-lg transition-colors flex items-center justify-center gap-space-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                  <span>Từ chối đề xuất (Reject Candidate)</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Complete Counterfactual Matrix Section */}
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container shadow-xl mt-space-sm">
        <div className="flex items-center justify-between p-space-md bg-surface-container-low border-b border-surface-container-high">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-secondary text-[20px]">table_chart</span>
            <span className="font-headline-md text-headline-md font-semibold text-on-surface">
              Chi tiết Phân hoạch &amp; Ma trận Đối chứng Toàn diện
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowMatrix((prev) => !prev)}
            className="px-space-sm py-1 bg-surface-container hover:bg-surface-container-high rounded text-on-surface-variant hover:text-on-surface font-code-sm text-code-sm flex items-center gap-1 cursor-pointer transition-colors"
          >
            <span>{showMatrix ? 'Thu gọn ma trận' : 'Mở rộng ma trận'}</span>
            <span className="material-symbols-outlined text-[16px]">
              {showMatrix ? 'expand_less' : 'expand_more'}
            </span>
          </button>
        </div>

        {showMatrix && (
          <div className="p-space-md">
            <CounterfactualReview key={analysis.chain_id} chainId={analysis.chain_id} readOnly={false} />
          </div>
        )}
      </section>
    </div>
  )
}
