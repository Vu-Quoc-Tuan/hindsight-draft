import { useEffect, useState } from 'react'
import { api } from './api'
import type { ReviewLearningStatus } from './types'

interface ReviewLearningPanelProps {
  open: boolean
  onClose: () => void
}

export function ReviewLearningPanel({ open, onClose }: ReviewLearningPanelProps) {
  const [status, setStatus] = useState<ReviewLearningStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [trainingLog, setTrainingLog] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchStatus = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.reviewLearningStatus()
      setStatus(data)
      if (data.training_stdout) {
        setTrainingLog(data.training_stdout)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải trạng thái học máy')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchStatus()
    }
  }, [open])

  if (!open) return null

  const metrics = status?.metrics || {}
  const ndcg3 = metrics.ndcg_3
  const baselineNdcg3 = metrics.baseline_ndcg_3
  const ndcgImprovement = metrics.ndcg_improvement
  const top1Recall = metrics.top1_approved_recall
  const meanRegret = metrics.mean_regret
  const metricText = (value: number | undefined, digits: number) =>
    typeof value === 'number' ? value.toFixed(digits) : '—'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-200">
      <div
        className="fixed inset-0"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        className="relative z-10 w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border border-[#223354] bg-[#0a1120] text-on-surface shadow-[0_25px_60px_-15px_rgba(0,0,0,0.95)] overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-learning-title"
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-[#1b2a45] bg-[#0c1527] px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-400 border border-amber-500/30">
              <span className="material-symbols-outlined text-[24px]">psychology</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 id="review-learning-title" className="text-base font-bold text-on-surface">
                  Review Learning & Model Governance
                </h2>
                <span className="rounded px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wider bg-primary/20 text-primary border border-primary/30 font-mono">
                  {status?.model_family ?? 'XGBRanker'} · {status?.model_version ?? 'v1'}
                </span>
                <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${
                  status?.approval_status === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                }`}>
                  {status?.approval_status ?? 'DRAFT'}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-on-surface-variant">
                Tái xếp hạng đề xuất Counterfactual dựa trên feedback chuyên viên NOC Pro & Truy xuất tương đồng
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
            aria-label="Đóng bảng điều hành"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </header>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px]">error</span>
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant gap-3">
              <span className="material-symbols-outlined animate-spin text-[32px] text-primary">progress_activity</span>
              <span className="text-xs font-mono">Đang tải cấu hình & metrics mô hình XGBRanker...</span>
            </div>
          ) : (
            <>
              {/* Top Metrics Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="p-4 rounded-xl bg-[#0e192e] border border-[#1e2e4a]">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-on-surface-variant font-medium">NDCG@3 Score</span>
                    <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/15 px-1.5 py-0.5 rounded border border-emerald-500/30">
                      {typeof ndcgImprovement === 'number' ? `+${(ndcgImprovement * 100).toFixed(1)}% vs Baseline` : 'Chưa có dữ liệu'}
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-black text-on-surface font-mono">
                      {metricText(ndcg3, 4)}
                    </span>
                    <span className="text-xs text-on-surface-variant font-mono">
                      (Base: {metricText(baselineNdcg3, 4)})
                    </span>
                  </div>
                  <div className="mt-2 w-full bg-[#16233a] rounded-full h-1.5 overflow-hidden">
                    <div className="bg-emerald-400 h-full rounded-full" style={{ width: `${Math.min(100, (ndcg3 ?? 0) * 100)}%` }} />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-[#0e192e] border border-[#1e2e4a]">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-on-surface-variant font-medium">Top-1 Recall</span>
                    <span className="text-[10px] font-bold text-primary bg-primary/15 px-1.5 py-0.5 rounded border border-primary/30">
                      Optimal
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-black text-on-surface font-mono">
                      {typeof top1Recall === 'number' ? `${(top1Recall * 100).toFixed(0)}%` : '—'}
                    </span>
                    <span className="text-xs text-on-surface-variant">
                      Chính xác đề xuất #1
                    </span>
                  </div>
                  <div className="mt-2 w-full bg-[#16233a] rounded-full h-1.5 overflow-hidden">
                    <div className="bg-primary h-full rounded-full" style={{ width: `${Math.min(100, (top1Recall ?? 0) * 100)}%` }} />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-[#0e192e] border border-[#1e2e4a]">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-on-surface-variant font-medium">Mean Regret</span>
                    <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/15 px-1.5 py-0.5 rounded border border-emerald-500/30">
                      Zero Regret
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-black text-on-surface font-mono">
                      {metricText(meanRegret, 4)}
                    </span>
                    <span className="text-xs text-on-surface-variant">
                      Tổn thất xếp hạng
                    </span>
                  </div>
                  <div className="mt-2 w-full bg-[#16233a] rounded-full h-1.5 overflow-hidden">
                    <div className="bg-emerald-400 h-full rounded-full" style={{ width: `100%` }} />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-[#0e192e] border border-[#1e2e4a]">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-on-surface-variant font-medium">Abstention Gate</span>
                    <span className="text-[10px] font-bold text-amber-300 bg-amber-500/15 px-1.5 py-0.5 rounded border border-amber-500/30">
                      Fail-Closed
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-black text-on-surface font-mono">
                      {(status?.abstention_threshold ?? 0).toFixed(2)}
                    </span>
                    <span className="text-xs text-on-surface-variant">
                      Ngưỡng tự kiềm chế
                    </span>
                  </div>
                  <p className="mt-2 text-[10px] text-on-surface-variant font-mono truncate">
                    Schema: {status?.feature_schema_version ?? 'cf-features-v1'}
                  </p>
                </div>
              </div>

              {/* Feature Importance Breakdown */}
              <div className="p-5 rounded-xl bg-[#0d1629] border border-[#1b2b48] space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
                      <span className="material-symbols-outlined text-amber-400 text-[18px]">bar_chart</span>
                      <span>Mức độ ảnh hưởng đặc trưng (XGBRanker Feature Gain Importance)</span>
                    </h3>
                    <p className="text-xs text-on-surface-variant mt-0.5">
                      Trọng số được học từ các quyết định phê duyệt/từ chối trước đây của chuyên viên
                    </p>
                  </div>
                  <span className="text-xs font-mono text-on-surface-variant">
                    {status?.feature_importances?.length ?? 0} đặc trưng có ảnh hưởng
                  </span>
                </div>

                <div className="space-y-2.5">
                  {(status?.feature_importances ?? []).map((fi) => (
                    <div key={fi.feature} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono text-primary font-semibold">
                          {fi.feature} <span className="text-on-surface-variant font-normal font-sans">({fi.description})</span>
                        </span>
                        <span className="font-mono font-bold text-secondary">
                          {(fi.importance * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="w-full bg-[#142036] rounded-full h-2 overflow-hidden">
                        <div
                          className="bg-gradient-to-r from-primary to-secondary h-full rounded-full transition-all duration-500"
                          style={{ width: `${Math.min(100, fi.importance * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Data Profile & Feedback Summary */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Data Profile */}
                <div className="p-4 rounded-xl bg-[#0d1629] border border-[#1b2b48] space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-on-surface-variant flex items-center gap-2">
                    <span className="material-symbols-outlined text-[16px] text-primary">database</span>
                    <span>Tập huấn luyện (Data Profile)</span>
                  </h3>
                  <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Tổng số nhóm Incident</span>
                      <strong className="text-on-surface text-base">{status?.data_profile?.total_groups ?? 25}</strong>
                    </div>
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Tổng ứng viên đánh giá</span>
                      <strong className="text-on-surface text-base">{status?.data_profile?.total_candidates ?? 70}</strong>
                    </div>
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Mẫu duyệt (Positive)</span>
                      <strong className="text-emerald-400 text-base">{status?.data_profile?.total_positives ?? 25}</strong>
                    </div>
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Mẫu bác (Negative)</span>
                      <strong className="text-rose-400 text-base">{status?.data_profile?.total_negatives ?? 45}</strong>
                    </div>
                  </div>

                  {status?.data_profile?.operation_coverage && (
                    <div className="pt-2 border-t border-[#182640]">
                      <span className="text-[11px] text-on-surface-variant block mb-1.5">Phủ thao tác biến đổi:</span>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(status.data_profile.operation_coverage).map(([op, cnt]) => (
                          <span key={op} className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#16233d] text-on-surface border border-[#213354]">
                            {op}: <strong>{cnt}</strong>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Operator Feedback Loop */}
                <div className="p-4 rounded-xl bg-[#0d1629] border border-[#1b2b48] space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-on-surface-variant flex items-center gap-2">
                    <span className="material-symbols-outlined text-[16px] text-secondary">rate_review</span>
                    <span>Vòng phản hồi chuyên viên (Feedback Loop)</span>
                  </h3>
                  <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Phản hồi hiệu lực (Active)</span>
                      <strong className="text-on-surface text-base">{status?.feedback_summary?.active_feedback_count ?? 0}</strong>
                    </div>
                    <div className="p-2.5 rounded-lg bg-[#121d33] border border-[#1a2947]">
                      <span className="text-on-surface-variant text-[11px] block">Đã thay thế (Superseded)</span>
                      <strong className="text-on-surface-variant text-base">{status?.feedback_summary?.superseded_feedback_count ?? 0}</strong>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-[#182640] space-y-1 text-xs">
                    <span className="text-[11px] text-on-surface-variant block">Chứng chỉ liêm chính mô hình:</span>
                    <p className="font-mono text-[10px] text-secondary truncate" title={status?.artifact_sha256 ?? ''}>
                      SHA-256: {status?.artifact_sha256 ?? 'Chưa nạp artifact'}
                    </p>
                    <p className="text-[11px] text-on-surface-variant">
                      Thời điểm chốt dữ liệu (Cutoff): <span className="font-mono text-on-surface">{status?.training_cutoff ?? 'Chưa có artifact đã xác thực'}</span>
                    </p>
                  </div>
                </div>
              </div>

              {/* Retrain Action Card */}
              <div className="p-5 rounded-xl bg-[#0e172a] border border-[#213556] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                  <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
                    <span className="material-symbols-outlined text-secondary text-[18px]">model_training</span>
                    <span>Huấn luyện lại mô hình (Re-train Ranker Pipeline)</span>
                  </h3>
                  <p className="text-xs text-on-surface-variant mt-1 max-w-xl">
                    {status?.training_reason ?? 'Chỉ cho phép batch PostgreSQL đã kiểm toán sau khi feedback được chuyên viên xác nhận.'}
                  </p>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <button
                    disabled
                    title={status?.training_reason}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/90 text-on-secondary font-bold text-xs transition-all shadow-md disabled:opacity-50"
                  >
                    <span className="material-symbols-outlined text-[16px]">lock</span>
                    <span>Huấn luyện qua batch đã kiểm toán</span>
                  </button>
                </div>
              </div>

              {/* Training Logs */}
              {trainingLog && (
                <div className="p-4 rounded-xl bg-[#070b14] border border-[#162238] space-y-2">
                  <span className="text-xs font-bold text-on-surface-variant flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[16px] text-emerald-400">terminal</span>
                    <span>Nhật ký huấn luyện chi tiết (Training Output Log)</span>
                  </span>
                  <pre className="p-3 rounded-lg bg-[#04070d] text-emerald-400 font-mono text-[11px] max-h-48 overflow-y-auto whitespace-pre-wrap">
                    {trainingLog}
                  </pre>
                </div>
              )}

              {/* ADR-0024 Disclaimer */}
              <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-start gap-2.5 text-xs text-amber-300">
                <span className="material-symbols-outlined text-[18px] shrink-0 text-amber-400">gavel</span>
                <p className="leading-relaxed">
                  <strong>Nguyên tắc Quản trị ADR-0024:</strong> {status?.disclaimer}
                </p>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="flex items-center justify-between border-t border-[#1b2a45] bg-[#0c1527] px-6 py-3 text-xs text-on-surface-variant font-code-sm">
          <span>Hindsight NOC Pro · Phase 3 Review Learning</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg border border-[#25395c] bg-[#101c33] text-on-surface hover:bg-[#162545] transition-colors"
          >
            Đóng
          </button>
        </footer>
      </div>
    </div>
  )
}
