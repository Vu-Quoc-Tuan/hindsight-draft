import { useEffect, useState } from 'react'

import { api } from './api'
import { GroundedProviderBadge } from './GroundedProviderBadge'
import type { AISuggestion, ChainAnalysis, CohesionNarrativeView, Job } from './types'

export function AIAdvisorPanel({
  chainId,
  initialSuggestion = null,
  initialCohesion = null,
  analysis: _analysis = null,
  job = null,
  onSubTabChange: _onSubTabChange,
  onNavigateTab,
}: {
  chainId: string
  initialSuggestion?: AISuggestion | null
  initialCohesion?: CohesionNarrativeView | null
  analysis?: ChainAnalysis | null
  job?: Job | null
  onSubTabChange?: (tab: 'OVERVIEW' | 'WHY' | 'MEMBERS') => void
  onNavigateTab?: (tab: string) => void
}) {
  const [refreshIndex, setRefreshIndex] = useState(0)
  const requestKey = `${chainId}\u0000${refreshIndex}`
  const [loaded, setLoaded] = useState<{
    requestKey: string
    suggestion: AISuggestion | null
    cohesion: CohesionNarrativeView | null
    error: string | null
  }>({ requestKey: '', suggestion: null, cohesion: null, error: null })

  useEffect(() => {
    if (
      initialSuggestion?.chain_id === chainId &&
      initialCohesion?.chain_id === chainId &&
      refreshIndex === 0
    ) return
    const controller = new AbortController()

    Promise.allSettled([
      api.aiSuggestion(chainId, controller.signal),
      api.cohesionNarrative(chainId, controller.signal, 'vi'),
    ]).then(([sugRes, cohRes]) => {
      if (controller.signal.aborted) return
      const sug = sugRes.status === 'fulfilled' ? sugRes.value : null
      const coh = cohRes.status === 'fulfilled' ? cohRes.value : null
      const err = sugRes.status === 'rejected' ? sugRes.reason : null

      if (!sug && err) {
        setLoaded({
          requestKey,
          suggestion: null,
          cohesion: null,
          error: err instanceof Error ? err.message : 'Không thể tải phân tích AI',
        })
      } else {
        setLoaded({
          requestKey,
          suggestion: sug,
          cohesion: coh,
          error: null,
        })
      }
    })

    return () => controller.abort()
  }, [chainId, initialSuggestion, initialCohesion, refreshIndex, requestKey])

  // Re-fetch Cohesion Narrative with forceRefresh when P2 deep dive completes
  useEffect(() => {
    if (!job || job.chain_id !== chainId || job.status !== 'SUCCEEDED') return
    const currentCohesion = loaded.requestKey === requestKey ? loaded.cohesion : initialCohesion
    if (currentCohesion?.context?.has_p2) return

    let cancelled = false
    const controller = new AbortController()
    api.cohesionNarrative(chainId, controller.signal, 'vi', true)
      .then(res => {
        if (!cancelled) {
          setLoaded(prev => ({
            ...prev,
            requestKey,
            cohesion: res,
          }))
        }
      })
      .catch(() => {})

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [chainId, job?.chain_id, job?.status, loaded.cohesion?.context?.has_p2, initialCohesion?.context?.has_p2, loaded.requestKey, requestKey])

  const initial = refreshIndex === 0 && initialSuggestion?.chain_id === chainId
    ? initialSuggestion
    : null
  const suggestion = initial ?? (loaded.requestKey === requestKey ? loaded.suggestion : null)
  const initialCohesionForChain = refreshIndex === 0 && initialCohesion?.chain_id === chainId
    ? initialCohesion
    : null
  const cohesion = initialCohesionForChain ?? (loaded.requestKey === requestKey ? loaded.cohesion : null)
  const error = initial ? null : (loaded.requestKey === requestKey ? loaded.error : null)
  const loading = initial == null && loaded.requestKey !== requestKey

  const formatMarkdownInline = (text: string) => {
    const regex = /(\*\*.*?\*\*|\*.*?\*)/g
    const tokens = text.split(regex)
    return tokens.map((token, idx) => {
      if (token.startsWith('**') && token.endsWith('**')) {
        return (
          <strong key={idx} className="font-semibold text-on-surface">
            {token.slice(2, -2)}
          </strong>
        )
      }
      if (token.startsWith('*') && token.endsWith('*')) {
        return (
          <em key={idx} className="text-secondary italic">
            {token.slice(1, -1)}
          </em>
        )
      }
      return token
    })
  }

  const renderDescriptorLine = (lineText: string, keyIdx: number) => {
    // Check if line contains descriptors like "Thuộc tính đặc trưng: device_code=... alarm_name=..."
    if (
      lineText.includes('device_code=') ||
      lineText.includes('alarm_name=') ||
      lineText.includes('component=') ||
      lineText.includes('location_code=')
    ) {
      const parts = lineText.replace('- ', '').split(':')
      const prefix = parts[0]
      const rawContent = parts.slice(1).join(':')

      // Extract tokens separated by commas outside brackets
      const rawTokens = rawContent
        .split(/,\s*(?=[a-z_]+=)/i)
        .map((t) => t.trim().replace(/\.$/, ''))
        .filter(Boolean)

      return (
        <div key={keyIdx} className="my-space-xs p-space-xs bg-[#0b1322] border border-[#1e2c47] rounded-md">
          <span className="font-label-caps text-xs text-on-surface-variant uppercase font-bold block mb-1">
            {prefix}:
          </span>
          <div className="flex flex-wrap gap-1.5 items-center">
            {rawTokens.map((tok, tIdx) => {
              let icon = 'tag'
              let color = 'bg-surface-container-high/60 text-on-surface border-surface-container-highest'
              if (tok.startsWith('device_code=')) {
                icon = 'router'
                color = 'bg-primary/15 text-primary border-primary/30'
              } else if (tok.startsWith('alarm_name=')) {
                icon = 'warning'
                color = 'bg-secondary/15 text-secondary border-secondary/30'
              } else if (tok.startsWith('component=')) {
                icon = 'dns'
                color = 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
              } else if (tok.startsWith('location_code=')) {
                icon = 'location_on'
                color = 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
              }
              const cleanVal = tok.replace(/^[a-z_]+=/, '')
              return (
                <span
                  key={tIdx}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border font-code-sm text-xs font-semibold ${color}`}
                >
                  <span className="material-symbols-outlined text-[13px]">{icon}</span>
                  <span>{cleanVal}</span>
                </span>
              )
            })}
          </div>
        </div>
      )
    }

    if (lineText.includes('Dữ liệu chưa đầy đủ') || lineText.includes('Evidence is incomplete')) {
      const alarmList = lineText.replace(/.*(?:cảnh báo:|for:)\s*/i, '').replace(/\.$/, '').trim()
      return (
        <div
          key={keyIdx}
          className="my-1 p-2 rounded bg-amber-500/10 border border-amber-500/25 flex items-start gap-2 text-xs text-amber-200"
        >
          <span className="material-symbols-outlined text-[14px] text-amber-400 mt-0.5 shrink-0">info</span>
          <div className="flex-1 leading-relaxed text-[11px]">
            <span className="font-semibold text-amber-300">Cần thêm mẫu lịch sử để xếp loại nòng cốt/ngoại vi: </span>
            <span className="font-mono font-bold text-amber-100 bg-amber-500/20 px-1 py-0.2 rounded border border-amber-500/30">
              {alarmList}
            </span>
            <span className="text-amber-300/70 ml-1.5">
              (độ bao phủ dữ liệu lịch sử chưa đạt 50% để xếp loại tự động; chuỗi vẫn được duy trì đầy đủ)
            </span>
          </div>
        </div>
      )
    }

    return (
      <p key={keyIdx} className="ai-narrative-item">
        {formatMarkdownInline(lineText.replace('- ', ''))}
      </p>
    )
  }

  const renderNarrativeBlocks = (text: string) => {
    const cleanText = text
      .replace(/^[-\s]*\*\*.*?\*\*:\s*/gm, '')
      .replace(/^[-*•]\s*(?:[^\w\s]\s*)?/gm, '')
      .replace(/\[Quy mô tổng quan\]:\s*/gi, '')
      .replace(/\[Thành viên nòng cốt\]:\s*/gi, '')
      .replace(/\[Kiểm định cấu trúc\]:\s*/gi, '')
      .replace(/Chuỗi có độ gắn kết cao nhờ:\s*/gi, '')
      .trim()

    const paragraphs = cleanText.includes('\n\n')
      ? cleanText.split('\n\n').map((p) => p.trim()).filter(Boolean)
      : cleanText.includes('\n')
      ? cleanText.split('\n').map((p) => p.trim()).filter(Boolean)
      : [cleanText]

    return (
      <div className="p-3 rounded-lg bg-[#070d17]/85 border border-[#18263e] text-xs text-on-surface leading-relaxed shadow-xs space-y-2">
        {paragraphs.map((para, pIdx) => (
          <p key={pIdx} className="m-0 text-[12.5px] leading-relaxed text-on-surface/95">
            {formatMarkdownInline(para)}
          </p>
        ))}
      </div>
    )
  }

  const renderCounterfactualBlock = (cfLines: string[]) => {
    const fullText = cfLines.join('\n')

    // Case 1: Recommendations / Proposals exist (e.g., chain 6913556 when calibrated)
    if (
      suggestion?.recommendation_status === 'AVAILABLE' &&
      (fullText.includes('Đề xuất (') || fullText.includes('Proposal action:'))
    ) {
      const actionLine = cfLines.find((l) => l.includes('Đề xuất (')) || ''
      const whyLine =
        cfLines.find(
          (l) =>
            l.includes('*Vì sao đề xuất này tốt hơn*:') ||
            l.includes('Proposal rationale:')
        ) || ''
      const deltaLine =
        cfLines.find(
          (l) =>
            l.includes('*Chỉ số cải thiện*:') || l.includes('Chỉ số cải thiện')
        ) || ''

      const cleanAction = actionLine
        .replace(/^[-\s]*\*\*Đề xuất \([^)]+\)\*\*:\s*/, '')
        .replace(/^[-\s]*/, '')
        .trim()

      const cleanWhy = whyLine
        .replace(/^[-\s]*\*Vì sao đề xuất này tốt hơn\*:\s*/, '')
        .replace(/^[-\s]*/, '')
        .trim()

      const rawDeltas = deltaLine
        .replace(/^[-\s]*\*Chỉ số cải thiện\*:\s*/, '')
        .replace(/\.$/, '')
        .split(';')
        .map((d) => d.trim())
        .filter(Boolean)

      return (
        <div
          key="counterfactual-block"
          className="mt-3 p-3 rounded-lg bg-[#0c1024] border border-primary/40 text-xs shadow-xs"
        >
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-primary/25 flex-wrap gap-2">
            <div className="flex items-center gap-1.5 text-primary font-bold text-xs">
              <span className="material-symbols-outlined text-[16px] text-amber-400">lightbulb</span>
              <span>Đề xuất tối ưu hóa chuỗi (Counterfactual Pareto)</span>
            </div>
            <span className="text-[10px] font-mono text-primary bg-primary/15 px-2 py-0.5 rounded border border-primary/30 font-bold">
              Khuyến Nghị Can Thiệp
            </span>
          </div>

          {/* Action callout */}
          <div className="mb-2 p-2.5 rounded bg-[#070a18] border border-primary/25 text-xs text-on-surface flex items-start gap-2">
            <span className="material-symbols-outlined text-[15px] text-cyan-400 shrink-0 mt-0.5">call_split</span>
            <div className="flex-1 leading-relaxed">
              <strong className="text-cyan-300 block mb-0.5 font-mono text-[11px] uppercase">
                Hành động can thiệp đề xuất:
              </strong>
              <span>{cleanAction || actionLine}</span>
            </div>
          </div>

          {/* Rationale */}
          {cleanWhy && (
            <div className="mb-2.5 text-xs text-on-surface-variant flex items-start gap-2 leading-relaxed bg-[#050814] p-2.5 rounded border border-[#171e3d]">
              <span className="material-symbols-outlined text-[15px] text-amber-400 shrink-0 mt-0.5">psychology</span>
              <div className="flex-1">
                <strong className="text-secondary mr-1">Vì sao đề xuất này tốt hơn:</strong>
                <span>{cleanWhy}</span>
              </div>
            </div>
          )}

          {/* Metric deltas */}
          {rawDeltas.length > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-1.5 items-center">
              <span className="text-[11px] text-on-surface-variant font-mono mr-1">Chỉ số cải thiện:</span>
              {rawDeltas.map((d, dIdx) => (
                <span
                  key={dIdx}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-mono text-xs font-bold"
                >
                  <span className="material-symbols-outlined text-[12px]">trending_up</span>
                  <span>{d}</span>
                </span>
              ))}
            </div>
          )}

          {/* Action button */}
          {onNavigateTab && (
            <div className="pt-2 border-t border-primary/20 flex items-center justify-end">
              <button
                type="button"
                onClick={() => onNavigateTab('review')}
                className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200 font-bold hover:underline cursor-pointer bg-cyan-500/15 px-2.5 py-1 rounded border border-cyan-500/30 transition-colors hover:bg-cyan-500/25"
                title="Nhấn để mở tab Recommendations & Validation xem chi tiết"
              >
                <span>Xem chi tiết đối sánh kịch bản trên tab Khuyến nghị</span>
                <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
              </button>
            </div>
          )}
        </div>
      )
    }

    if (suggestion?.recommendation_status === 'NO_CLEAR_ALTERNATIVE') {
      return (
        <div
          key="counterfactual-block"
          className="mt-3 p-3 rounded-lg bg-[#0d131f] border border-[#31415e] text-xs shadow-xs"
        >
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#31415e] flex-wrap gap-2">
            <div className="flex items-center gap-1.5 text-on-surface font-bold text-xs">
              <span className="material-symbols-outlined text-[16px]">search_check</span>
              <span>Kết quả Counterfactual Review</span>
            </div>
            <span className="text-[10px] font-mono text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded border border-[#31415e] font-bold">
              NO_CLEAR_ALTERNATIVE
            </span>
          </div>

          <div className="text-on-surface leading-relaxed mb-2.5">
            <span>
              Không tìm thấy phương án vượt trội rõ ràng trong không gian tìm kiếm hữu hạn đã đánh giá. Đây không phải xác nhận tối ưu toàn cục.
            </span>
          </div>

          {onNavigateTab && (
            <div className="pt-2 border-t border-[#31415e] flex items-center justify-end">
              <button
                type="button"
                onClick={() => onNavigateTab('review')}
                className="inline-flex items-center gap-1 text-[11px] text-cyan-400 hover:text-cyan-300 font-bold hover:underline cursor-pointer bg-cyan-500/10 px-2 py-1 rounded border border-cyan-500/25 transition-colors hover:bg-cyan-500/20"
                title="Xem chi tiết các kịch bản can thiệp đã thử nghiệm trong tab Recommendations"
              >
                <span>Xem đối sánh kịch bản thử nghiệm</span>
                <span className="material-symbols-outlined text-[13px]">arrow_forward</span>
              </button>
            </div>
          )}
        </div>
      )
    }

    if (suggestion?.review_reason === 'COUNTERFACTUAL_POLICY_NOT_CALIBRATED') {
      const candidateActionLine =
        cfLines.find(
          (l) =>
            l.includes('Phương án thử nghiệm') ||
            l.includes('Candidate đã đánh giá') ||
            l.includes('Đề xuất (')
        ) || ''
      const candidateWhyLine =
        cfLines.find(
          (l) =>
            l.includes('Vì sao đề xuất này tốt hơn') ||
            l.includes('Rationale metric')
        ) || ''
      const candidateDeltaLine =
        cfLines.find(
          (l) =>
            l.includes('Chỉ số cải thiện') ||
            l.includes('Metric delta quan sát')
        ) || ''

      const cleanCandidateAction = candidateActionLine
        .replace(/^[-\s]*\*(?:Phương án thử nghiệm|Candidate đã đánh giá|Đề xuất \([^)]+\))\*:\s*/, '')
        .replace(/^[-\s]*(?:Phương án thử nghiệm|Candidate đã đánh giá|Đề xuất \([^)]+\)):\s*/, '')
        .trim()

      const cleanCandidateWhy = candidateWhyLine
        .replace(/^[-\s]*\*(?:Vì sao đề xuất này tốt hơn|Rationale metric)\*:\s*/, '')
        .replace(/^[-\s]*(?:Vì sao đề xuất này tốt hơn|Rationale metric):\s*/, '')
        .trim()

      const cleanCandidateDeltas = candidateDeltaLine
        .replace(/^[-\s]*\*(?:Chỉ số cải thiện|Metric delta quan sát)\*:\s*/, '')
        .replace(/^[-\s]*(?:Chỉ số cải thiện|Metric delta quan sát):\s*/, '')
        .replace(/\.$/, '')
        .split(';')
        .map((d) => d.trim())
        .filter(Boolean)

      return (
        <div
          key="counterfactual-block"
          className="mt-3 p-3 rounded-lg bg-[#0c1322] border border-cyan-500/30 text-xs shadow-xs"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-cyan-500/20 flex-wrap gap-2">
            <div className="flex items-center gap-1.5 text-cyan-300 font-bold text-xs">
              <span className="material-symbols-outlined text-[16px] text-amber-400">science</span>
              <span>Counterfactual đã phân tích xong: Kịch bản can thiệp tiềm năng</span>
            </div>
            <span className="text-[10px] font-mono text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/25 font-bold">
              Mô phỏng thử nghiệm
            </span>
          </div>

          {/* Action details if found */}
          {cleanCandidateAction ? (
            <div className="space-y-2 mb-2.5">
              <div className="p-2 rounded bg-[#060a14] border border-cyan-500/20 text-xs text-on-surface flex items-start gap-2">
                <span className="material-symbols-outlined text-[15px] text-cyan-400 shrink-0 mt-0.5">call_split</span>
                <div className="flex-1 leading-relaxed">
                  <strong className="text-cyan-300 block mb-0.5 font-mono text-[11px] uppercase">
                    Phương án mô phỏng đã đánh giá:
                  </strong>
                  <span>{cleanCandidateAction}</span>
                </div>
              </div>

              {cleanCandidateWhy && (
                <div className="text-xs text-on-surface-variant flex items-start gap-2 leading-relaxed bg-[#050814] p-2 rounded border border-[#171e3d]">
                  <span className="material-symbols-outlined text-[15px] text-amber-400 shrink-0 mt-0.5">psychology</span>
                  <div className="flex-1">
                    <strong className="text-secondary mr-1">Hiệu quả cải thiện:</strong>
                    <span>{cleanCandidateWhy}</span>
                  </div>
                </div>
              )}

              {cleanCandidateDeltas.length > 0 && (
                <div className="flex flex-wrap gap-1.5 items-center">
                  <span className="text-[11px] text-on-surface-variant font-mono mr-1">Chỉ số cải thiện:</span>
                  {cleanCandidateDeltas.map((d, dIdx) => (
                    <span
                      key={dIdx}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-mono text-xs font-bold"
                    >
                      <span className="material-symbols-outlined text-[12px]">trending_up</span>
                      <span>{d}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="text-on-surface leading-relaxed mb-2.5 text-xs">
              <span>
                Counterfactual đã phân tích xong toàn bộ kịch bản; các phương án mô phỏng đã được đánh giá và sẵn sàng để bạn đối sánh chi tiết.
              </span>
            </div>
          )}

          {/* Footer note & CTA */}
          <div className="pt-2 border-t border-cyan-500/15 flex items-center justify-between gap-2 flex-wrap text-on-surface-variant text-[11px]">
            <span className="flex items-center gap-1 text-slate-400">
              <span className="material-symbols-outlined text-[13px] text-amber-400">lock</span>
              <span>Chế độ an toàn: đề xuất tự động đang bị khóa (COUNTERFACTUAL_POLICY_NOT_CALIBRATED)</span>
            </span>
            {onNavigateTab && (
              <button
                type="button"
                onClick={() => onNavigateTab('review')}
                className="inline-flex items-center gap-1 text-[11px] text-cyan-400 hover:text-cyan-300 font-bold hover:underline cursor-pointer bg-cyan-500/10 px-2 py-1 rounded border border-cyan-500/25 transition-colors hover:bg-cyan-500/20"
                title="Xem chi tiết các kịch bản can thiệp đã thử nghiệm trong tab Recommendations"
              >
                <span>Xem đối sánh kịch bản thử nghiệm</span>
                <span className="material-symbols-outlined text-[13px]">arrow_forward</span>
              </button>
            )}
          </div>
        </div>
      )
    }

    const analysisCompleted = suggestion?.review_status === 'AVAILABLE'
    const unavailableMessage = suggestion?.recommendation_status === 'AVAILABLE'
      ? 'Kết quả Counterfactual không nhất quán: AVAILABLE nhưng không có recommendation; không thể kết luận tối ưu.'
      : analysisCompleted
        ? `Counterfactual đã phân tích xong; chưa có phương án đủ điều kiện và đề xuất tự động đang bị khóa${suggestion?.review_reason ? ` (${suggestion.review_reason})` : ''}.`
        : `Không thể đọc kết quả Counterfactual${suggestion?.review_reason ? ` (${suggestion.review_reason})` : ''}.`

    return (
      <div
        key="counterfactual-block"
        className="mt-3 p-2.5 rounded-lg bg-[#0d131f] border border-[#1c2a44] text-xs text-on-surface-variant flex items-center justify-between gap-2"
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px] text-amber-400">info</span>
          <span>{unavailableMessage}</span>
        </div>
        {onNavigateTab && (
          <button
            type="button"
            onClick={() => onNavigateTab('review')}
            className="text-[11px] text-cyan-400 hover:underline shrink-0 cursor-pointer"
          >
            Mở tab Khuyến nghị →
          </button>
        )}
      </div>
    )
  }

  const renderNarrative = (text: string, hasCohesionNarrative = false) => {
    const lines = text.split('\n')
    const normalElements: React.ReactNode[] = []
    let inCounterfactual = false
    const cfLines: string[] = []
    let footerQuote: string | null = null

    for (let idx = 0; idx < lines.length; idx++) {
      const line = lines[idx]
      const trimmed = line.trim()

      if (
        trimmed.startsWith('### Đề xuất tối ưu hóa chuỗi (Counterfactual)') ||
        trimmed.startsWith('### Kết quả Counterfactual Review') ||
        trimmed.startsWith('### Counterfactual review') ||
        trimmed.startsWith('### Counterfactual review recommendations')
      ) {
        inCounterfactual = true
        continue
      }

      if (trimmed.startsWith('> ')) {
        footerQuote = trimmed.replace('> ', '').replace('[!NOTE]', '').trim()
        continue
      }

      if (inCounterfactual) {
        if (trimmed.startsWith('### ')) {
          inCounterfactual = false
          // Fall through to normal heading
        } else {
          if (trimmed) {
            cfLines.push(trimmed)
          }
          continue
        }
      }

      // If the comprehensive cohesion incident briefing is already shown above, skip duplicate lines
      if (hasCohesionNarrative) {
        if (
          trimmed.startsWith('### Tóm tắt bằng chứng') ||
          trimmed.startsWith('### Evidence summary') ||
          trimmed.startsWith('- Số lượng cảnh báo') ||
          trimmed.startsWith('- Analyzed members') ||
          trimmed.startsWith('- Toàn bộ thành viên') ||
          trimmed.startsWith('- No analyzed member') ||
          trimmed.startsWith('- Members classified WEAK')
        ) {
          continue
        }
        // The cohesion briefing owns incident facts. Keep only the separately
        // parsed Counterfactual block from the legacy suggestion narrative.
        continue
      }

      if (trimmed.startsWith('### ')) {
        normalElements.push(
          <h3 key={idx} className="ai-narrative-heading">
            {trimmed.replace('### ', '')}
          </h3>
        )
      } else if (trimmed.startsWith('- ')) {
        normalElements.push(renderDescriptorLine(trimmed, idx))
      } else if (trimmed) {
        normalElements.push(
          <p key={idx} className="ai-narrative-paragraph">
            {formatMarkdownInline(trimmed)}
          </p>
        )
      }
    }

    return (
      <>
        {normalElements}
        {cfLines.length > 0 && renderCounterfactualBlock(cfLines)}
        {footerQuote && (
          <blockquote className="ai-narrative-quote mt-2">
            {footerQuote}
          </blockquote>
        )}
      </>
    )
  }

  const renderAnalyticalFindings = (context: CohesionNarrativeView['context']) => {
    const findings = context.analytical_findings ?? []
    if (findings.length === 0) return null

    return (
      <section className="mt-2.5 pt-2 border-t border-[#17233a]" aria-label="Analytical Findings">
        <div className="text-[10px] uppercase font-bold text-on-surface-variant font-mono tracking-wider mb-1.5 flex items-center gap-1">
          <span className="material-symbols-outlined text-[14px] text-primary">insights</span>
          Analytical Findings
        </div>
        <div className="grid gap-1.5">
          {findings.map((finding) => (
            <article
              key={finding.finding_id}
              className={`p-2.5 rounded border text-xs ${
                finding.status === 'AVAILABLE'
                  ? 'bg-[#080d17] border-[#1b2b48]'
                  : 'bg-amber-500/5 border-amber-500/25'
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <strong className="text-on-surface">{finding.title}</strong>
                <span className="text-[10px] font-mono text-on-surface-variant">
                  {finding.confidence ? `${finding.confidence} CONFIDENCE · ` : ''}{finding.kind} · {finding.status}
                </span>
              </div>
              <p className="m-0 text-on-surface-variant leading-relaxed">{finding.claim}</p>
              {finding.evidence.length > 0 && (
                <ul className="mt-1.5 mb-0 pl-4 text-on-surface-variant">
                  {finding.evidence.map((item) => <li key={item}>{item}</li>)}
                </ul>
              )}
              {finding.limitations.length > 0 && (
                <div className="mt-1.5 text-[10px] font-mono text-amber-300">
                  Limits: {finding.limitations.join(' · ')}
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="ai-advisor-panel">
      <header className="ai-advisor-header flex items-center justify-between py-1 mb-2 border-b border-surface-container-highest/60 pb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="material-symbols-outlined text-primary text-[18px]">smart_toy</span>
          <h2 className="text-sm font-bold text-on-surface m-0 leading-none">Evidence summary</h2>
          <span className="text-xs text-on-surface-variant font-mono">· Chuỗi <strong>{chainId}</strong></span>
          <span className="text-[10px] font-mono text-secondary/80 bg-secondary/10 px-1.5 py-0.5 rounded border border-secondary/20 font-medium">
            ADR-0024 Grounded Narrative
          </span>
        </div>
        <div className="ai-advisor-actions flex items-center gap-2">
          {suggestion ? (
            <GroundedProviderBadge
              model={suggestion.model}
              providerStatus={suggestion.provider_status ?? 'NOT_CONFIGURED'}
            />
          ) : null}
          <button
            type="button"
            className="review-btn-action review-btn-approve text-xs py-1 px-2.5"
            onClick={() => setRefreshIndex((v) => v + 1)}
            disabled={loading}
          >
            {loading ? 'Đang tải…' : '🔄 Tải lại'}
          </button>
        </div>
      </header>

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
        <article className="ai-suggestion-body flex flex-col gap-space-md">
          {/* AI Narrative Content */}
          <div className="ai-narrative-content flex flex-col gap-2.5">
            {cohesion?.narrative && (
              <div className="p-3 bg-[#0a1220] rounded-lg border border-[#1b2b48] text-xs leading-relaxed text-on-surface shadow-xs">
                <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-[#17233a]">
                  <span className="text-secondary font-bold font-label-caps uppercase text-[11px] flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[15px]">summarize</span>
                    Bản Diễn Giải Tổng Quan Sự Cố (Executive Incident Briefing):
                  </span>
                  <span className="text-[10px] font-mono text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded">
                    Phân tích đa chiều
                  </span>
                </div>
                <div className="flex flex-col gap-1.5 mb-2">
                  {renderNarrativeBlocks(cohesion.narrative)}
                </div>

                {cohesion.context.temporal_progression?.status === 'AVAILABLE' &&
                  cohesion.context.temporal_progression.waves.length > 0 && (
                    <section className="mt-2 pt-2 border-t border-[#17233a]" aria-label="Observed temporal progression">
                      <div className="text-[10px] uppercase font-bold text-on-surface-variant font-mono tracking-wider mb-1.5 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[14px] text-primary">timeline</span>
                        Diễn tiến quan sát
                      </div>
                      <div className="flex gap-1.5 overflow-x-auto pb-1">
                        {cohesion.context.temporal_progression.waves.map((wave, index) => (
                          <div key={`${wave.start_time}-${index}`} className="min-w-[150px] p-2 rounded border border-[#1b2b48] bg-[#080d17]">
                            <div className="flex items-center justify-between gap-2 text-[10px] font-mono">
                              <strong className="text-secondary">{index === 0 ? 'T₀' : `+${Math.floor(wave.offset_seconds / 60)}m ${String(wave.offset_seconds % 60).padStart(2, '0')}s`}</strong>
                              <span className="text-on-surface-variant">{wave.start_time.slice(11, 19)}</span>
                            </div>
                            <div className="mt-1 text-[11px] text-on-surface">{wave.devices.join(' · ')}</div>
                            <div className="mt-0.5 text-[10px] text-on-surface-variant line-clamp-2">{wave.alarm_names.join(' · ')}</div>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}

                {renderAnalyticalFindings(cohesion.context)}

                {/* NOC Actionable Takeaway Callout */}
                {cohesion.context.operational_insights?.actionable_takeaway && (
                  <div className="mt-2.5 p-2.5 rounded bg-cyan-950/40 border border-cyan-800/60 text-xs text-cyan-200 flex items-start gap-2">
                    <span className="material-symbols-outlined text-[16px] text-cyan-400 shrink-0 mt-0.5">tips_and_updates</span>
                    <div className="flex-1 leading-snug">
                      <strong className="text-cyan-300 mr-1">Khuyến nghị vận hành NOC:</strong>
                      <span>{cohesion.context.operational_insights.actionable_takeaway}</span>
                    </div>
                  </div>
                )}

                {/* Observed Pattern Indicators / Structural Insights */}
                {(cohesion.context.analytical_findings?.length ?? 0) === 0 && Array.isArray(cohesion?.context?.structural_insights) && cohesion.context.structural_insights.length > 0 && (
                  <div className="mt-2.5 pt-2 border-t border-[#17233a] flex flex-col gap-1.5">
                    <span className="text-[10px] uppercase font-bold text-on-surface-variant font-mono tracking-wider flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px] text-primary">hub</span>
                      Chỉ dấu mẫu hình quan sát (Observed Pattern Indicators):
                    </span>
                    <div className="flex flex-col gap-1">
                      {cohesion.context.structural_insights.map((ins, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs text-on-surface bg-[#080d17] p-2 rounded border border-[#1b2b48]/70">
                          <span className="material-symbols-outlined text-secondary text-[16px] mt-0.5 shrink-0">{ins.icon || 'verified'}</span>
                          <div className="flex-1 leading-snug">
                            <strong className="text-secondary mr-1.5">{ins.label}:</strong>
                            <span className="text-on-surface-variant">{ins.detail}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {renderNarrative(suggestion.narrative, Boolean(cohesion?.narrative))}
          </div>

          {suggestion.review_status === 'UNAVAILABLE' && (
            <div className="ai-provider-notice" role="status">
              <span>⚠️ Counterfactual Review:</span> không thể đọc artifact hiện tại
              {suggestion.review_reason ? ` (${suggestion.review_reason})` : ''}.
            </div>
          )}

          {suggestion.grounded_claims.length > 0 && (
            <div className="ai-claims-section hidden" aria-hidden="true">
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

          <footer className="ai-advisor-footer hidden" aria-hidden="true">
            <small>{suggestion.disclaimer}</small>
          </footer>
        </article>
      ) : null}
    </section>
  )
}
