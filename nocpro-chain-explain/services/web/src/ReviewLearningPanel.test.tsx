import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ReviewLearningPanel } from './ReviewLearningPanel'

describe('ReviewLearningPanel', () => {
  it('does not render when open is false', () => {
    const html = renderToStaticMarkup(
      <ReviewLearningPanel open={false} onClose={() => {}} />
    )
    expect(html).toBe('')
  })

  it('renders governance modal frame and header when open is true', () => {
    const html = renderToStaticMarkup(
      <ReviewLearningPanel open={true} onClose={() => {}} />
    )
    expect(html).toContain('Review Learning &amp; Model Governance')
    expect(html).toContain('XGBRanker')
    expect(html).toContain('NDCG@3 Score')
    expect(html).toContain('Top-1 Recall')
    expect(html).toContain('Mean Regret')
    expect(html).toContain('Mức độ ảnh hưởng đặc trưng (XGBRanker Feature Gain Importance)')
    expect(html).toContain('Tập huấn luyện (Data Profile)')
    expect(html).toContain('Vòng phản hồi chuyên viên (Feedback Loop)')
    expect(html).toContain('Huấn luyện lại mô hình (Re-train Ranker Pipeline)')
    expect(html).toContain('Nguyên tắc Quản trị ADR-0024:')
    expect(html).toContain('Hindsight NOC Pro · Phase 3 Review Learning')
  })
})
