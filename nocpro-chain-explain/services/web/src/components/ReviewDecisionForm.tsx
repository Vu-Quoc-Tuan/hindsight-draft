import { useState, useEffect } from 'react'
import { api } from '../api'
import type {
  ReviewDecision,
  ReasonPolicy,
  OperatorFeedback,
  ManualCorrectionPayload,
} from '../types'
import { isReviewApproved } from '../types'

interface ReviewDecisionFormProps {
  jobId: string
  chainId: string
  chainAlarms?: string[]
  candidateId: string | null
  existingFeedback?: OperatorFeedback | null
  onFeedbackSaved: (feedback: OperatorFeedback) => void
  onFeedbackRetracted?: (feedbackId: string) => void
}

const DECISIONS: Array<{
  value: ReviewDecision
  label: string
  desc: string
  badgeClass: string
}> = [
  {
    value: 'APPROVE',
    label: 'Approve (Phê duyệt)',
    desc: 'Đề xuất phân hoạch đối chứng chính xác, phản ánh đúng hiện trạng mạng',
    badgeClass: 'bg-emerald-950/80 border-emerald-500 text-emerald-300 hover:bg-emerald-900/90',
  },
  {
    value: 'REJECT',
    label: 'Reject (Từ chối)',
    desc: 'Đề xuất phân hoạch không chính xác hoặc gộp sai các cảnh báo',
    badgeClass: 'bg-rose-950/80 border-rose-500 text-rose-300 hover:bg-rose-900/90',
  },
]

