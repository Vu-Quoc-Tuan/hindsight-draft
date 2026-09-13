import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ExplainClarityComparisonModal } from './ExplainClarityComparisonModal'

describe('ExplainClarityComparisonModal', () => {
  it('does not render when isOpen is false', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={false}
        onClose={() => {}}
        mode="proposals"
        jobId="job-123"
      />
    )
    expect(html).toBe('')
  })

  it('renders modal structure for proposals comparison when isOpen is true', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="proposals"
        jobId="job-123"
      />
    )
    expect(html).toContain('So Sánh Trực Diện: Đề Xuất Nào Có Lời Giải Thích Rõ Ràng &amp; Thuyết Phục Hơn?')
    expect(html).toContain('⚖️ So sánh Đề xuất Tối ưu')
    expect(html).toContain('Job: job-123')
  })

  it('renders modal structure for threshold optimization when isOpen is true', () => {
    const html = renderToStaticMarkup(
      <ExplainClarityComparisonModal
        isOpen={true}
        onClose={() => {}}
        mode="threshold"
        chainId="C1"
      />
    )
    expect(html).toContain('Tìm Ngưỡng Tham Số Cho Ra Lời Giải Thích Rõ Ràng &amp; Sắc Nét Nhất')
    expect(html).toContain('🎯 Tối ưu hóa Ngưỡng Explain')
    expect(html).toContain('Chain: C1')
  })
})
