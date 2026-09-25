import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { ReviewFeedbackHistoryErrorNotice } from './ReviewFeedbackHistoryErrorNotice'

describe('ReviewFeedbackHistoryErrorNotice', () => {
  it('renders provenance guidance without a retry button', () => {
    const onRetry = vi.fn()
    const alert = renderToStaticMarkup(
      <ReviewFeedbackHistoryErrorNotice
        message="REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE"
        onRetry={onRetry}
        variant="alert"
      />,
    )
    const status = renderToStaticMarkup(
      <ReviewFeedbackHistoryErrorNotice
        message="REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE"
        onRetry={onRetry}
        variant="status"
      />,
    )

    expect(alert).toContain('role="alert"')
    expect(alert).toContain('Thiếu thông tin provenance')
    expect(alert).toContain('Snapshot này chưa có hồ sơ nguồn (profile) rõ ràng hoặc provenance đang mâu thuẫn.')
    expect(alert).not.toContain('<button')
    expect(status).toContain('role="status"')
    expect(status).toContain('Cần ingest lại snapshot với provenance xác định; tải lại trang không khắc phục được lỗi dữ liệu này.')
  })

  it('renders generic retry guidance and the retry button', () => {
    const alert = renderToStaticMarkup(
      <ReviewFeedbackHistoryErrorNotice
        message="Failed to fetch"
        onRetry={vi.fn()}
        variant="alert"
      />,
    )
    const status = renderToStaticMarkup(
      <ReviewFeedbackHistoryErrorNotice
        message="Failed to fetch"
        onRetry={vi.fn()}
        variant="status"
      />,
    )

    expect(alert).toContain('role="alert"')
    expect(alert).toContain('Failed to fetch')
    expect(alert).toContain('<button type="button"')
    expect(alert).toContain('Thử lại')
    expect(status).toContain('role="status"')
    expect(status).toContain('Kiểm tra kết nối hoặc thử tải lại trang.')
  })
})
