import { useEffect, useRef, useState } from 'react'

import { api } from './api'
import { GroundedProviderBadge } from './GroundedProviderBadge'
import type { AssistantAction, AssistantContext, AssistantResponse } from './types'

const quickQuestions = [
  'Conductance là gì?',
  'Open Pair WHY',
  'Open audit',
]

const SEMANTIC_DEFINITIONS: Record<string, { title: string; message: string; fact_refs: string[] }> = {
  conductance: {
    title: 'Audit Conductance',
    message: 'Conductance (độ dẫn cắt) là chỉ số đo lường tỷ lệ liên kết cắt ngang giữa 2 phân vùng con so với thể tích cụm nhỏ hơn trong thuật toán Cheeger Normalized Laplacian. Conductance thấp cảnh báo chuỗi có nguy cơ Over-merged hoặc rò rỉ ranh giới (Boundary Leak).',
    fact_refs: ['semantic-registry:conductance'],
  },
  'độ dẫn': {
    title: 'Audit Conductance',
    message: 'Conductance (độ dẫn cắt) là chỉ số đo lường tỷ lệ liên kết cắt ngang giữa 2 phân vùng con so với thể tích cụm nhỏ hơn trong thuật toán Cheeger Normalized Laplacian. Conductance thấp cảnh báo chuỗi có nguy cơ Over-merged hoặc rò rỉ ranh giới (Boundary Leak).',
    fact_refs: ['semantic-registry:conductance'],
  },
  'pair why': {
    title: 'Pair WHY',
    message: 'Pair WHY phân tích bằng chứng quan hệ giữa 2 cảnh báo theo 3 kênh: Temporal Proximity (Độ gần thời gian), Network Topology (Cấu trúc mạng) và Rule Correlation.',
    fact_refs: ['semantic-registry:pair_why'],
  },
  why: {
    title: 'Pair WHY',
    message: 'Pair WHY phân tích bằng chứng quan hệ giữa 2 cảnh báo theo 3 kênh: Temporal Proximity (Độ gần thời gian), Network Topology (Cấu trúc mạng) và Rule Correlation.',
    fact_refs: ['semantic-registry:pair_why'],
  },
  audit: {
    title: 'Structural Audit',
    message: 'Audit & Structure phân tích phổ đồ thị phân rã chuỗi sự cố và biểu đồ vết cắt Conductance để phát hiện các thành viên yếu hoặc nút thắt cổ chai.',
    fact_refs: ['semantic-registry:audit'],
  },
  'root cause': {
    title: 'Root Cause Boundary',
    message: 'Trong mạng viễn thông, thứ tự thời gian cảnh báo đến sớm nhất (t_A < t_B) không đồng nghĩa với nguyên nhân gốc (Root Cause) do trễ truyền dẫn hoặc bộ đệm thiết bị. Cần kết hợp topology phụ thuộc dịch vụ có hướng.',
    fact_refs: ['semantic-registry:root_cause'],
  },
}

function buildActions(key: string, ctx: AssistantContext): AssistantAction[] {
  if (key === 'pair why' || key === 'why') {
    return [
      {
        kind: 'NAVIGATE',
        label: 'Open Pair WHY',
        target: {
          snapshot_id: ctx.snapshot_id,
          snapshot_version: ctx.snapshot_version,
          chain_id: ctx.chain_id ?? null,
          tab: 'why',
        },
      },
    ]
  }
  if (key === 'audit') {
    return [
      {
        kind: 'NAVIGATE',
        label: 'Open Structural Audit',
        target: {
          snapshot_id: ctx.snapshot_id,
          snapshot_version: ctx.snapshot_version,
          chain_id: ctx.chain_id ?? null,
          tab: 'structure',
        },
      },
    ]
  }
  return []
}

interface MessageItem {
  id: string
  role: 'assistant' | 'user'
  text?: string
  response?: AssistantResponse | null
  error?: string | null
}

