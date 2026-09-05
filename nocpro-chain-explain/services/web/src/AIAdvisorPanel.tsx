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
          <p key={idx} className="ai-narrative-item">
            {trimmed.replace('- ', '')}
          </p>
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
          <h2>Evidence summary</h2>
          <p className="ai-advisor-sub">
            Bản diễn giải xác định từ evidence đã persist của chuỗi <strong>{chainId}</strong>.
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
            {loading ? 'Đang tải…' : '🔄 Tải lại evidence summary'}
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
          <p>Đang tải evidence summary xác định…</p>
        </div>
      ) : error ? (
        <div className="error-banner" role="alert">
          <strong>Không thể tải evidence summary</strong>
          <p>{error}</p>
        </div>
      ) : suggestion ? (
        <article className="ai-suggestion-body">
          {suggestion.provider_status === 'ERROR' && (
            <div className="ai-provider-notice">
              <span>⚠️ Provider status:</span> {suggestion.provider_status}.
            </div>
          )}

          <div className="ai-narrative-content">
            {renderNarrative(suggestion.narrative)}
          </div>

          {suggestion.review_status === 'UNAVAILABLE' && (
            <div className="ai-provider-notice" role="status">
              <span>⚠️ Counterfactual Review:</span> không thể đọc artifact hiện tại
              {suggestion.review_reason ? ` (${suggestion.review_reason})` : ''}.
            </div>
          )}

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
