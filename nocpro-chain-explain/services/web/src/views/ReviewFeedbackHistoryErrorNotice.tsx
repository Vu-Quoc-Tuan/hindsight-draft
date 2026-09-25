import { reviewFeedbackHistoryErrorPresentation } from './reviewFeedbackHistoryError'

type ReviewFeedbackHistoryErrorNoticeProps = {
  message: string
  onRetry: () => void
  variant: 'alert' | 'status'
}

export function ReviewFeedbackHistoryErrorNotice({
  message,
  onRetry,
  variant,
}: ReviewFeedbackHistoryErrorNoticeProps) {
  const presentation = reviewFeedbackHistoryErrorPresentation(message)

  if (variant === 'alert') {
    return (
      <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
        <span className="font-semibold">{presentation.title}:</span> {presentation.message}
        {presentation.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="ml-3 rounded border border-rose-300/30 px-2 py-1 text-xs font-semibold text-rose-100 hover:bg-rose-400/10 focus:outline-none focus:ring-1 focus:ring-rose-300"
          >
            Thử lại
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex min-h-44 flex-col items-center justify-center px-6 py-10 text-center" role="status">
      <span className="material-symbols-outlined text-3xl text-rose-300">cloud_off</span>
      <h3 className="mt-2 font-semibold text-on-surface">Chưa thể hiển thị lịch sử</h3>
      <p className="mt-1 max-w-lg text-sm text-on-surface-variant">{presentation.guidance}</p>
    </div>
  )
}