export function ReviewDecisionForm({
  jobId,
  chainId,
  chainAlarms,
  candidateId,
  existingFeedback,
  onFeedbackSaved,
  onFeedbackRetracted,
}: ReviewDecisionFormProps) {
  const [policy, setPolicy] = useState<ReasonPolicy | null>(null)
  const [selectedDecision, setSelectedDecision] = useState<ReviewDecision>(() => (
    existingFeedback
      ? (isReviewApproved(existingFeedback.decision) ? 'APPROVE' : 'REJECT')
      : 'APPROVE'
  ))
  const [userReasonCode, setUserReasonCode] = useState<string | null>(
    () => existingFeedback?.reason_codes?.[0] ?? null,
  )
  const [confidence, setConfidence] = useState<number>(
    () => existingFeedback?.confidence ?? 1.0,
  )
  const [notes, setNotes] = useState<string>(() => existingFeedback?.reason ?? '')
  const [isSuperseding, setIsSuperseding] = useState<boolean>(false)
  const [retractReason, setRetractReason] = useState<string>('')
  const [showRetractModal, setShowRetractModal] = useState<boolean>(false)

  // Manual correction fields
  const [mcOperation, setMcOperation] = useState<string>('MOVE_MEMBER')
  const [mcTargetChain, setMcTargetChain] = useState<string>(`${chainId}::isolated`)
  const [mcAlarmIds, setMcAlarmIds] = useState<string>('')
  const [mcSummary, setMcSummary] = useState<string>('')

  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Fetch reason policy on mount
  useEffect(() => {
    const controller = new AbortController()
    api.reviewReasons(controller.signal)
      .then((p) => {
        setPolicy(p)
      })
      .catch(() => {
        // Fallback gracefully if reasons endpoint is slow or unreachable
      })
    return () => controller.abort()
  }, [])

  const availableReasons = policy?.reasons_by_decision[selectedDecision] ?? []
  const selectedReasonCode =
    userReasonCode && availableReasons.some((r) => r.code === userReasonCode)
      ? userReasonCode
      : (availableReasons[0]?.code ?? '')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    setSuccessMsg(null)

    try {
      let manualCorrectionPayload: ManualCorrectionPayload | null = null
      if (selectedDecision === 'MANUAL_CORRECTION') {
        const selectedAlarms = mcAlarmIds.split(',').map((a) => a.trim()).filter(Boolean)
        const allAlarms =
          chainAlarms && chainAlarms.length > 0
            ? chainAlarms
            : selectedAlarms
        const remainingAlarms = allAlarms.filter((a) => !selectedAlarms.includes(a))
        const target = mcTargetChain.trim() || `${chainId}::partition_1`

        if (mcOperation === 'MERGE') {
          manualCorrectionPayload = {
            operation: 'MANUAL_MERGE',
            partition_delta: {
              before: [[chainId, allAlarms]],
              after: [[target, allAlarms]],
            },
            edit_summary: mcSummary || `Manually merged chain ${chainId} into ${target}`,
          }
        } else if (mcOperation === 'SPLIT') {
          manualCorrectionPayload = {
            operation: 'MANUAL_SPLIT',
            partition_delta: {
              before: [[chainId, allAlarms]],
              after: [
                [chainId, remainingAlarms],
                [target, selectedAlarms],
              ],
            },
            edit_summary: mcSummary || `Manually split ${selectedAlarms.length} alarms into ${target}`,
          }
        } else {
          // MOVE_MEMBER / MANUAL_MOVE
          manualCorrectionPayload = {
            operation: 'MANUAL_MOVE',
            partition_delta: {
              before: [[chainId, allAlarms]],
              after: [
                [chainId, remainingAlarms],
                [target, selectedAlarms],
              ],
            },
            edit_summary: mcSummary || `Manually moved ${selectedAlarms.length} alarms to ${target}`,
          }
        }
      }

      const payload = {
        candidate_id: selectedDecision === 'NONE_ACCEPTABLE' ? null : candidateId,
        decision: selectedDecision,
        confidence,
        notes,
        reason_code: selectedReasonCode || undefined,
        reason_codes: selectedReasonCode ? [selectedReasonCode] : [],
        reason_policy_version: policy?.policy_version ?? 'review-reasons-v1',
        manual_correction: manualCorrectionPayload,
      }

      let result: OperatorFeedback
      if (isSuperseding && existingFeedback) {
        result = await api.supersedeFeedback(jobId, existingFeedback.feedback_id, payload)
        setSuccessMsg(`Feedback successfully superseded. New ID: ${result.feedback_id.slice(0, 12)}`)
        setIsSuperseding(false)
      } else {
        result = await api.submitReviewFeedback(jobId, payload)
        setSuccessMsg(`Review feedback recorded as PO-asserted evidence. ID: ${result.feedback_id.slice(0, 12)}`)
      }

      onFeedbackSaved(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to submit review feedback')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRetract = async () => {
    if (!existingFeedback) return
    setSubmitting(true)
    setError(null)
    try {
      await api.retractFeedback(jobId, existingFeedback.feedback_id, retractReason)
      setShowRetractModal(false)
      setSuccessMsg(`Feedback ${existingFeedback.feedback_id.slice(0, 12)} retracted.`)
      if (onFeedbackRetracted) {
        onFeedbackRetracted(existingFeedback.feedback_id)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to retract feedback')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="review-decision-form bg-slate-900 border border-slate-700/60 rounded-xl p-5 text-slate-100 shadow-xl">
      {/* Zero Mutation Safe Mode Header */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800/80">
            Zero-Mutation Safe Mode
          </span>
        </div>
        <span className="text-xs text-slate-400 font-medium">
          Ý kiến Ký duyệt Vận hành
        </span>
      </div>

      {/* Existing Feedback Notice */}
      {existingFeedback && !isSuperseding && (
        <div className="mt-4 p-3 rounded-lg bg-slate-800/90 border border-cyan-800/60 flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold text-cyan-300 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
              Active Feedback on this Candidate: {existingFeedback.decision}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              By {existingFeedback.reviewer_subject || existingFeedback.operator_id} &bull; Confidence: {(existingFeedback.confidence ?? 1.0) * 100}%
              {existingFeedback.reason && ` &bull; "${existingFeedback.reason}"`}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsSuperseding(true)}
              className="px-2.5 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded font-medium transition-colors cursor-pointer"
            >
              Sửa / thay thế
            </button>
            <button
              type="button"
              onClick={() => setShowRetractModal(true)}
              className="px-2.5 py-1 text-xs bg-rose-950 hover:bg-rose-900 border border-rose-800 text-rose-300 rounded font-medium transition-colors cursor-pointer"
            >
              Thu hồi
            </button>
          </div>
        </div>
      )}

      {isSuperseding && (
        <div className="mt-4 p-2.5 rounded-lg bg-amber-950/40 border border-amber-800/60 text-xs text-amber-300 flex items-center justify-between">
          <span>
            <strong>Superseding mode:</strong> This submission will append a new feedback row and record an audited <code>SUPERSEDED</code> lifecycle event for {existingFeedback?.feedback_id.slice(0, 12)}.
          </span>
          <button
            type="button"
            onClick={() => setIsSuperseding(false)}
            className="text-amber-200 underline hover:text-amber-100 cursor-pointer"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Retract Modal */}
      {showRetractModal && (
        <div className="mt-4 p-4 rounded-xl bg-slate-800 border border-rose-700/60 space-y-3">
          <div className="text-sm font-semibold text-rose-300">
            Confirm Retraction of Review Feedback
          </div>
          <p className="text-xs text-slate-300">
            Retraction marks the feedback as <code>RETRACTED</code> in the immutable lifecycle audit log, excluding it from downstream ranker training sets.
          </p>
          <input
            type="text"
            placeholder="Reason for retraction (e.g. invalid topology context)"
            value={retractReason}
            onChange={(e) => setRetractReason(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-100"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowRetractModal(false)}
              className="px-3 py-1 text-xs bg-slate-700 rounded text-slate-300 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={handleRetract}
              className="px-3 py-1 text-xs bg-rose-700 hover:bg-rose-600 rounded font-semibold text-white cursor-pointer"
            >
              {submitting ? 'Retracting...' : 'Confirm Retract'}
            </button>
          </div>
        </div>
      )}

      {/* Main Submission Form */}
      {(!existingFeedback || isSuperseding) && (
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {/* Decision Selection Cards */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Ý kiến ký duyệt (Review Decision)
            </label>
            <div className="grid grid-cols-2 gap-3">
              {DECISIONS.map((d) => {
                const isSelected = selectedDecision === d.value
                return (
                  <button
                    key={d.value}
                    type="button"
                    title={d.desc}
                    onClick={() => {
                      setSelectedDecision(d.value)
                      setUserReasonCode(null)
                    }}
                    className={`px-4 py-3 rounded-xl border text-center transition-all cursor-pointer font-semibold shadow-sm ${
                      isSelected
                        ? `${d.badgeClass} ring-2 ring-cyan-500/50 scale-[1.02] shadow-md`
                        : 'bg-slate-800/70 border-slate-700/60 text-slate-300 hover:bg-slate-800 hover:text-white'
                    }`}
                  >
                    <div className="text-sm font-bold flex items-center justify-center gap-2">
                      <span className="material-symbols-outlined text-[18px]">
                        {d.value === 'APPROVE' ? 'check_circle' : 'cancel'}
                      </span>
                      <span>{d.label}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Dynamic Reason Codes - Only shown for MANUAL_CORRECTION where server strictly requires an explicit reason code */}
          {selectedDecision === 'MANUAL_CORRECTION' && availableReasons.length > 0 && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                Lý do hiệu chỉnh ({policy?.policy_version ?? 'review-reasons-v1'})
              </label>
              <select
                value={selectedReasonCode}
                onChange={(e) => setUserReasonCode(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-cyan-500"
              >
                {availableReasons.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label} — {r.description}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Manual Correction Fields */}
          {selectedDecision === 'MANUAL_CORRECTION' && (
            <div className="p-3.5 rounded-lg bg-slate-800/80 border border-cyan-800/70 space-y-3">
              <div className="text-xs font-semibold text-cyan-300 uppercase tracking-wider">
                Manual Partition Definition (Conserved Alarm Universe)
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Operation</label>
                  <select
                    value={mcOperation}
                    onChange={(e) => setMcOperation(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100"
                  >
                    <option value="MOVE_MEMBER">Move Member</option>
                    <option value="SPLIT">Split Chain</option>
                    <option value="MERGE">Merge Chains</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Target / New Chain ID</label>
                  <input
                    type="text"
                    value={mcTargetChain}
                    onChange={(e) => setMcTargetChain(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Affected Alarm IDs (comma separated)</label>
                <input
                  type="text"
                  placeholder="e.g. alarm_101, alarm_102"
                  value={mcAlarmIds}
                  onChange={(e) => setMcAlarmIds(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Edit Summary / Protocol Context</label>
                <input
                  type="text"
                  placeholder="e.g. Isolating optical transponder alarms from IP BGP layer"
                  value={mcSummary}
                  onChange={(e) => setMcSummary(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100"
                />
              </div>
            </div>
          )}

          {/* Confidence Slider */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Mức độ tin cậy (Decision Confidence: {Math.round(confidence * 100)}%)
              </label>
              <span className="text-[11px] text-slate-400">
                {confidence >= 0.9 ? 'Chắc chắn (Definitive)' : confidence >= 0.6 ? 'Có thể' : 'Chưa rõ'}
              </span>
            </div>
            <input
              type="range"
              min="0.0"
              max="1.0"
              step="0.05"
              value={confidence}
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
              className="w-full accent-cyan-500 cursor-pointer"
            />
          </div>

          {/* Justification Notes */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
              Ghi chú của kỹ sư (Reviewer Justification / Notes)
            </label>
            <textarea
              rows={2}
              placeholder="Nhập căn cứ kỹ thuật hoặc lý do vận hành (tùy chọn)..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>

          {error && <div className="text-xs text-rose-400 p-2 bg-rose-950/50 rounded">{error}</div>}
          {successMsg && <div className="text-xs text-emerald-400 p-2 bg-emerald-950/50 rounded">{successMsg}</div>}

          {/* Submit Button */}
          <div className="pt-2 flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-semibold tracking-wide shadow-lg shadow-cyan-900/40 disabled:opacity-50 transition-all cursor-pointer"
            >
              {submitting ? 'Đang lưu...' : isSuperseding ? 'Xác nhận thay thế' : 'Lưu Ý Kiến (Record Review Feedback)'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
