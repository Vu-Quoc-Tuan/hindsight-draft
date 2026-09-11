import { useState, useEffect } from 'react'
import { api } from '../api'
import type { ChainAnalysis, CounterfactualJob, CounterfactualCandidate, OperatorFeedback } from '../types'
import { ReviewDecisionForm } from '../components/ReviewDecisionForm'
import { SimilarReviewCases } from '../components/SimilarReviewCases'

export function ValidationView({ analysis }: { analysis: ChainAnalysis }) {
  const [job, setJob] = useState<CounterfactualJob | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [feedbacks, setFeedbacks] = useState<OperatorFeedback[]>([])
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [submitFeedbackMsg, setSubmitFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

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
          setJob(reviewRes.value)
          const recs = reviewRes.value?.result?.recommendations ?? []
          const evaluated = reviewRes.value?.result?.evaluated_candidates ?? []
          const defaultCandidate = recs[0] ?? evaluated[0]
          if (defaultCandidate) {
            setSelectedCandidateId((prev) => prev ?? defaultCandidate.candidate_id)
          }
        } else {
          setJob(null)
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
  }, [analysis.chain_id])

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

  // Impression logging: log candidate display events to counter position bias
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
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Cơ sở dữ liệu Đích (Review Store)</small>
            <strong className="font-code-sm text-emerald-400">PO-Asserted Review Evidence Store</strong>
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
              PROPOSAL SAFETY GATE
            </span>
            <span className="material-symbols-outlined text-[18px] text-secondary">
              {activeCandidate ? (activeCandidate.hard_gate_passed !== false ? 'verified' : 'cancel') : 'help'}
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className={`font-headline-lg text-headline-lg font-bold ${
              !activeCandidate ? 'text-amber-400' : activeCandidate.hard_gate_passed !== false ? 'text-emerald-400' : 'text-rose-400'
            }`}>
              {!activeCandidate ? 'UNAVAILABLE' : activeCandidate.hard_gate_passed !== false ? 'PASS' : 'FAIL'}
            </span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Deterministic</span>
          </div>
          <span className="font-code-sm text-[11px] text-on-surface-variant">
            Zero Upstream Mutation Enforced
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
              REVIEW-ONLY PROPOSAL
            </span>
            <span className="material-symbols-outlined text-[18px] text-tertiary">shield</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-tertiary">READ-ONLY</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Zero Mutation</span>
          </div>
          <span className="font-code-sm text-[11px] text-on-surface-variant">
            Review-only proposal inspection
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
            PO-asserted review evidence records
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
                  PROPOSED CANDIDATE INSPECTION (REVIEW-ONLY)
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
                    Mô hình can thiệp chỉ đọc: Không ghi đè hay cập nhật trực tiếp phân hoạch chuỗi hiện hành
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">STATUS: READ_ONLY</span>
              </div>

              <div className="flex items-center justify-between p-space-sm bg-surface-container-low rounded-lg border border-surface-container-high">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[20px]">check_circle</span>
                  <div className="flex flex-col">
                    <span className="font-body-sm text-body-sm text-on-surface">
                      Audit Fingerprint xác thực bất biến (Candidate Set Checksum)
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
                    Cách ly phân tích: Toàn bộ quá trình tính toán và đánh giá diễn ra trên snapshot độc lập
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">SNAPSHOT: ISOLATED</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (4 cols): PO Review Decision & Multi-Block Similar Cases */}
        <div className="lg:col-span-4 flex flex-col gap-space-md">
          {job?.job_id ? (
            <>
              <ReviewDecisionForm
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
                }}
                onFeedbackRetracted={(feedbackId) => {
                  setFeedbacks((prev) =>
                    prev.filter((item) => item.feedback_id !== feedbackId),
                  )
                }}
              />

              <SimilarReviewCases
                jobId={job.job_id}
                candidateId={activeCandidate?.candidate_id ?? null}
              />
            </>
          ) : (
            <div className="p-space-lg rounded-xl bg-surface-container-lowest/95 border border-surface-container-high text-xs text-on-surface-variant text-center">
              Chưa có phiên đánh giá Counterfactual nào khả dụng cho chuỗi này.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
