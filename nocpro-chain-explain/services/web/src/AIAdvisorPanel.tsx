import { useEffect, useMemo, useRef, useState } from 'react'

import {
  api,
  cachedCohesionNarrative,
  isProviderCohesion,
  sanitizeCohesionNarrative,
  shouldForceCohesionRefresh,
} from './api'
import { GroundedProviderBadge } from './GroundedProviderBadge'
import type { ChainAnalysis, CohesionNarrativeView, Job } from './types'

export function AIAdvisorPanel({
  chainId,
  initialCohesion = null,
  job = null,
  onCohesionChange,
  reviewEpoch = 0,
}: {
  chainId: string
  initialCohesion?: CohesionNarrativeView | null
  analysis?: ChainAnalysis | null
  job?: Job | null
  onSubTabChange?: (tab: 'OVERVIEW' | 'WHY' | 'MEMBERS') => void
  onNavigateTab?: (tab: string) => void
  onCohesionChange?: (cohesion: CohesionNarrativeView | null) => void
  reviewEpoch?: number
}) {
  const [refreshIndex, setRefreshIndex] = useState(0)
  const refreshedJobKey = useRef<string | null>(null)
  const requestKey = `${chainId}\u0000${refreshIndex}\u0000${reviewEpoch}`
  const normalizedInitialCohesion = useMemo(
    () => initialCohesion?.chain_id === chainId
      ? sanitizeCohesionNarrative(initialCohesion)
      : null,
    [chainId, initialCohesion],
  )
  const [loaded, setLoaded] = useState<{
    requestKey: string
    cohesion: CohesionNarrativeView | null
    error: string | null
  }>(() => {
    const initial = normalizedInitialCohesion ?? cachedCohesionNarrative(chainId, 'vi')
    return { requestKey: initial ? requestKey : '', cohesion: initial, error: null }
  })

  useEffect(() => {
    if (refreshIndex === 0 && reviewEpoch === 0 && normalizedInitialCohesion && isProviderCohesion(normalizedInitialCohesion)) return
    const controller = new AbortController()
    api.cohesionNarrative(
      chainId,
      controller.signal,
      'vi',
      shouldForceCohesionRefresh(refreshIndex),
    )
      .then((cohesion) => {
        if (!controller.signal.aborted) {
          setLoaded({ requestKey, cohesion, error: null })
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setLoaded((previous) => ({
            requestKey,
            cohesion: previous.cohesion?.chain_id === chainId ? previous.cohesion : null,
            error: cause instanceof Error ? cause.message : 'Không thể tải nhận định',
          }))
        }
      })
    return () => controller.abort()
  }, [chainId, normalizedInitialCohesion, refreshIndex, requestKey, reviewEpoch])

  const initialForChain = refreshIndex === 0 && reviewEpoch === 0 && normalizedInitialCohesion
    ? normalizedInitialCohesion
    : null
  const loadedForChain = loaded.cohesion?.chain_id === chainId ? loaded.cohesion : null
  const cohesion = initialForChain ?? loadedForChain
  const error = initialForChain ? null : (loaded.requestKey === requestKey ? loaded.error : null)
  const refreshing = loaded.requestKey !== requestKey
  const loading = cohesion == null && refreshing
  const jobChainId = job?.chain_id
  const jobId = job?.job_id
  const jobStatus = job?.status

  useEffect(() => {
    onCohesionChange?.(cohesion)
  }, [cohesion, onCohesionChange])

  useEffect(() => {
    if (!jobId || jobChainId !== chainId || jobStatus !== 'SUCCEEDED') return
    if (cohesion?.context?.has_p2) return
    const jobKey = `${chainId}:${jobId}`
    if (refreshedJobKey.current === jobKey) return
    refreshedJobKey.current = jobKey
    const controller = new AbortController()
    api.cohesionNarrative(chainId, controller.signal, 'vi', true)
      .then((fresh) => {
        if (!controller.signal.aborted) setLoaded({ requestKey, cohesion: fresh, error: null })
      })
      .catch(() => {})
    return () => controller.abort()
  }, [chainId, cohesion?.context?.has_p2, jobChainId, jobId, jobStatus, requestKey])

  return (
    <section className="ai-advisor-panel">
      <header className="ai-advisor-header flex items-center justify-between py-1 mb-2 border-b border-surface-container-highest/60 pb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="material-symbols-outlined text-primary text-[18px]">psychology</span>
          <h2 className="text-sm font-bold text-on-surface m-0 leading-none">Nhận định điều tra chuỗi</h2>
          <span className="text-xs text-on-surface-variant font-mono">· Chuỗi <strong>{chainId}</strong></span>
        </div>
        <div className="flex items-center gap-2">
          {cohesion && (
            <GroundedProviderBadge
              model={cohesion.model}
              providerStatus={cohesion.provider_status ?? 'NOT_CONFIGURED'}
              hasProviderOutput={Boolean(cohesion.narrative?.trim())}
            />
          )}
          <button
            type="button"
            className="review-btn-action review-btn-approve text-xs py-1 px-2.5"
            onClick={() => setRefreshIndex((value) => value + 1)}
            disabled={refreshing}
          >
            {refreshing ? 'Đang tải…' : '↻ Tải lại'}
          </button>
        </div>
      </header>

      {loading ? (
        <div className="loading-state"><span /><p>Đang tổng hợp nhận định…</p></div>
      ) : cohesion ? (
        <article className="p-3 bg-[#0a1220] rounded-lg border border-[#1b2b48] text-sm leading-relaxed text-on-surface shadow-xs">
          {cohesion.narrative?.trim() ? (
            <p className="m-0">{cohesion.narrative}</p>
          ) : (
            <p className="m-0 text-on-surface-variant" role="status">
              Chưa có văn bản AI từ provider ({cohesion.provider_status ?? 'UNAVAILABLE'}). Evidence xác định vẫn có ở các tab Timeline, WHY, Topology và Audit.
            </p>
          )}
          {refreshing && (
            <p className="m-0 mt-2 text-[10px] font-mono text-secondary" aria-live="polite">
              Đang tạo lại nhận định từ evidence hiện tại…
            </p>
          )}
          <p className="m-0 mt-2 text-[10px] font-mono text-on-surface-variant">
            Nhận định chỉ dùng evidence đã kiểm tra; không tự suy ra nguyên nhân gốc hoặc hướng lan truyền.
          </p>
        </article>
      ) : error ? (
        <div className="error-banner" role="alert">
          <strong>Chưa thể tạo nhận định</strong>
          <p>{error}</p>
        </div>
      ) : null}
    </section>
  )
}
