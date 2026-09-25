export type ReviewFeedbackHistoryErrorPresentation = {
  title: string
  message: string
  guidance: string
  retryable: boolean
}

export function reviewFeedbackHistoryErrorPresentation(
  message: string,
): ReviewFeedbackHistoryErrorPresentation {
  if (message === 'REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE') {
    return {
      title: 'Thiếu thông tin provenance',
      message: 'Snapshot này chưa có hồ sơ nguồn (profile) rõ ràng hoặc provenance đang mâu thuẫn.',
      guidance: 'Cần ingest lại snapshot với provenance xác định; tải lại trang không khắc phục được lỗi dữ liệu này.',
      retryable: false,
    }
  }
  return {
    title: 'Không tải được lịch sử',
    message,
    guidance: 'Kiểm tra kết nối hoặc thử tải lại trang.',
    retryable: true,
  }
}
