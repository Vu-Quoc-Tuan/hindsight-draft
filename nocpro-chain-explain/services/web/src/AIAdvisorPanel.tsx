import { useEffect, useState } from 'react'

import { api } from './api'
import type { AISuggestion } from './types'

export function AIAdvisorPanel({
  chainId,
  initialSuggestion = null,
}: {
  chainId: string
  initialSuggestion?: AISuggestion | null
}) {
  const [suggestion, setSuggestion] = useState<AISuggestion | null>(initialSuggestion)
  const [loading, setLoading] = useState(initialSuggestion == null)
  const [error, setError] = useState<string | null>(null)
  const [refreshIndex, setRefreshIndex] = useState(0)

  useEffect(() => {
    if (initialSuggestion?.chain_id === chainId && refreshIndex === 0) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)

    api.aiSuggestion(chainId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSuggestion(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Không thể tải phân tích AI')
          setLoading(false)
        }
      })

    return () => controller.abort()
  }, [chainId, initialSuggestion, refreshIndex])

  const renderNarrative = (text: string) => {
    const lines = text.split('\n')
    return lines.map((line, idx) => {
      const trimmed = line.trim()
      if (trimmed.startsWith('### ')) {
        return <h3 key={idx} className="ai-narrative-heading">{trimmed.replace('### ', '')}</h3>
      }
      if (trimmed.startsWith('- ')) {
        return (
          <li key={idx} className="ai-narrative-item">
            {trimmed.replace('- ', '')}
          </li>
        )
      }
      if (trimmed.startsWith('> ')) {
        return (
          <blockquote key={idx} className="ai-narrative-quote">
            {trimmed.replace('> ', '').replace('[!NOTE]', '').trim()}
          </blockquote>
        )
      }
      if (!trimmed) {
        return <div key={idx} className="ai-narrative-spacer" />
      }
      return <p key={idx} className="ai-narrative-paragraph">{trimmed}</p>
    })
  }

  return (
    <section className="ai-advisor-panel">
      <header className="ai-advisor-header">
        <div>
          <p className="kicker">ADR-0024 Grounded Narrative · Viettel NOC AI Support</p>
          <h2>✨ Trợ lý AI Viettel NocPro</h2>
          <p className="ai-advisor-sub">
            Diễn giải và tổng hợp các mệnh đề bằng chứng xác định của chuỗi <strong>{chainId}</strong>.
          </p>
        </div>
        <div className="ai-advisor-actions">
          {suggestion ? (
            <span className={`pill pill--${suggestion.status === 'AVAILABLE' ? 'positive' : 'neutral'}`}>
              {suggestion.model} · {suggestion.status}
            </span>
          ) : null}
          <button
            type="button"
            className="review-btn-action review-btn-approve"
            onClick={() => setRefreshIndex((v) => v + 1)}
            disabled={loading}
          >
            {loading ? 'Đang phân tích…' : '🔄 Tải lại phân tích AI'}
          </button>
        </div>
      </header>

      <div className="ai-epistemic-banner">
        <span className="ai-epistemic-icon">🔒</span>
        <div>
          <strong>Nguyên tắc tri thức luận (ADR-0024 Epistemic Boundary)</strong>
          <p>
            AI chỉ được phép đọc kết quả phân tích toán học xác định của hệ thống để diễn giải ngôn ngữ tự nhiên.
            Tuyệt đối không tự tạo bằng chứng giả định, không tự sửa điểm số, và không tự ý thay đổi chuỗi cảnh báo.
          </p>
        </div>
      </div>

      {loading && !suggestion ? (
        <div className="loading-state">
          <span />
          <p>Đang phân tích dữ liệu chuỗi bằng Mistral-Large…</p>
        </div>
      ) : error ? (
        <div className="error-banner" role="alert">
          <strong>Lỗi khi kết nối Trợ lý AI</strong>
          <p>{error}</p>
        </div>
      ) : suggestion ? (
        <article className="ai-suggestion-body">
          {suggestion.provider_status && suggestion.provider_status !== 'OK' && (
            <div className="ai-provider-notice">
              <span>⚠️ Thông báo nhà cung cấp LLM:</span> {suggestion.provider_status}.
              <small>Hệ thống tự động sử dụng Bản tổng hợp xác định (Deterministic Grounded Synthesis) để đảm bảo không gián đoạn.</small>
            </div>
          )}

          <div className="ai-narrative-content">
            {renderNarrative(suggestion.narrative)}
          </div>

          {suggestion.grounded_claims.length > 0 && (
            <div className="ai-claims-section">
              <h4>Mệnh đề bằng chứng xác minh (Grounded Claims)</h4>
              <ul className="ai-claims-list">
                {suggestion.grounded_claims.map((claim, idx) => (
                  <li key={idx} className="ai-claim-pill">
                    ✓ {claim}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <footer className="ai-advisor-footer">
            <small>{suggestion.disclaimer}</small>
          </footer>
        </article>
      ) : null}
    </section>
  )
}
