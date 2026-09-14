import { useState, useEffect } from 'react'
import { api } from '../api'
import { GroundedProviderBadge } from '../GroundedProviderBadge'
import type {

  ProposalClarityComparison,
  ThresholdExplainOptimization,
} from '../types'

export interface ExplainClarityComparisonModalProps {
  isOpen: boolean
  onClose: () => void
  mode: 'proposals' | 'threshold'
  jobId?: string
  chainId?: string
  onThresholdApplied?: () => void
}

export function ExplainClarityComparisonModal({
  isOpen,
  onClose,
  mode,
  jobId,
  chainId,
  onThresholdApplied,
}: ExplainClarityComparisonModalProps) {
  const currentKey = `${isOpen ? '1' : '0'}:${mode}:${jobId ?? ''}:${chainId ?? ''}`
  const [dataState, setDataState] = useState<{
    key: string
    proposalsData: ProposalClarityComparison | null
    thresholdData: ThresholdExplainOptimization | null
    selectedTargetCandId: string | null
    error: string | null
  }>({
    key: '',
    proposalsData: null,
    thresholdData: null,
    selectedTargetCandId: null,
    error: null,
  })

  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const hasRequest = (mode === 'proposals' && Boolean(jobId)) || (mode === 'threshold' && Boolean(chainId))
  const isStale = isOpen && hasRequest && dataState.key !== currentKey
  const loading = isStale
  const proposalsData = isStale ? null : dataState.proposalsData
  const thresholdData = isStale ? null : dataState.thresholdData
  const selectedTargetCandId = isStale ? null : dataState.selectedTargetCandId
  const error = isStale ? null : (dataState.error || applyError)

  const setSelectedTargetCandId = (id: string | null) => {
    setDataState((prev) => ({ ...prev, selectedTargetCandId: id }))
  }

  useEffect(() => {
    if (!isOpen) return
    let active = true

    if (mode === 'proposals' && jobId) {
      api.getProposalClarityComparison(jobId)
        .then((res) => {
          if (!active) return
          setDataState({
            key: currentKey,
            proposalsData: res,
            thresholdData: null,
            selectedTargetCandId: res.head_to_head_comparisons[0]?.target_candidate_id ?? null,
            error: null,
          })
        })
        .catch((err: unknown) => {
          if (!active) return
          setDataState({
            key: currentKey,
            proposalsData: null,
            thresholdData: null,
            selectedTargetCandId: null,
            error: err instanceof Error ? err.message : 'Không thể tải so sánh độ rõ ràng đề xuất.',
          })
        })
    } else if (mode === 'threshold' && chainId) {
      api.optimizeExplainThreshold(chainId)
        .then((res) => {
          if (!active) return
          setDataState({
            key: currentKey,
            proposalsData: null,
            thresholdData: res,
            selectedTargetCandId: null,
            error: null,
          })
        })
        .catch((err: unknown) => {
          if (!active) return
          setDataState({
            key: currentKey,
            proposalsData: null,
            thresholdData: null,
            selectedTargetCandId: null,
            error: err instanceof Error ? err.message : 'Không thể quét ngưỡng tối ưu giải thích.',
          })
        })
    }

    return () => {
      active = false
    }
  }, [isOpen, mode, jobId, chainId, currentKey])

  if (!isOpen) return null

  const handleApplyThreshold = async () => {
    if (!thresholdData || !chainId) return
    setApplying(true)
    setApplyError(null)
    setSuccessMsg(null)
    try {
      const res = await api.applyExplainThreshold(chainId, thresholdData.optimal_parameters)
      setSuccessMsg(res.message || 'Đã áp dụng ngưỡng tối ưu giải thích thành công!')
      if (onThresholdApplied) {
        onThresholdApplied()
      }
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : 'Lỗi khi áp dụng ngưỡng.')
    } finally {
      setApplying(false)
    }
  }

  // Active head-to-head comparison in proposals mode
  const activeH2H = proposalsData?.head_to_head_comparisons.find(
    (h) => h.target_candidate_id === selectedTargetCandId,
  ) || proposalsData?.head_to_head_comparisons[0]

  const topProposal = proposalsData?.proposals.find((p) => p.is_top_pick)
  const targetProposal = proposalsData?.proposals.find(
    (p) => p.candidate_id === activeH2H?.target_candidate_id,
  )

  const activeAiModel = mode === 'proposals' ? proposalsData?.ai_model : thresholdData?.ai_model
  const activeAiStatus = mode === 'proposals' ? proposalsData?.ai_provider_status : thresholdData?.ai_provider_status

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(7, 12, 24, 0.86)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: '1.5rem',
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#0d1527',
          border: '1px solid #1e293b',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '1240px',
          maxHeight: '92vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(56, 189, 248, 0.1)',
          overflow: 'hidden',
          color: '#f8fafc',
          fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '1.25rem 1.75rem',
            borderBottom: '1px solid #1e293b',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            backgroundColor: '#131f38',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: '#38bdf8',
                  background: 'rgba(56, 189, 248, 0.12)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                }}
              >
                {mode === 'proposals' ? '⚖️ So sánh Đề xuất Tối ưu' : '🎯 Tối ưu hóa Ngưỡng Explain'}
              </span>
              <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
                {mode === 'proposals' ? `Job: ${jobId?.slice(0, 8)}` : `Chain: ${chainId}`}
              </span>
              {activeAiModel && (
                <GroundedProviderBadge
                  model={activeAiModel}
                  providerStatus={activeAiStatus || 'OK'}
                />
              )}
            </div>
            <h2 style={{ margin: '0.35rem 0 0', fontSize: '1.25rem', fontWeight: 700, color: '#f1f5f9' }}>
              {mode === 'proposals'
                ? 'So Sánh Trực Diện: Đề Xuất Nào Có Lời Giải Thích Rõ Ràng & Thuyết Phục Hơn?'
                : 'Tìm Ngưỡng Tham Số Cho Ra Lời Giải Thích Rõ Ràng & Sắc Nét Nhất'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#94a3b8',
              fontSize: '1.2rem',
              width: '36px',
              height: '36px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.15s ease',
            }}
            aria-label="Đóng"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '1.5rem 1.75rem', overflowY: 'auto', flex: 1 }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '3.5rem 1rem', color: '#94a3b8' }}>
              <div
                style={{
                  display: 'inline-block',
                  width: '36px',
                  height: '36px',
                  border: '3px solid rgba(56, 189, 248, 0.2)',
                  borderTopColor: '#38bdf8',
                  borderRadius: '50%',
                  animation: 'spin 0.8s linear infinite',
                  marginBottom: '1rem',
                }}
              />
              <div>Đang đối chiếu ngữ nghĩa, tính cụ thể và tính nhân quả của các lời giải thích...</div>
            </div>
          )}

          {error && (
            <div
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '8px',
                padding: '1rem',
                color: '#fca5a5',
                marginBottom: '1rem',
                fontSize: '0.9rem',
              }}
            >
              ⚠️ {error}
            </div>
          )}

          {successMsg && (
            <div
              style={{
                backgroundColor: 'rgba(34, 197, 94, 0.1)',
                border: '1px solid rgba(34, 197, 94, 0.3)',
                borderRadius: '8px',
                padding: '1rem',
                color: '#86efac',
                marginBottom: '1rem',
                fontSize: '0.9rem',
              }}
            >
              ✅ {successMsg}
            </div>
          )}

          {/* MODE 1: PROPOSALS COMPARISON */}
          {!loading && mode === 'proposals' && proposalsData && (
            <div>
              {/* Overall rationale alert */}
              <div
                style={{
                  background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  padding: '1rem 1.25rem',
                  marginBottom: '1.5rem',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.8rem',
                }}
              >
                <div style={{ fontSize: '1.5rem', lineHeight: 1 }}>💡</div>
                <div style={{ fontSize: '0.92rem', color: '#cbd5e1', lineHeight: 1.5 }}>
                  <strong style={{ color: '#38bdf8' }}>Nhận định So sánh Tổng thể: </strong>
                  {proposalsData.overall_recommendation_rationale}
                </div>
              </div>

              {/* Selector for target proposal to compare with top pick */}
              {proposalsData.head_to_head_comparisons.length > 1 && (
                <div style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>So sánh Đề xuất Tối ưu với:</span>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {proposalsData.head_to_head_comparisons.map((h) => (
                      <button
                        key={h.target_candidate_id}
                        type="button"
                        onClick={() => setSelectedTargetCandId(h.target_candidate_id)}
                        style={{
                          background: selectedTargetCandId === h.target_candidate_id ? '#1e293b' : 'transparent',
                          border: `1px solid ${selectedTargetCandId === h.target_candidate_id ? '#38bdf8' : '#334155'}`,
                          color: selectedTargetCandId === h.target_candidate_id ? '#38bdf8' : '#94a3b8',
                          padding: '0.35rem 0.85rem',
                          borderRadius: '6px',
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                          fontWeight: 600,
                        }}
                      >
                        {h.target_operation} ({h.target_candidate_id.slice(0, 8)})
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Side-by-Side Dual Column View */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '1.25rem',
                  marginBottom: '1.5rem',
                }}
              >
                {/* Left Column: Candidate Proposal */}
                <div
                  style={{
                    backgroundColor: '#111c33',
                    border: '1px solid #1e293b',
                    borderRadius: '12px',
                    padding: '1.25rem',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                      Phương Án Đối Chiếu
                    </span>
                    <span
                      style={{
                        background: '#1e293b',
                        color: '#94a3b8',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 700,
                      }}
                    >
                      Điểm Clarity: {targetProposal?.clarity_score.toFixed(1)}/100
                    </span>
                  </div>
                  <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.1rem', color: '#f8fafc' }}>
                    Đề xuất: {targetProposal?.operation} ({targetProposal?.candidate_id.slice(0, 8)})
                  </h3>
                  <div
                    style={{
                      fontSize: '0.9rem',
                      color: '#94a3b8',
                      lineHeight: 1.5,
                      backgroundColor: 'rgba(15, 23, 42, 0.6)',
                      padding: '0.85rem',
                      borderRadius: '8px',
                      border: '1px solid #1e293b',
                      flex: 1,
                    }}
                  >
                    {targetProposal?.explanation_text || 'Chưa có dữ liệu giải thích'}
                  </div>
                </div>

                {/* Right Column: Top Pick Proposal (Highlighted) */}
                <div
                  style={{
                    backgroundColor: '#112240',
                    border: '1.5px solid #10b981',
                    boxShadow: '0 0 20px rgba(16, 185, 129, 0.15)',
                    borderRadius: '12px',
                    padding: '1.25rem',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.15)',
                        border: '1px solid rgba(16, 185, 129, 0.4)',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontWeight: 700,
                      }}
                    >
                      🏆 ĐỀ XUẤT RÕ RÀNG NHẤT (+{activeH2H ? activeH2H.score_advantage.toFixed(1) : '0'} điểm)
                    </span>
                    <span
                      style={{
                        background: 'rgba(16, 185, 129, 0.2)',
                        color: '#34d399',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 700,
                      }}
                    >
                      Điểm Clarity: {topProposal?.clarity_score.toFixed(1)}/100
                    </span>
                  </div>
                  <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.1rem', color: '#f8fafc' }}>
                    Đề xuất: {topProposal?.operation} ({topProposal?.candidate_id.slice(0, 8)})
                  </h3>
                  <div
                    style={{
                      fontSize: '0.9rem',
                      color: '#e2e8f0',
                      lineHeight: 1.5,
                      backgroundColor: 'rgba(15, 23, 42, 0.8)',
                      padding: '0.85rem',
                      borderRadius: '8px',
                      border: '1px solid rgba(16, 185, 129, 0.3)',
                      flex: 1,
                    }}
                  >
                    {topProposal?.explanation_text || 'Chưa có dữ liệu giải thích'}
                  </div>
                </div>
              </div>

              {/* Explicit "WHY IS THIS EXPLANATION CLEARER?" Card */}
              {activeH2H && (
                <div
                  style={{
                    backgroundColor: 'rgba(16, 185, 129, 0.06)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    borderRadius: '12px',
                    padding: '1.25rem 1.5rem',
                  }}
                >
                  <h4
                    style={{
                      margin: '0 0 0.75rem',
                      fontSize: '0.95rem',
                      color: '#10b981',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      fontWeight: 700,
                    }}
                  >
                    <span>🔍</span> Vì sao Lời Giải Thích của Đề Xuất {topProposal?.operation} Vượt Trội Hơn?
                  </h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem', color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.6 }}>
                    {activeH2H.why_top_is_clearer.map((reason, idx) => (
                      <li key={idx} style={{ marginBottom: '0.4rem' }}>
                        {reason}
                      </li>
                    ))}
                  </ul>
                  <div
                    style={{
                      marginTop: '0.75rem',
                      paddingTop: '0.75rem',
                      borderTop: '1px solid rgba(16, 185, 129, 0.2)',
                      fontSize: '0.85rem',
                      color: '#94a3b8',
                      fontStyle: 'italic',
                    }}
                  >
                    👉 <strong>Kết luận:</strong> {activeH2H.summary_verdict}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* MODE 2: THRESHOLD OPTIMIZATION */}
          {!loading && mode === 'threshold' && thresholdData && (
            <div>
              {/* Summary gain badge */}
              <div
                style={{
                  background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  padding: '1rem 1.25rem',
                  marginBottom: '1.5rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                    Mức độ cải thiện độ rõ ràng (Clarity Gain)
                  </div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#38bdf8', marginTop: '0.2rem' }}>
                    {thresholdData.clarity_gain >= 0 ? `+${thresholdData.clarity_gain.toFixed(1)} điểm` : `${thresholdData.clarity_gain.toFixed(1)} điểm`}
                    <span style={{ fontSize: '0.9rem', color: '#94a3b8', fontWeight: 400, marginLeft: '0.5rem' }}>
                      ({thresholdData.current_clarity_score.toFixed(1)} $\rightarrow$ {thresholdData.optimal_clarity_score.toFixed(1)}/100)
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleApplyThreshold}
                  disabled={applying}
                  style={{
                    backgroundColor: '#0284c7',
                    border: 'none',
                    borderRadius: '8px',
                    color: '#ffffff',
                    padding: '0.6rem 1.25rem',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: applying ? 'not-allowed' : 'pointer',
                    boxShadow: '0 4px 12px rgba(2, 132, 199, 0.3)',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {applying ? 'Đang áp dụng...' : '⚡ Áp Dụng Ngưỡng Này Cho Chuỗi'}
                </button>
              </div>

              {/* Before vs After Dual Column View */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '1.25rem',
                  marginBottom: '1.5rem',
                }}
              >
                {/* Left: Current Threshold */}
                <div
                  style={{
                    backgroundColor: '#111c33',
                    border: '1px solid #1e293b',
                    borderRadius: '12px',
                    padding: '1.25rem',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                      Ngưỡng Hiện Tại (s_weak={thresholdData.current_parameters['role.s_weak']})
                    </span>
                    <span
                      style={{
                        background: '#1e293b',
                        color: '#94a3b8',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 700,
                      }}
                    >
                      {thresholdData.current_clarity_score.toFixed(1)}/100
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: '0.9rem',
                      color: '#94a3b8',
                      lineHeight: 1.5,
                      backgroundColor: 'rgba(15, 23, 42, 0.6)',
                      padding: '0.85rem',
                      borderRadius: '8px',
                      border: '1px solid #1e293b',
                      flex: 1,
                    }}
                  >
                    {thresholdData.current_explanation}
                  </div>
                </div>

                {/* Right: Optimal Threshold */}
                <div
                  style={{
                    backgroundColor: '#112240',
                    border: '1.5px solid #0284c7',
                    boxShadow: '0 0 20px rgba(2, 132, 199, 0.15)',
                    borderRadius: '12px',
                    padding: '1.25rem',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: '#38bdf8',
                        backgroundColor: 'rgba(56, 189, 248, 0.15)',
                        border: '1px solid rgba(56, 189, 248, 0.4)',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontWeight: 700,
                      }}
                    >
                      🎯 NGƯỠNG TỐI ƯU MỚI (s_weak={thresholdData.optimal_parameters['role.s_weak']})
                    </span>
                    <span
                      style={{
                        background: 'rgba(56, 189, 248, 0.2)',
                        color: '#38bdf8',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 700,
                      }}
                    >
                      {thresholdData.optimal_clarity_score.toFixed(1)}/100
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: '0.9rem',
                      color: '#e2e8f0',
                      lineHeight: 1.5,
                      backgroundColor: 'rgba(15, 23, 42, 0.8)',
                      padding: '0.85rem',
                      borderRadius: '8px',
                      border: '1px solid rgba(56, 189, 248, 0.3)',
                      flex: 1,
                    }}
                  >
                    {thresholdData.optimal_explanation}
                  </div>
                </div>
              </div>

              {/* Explicit "WHY IS THIS EXPLANATION CLEARER?" Card */}
              <div
                style={{
                  backgroundColor: 'rgba(56, 189, 248, 0.06)',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  borderRadius: '12px',
                  padding: '1.25rem 1.5rem',
                  marginBottom: '1.5rem',
                }}
              >
                <h4
                  style={{
                    margin: '0 0 0.75rem',
                    fontSize: '0.95rem',
                    color: '#38bdf8',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    fontWeight: 700,
                  }}
                >
                  <span>🔍</span> Vì sao Lời Giải Thích ở Ngưỡng Mới Rõ Ràng & Hợp Lý Hơn?
                </h4>
                <ul style={{ margin: 0, paddingLeft: '1.25rem', color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.6 }}>
                  {thresholdData.why_clearer.map((reason, idx) => (
                    <li key={idx} style={{ marginBottom: '0.4rem' }}>
                      {reason}
                    </li>
                  ))}
                </ul>
                <div
                  style={{
                    marginTop: '0.75rem',
                    paddingTop: '0.75rem',
                    borderTop: '1px solid rgba(56, 189, 248, 0.2)',
                    fontSize: '0.85rem',
                    color: '#94a3b8',
                    fontStyle: 'italic',
                  }}
                >
                  👉 <strong>Kết luận:</strong> {thresholdData.summary_verdict}
                </div>
              </div>

              {/* Threshold Sweep Trials Table */}
              {thresholdData.sweep_results && thresholdData.sweep_results.length > 0 && (
                <div>
                  <h4 style={{ margin: '0 0 0.75rem', fontSize: '0.9rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                    Các Ngưỡng Đã Thử Nghiệm (Sweep Trials)
                  </h4>
                  <div
                    style={{
                      border: '1px solid #1e293b',
                      borderRadius: '8px',
                      overflow: 'hidden',
                      fontSize: '0.85rem',
                    }}
                  >
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                      <thead>
                        <tr style={{ backgroundColor: '#131f38', color: '#94a3b8', borderBottom: '1px solid #1e293b' }}>
                          <th style={{ padding: '0.6rem 0.75rem' }}>Chiến lược</th>
                          <th style={{ padding: '0.6rem 0.75rem' }}>s_weak</th>
                          <th style={{ padding: '0.6rem 0.75rem' }}>c_min</th>
                          <th style={{ padding: '0.6rem 0.75rem' }}>Số WEAK</th>
                          <th style={{ padding: '0.6rem 0.75rem' }}>Số CORE</th>
                          <th style={{ padding: '0.6rem 0.75rem' }}>Độ Rõ Ràng (Clarity)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {thresholdData.sweep_results.map((t, idx) => {
                          const isOpt = t.parameters['role.s_weak'] === thresholdData.optimal_parameters['role.s_weak']
                          return (
                            <tr
                              key={idx}
                              style={{
                                backgroundColor: isOpt ? 'rgba(56, 189, 248, 0.1)' : idx % 2 === 0 ? '#0b1329' : '#0e172e',
                                borderBottom: '1px solid #1e293b',
                                color: isOpt ? '#38bdf8' : '#cbd5e1',
                                fontWeight: isOpt ? 600 : 400,
                              }}
                            >
                              <td style={{ padding: '0.5rem 0.75rem' }}>
                                {t.label} {isOpt && '⭐ (Tối ưu)'}
                              </td>
                              <td style={{ padding: '0.5rem 0.75rem' }}>{t.parameters['role.s_weak']}</td>
                              <td style={{ padding: '0.5rem 0.75rem' }}>{t.parameters['role.c_min']}</td>
                              <td style={{ padding: '0.5rem 0.75rem' }}>{t.weak_count}</td>
                              <td style={{ padding: '0.5rem 0.75rem' }}>{t.core_count}</td>
                              <td style={{ padding: '0.5rem 0.75rem' }}>{t.clarity_score.toFixed(1)}/100</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '1rem 1.75rem',
            borderTop: '1px solid #1e293b',
            display: 'flex',
            justifyContent: 'flex-end',
            backgroundColor: '#0c1427',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#cbd5e1',
              padding: '0.5rem 1.25rem',
              fontSize: '0.85rem',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