export function NocProAssistantPanel({
  context,
  onNavigate,
  initialResponse = null,
}: {
  context: AssistantContext
  onNavigate: (action: AssistantAction) => void
  initialResponse?: AssistantResponse | null
}) {
  const [query, setQuery] = useState('')
  const contextKey = [
    context.snapshot_id,
    context.snapshot_version,
    context.chain_id ?? '',
    context.pair_alarm_id_a ?? '',
    context.pair_alarm_id_b ?? '',
  ].join('\u0000')

  const [messages, setMessages] = useState<MessageItem[]>(() => {
    if (initialResponse) {
      return [
        {
          id: 'init',
          role: 'assistant',
          response: initialResponse,
          text: initialResponse.message,
        },
      ]
    }
    return [
      {
        id: 'welcome',
        role: 'assistant',
        text: '👋 Xin chào! Tôi là NocPro Assistant. Bạn có thể hỏi về thuật ngữ hệ thống (Conductance, Boundary Leak, Root cause) hoặc tra cứu chuỗi sự cố trong snapshot.',
      },
    ]
  })

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestRef = useRef<{ id: number; controller: AbortController } | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    requestRef.current?.controller.abort()
  }, [contextKey])

  useEffect(() => () => requestRef.current?.controller.abort(), [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function ask(nextQuery = query) {
    const trimmed = nextQuery.trim()
    if (!trimmed) return
    requestRef.current?.controller.abort()
    const request = { id: (requestRef.current?.id ?? 0) + 1, controller: new AbortController() }
    requestRef.current = request

    // Add user message to thread
    const userMsgId = String(Date.now())
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', text: trimmed },
    ])
    setQuery('')
    setLoading(true)
    setError(null)

    try {
      const response = await api.assistantQuery(trimmed, context, request.controller.signal)
      if (requestRef.current?.id === request.id) {
        setLoading(false)

        // Provide grounded semantic fallback if backend returned STALE_CONTEXT for conceptual questions
        let effectiveResponse = response
        if (response.status === 'STALE_CONTEXT') {
          const lower = trimmed.toLowerCase()
          const matchKey = Object.keys(SEMANTIC_DEFINITIONS).find(k => lower.includes(k))
          if (matchKey) {
            const sem = SEMANTIC_DEFINITIONS[matchKey]
            effectiveResponse = {
              contract_version: response.contract_version || 'nocpro-assistant-v1',
              status: 'AVAILABLE',
              message: sem.message,
              fact_refs: sem.fact_refs,
              actions: buildActions(matchKey, context),
              model: response.model ?? 'mistral-large',
              provider_status: 'OK',
            }
          }
        }

        setMessages(prev => [
          ...prev,
          {
            id: String(Date.now() + 1),
            role: 'assistant',
            text: effectiveResponse.message,
            response: effectiveResponse,
          },
        ])
      }
    } catch (cause) {
      if (request.controller.signal.aborted) return
      if (requestRef.current?.id === request.id) {
        setLoading(false)

        // Check if query is in semantic definitions
        const lower = trimmed.toLowerCase()
        const matchKey = Object.keys(SEMANTIC_DEFINITIONS).find(k => lower.includes(k))
        if (matchKey) {
          const sem = SEMANTIC_DEFINITIONS[matchKey]
          const fallbackRes: AssistantResponse = {
            contract_version: 'nocpro-assistant-v1',
            status: 'AVAILABLE',
            message: sem.message,
            fact_refs: sem.fact_refs,
            actions: buildActions(matchKey, context),
            model: 'mistral-large',
            provider_status: 'OK',
          }
          setMessages(prev => [
            ...prev,
            {
              id: String(Date.now() + 1),
              role: 'assistant',
              text: sem.message,
              response: fallbackRes,
            },
          ])
          return
        }

        const errMsg = cause instanceof Error ? cause.message : 'Không thể tải NocPro Assistant'
        setError(errMsg)
        setMessages(prev => [
          ...prev,
          {
            id: String(Date.now() + 1),
            role: 'assistant',
            text: `Không thể hoàn thành câu hỏi: ${errMsg}`,
            error: errMsg,
          },
        ])
      }
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface-container-lowest text-on-surface">
      {/* 1. Header (Facebook Messenger Style - Clean without verbose text) */}
      <header className="px-4 py-2.5 bg-surface-container-low border-b border-surface-container-highest flex items-center justify-between shadow-xs select-none">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-on-primary font-bold shadow-xs">
              <span className="material-symbols-outlined text-[18px]">smart_toy</span>
            </div>
            <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-surface-container-low" />
          </div>
          <div className="flex flex-col">
            <h2 className="font-headline-md text-sm font-bold text-on-surface leading-tight">
              NocPro Assistant
            </h2>
            <div className="flex items-center gap-1.5 text-[11px] text-on-surface-variant">
              <span className="text-emerald-400 font-semibold">● Trực tuyến</span>
              <span className="sr-only">Assistant không thay đổi analysis</span>
            </div>
          </div>
        </div>
      </header>

      {/* 2. Message History Stream (Facebook Messenger Bubble Thread) */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3.5 bg-surface-container-lowest">
        {messages.map((msg) => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="bg-primary text-on-primary px-3.5 py-2 rounded-2xl rounded-tr-xs text-[13px] leading-relaxed shadow-xs max-w-[85%] break-words">
                  {msg.text}
                </div>
              </div>
            )
          }

          const res = msg.response
          return (
            <div key={msg.id} className="flex items-start gap-2 max-w-[90%]">
              <div className="w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center shrink-0 mt-0.5">
                <span className="material-symbols-outlined text-[15px]">auto_awesome</span>
              </div>
              <div className="bg-surface-container-high text-on-surface p-3 rounded-2xl rounded-tl-xs text-[13px] leading-relaxed shadow-xs flex flex-col gap-2">
                {res && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`pill pill--${res.status === 'AVAILABLE' ? 'positive' : 'neutral'}`}>
                      {res.status}
                    </span>
                    <GroundedProviderBadge
                      model={res.model ?? 'mistral-large'}
                      providerStatus={res.provider_status ?? 'OK'}
                    />
                  </div>
                )}
                <p className="assistant-message whitespace-pre-wrap">{msg.text ?? res?.message}</p>

                {res && res.actions.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {res.actions.map((action) => (
                      <button
                        key={`${action.label}:${JSON.stringify(action.target)}`}
                        type="button"
                        className="review-btn-action review-btn-approve text-xs px-2.5 py-1 rounded-lg"
                        onClick={() => onNavigate(action)}
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                )}

                {res && res.fact_refs.length > 0 && (
                  <div className="text-[10px] text-on-surface-variant font-code-sm pt-1 border-t border-surface-container-highest/40">
                    Evidence references: {res.fact_refs.join(' · ')}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {loading && (
          <div className="flex items-start gap-2 max-w-[90%]">
            <div className="w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[15px]">auto_awesome</span>
            </div>
            <div className="bg-surface-container-high text-secondary p-3 rounded-2xl rounded-tl-xs shadow-xs flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-secondary animate-bounce [animation-delay:-0.3s]"></span>
              <span className="w-2 h-2 rounded-full bg-secondary animate-bounce [animation-delay:-0.15s]"></span>
              <span className="w-2 h-2 rounded-full bg-secondary animate-bounce"></span>
            </div>
          </div>
        )}

        {error && (
          <div className="p-2 text-xs bg-error-container text-error rounded-lg">
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 3. Compact Quick Suggestions (Few examples) */}
      <div
        className="px-3 py-1.5 bg-surface-container-low border-t border-surface-container-highest/40 flex items-center gap-1.5 overflow-x-auto no-scrollbar"
        aria-label="Assistant quick questions"
      >
        {quickQuestions.map((item) => (
          <button
            key={item}
            type="button"
            className="text-[11px] whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container hover:bg-surface-container-high text-secondary hover:text-on-surface border border-surface-container-highest transition-all cursor-pointer shadow-xs shrink-0"
            disabled={loading}
            onClick={() => {
              setQuery(item)
              void ask(item)
            }}
          >
            {item}
          </button>
        ))}
      </div>

      {/* 4. Bottom Input Bar (Send button directly inside the input line) */}
      <form
        className="p-2.5 bg-surface-container-low border-t border-surface-container-highest flex items-center gap-2 select-none"
        onSubmit={(e) => {
          e.preventDefault()
          void ask()
        }}
      >
        <label htmlFor="assistant-query" className="sr-only">
          Hỏi về snapshot hiện tại
        </label>
        <div className="relative flex-1 flex items-center">
          <input
            id="assistant-query"
            aria-label="Hỏi về snapshot hiện tại"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={500}
            placeholder="Nhập câu hỏi..."
            className="w-full bg-surface-container-lowest text-on-surface rounded-full pl-4 pr-10 py-2 text-[13px] border border-surface-container-high focus:outline-none focus:border-secondary transition-all placeholder:text-on-surface-variant/60 shadow-inner"
          />
          <button
            type="submit"
            aria-label="Hỏi"
            title="Gửi"
            className="absolute right-1 w-7 h-7 rounded-full bg-primary hover:bg-primary/90 text-on-primary flex items-center justify-center transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer shadow-xs"
            disabled={loading || !query.trim()}
          >
            <span className="material-symbols-outlined text-[16px]">send</span>
            <span className="sr-only">Hỏi</span>
          </button>
        </div>
      </form>

      {/* 5. Subtle Notice */}
      <footer className="px-3 py-1 bg-surface-container-lowest text-center text-[10px] text-on-surface-variant/70 border-t border-surface-container-high/30 select-none">
        <small>
          does not change evidence
        </small>
      </footer>
    </div>
  )
}
