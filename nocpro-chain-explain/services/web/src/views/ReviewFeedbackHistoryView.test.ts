import { describe, expect, it } from 'vitest'

import { reviewFeedbackHistoryErrorPresentation } from './reviewFeedbackHistoryError'

describe('review feedback history error presentation', () => {
  it('explains unavailable provenance without recommending a retry', () => {
    expect(reviewFeedbackHistoryErrorPresentation('REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE')).toEqual({
      title: 'Thiếu thông tin provenance',
      message: 'Snapshot này chưa có hồ sơ nguồn (profile) rõ ràng hoặc provenance đang mâu thuẫn.',
      guidance: 'Cần ingest lại snapshot với provenance xác định; tải lại trang không khắc phục được lỗi dữ liệu này.',
      retryable: false,
    })
  })

  it('keeps retry guidance for other errors', () => {
    expect(reviewFeedbackHistoryErrorPresentation('Failed to fetch')).toEqual({
      title: 'Không tải được lịch sử',
      message: 'Failed to fetch',
      guidance: 'Kiểm tra kết nối hoặc thử tải lại trang.',
      retryable: true,
    })
  })
})
