import { useEffect, useRef, useState } from 'react'

import { api } from './api'
import type { AssistantAction, AssistantContext, AssistantResponse } from './types'

const quickQuestions = [
  'Conductance là gì?',
  'Open Pair WHY',
  'Open audit',
  'Open review',
  'What is the root cause?',
]

export function NocProAssistantPanel({
  context,
  onNavigate,
}: {
  context: AssistantContext
  onNavigate: (action: AssistantAction) => void
}) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<AssistantResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestRef = useRef<{ id: number; controller: AbortController } | null>(null)
  const contextKey = [
    context.snapshot_id,
    context.snapshot_version,
    context.chain_id ?? '',
    context.pair_alarm_id_a ?? '',
    context.pair_alarm_id_b ?? '',
  ].join('\u0000')
  const contextKeyRef = useRef(contextKey)
  contextKeyRef.current = contextKey

  useEffect(() => () => requestRef.current?.controller.abort(), [])

  async function ask(nextQuery = query) {
    const trimmed = nextQuery.trim()
    if (!trimmed) return
    requestRef.current?.controller.abort()
    const request = { id: (requestRef.current?.id ?? 0) + 1, controller: new AbortController() }
    requestRef.current = request
    const requestedContextKey = contextKey
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const response = await api.assistantQuery(trimmed, context, request.controller.signal)
      if (requestRef.current?.id === request.id && contextKeyRef.current === requestedContextKey) setResult(response)
    } catch (cause) {
      if (request.controller.signal.aborted) return
      if (requestRef.current?.id === request.id) {
        setError(cause instanceof Error ? cause.message : 'Không thể tải NocPro Assistant')
      }
    } finally {
      if (requestRef.current?.id === request.id) setLoading(false)
    }
  }

  return (
    <section className="ai-advisor-panel nocpro-assistant-panel">
      <header className="ai-advisor-header">
        <div>
          <p className="kicker">Read-only investigation assistant · {context.snapshot_id}/{context.snapshot_version}</p>
          <h2>NocPro Assistant</h2>
          <p className="ai-advisor-sub">Giải thích evidence đã có, tìm chain và điều hướng trong snapshot đang mở.</p>
        </div>
        <span className="pill pill--positive">DETERMINISTIC · READ ONLY</span>
      </header>

      <div className="ai-epistemic-banner">
        <span className="ai-epistemic-icon">🔒</span>
        <div>
          <strong>Assistant không thay đổi analysis</strong>
          <p>Không chạy Deep Dive/Review, không tạo evidence, không Apply recommendation, không gửi feedback và không kết luận root cause.</p>
        </div>
      </div>

      <form className="assistant-query-form" onSubmit={(event) => { event.preventDefault(); void ask() }}>
        <label htmlFor="assistant-query">Hỏi về snapshot hiện tại</label>
        <div className="assistant-query-row">
          <input
            id="assistant-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={500}
            placeholder="Ví dụ: Conductance là gì? / Open audit / CHAIN-123"
          />
          <button className="review-btn-action review-btn-approve" disabled={loading || !query.trim()}>
            {loading ? 'Đang tra cứu…' : 'Hỏi'}
          </button>
        </div>
      </form>

      <div className="assistant-quick-actions" aria-label="Assistant quick questions">
        {quickQuestions.map((item) => (
          <button key={item} type="button" className="text-action-btn" disabled={loading} onClick={() => { setQuery(item); void ask(item) }}>
            {item}
          </button>
        ))}
      </div>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {result && (
        <article className="ai-suggestion-body assistant-result" aria-live="polite">
          <div className="assistant-result-status">
            <span className={`pill pill--${result.status === 'AVAILABLE' ? 'positive' : 'neutral'}`}>{result.status}</span>
            <small>{result.contract_version}</small>
          </div>
          <p className="assistant-message">{result.message}</p>
          {result.actions.length > 0 && (
            <div className="assistant-action-list">
              {result.actions.map((action) => (
                <button key={`${action.label}:${JSON.stringify(action.target)}`} type="button" className="review-btn-action review-btn-approve" onClick={() => onNavigate(action)}>
                  {action.label}
                </button>
              ))}
            </div>
          )}
          {result.fact_refs.length > 0 && (
            <footer className="ai-advisor-footer"><small>Evidence references: {result.fact_refs.join(' · ')}</small></footer>
          )}
        </article>
      )}
      <footer className="ai-advisor-footer"><small>Assistant can explain registered concepts, search active chains, and navigate. It does not change evidence, analysis results, recommendations or NocPro chains.</small></footer>
    </section>
  )
}
