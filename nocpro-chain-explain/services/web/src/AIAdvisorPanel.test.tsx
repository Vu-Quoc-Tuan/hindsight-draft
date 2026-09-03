import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AIAdvisorPanel } from './AIAdvisorPanel'
import type { AISuggestion } from './types'

const mockSuggestion: AISuggestion = {
  chain_id: 'CHAIN-VN-001',
  status: 'AVAILABLE',
  model: 'mistral-large',
  narrative: `### Tổng quan Chuỗi Sự Cố
- Chuỗi bao gồm 3 cảnh báo.
- Cảnh báo gốc suy diễn: ALARM-1 (Độ tin cậy: 0.95).
> [!NOTE] Cấu trúc phụ thuộc hình cây rõ ràng.
Đề xuất tối ưu hóa có sẵn trong mục Review.`,
  grounded_claims: [
    'Tổng số cảnh báo trong chuỗi: 3',
    'Cảnh báo gốc suy diễn (Root-cause): ALARM-1 (Score: 0.95)',
    'Số thành viên yếu (Weak members): 0',
  ],
  disclaimer: 'Phân tích được tạo bởi mô hình AI (Mistral-Large) tuân thủ ADR-0024.',
  provider_status: 'OK',
}

const mockFallbackSuggestion: AISuggestion = {
  chain_id: 'CHAIN-VN-002',
  status: 'AVAILABLE',
  model: 'mistral-large',
  narrative: '### Bản Tổng Hợp Xác Định (Deterministic Grounded Synthesis)\nChuỗi 5 cảnh báo.',
  grounded_claims: ['Tổng số cảnh báo trong chuỗi: 5'],
  disclaimer: 'Bản diễn giải xác định (ADR-0024).',
  provider_status: 'telegram_required: Join the required Telegram group/channel and relink at /settings to continue.',
}

describe('AIAdvisorPanel', () => {
  it('renders grounded narrative, epistemic banner, and claims for available suggestion', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel chainId="CHAIN-VN-001" initialSuggestion={mockSuggestion} />,
    )

    // Epistemic boundary banner
    expect(html).toContain('ADR-0024 Grounded Narrative')
    expect(html).toContain('Nguyên tắc tri thức luận (ADR-0024 Epistemic Boundary)')
    expect(html).toContain('Tuyệt đối không tự tạo bằng chứng giả định')

    // Model and status
    expect(html).toContain('mistral-large')
    expect(html).toContain('AVAILABLE')

    // Narrative content
    expect(html).toContain('Tổng quan Chuỗi Sự Cố')
    expect(html).toContain('Chuỗi bao gồm 3 cảnh báo.')
    expect(html).toContain('Cảnh báo gốc suy diễn: ALARM-1')
    expect(html).toContain('Cấu trúc phụ thuộc hình cây rõ ràng.')

    // Grounded claims
    expect(html).toContain('Mệnh đề bằng chứng xác minh (Grounded Claims)')
    expect(html).toContain('Tổng số cảnh báo trong chuỗi: 3')
    expect(html).toContain('Cảnh báo gốc suy diễn (Root-cause): ALARM-1 (Score: 0.95)')

    // Disclaimer
    expect(html).toContain('Phân tích được tạo bởi mô hình AI (Mistral-Large) tuân thủ ADR-0024.')
  })

  it('renders provider notice when external LLM provider reports non-OK status', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel chainId="CHAIN-VN-002" initialSuggestion={mockFallbackSuggestion} />,
    )

    expect(html).toContain('Thông báo nhà cung cấp LLM')
    expect(html).toContain('telegram_required')
    expect(html).toContain('Deterministic Grounded Synthesis')
  })
})
