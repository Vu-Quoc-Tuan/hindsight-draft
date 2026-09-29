import { useState, useEffect, useMemo, useRef, useCallback, lazy, Suspense } from 'react'

import {
  api,
  ApiError,
  clearCohesionCache,
  clearChainReadCache,
  clearTopologySubgraphCache,
  setActiveSnapshotContext,
} from './api'
import { clearReviewJobCache } from './reviewJobCache'
import { serializeAnalysisIdentity } from './analysisIdentity'
import type { TopologyTreePayload } from './TopologyTree'
import { NocHeader, type HeaderSnapshotItem } from './components/NocHeader'
import { SubNavBar, type SubNavTab } from './components/SubNavBar'
import { ChainOverviewPreview } from './components/ChainOverviewPreview'
import { useLiveUpdates } from './useLiveUpdates'
import {
  chainListResponseMatchesRefresh,
  invalidationMatchesChain,
  invalidationMatchesSnapshot,
} from './liveUpdates'
import type { LiveNotice, LiveRefreshScheduler, RefreshTask } from './liveUpdates'

const SnapshotOverviewView = lazy(() => import('./views/SnapshotOverviewView').then(m => ({ default: m.SnapshotOverviewView })))
const SnapshotsPortfolioView = lazy(() => import('./views/SnapshotsPortfolioView').then(m => ({ default: m.SnapshotsPortfolioView })))
const AllChainsView = lazy(() => import('./views/AllChainsView').then(m => ({ default: m.AllChainsView })))
const ChainDetailView = lazy(() => import('./views/ChainDetailView').then(m => ({ default: m.ChainDetailView })))
const AuditStructureView = lazy(() => import('./views/AuditStructureView').then(m => ({ default: m.AuditStructureView })))
const RecommendationsView = lazy(() => import('./views/RecommendationsView').then(m => ({ default: m.RecommendationsView })))
const EvolutionView = lazy(() => import('./views/EvolutionView').then(m => ({ default: m.EvolutionView })))
const TopologyOverlayView = lazy(() => import('./views/TopologyOverlayView').then(m => ({ default: m.TopologyOverlayView })))
const ReviewFeedbackHistoryView = lazy(() => import('./views/ReviewFeedbackHistoryView').then(m => ({ default: m.ReviewFeedbackHistoryView })))
const AIAnalystDrawer = lazy(() => import('./components/AIAnalystDrawer').then(m => ({ default: m.AIAnalystDrawer })))
const LearningModal = lazy(() => import('./components/LearningModal').then(m => ({ default: m.LearningModal })))
import {
  analysisContextKey,
  analysisMatchesContext,
  type AnalysisState,
} from './appContext'

import type {
  AssistantAction,
  AssistantContext,
  AuditVisualizationArtifact,
  ChainOverviewCards,
  ChainList,
  ChainQualitySummary,
  CounterfactualJob,
  Job,
  ReviewFeedbackHistoryItem,
} from './types'
import './App.css'

export default function App() {
  const [chainList, setChainList] = useState<ChainList | null>(null)
  const [chainId, setChainId] = useState<string>('')
  const [apiStatus, setApiStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [analysisState, setAnalysisState] = useState<AnalysisState | null>(null)
  const [analysisError, setAnalysisError] = useState<{ requestKey: string; message: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const deepDiveSubmissionGeneration = useRef(0)
  const [auditVisualizationState, setAuditVisualizationState] = useState<{
    requestKey: string
    payload: AuditVisualizationArtifact
  } | null>(null)
  const [topologyProfile, setTopologyProfile] = useState<'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'>('ALARM_ONLY')
  const [topologyRootId, setTopologyRootId] = useState<string | undefined>(undefined)
  const topologyRequestKey = `${chainList?.snapshot_id ?? 'NO_SNAPSHOT'}:${chainList?.snapshot_version ?? 'NO_VERSION'}:${chainList?.topology_version === undefined ? 'UNKNOWN_TOPOLOGY' : chainList.topology_version ?? 'NO_TOPOLOGY'}\u0000${topologyProfile}\u0000${topologyRootId ?? ''}`
  const [loadedTopology, setLoadedTopology] = useState<{
    requestKey: string
    payload: TopologyTreePayload
  } | null>(null)
  const [learningModalOpen, setLearningModalOpen] = useState(false)
  const [learningModalTab, setLearningModalTab] = useState<'engine' | 'ranker'>('engine')

  const handleOpenLearning = (tab: 'engine' | 'ranker' = 'engine') => {
    setLearningModalTab(tab)
    setLearningModalOpen(true)
  }

  const [configEpoch, setConfigEpoch] = useState(0)
  const previousConfigEpoch = useRef(configEpoch)
  const [reviewEpoch, setReviewEpoch] = useState(0)
  const [chainDataRefreshEpoch, setChainDataRefreshEpoch] = useState(0)
  const [topologyRefreshEpoch, setTopologyRefreshEpoch] = useState(0)
  const [evolutionRefreshEpoch, setEvolutionRefreshEpoch] = useState(0)
  const refreshedCohesionReviewId = useRef<string | null>(null)
  const [snapshotsCatalog, setSnapshotsCatalog] = useState<HeaderSnapshotItem[]>([])
  const [qualitySummaries, setQualitySummaries] = useState<ChainQualitySummary[]>([])
  const [qualitySummariesLoaded, setQualitySummariesLoaded] = useState(false)
  const [qualitySummarySnapshotKey, setQualitySummarySnapshotKey] = useState<string | null>(null)
  const [qualitySummaryError, setQualitySummaryError] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [liveRefreshErrors, setLiveRefreshErrors] = useState<Record<string, string>>({})
  const [selectingSnapshotId, setSelectingSnapshotId] = useState<string | null>(null)
  const snapshotSelectionGeneration = useRef(0)
  const snapshotSelectionAbort = useRef<AbortController | null>(null)
  const chainListRefreshGeneration = useRef(0)
  const [overviewPreview, setOverviewPreview] = useState<{
    requestKey: string
    payload: ChainOverviewCards
  } | null>(null)
  const [overviewPollEpoch, setOverviewPollEpoch] = useState(0)
  const overviewRetryTimer = useRef<number | null>(null)

  // Navigation & Drawer UI states
  const [currentTab, setCurrentTab] = useState<SubNavTab>('snapshot-overview')
  const [isDrawerOpen, setDrawerOpen] = useState(false)
  const [assistantPair, setAssistantPair] = useState<[string, string] | null>(null)

  const snapshotKey = chainList
    ? `${chainList.snapshot_id}:${chainList.snapshot_version}:${
      chainList.topology_version === undefined
        ? 'UNKNOWN_TOPOLOGY'
        : chainList.topology_version ?? 'NO_TOPOLOGY'
    }`
    : null
  const chainListSnapshotId = chainList?.snapshot_id ?? null
  const chainListSnapshotVersion = chainList?.snapshot_version ?? null
  const chainListTopologyVersion = chainList?.topology_version
  const chainOverviewSnapshotContext = useMemo(() => (
    chainListSnapshotId && chainListSnapshotVersion
      ? {
          snapshot_id: chainListSnapshotId,
          snapshot_version: chainListSnapshotVersion,
          topology_version: chainListTopologyVersion,
        }
      : undefined
  ), [chainListSnapshotId, chainListSnapshotVersion, chainListTopologyVersion])
  useEffect(() => {
    setActiveSnapshotContext(
      chainList?.snapshot_id ?? null,
      chainList?.snapshot_version ?? null,
      chainList?.topology_version,
    )
  }, [chainList?.snapshot_id, chainList?.snapshot_version, chainList?.topology_version])
  const activeJob = job
    && chainList
    && job.chain_id === chainId
    && job.snapshot_id === chainList.snapshot_id
    && job.snapshot_version === chainList.snapshot_version
    && (
      chainList.topology_version === undefined
      || job.topology_version === chainList.topology_version
    )
    ? job
    : null
  const currentAnalysisKey = snapshotKey && chainId
    ? analysisContextKey(snapshotKey, chainId, configEpoch)
    : null
  const analysisRefreshKey = currentAnalysisKey
    ? JSON.stringify(['chain-analysis', currentAnalysisKey])
    : null
  const analysis = analysisMatchesContext(analysisState, currentAnalysisKey, chainId)
    ? analysisState!.payload
    : null
  const selectedChainSummary = chainList?.chains.find(chain => chain.chain_id === chainId) ?? null
  const overviewPreviewRequestKey = snapshotKey && chainId
    ? `${snapshotKey}\u0000${chainId}\u0000${configEpoch}`
    : null
  const overviewRefreshKey = overviewPreviewRequestKey
    ? JSON.stringify(['chain-overview', overviewPreviewRequestKey, reviewEpoch])
    : null
  const evolutionRefreshKey = chainId && chainListSnapshotId && chainListSnapshotVersion
    ? JSON.stringify(['evolution', snapshotKey, chainId])
    : null
  const currentOverviewPreview = overviewPreview?.requestKey === overviewPreviewRequestKey
    ? overviewPreview.payload
    : null
  const expectedOverviewIdentityKey = serializeAnalysisIdentity(currentOverviewPreview?.analysis_identity)
  const expectedOverviewIdentity = useMemo(
    () => expectedOverviewIdentityKey
      ? JSON.parse(expectedOverviewIdentityKey) as NonNullable<ChainOverviewCards['analysis_identity']>
      : null,
    [expectedOverviewIdentityKey],
  )
  const expectedOverviewResourceKind = currentOverviewPreview?.artifact_revision?.resource_kind ?? null
  const expectedOverviewFingerprint = currentOverviewPreview?.artifact_revision?.fingerprint ?? null
  const expectedOverviewRevision = useMemo(
    () => expectedOverviewResourceKind && expectedOverviewFingerprint
      ? {
          resource_kind: expectedOverviewResourceKind,
          fingerprint: expectedOverviewFingerprint,
        } as NonNullable<ChainOverviewCards['artifact_revision']>
      : null,
    [expectedOverviewResourceKind, expectedOverviewFingerprint],
  )

  const liveSyncMarker = useRef<() => void>(() => {})
  const setLiveRefreshIssue = useCallback((resource: string, message: string | null) => {
    setLiveRefreshErrors(current => {
      if (message === null) {
        if (!(resource in current)) return current
        const next = { ...current }
        delete next[resource]
        return next
      }
      return current[resource] === message ? current : { ...current, [resource]: message }
    })
  }, [])
  const reportEvolutionIssue = useCallback((message: string | null) => {
    setLiveRefreshIssue('evolution', message)
    if (message === null) liveSyncMarker.current()
  }, [setLiveRefreshIssue])

  const refreshCatalogTask = useCallback<RefreshTask>(async signal => {
    try {
      const catalog = await api.listSnapshots(signal)
      if (signal.aborted) return
      setSnapshotsCatalog(catalog.snapshots as HeaderSnapshotItem[])
      setCatalogError(null)
      setLiveRefreshIssue('catalog', null)
      setApiStatus('online')
      liveSyncMarker.current()
    } catch (cause) {
      if (signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) return
      const message = cause instanceof Error ? cause.message : 'Không làm mới được catalog snapshot'
      setCatalogError(message)
      setLiveRefreshIssue('catalog', message)
    }
  }, [setLiveRefreshIssue])

  const refreshQualitySummaryTask = useCallback<RefreshTask>(async signal => {
    try {
      const payload = await api.snapshotQualitySummaries(signal)
      if (signal.aborted) return
      setQualitySummaries(payload.summaries)
      setQualitySummarySnapshotKey(snapshotKey)
      setQualitySummaryError(null)
      setLiveRefreshIssue('quality-summary', null)
      setQualitySummariesLoaded(true)
      setApiStatus('online')
      liveSyncMarker.current()
    } catch (cause) {
      if (signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) return
      const message = cause instanceof Error ? cause.message : 'Không đọc được trạng thái đánh giá snapshot'
      setQualitySummaryError(message)
      setLiveRefreshIssue('quality-summary', message)
      setQualitySummariesLoaded(true)
    }
  }, [setLiveRefreshIssue, snapshotKey])

  const createChainListRefreshTask = useCallback((
    requestedSnapshotId: string,
    requestedSnapshotVersion: string,
    generation: number,
    expectedTopologyVersion: string | null | undefined,
  ): RefreshTask => async signal => {
    try {
      const updated = await api.chains(signal)
      if (signal.aborted || generation !== chainListRefreshGeneration.current) return
      if (updated.snapshot_id !== requestedSnapshotId || updated.snapshot_version !== requestedSnapshotVersion) {
        setLiveRefreshIssue('chain-list', 'API đang ở snapshot khác; giữ nguyên dữ liệu snapshot hiện tại.')
        return
      }
      if (!chainListResponseMatchesRefresh(updated, {
        snapshotId: requestedSnapshotId,
        snapshotVersion: requestedSnapshotVersion,
        ...(expectedTopologyVersion === undefined ? {} : { topologyVersion: expectedTopologyVersion }),
      })) {
        setLiveRefreshIssue(
          'chain-list',
          'Topology vừa thay đổi nhưng API chưa trả đúng phiên bản; giữ nguyên dữ liệu hiện tại và chờ đồng bộ lại.',
        )
        return
      }
      setChainList(current => {
        if (
          generation !== chainListRefreshGeneration.current
          || current?.snapshot_id !== requestedSnapshotId
          || current.snapshot_version !== requestedSnapshotVersion
        ) return current
        return updated
      })
      setLiveRefreshIssue('chain-list', null)
      setApiStatus('online')
      liveSyncMarker.current()
    } catch (cause) {
      if (signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) return
      setLiveRefreshIssue(
        'chain-list',
        cause instanceof Error ? cause.message : 'Không làm mới được danh sách chain hiện tại',
      )
    }
  }, [setLiveRefreshIssue])

  const createAnalysisRefreshTask = useCallback((
    requestKey: string,
    requestedChainId: string,
  ): RefreshTask => async signal => {
    try {
      const payload = await api.analysis(requestedChainId, signal)
      if (signal.aborted) return
      if (payload.chain_id !== requestedChainId) {
        setAnalysisError({ requestKey, message: 'ANALYSIS_CONTEXT_MISMATCH' })
        setLiveRefreshIssue('chain-detail', 'API trả về evidence không khớp chain đang mở; giữ nguyên dữ liệu hiện tại.')
        return
      }
      setAnalysisState({ requestKey, payload })
      setAnalysisError(null)
      setLiveRefreshIssue('chain-detail', null)
      setApiStatus('online')
      liveSyncMarker.current()
    } catch (cause) {
      if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
      const message = cause instanceof Error ? cause.message : 'Analysis failed'
      setAnalysisError({ requestKey, message })
      setLiveRefreshIssue('chain-detail', message)
    }
  }, [setLiveRefreshIssue])

  const clearOverviewRetryTimer = useCallback(() => {
    if (overviewRetryTimer.current === null) return
    window.clearTimeout(overviewRetryTimer.current)
    overviewRetryTimer.current = null
  }, [])

  const createOverviewRefreshTask = useCallback((
    requestKey: string,
    requestedChainId: string,
    expectedIdentity: ChainOverviewCards['analysis_identity'],
    expectedRevision: ChainOverviewCards['artifact_revision'],
    snapshotContext: typeof chainOverviewSnapshotContext,
    expectedSnapshotId: string,
    expectedSnapshotVersion: string,
  ): RefreshTask => async signal => {
    try {
      const payload = await api.chainOverviewCards(
        requestedChainId,
        signal,
        expectedIdentity,
        expectedRevision,
        snapshotContext,
      )
      if (signal.aborted) return
      if (
        payload.chain_id !== requestedChainId
        || payload.snapshot_id !== expectedSnapshotId
        || payload.snapshot_version !== expectedSnapshotVersion
        || (
          snapshotContext?.topology_version !== undefined
          && payload.topology_version !== snapshotContext.topology_version
        )
      ) {
        setLiveRefreshIssue('overview-cards', 'Overview trả về sai snapshot/topology; đang giữ dữ liệu đã hiển thị.')
        return
      }
      setOverviewPreview({ requestKey, payload })
      setLiveRefreshIssue('overview-cards', null)
      setApiStatus('online')
      liveSyncMarker.current()
      if (payload.status === 'PENDING') {
        clearOverviewRetryTimer()
        overviewRetryTimer.current = window.setTimeout(() => {
          overviewRetryTimer.current = null
          setOverviewPollEpoch(epoch => epoch + 1)
        }, 1200)
      } else {
        clearOverviewRetryTimer()
      }
    } catch (cause) {
      if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
      const message = cause instanceof Error ? cause.message : 'OVERVIEW_CARDS_REQUEST_FAILED'
      setLiveRefreshIssue('overview-cards', message)
      setOverviewPreview(current => current?.requestKey === requestKey ? current : ({
        requestKey,
        payload: {
          snapshot_id: expectedSnapshotId,
          snapshot_version: expectedSnapshotVersion,
          chain_id: requestedChainId,
          status: 'UNAVAILABLE',
          projection_version: null,
          reason: message,
          topology_version: snapshotContext?.topology_version ?? null,
          representative_member: null,
          topology: null,
          quality_assessment: null,
          recommendations: null,
        },
      }))
    }
  }, [clearOverviewRetryTimer, setLiveRefreshIssue])

  const createTopologyRefreshTask = useCallback((
    requestKey: string,
    requestedProfile: typeof topologyProfile,
    requestedRootId: string | undefined,
  ): RefreshTask => async signal => {
    try {
      const payload = await api.topologyProjection(requestedProfile, signal, requestedRootId)
      if (signal.aborted) return
      if (payload.profile !== requestedProfile) {
        const message = 'TOPOLOGY_PROFILE_MISMATCH'
        setLiveRefreshIssue('topology', 'Topology trả về sai profile; đang giữ dữ liệu đã hiển thị.')
        setLoadedTopology(current => current?.requestKey === requestKey ? current : ({
          requestKey,
          payload: {
            status: 'UNAVAILABLE',
            profile: requestedProfile,
            topology_kind: 'UNAVAILABLE',
            reason: message,
          },
        }))
        return
      }
      setLoadedTopology({ requestKey, payload })
      setLiveRefreshIssue('topology', null)
      setApiStatus('online')
      liveSyncMarker.current()
    } catch (cause) {
      if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
      const message = cause instanceof Error ? cause.message : 'TOPOLOGY_PROJECTION_UNAVAILABLE'
      setLiveRefreshIssue('topology', message)
      setLoadedTopology(current => current?.requestKey === requestKey ? current : ({
        requestKey,
        payload: {
          status: 'UNAVAILABLE',
          profile: requestedProfile,
          topology_kind: 'UNAVAILABLE',
          reason: message,
        },
      }))
    }
  }, [setLiveRefreshIssue])

  const topologyRefreshKey = JSON.stringify(['topology-projection', topologyRequestKey])

  const chainListRefreshKey = chainListSnapshotId && chainListSnapshotVersion
    ? JSON.stringify(['chain-list', chainListSnapshotId, chainListSnapshotVersion])
    : null

  const handleLiveInvalidations = useCallback((
    notices: readonly LiveNotice[],
    scheduler: LiveRefreshScheduler,
  ) => {
    const fullResync = notices.some(notice => notice.kind === 'resync')
    const scopes = new Set<string>()
    for (const notice of notices) {
      if (notice.kind === 'invalidate') {
        for (const scope of notice.invalidates) scopes.add(scope)
      }
    }
    if (fullResync) {
      for (const scope of ['catalog', 'quality-summary', 'chain-list', 'chain-detail', 'topology', 'evolution']) {
        scopes.add(scope)
      }
    }

    // Portfolio/catalog responses are global and must include changes from
    // snapshots other than the one currently selected in this tab.
    if (scopes.has('catalog')) scheduler.schedule('catalog', refreshCatalogTask)
    if (scopes.has('quality-summary')) scheduler.schedule('quality-summary', refreshQualitySummaryTask)

    const matchingSnapshotNotices = notices.filter(notice => (
      notice.kind === 'resync'
      || invalidationMatchesSnapshot(notice, chainListSnapshotId, chainListSnapshotVersion)
    ))
    const chainListInvalidated = fullResync || matchingSnapshotNotices.some(notice => (
      notice.kind === 'invalidate'
      && (notice.invalidates.includes('chain-list') || notice.invalidates.includes('topology'))
    ))
    if (chainListInvalidated && chainListRefreshKey) {
      const generation = ++chainListRefreshGeneration.current
      const topologyEvent = [...matchingSnapshotNotices].reverse().find(notice => (
        notice.kind === 'invalidate' && notice.event_type === 'topology.changed'
      ))
      scheduler.schedule(
        chainListRefreshKey,
        createChainListRefreshTask(
          chainListSnapshotId!,
          chainListSnapshotVersion!,
          generation,
          topologyEvent?.kind === 'invalidate' ? topologyEvent.topology_version : undefined,
        ),
      )
    }

    if (scopes.has('topology')) {
      clearTopologySubgraphCache()
      const topologyRelevant = currentTab === 'topology' && matchingSnapshotNotices.length > 0
      const chainListWillMoveTopology = matchingSnapshotNotices.some(notice => (
        notice.kind === 'invalidate'
        && notice.event_type === 'topology.changed'
        && notice.topology_version !== chainListTopologyVersion
      ))
      if (topologyRelevant && !chainListWillMoveTopology) {
        setTopologyRefreshEpoch(epoch => epoch + 1)
        scheduler.schedule(
          topologyRefreshKey,
          createTopologyRefreshTask(topologyRequestKey, topologyProfile, topologyRootId),
        )
      }
    }

    const matchingDetailNotices = matchingSnapshotNotices.filter(notice => (
      notice.kind === 'resync'
      || invalidationMatchesChain(notice, {
        snapshotId: chainListSnapshotId,
        snapshotVersion: chainListSnapshotVersion,
        topologyVersion: chainListTopologyVersion,
        chainId,
      })
    ))
    const chainDetailInvalidated = Boolean(chainId) && (
      (fullResync && !['snapshots-overview', 'snapshot-overview', 'all-chains'].includes(currentTab))
      || matchingDetailNotices.some(notice => (
        notice.kind === 'invalidate' && notice.invalidates.includes('chain-detail')
      ))
    )
    if (chainDetailInvalidated) {
      clearChainReadCache()
      clearReviewJobCache()
      clearCohesionCache(chainId)
      clearOverviewRetryTimer()
      if (analysisRefreshKey && currentAnalysisKey) {
        scheduler.schedule(analysisRefreshKey, createAnalysisRefreshTask(currentAnalysisKey, chainId))
      }
      if (
        overviewRefreshKey
        && overviewPreviewRequestKey
        && chainListSnapshotId
        && chainListSnapshotVersion
        && ['chain-overview', 'review', 'validation'].includes(currentTab)
      ) {
        scheduler.schedule(
          overviewRefreshKey,
          createOverviewRefreshTask(
            overviewPreviewRequestKey,
            chainId,
            expectedOverviewIdentity,
            expectedOverviewRevision,
            chainOverviewSnapshotContext,
            chainListSnapshotId,
            chainListSnapshotVersion,
          ),
        )
      }
      setChainDataRefreshEpoch(epoch => epoch + 1)
      if (currentTab === 'topology' && !scopes.has('topology')) {
        setTopologyRefreshEpoch(epoch => epoch + 1)
      }
    }

    const evolutionInvalidated = currentTab === 'evolution' && Boolean(chainId) && (
      (fullResync && matchingDetailNotices.length > 0)
      || matchingDetailNotices.some(notice => (
        notice.kind === 'invalidate' && notice.invalidates.includes('evolution')
      ))
      || notices.some(notice => (
        notice.kind === 'invalidate'
        && notice.event_type === 'snapshot.changed'
        && notice.invalidates.includes('evolution')
      ))
    )
    if (evolutionInvalidated) setEvolutionRefreshEpoch(epoch => epoch + 1)
  }, [
    analysisRefreshKey,
    chainId,
    chainListSnapshotId,
    chainListSnapshotVersion,
    chainListRefreshKey,
    chainListTopologyVersion,
    chainOverviewSnapshotContext,
    clearOverviewRetryTimer,
    createChainListRefreshTask,
    createAnalysisRefreshTask,
    createOverviewRefreshTask,
    createTopologyRefreshTask,
    currentAnalysisKey,
    currentTab,
    expectedOverviewIdentity,
    expectedOverviewRevision,
    overviewPreviewRequestKey,
    overviewRefreshKey,
    refreshCatalogTask,
    refreshQualitySummaryTask,
    topologyProfile,
    topologyRefreshKey,
    topologyRequestKey,
    topologyRootId,
  ])

  const {
    connectionState: liveConnectionState,
    lastSuccessfulSync,
    scheduleRefresh,
    cancelRefresh,
    markSuccessfulSync,
  } = useLiveUpdates(handleLiveInvalidations)

  useEffect(() => {
    liveSyncMarker.current = markSuccessfulSync
  }, [markSuccessfulSync])

  useEffect(() => {
    if (previousConfigEpoch.current === configEpoch) return
    previousConfigEpoch.current = configEpoch
    clearChainReadCache()
    clearReviewJobCache()
    clearCohesionCache()
    clearTopologySubgraphCache()
    setOverviewPreview(null)
  }, [configEpoch])

  const handleReviewSucceeded = useCallback((reviewJob: CounterfactualJob) => {
    if (reviewJob.chain_id !== chainId || reviewJob.status !== 'SUCCEEDED') return
    if (refreshedCohesionReviewId.current === reviewJob.job_id) return
    refreshedCohesionReviewId.current = reviewJob.job_id
    clearChainReadCache()
    clearCohesionCache(reviewJob.chain_id)
    setReviewEpoch((epoch) => epoch + 1)
  }, [chainId])

  // Initial Connect & API Health Check
  useEffect(() => {
    const controller = new AbortController()
    const wait = (milliseconds: number) => new Promise<void>((resolve, reject) => {
      const abort = () => {
        window.clearTimeout(timer)
        controller.signal.removeEventListener('abort', abort)
        reject(new DOMException('The operation was aborted.', 'AbortError'))
      }
      const timer = window.setTimeout(() => {
        controller.signal.removeEventListener('abort', abort)
        resolve()
      }, milliseconds)
      if (controller.signal.aborted) {
        abort()
        return
      }
      controller.signal.addEventListener('abort', abort, { once: true })
    })

    async function connect() {
      try {
        await api.health(controller.signal)
        setApiStatus('online')
        // Uvicorn can finish the health route just before the active snapshot
        // is hydrated after a reload.  A single 409 here is transient, not a
        // reason to render NO_SNAPSHOT forever.  Retry briefly, but keep the
        // request bounded and abortable so a real API failure is still visible.
        let lastChainError: unknown = null
        for (let attempt = 0; attempt < 6; attempt += 1) {
          const [catalogResult, chainResult] = await Promise.allSettled([
            api.listSnapshots(controller.signal),
            api.chains(controller.signal),
          ])
          if (catalogResult.status === 'fulfilled') {
            // Keep the catalog visible even while the active snapshot is
            // still being hydrated and /chains temporarily returns 409.
            setSnapshotsCatalog(catalogResult.value.snapshots as HeaderSnapshotItem[])
            setCatalogError(null)
            setLiveRefreshIssue('catalog', null)
            liveSyncMarker.current()
          } else if (!(catalogResult.reason instanceof DOMException && catalogResult.reason.name === 'AbortError')) {
            const message = catalogResult.reason instanceof Error ? catalogResult.reason.message : 'Không đọc được catalog snapshot'
            setCatalogError(message)
            setLiveRefreshIssue('catalog', message)
          }
          if (chainResult.status === 'fulfilled') {
            const existing = chainResult.value
            chainListRefreshGeneration.current += 1
            setChainList(existing)
            setLiveRefreshIssue('chain-list', null)
            liveSyncMarker.current()
            setChainId('')
            const activeCatalogItem = catalogResult.status === 'fulfilled'
              ? catalogResult.value.snapshots.find(item => (
                item.snapshot_id === existing.snapshot_id
                && (!item.snapshot_version || item.snapshot_version === existing.snapshot_version)
              ))
              : undefined
            setTopologyProfile(activeCatalogItem?.profile ?? 'ALARM_ONLY')
            return
          }
          lastChainError = chainResult.reason
          if (!(lastChainError instanceof ApiError && lastChainError.status === 409)) {
            throw lastChainError
          }
          if (attempt < 5) {
            await wait(250 * (attempt + 1))
          }
        }
        if (lastChainError) throw lastChainError
      } catch (cause) {
        if (!controller.signal.aborted && !(cause instanceof DOMException && cause.name === 'AbortError')) {
          setApiStatus('offline')
          const msg = cause instanceof Error ? cause.message : 'API offline'
          if (!msg.includes('502') && !msg.includes('Failed to fetch')) {
            setError(msg)
          }
        }
      }
    }
    void connect()
    return () => controller.abort()
  }, [setLiveRefreshIssue])

  useEffect(() => () => snapshotSelectionAbort.current?.abort(), [])

  useEffect(() => {
    if (currentTab !== 'snapshot-overview' && currentTab !== 'snapshots-overview' && currentTab !== 'all-chains') return
    scheduleRefresh('quality-summary', refreshQualitySummaryTask)
  }, [currentTab, snapshotKey, scheduleRefresh, refreshQualitySummaryTask])

  useEffect(() => () => {
    if (chainListRefreshKey) cancelRefresh(chainListRefreshKey)
  }, [chainListRefreshKey, cancelRefresh])

  // Load Analysis when chainId or snapshot changes
  useEffect(() => {
    if (!chainId || !snapshotKey || !currentAnalysisKey || !analysisRefreshKey) return
    scheduleRefresh(analysisRefreshKey, createAnalysisRefreshTask(currentAnalysisKey, chainId))
  }, [analysisRefreshKey, chainId, createAnalysisRefreshTask, currentAnalysisKey, scheduleRefresh, snapshotKey])

  useEffect(() => () => {
    if (analysisRefreshKey) cancelRefresh(analysisRefreshKey)
  }, [analysisRefreshKey, cancelRefresh])

  // Load the persisted deterministic Overview projection as soon as a chain
  // is selected.  This intentionally does not wait for Tier-1B analysis or
  // the LLM narrative, so the first paint is useful even on a cold chain.
  useEffect(() => {
    if (
      !['chain-overview', 'review', 'validation'].includes(currentTab)
      || !chainId
      || !overviewPreviewRequestKey
      || !overviewRefreshKey
      || !chainListSnapshotId
      || !chainListSnapshotVersion
    ) return
    scheduleRefresh(
      overviewRefreshKey,
      createOverviewRefreshTask(
        overviewPreviewRequestKey,
        chainId,
        expectedOverviewIdentity,
        expectedOverviewRevision,
        chainOverviewSnapshotContext,
        chainListSnapshotId,
        chainListSnapshotVersion,
      ),
    )
  }, [
    chainId,
    chainListSnapshotId,
    chainListSnapshotVersion,
    chainOverviewSnapshotContext,
    createOverviewRefreshTask,
    currentTab,
    expectedOverviewIdentity,
    expectedOverviewRevision,
    overviewPollEpoch,
    overviewPreviewRequestKey,
    overviewRefreshKey,
    scheduleRefresh,
  ])

  useEffect(() => () => {
    if (!overviewRefreshKey) return
    cancelRefresh(overviewRefreshKey)
    clearOverviewRetryTimer()
  }, [
    cancelRefresh,
    clearOverviewRetryTimer,
    currentTab,
    overviewRefreshKey,
  ])

  // Job Polling
  useEffect(() => {
    if (!activeJob || !['QUEUED', 'RUNNING'].includes(activeJob.status)) return
    const controller = new AbortController()
    const requestedJobId = activeJob.job_id
    const requestedSnapshotId = activeJob.snapshot_id
    const requestedSnapshotVersion = activeJob.snapshot_version
    const requestedTopologyVersion = activeJob.topology_version
    const requestedChainId = activeJob.chain_id
    const requestedGeneration = deepDiveSubmissionGeneration.current
    const timer = window.setTimeout(() => {
      api.job(requestedJobId, controller.signal).then(updated => {
        if (
          !controller.signal.aborted
          && deepDiveSubmissionGeneration.current === requestedGeneration
          && updated.job_id === requestedJobId
          && updated.chain_id === requestedChainId
          && updated.snapshot_id === requestedSnapshotId
          && updated.snapshot_version === requestedSnapshotVersion
          && updated.topology_version === requestedTopologyVersion
        ) {
          setJob(updated)
        }
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted && deepDiveSubmissionGeneration.current === requestedGeneration) {
          setError(cause instanceof Error ? cause.message : 'Job polling failed')
        }
      })
    }, 450)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [activeJob])

  // Reattach to the latest compatible Deep Dive after a browser reload. This
  // is read-only: opening the tab never submits new Tier-2 work.
  useEffect(() => {
    if ((currentTab !== 'structure' && currentTab !== 'topology') || !chainId || !chainList || !currentAnalysisKey) return
    const controller = new AbortController()
    const requestedChainId = chainId
    const requestedSnapshotId = chainList.snapshot_id
    const requestedSnapshotVersion = chainList.snapshot_version
    const requestedTopologyVersion = chainList.topology_version
    const requestedGeneration = deepDiveSubmissionGeneration.current
    api.latestDeepDive(chainId, controller.signal).then(payload => {
      if (
        !controller.signal.aborted
        && payload !== null
        && payload.chain_id === requestedChainId
        && payload.snapshot_id === requestedSnapshotId
        && payload.snapshot_version === requestedSnapshotVersion
        && payload.topology_version === requestedTopologyVersion
        && deepDiveSubmissionGeneration.current === requestedGeneration
      ) {
        setJob(payload)
      }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Deep Dive hydration failed')
      }
    })
    return () => controller.abort()
  }, [chainId, chainList, currentAnalysisKey, currentTab])

  // Read an already-persisted bounded Audit graph. This endpoint never starts
  // Deep Dive; running analysis remains an explicit operator action.
  useEffect(() => {
    if (currentTab !== 'structure' || !chainId || !currentAnalysisKey) return
    const controller = new AbortController()
    const requestKey = currentAnalysisKey
    api.auditVisualization(chainId, controller.signal).then(payload => {
      if (controller.signal.aborted) return
      if (
        payload.chain_id !== chainId
        || !chainList
        || payload.snapshot_id !== chainList.snapshot_id
        || payload.snapshot_version !== chainList.snapshot_version
      ) {
        setError('AUDIT_VISUALIZATION_CONTEXT_MISMATCH')
        return
      }
      setAuditVisualizationState({ requestKey, payload })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Audit visualization failed')
      }
    })
    return () => controller.abort()
  }, [chainId, chainList, currentAnalysisKey, currentTab])

  const auditVisualization = auditVisualizationState?.requestKey === currentAnalysisKey
    ? auditVisualizationState.payload
    : null

  // Load Topology when needed
  useEffect(() => {
    if (currentTab !== 'topology') return
    scheduleRefresh(
      topologyRefreshKey,
      createTopologyRefreshTask(topologyRequestKey, topologyProfile, topologyRootId),
    )
  }, [
    createTopologyRefreshTask,
    currentTab,
    scheduleRefresh,
    topologyProfile,
    topologyRefreshKey,
    topologyRequestKey,
    topologyRootId,
  ])

  useEffect(() => () => {
    if (currentTab === 'topology') cancelRefresh(topologyRefreshKey)
  }, [cancelRefresh, currentTab, topologyRefreshKey])

  const topologyPayload = loadedTopology?.requestKey === topologyRequestKey
    ? loadedTopology.payload
    : null

  // Upload Snapshot
  async function uploadSnapshot(file: File) {
    deepDiveSubmissionGeneration.current += 1
    snapshotSelectionGeneration.current += 1
    snapshotSelectionAbort.current?.abort()
    snapshotSelectionAbort.current = null
    setJob(null)
    setError(null)
    try {
      const payload = JSON.parse(await file.text()) as unknown
      const loaded = await api.loadSnapshot(payload)
      setActiveSnapshotContext(loaded.snapshot_id, loaded.snapshot_version, loaded.topology_version)
      const chains = await api.chains()
      chainListRefreshGeneration.current += 1
      setChainList(chains)
      setLiveRefreshIssue('chain-list', null)
      liveSyncMarker.current()
      setChainId('')
      setCurrentTab('snapshot-overview')
      setAnalysisState(null)
      setAnalysisError(null)
      setAssistantPair(null)
      setJob(null)
      setAuditVisualizationState(null)
      clearCohesionCache()
      setApiStatus('online')
      scheduleRefresh('catalog', refreshCatalogTask)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    }
  }

  // Preset Snapshot selection handler
  const handleSelectSnapshot = async (
    id: string,
    profile: 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY',
    version?: string | null,
    preserveCurrentTab = false,
  ): Promise<ChainList | null> => {
    deepDiveSubmissionGeneration.current += 1
    setJob(null)
    const generation = snapshotSelectionGeneration.current + 1
    snapshotSelectionGeneration.current = generation
    snapshotSelectionAbort.current?.abort()
    const controller = new AbortController()
    snapshotSelectionAbort.current = controller
    setError(null)
    const selectionKey = `${id}@${version ?? 'latest'}`
    setSelectingSnapshotId(selectionKey)
    try {
      const selected = await api.selectSnapshot(id, version, controller.signal)
      if (controller.signal.aborted || generation !== snapshotSelectionGeneration.current) return null
      setActiveSnapshotContext(selected.snapshot_id, selected.snapshot_version, selected.topology_version)
      setTopologyProfile(profile)
      setTopologyRootId(undefined)
      // Selection responses now carry the exact immutable chain catalog, so
      // opening a snapshot no longer waits on a sequential second request.
      // Keep the fallback for older API instances during a rolling restart.
      const chains = selected.chains
        ? {
            snapshot_id: selected.snapshot_id,
            snapshot_version: selected.snapshot_version,
            topology_version: selected.topology_version,
            chains: selected.chains,
          }
        : await api.chains(controller.signal)
      chainListRefreshGeneration.current += 1
      setChainList(chains)
      setLiveRefreshIssue('chain-list', null)
      liveSyncMarker.current()
      setChainId('')
      if (!preserveCurrentTab) setCurrentTab('snapshot-overview')
      setAnalysisState(null)
      setAnalysisError(null)
      setAssistantPair(null)
      setJob(null)
      setAuditVisualizationState(null)
      clearCohesionCache()
      setApiStatus('online')
      liveSyncMarker.current()
      scheduleRefresh('catalog', refreshCatalogTask)
      return chains
    } catch (cause) {
      if (!controller.signal.aborted && generation === snapshotSelectionGeneration.current) {
        setError(cause instanceof Error ? cause.message : 'Snapshot selection failed')
      }
      return null
    } finally {
      if (generation === snapshotSelectionGeneration.current) {
        setSelectingSnapshotId(null)
        if (snapshotSelectionAbort.current === controller) snapshotSelectionAbort.current = null
      }
    }
  }

  const handleOpenReviewHistoryItem = async (item: ReviewFeedbackHistoryItem) => {
    setError(null)
    if (snapshotSelectionAbort.current) {
      snapshotSelectionGeneration.current += 1
      snapshotSelectionAbort.current.abort()
      snapshotSelectionAbort.current = null
      setSelectingSnapshotId(null)
    }
    let targetChainList = chainList
    const exactSnapshotIsActive = chainList?.snapshot_id === item.snapshot_id
      && chainList.snapshot_version === item.snapshot_version
    if (!exactSnapshotIsActive) {
      targetChainList = await handleSelectSnapshot(
        item.snapshot_id,
        item.profile_id,
        item.snapshot_version,
        true,
      )
    } else {
      setTopologyProfile(item.profile_id)
      setTopologyRootId(undefined)
    }

    if (!targetChainList) return
    if (
      targetChainList.snapshot_id !== item.snapshot_id
      || targetChainList.snapshot_version !== item.snapshot_version
    ) {
      setError(`Không xác nhận được snapshot ${item.snapshot_id}@${item.snapshot_version}; vẫn ở trang Lịch sử ký duyệt.`)
      return
    }

    const targetChainExists = targetChainList.chains.some(chain => chain.chain_id === item.chain_id)
    if (!targetChainExists) {
      setError(`Không tìm thấy chain ${item.chain_id} trong snapshot ${item.snapshot_id}@${item.snapshot_version}; vẫn ở trang Lịch sử ký duyệt.`)
      return
    }

    deepDiveSubmissionGeneration.current += 1
    setJob(null)
    setAssistantPair(null)
    setChainId(item.chain_id)
    setCurrentTab('validation')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Chain selection handler
  const handleSelectChain = (id: string) => {
    deepDiveSubmissionGeneration.current += 1
    setJob(null)
    setAssistantPair(null)
    setChainId(id)
    setCurrentTab('chain-overview')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Clear selected chain (back to the active snapshot overview)
  const handleClearSelectedChain = () => {
    deepDiveSubmissionGeneration.current += 1
    setJob(null)
    setAssistantPair(null)
    setChainId('')
    setOverviewPreview(null)
    setCurrentTab('snapshot-overview')
  }

  async function runDeepDive() {
    if (!chainId || !chainList || selectingSnapshotId) return
    const requestedChainId = chainId
    const requestedSnapshotId = chainList.snapshot_id
    const requestedSnapshotVersion = chainList.snapshot_version
    const requestedGeneration = deepDiveSubmissionGeneration.current + 1
    deepDiveSubmissionGeneration.current = requestedGeneration
    const stillCurrent = () => deepDiveSubmissionGeneration.current === requestedGeneration
    setError(null)
    try {
      const submission = await api.submitDeepDive(requestedChainId)
      if (!stillCurrent()) return
      const submittedJob = await api.job(submission.job_id)
      if (
        !stillCurrent()
        || submittedJob.chain_id !== requestedChainId
        || submittedJob.snapshot_id !== requestedSnapshotId
        || submittedJob.snapshot_version !== requestedSnapshotVersion
        || submittedJob.topology_version !== chainList.topology_version
      ) {
        setError('DEEP_DIVE_CONTEXT_MISMATCH')
        return
      }
      setJob(submittedJob)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Deep Dive submission failed')
    }
  }

  // Assistant navigation handler
  function handleAssistantNavigation(action: AssistantAction) {
    if (!chainList || action.target.snapshot_id !== chainList.snapshot_id || action.target.snapshot_version !== chainList.snapshot_version) {
      setError('Assistant action is stale for the currently loaded snapshot.')
      return
    }
    const targetChainId = action.target.chain_id
    const validTabs: SubNavTab[] = [
      'snapshots-overview', 'snapshot-overview', 'all-chains', 'review-history', 'chain-overview',
      'why', 'members', 'structure', 'review', 'evolution', 'topology', 'validation',
    ]
    const targetTab = action.target.tab
    if (targetTab && !validTabs.includes(targetTab as SubNavTab)) {
      setError(`Assistant returned an unsupported workspace tab: ${targetTab}`)
      return
    }
    const normalizedTab = targetTab as SubNavTab | undefined
    const snapshotLevelTab = normalizedTab && ['snapshots-overview', 'snapshot-overview', 'all-chains', 'review-history'].includes(normalizedTab)
    if (snapshotLevelTab) {
      deepDiveSubmissionGeneration.current += 1
      setJob(null)
      setChainId('')
      setAssistantPair(null)
      setOverviewPreview(null)
    }
    if (targetChainId && !snapshotLevelTab) {
      if (targetChainId !== chainId) {
        deepDiveSubmissionGeneration.current += 1
        setJob(null)
        setAssistantPair(null)
      }
      setChainId(targetChainId)
    }
    if (!snapshotLevelTab && action.target.pair_alarm_id_a && action.target.pair_alarm_id_b) {
      setAssistantPair([action.target.pair_alarm_id_a, action.target.pair_alarm_id_b])
    }
    if (normalizedTab) {
      setCurrentTab(normalizedTab)
    }
    setDrawerOpen(false)
  }

  // Assistant Context
  const assistantContext: AssistantContext = useMemo(() => ({
    snapshot_id: chainList?.snapshot_id ?? 'NO_SNAPSHOT',
    snapshot_version: chainList?.snapshot_version ?? 'NO_VERSION',
    page: currentTab,
    chain_id: chainId || undefined,
    pair_alarm_id_a: assistantPair?.[0],
    pair_alarm_id_b: assistantPair?.[1],
    selection: assistantPair ? { kind: 'pair', alarm_id_a: assistantPair[0], alarm_id_b: assistantPair[1] } : undefined,
    filters: {},
  }), [assistantPair, chainList, chainId, currentTab])

  const selectedAnalysisError = currentAnalysisKey && analysisError?.requestKey === currentAnalysisKey
    ? analysisError.message
    : null
  const analysisIsLoading = Boolean(currentAnalysisKey && !analysis && !selectedAnalysisError)
  const chainViewNeedsAnalysis = [
    'chain-overview',
    'why',
    'members',
    'structure',
    'review',
    'evolution',
    'topology',
    'validation',
  ].includes(currentTab)
  const liveRefreshIssue = Object.values(liveRefreshErrors)[0] ?? qualitySummaryError ?? catalogError
  const liveStatusText = liveConnectionState === 'LIVE'
    ? 'Đang cập nhật trực tiếp'
    : liveConnectionState === 'CONNECTING'
      ? 'Đang kết nối cập nhật trực tiếp'
      : liveConnectionState === 'DISABLED'
        ? 'Cập nhật trực tiếp không khả dụng · đang đồng bộ định kỳ'
        : 'Kết nối gián đoạn · đang đồng bộ định kỳ'
  const liveStatusTone = liveConnectionState === 'LIVE'
    ? 'bg-emerald-400'
    : liveConnectionState === 'CONNECTING'
      ? 'bg-amber-400 animate-pulse'
      : 'bg-orange-400'
  const lastSyncText = lastSuccessfulSync?.toLocaleTimeString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return (
    <div className="min-h-screen w-full max-w-[100vw] min-w-0 overflow-x-hidden bg-background text-on-surface font-body-md antialiased select-none flex flex-col">
      {/* 1. Global NOC Header */}
      <NocHeader
        datasetName={topologyProfile}
        snapshotId={chainList ? `${chainList.snapshot_id}@${chainList.snapshot_version}` : 'NO_SNAPSHOT'}
        currentView={currentTab}
        snapshots={snapshotsCatalog}
        onSelectSnapshot={handleSelectSnapshot}
        onUploadSnapshotFile={uploadSnapshot}
        onChangeDatasetProfile={profile => {
          setTopologyProfile(profile)
          setTopologyRootId(undefined)
        }}
        onNavigate={tabName => {
          if (tabName === 'Snapshots' || tabName === 'snapshots-overview') {
            deepDiveSubmissionGeneration.current += 1
            setJob(null)
            setChainId('')
            setCurrentTab('snapshots-overview')
          } else if (tabName === 'Snapshot Overview' || tabName === 'snapshot-overview' || tabName === 'overview') {
            deepDiveSubmissionGeneration.current += 1
            setJob(null)
            setChainId('')
            setCurrentTab('snapshot-overview')
          } else if (tabName === 'All Chains' || tabName === 'all-chains' || tabName === 'chains' || tabName === 'CHAINS') {
            deepDiveSubmissionGeneration.current += 1
            setJob(null)
            setChainId('')
            setAssistantPair(null)
            setCurrentTab('all-chains')
          } else if (tabName === 'Lịch sử ký duyệt' || tabName === 'review-history') {
            deepDiveSubmissionGeneration.current += 1
            setJob(null)
            setChainId('')
            setAssistantPair(null)
            setOverviewPreview(null)
            setError(null)
            setCurrentTab('review-history')
          } else {
            setCurrentTab(tabName as SubNavTab)
          }
        }}
        onOpenLearning={handleOpenLearning}
      />

      <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1 border-b border-[#1b273e] bg-[#0b1220] px-space-lg py-1 font-code-sm text-[11px] text-on-surface-variant">
        <span className="inline-flex items-center gap-1.5" role="status" aria-live="polite">
          <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${liveStatusTone}`} />
          {liveStatusText}
        </span>
        <span className="text-[#64748b]" aria-live="off">
          {lastSyncText ? `Đồng bộ gần nhất ${lastSyncText}` : 'Chưa có lần đồng bộ thành công'}
        </span>
        {liveRefreshIssue && (
          <span className="text-amber-300" role="status" aria-live="polite">
            Bản dữ liệu trước vẫn được giữ: {liveRefreshIssue}
          </span>
        )}
      </div>

      {/* 2. Sub Navigation Bar (Chain-level IA: only when on a chain-level tab and a chain is selected) */}
      {!['snapshots-overview', 'snapshot-overview', 'all-chains', 'review-history'].includes(currentTab) && Boolean(chainId) && (
        <SubNavBar
          currentTab={currentTab}
          onSelectTab={tab => {
            setCurrentTab(tab)
          }}
          selectedChainId={chainId || null}
          onClearSelectedChain={handleClearSelectedChain}
        />
      )}

      {/* 4. Global Error Alert if present */}
      {error && (
        <div className="mx-space-lg mt-space-sm p-space-sm bg-error-container text-error rounded flex items-center justify-between shadow-md">
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-[18px]">error</span>
            <span className="font-code-sm text-code-sm font-semibold">{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-error font-bold">×</button>
        </div>
      )}

      {/* 5. Main Workspace Views Router */}
      <main className="flex-1 w-full max-w-[100vw] min-w-0 overflow-x-hidden px-space-lg py-space-md">
        <Suspense
          fallback={
            <div className="flex h-64 items-center justify-center gap-space-sm text-on-surface-variant font-code-sm">
              <span className="material-symbols-outlined animate-spin text-xl text-primary">progress_activity</span>
              <span>Loading view module…</span>
            </div>
          }
        >
          {chainViewNeedsAnalysis && !analysis && !(currentTab === 'chain-overview' && selectedChainSummary) && (
            <section
              className="mx-auto max-w-4xl rounded-xl border border-surface-container-highest bg-surface-container p-space-lg shadow-sm"
              role={selectedAnalysisError ? 'alert' : 'status'}
              aria-live="polite"
            >
              <div className="flex items-start gap-space-md">
                <span className={`material-symbols-outlined mt-0.5 text-2xl ${selectedAnalysisError ? 'text-error' : 'animate-spin text-secondary'}`}>
                  {selectedAnalysisError ? 'database_off' : 'progress_activity'}
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-headline-md text-headline-md font-bold text-on-surface">
                    {selectedAnalysisError ? 'Không tải được evidence của chain' : `Đang mở chain ${chainId}`}
                  </h2>
                  {selectedChainSummary && (
                    <p className="mt-1 truncate text-sm font-semibold text-on-surface" title={selectedChainSummary.title}>
                      {selectedChainSummary.title} · {selectedChainSummary.member_count} cảnh báo
                    </p>
                  )}
                  <p className="mt-space-xs font-code-sm text-code-sm text-on-surface-variant">
                    {selectedAnalysisError ?? 'Đang đọc thành viên, WHY và topology đã ánh xạ. Deep Dive và AI được tải riêng, không chặn bước này.'}
                  </p>
                  {analysisIsLoading && (
                    <div className="mt-space-md h-1.5 overflow-hidden rounded-full bg-surface-container-highest">
                      <div className="h-full w-2/5 animate-pulse rounded-full bg-gradient-to-r from-secondary to-primary" />
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
          {currentTab === 'chain-overview' && !analysis && selectedChainSummary && (
            <ChainOverviewPreview
              chain={selectedChainSummary}
              cards={overviewPreview?.requestKey === overviewPreviewRequestKey ? overviewPreview.payload : null}
            />
          )}
          {/* SNAPSHOT LEVEL VIEWS */}
          {currentTab === 'snapshots-overview' && (
            <SnapshotsPortfolioView
              snapshots={snapshotsCatalog}
              summaries={qualitySummaries}
              activeSnapshotId={chainList?.snapshot_id ?? null}
              activeSnapshotVersion={chainList?.snapshot_version ?? null}
              selectingSnapshotId={selectingSnapshotId}
              qualitySummaryError={qualitySummaryError}
              catalogError={catalogError}
              onSelectSnapshot={handleSelectSnapshot}
            />
          )}

          {currentTab === 'snapshot-overview' && (
            <SnapshotOverviewView
              chainList={chainList}
              qualitySummary={qualitySummaries.find(summary => summary.snapshot_id === chainList?.snapshot_id && summary.snapshot_version === chainList?.snapshot_version) ?? null}
              qualitySummaryLoading={!qualitySummariesLoaded || qualitySummarySnapshotKey !== snapshotKey}
              qualitySummaryError={qualitySummaryError}
              onSelectChain={handleSelectChain}
              onNavigate={view => {
                if (view === 'CHAINS' || view === 'all-chains') setCurrentTab('all-chains')
                else setCurrentTab(view as SubNavTab)
              }}
            />
          )}

          {currentTab === 'all-chains' && (
            <AllChainsView
              chainList={chainList}
              qualitySummary={qualitySummaries.find(summary => summary.snapshot_id === chainList?.snapshot_id && summary.snapshot_version === chainList?.snapshot_version) ?? null}
              qualitySummaryError={qualitySummaryError}
              onSelectChain={handleSelectChain}
            />
          )}

          {currentTab === 'review-history' && (
            <ReviewFeedbackHistoryView
              key={JSON.stringify(chainOverviewSnapshotContext ?? null)}
              snapshotContext={chainOverviewSnapshotContext ?? null}
              onOpenChain={item => void handleOpenReviewHistoryItem(item)}
            />
          )}

          {/* CHAIN LEVEL VIEWS */}
          {analysis && (currentTab === 'chain-overview' || currentTab === 'why' || currentTab === 'members') && (
            <ChainDetailView
              key={[snapshotKey, analysis.chain_id].join(':')}
              analysis={analysis}
              snapshotKey={snapshotKey}
              initialOverviewCards={currentOverviewPreview}
              snapshotContext={chainOverviewSnapshotContext}
              job={activeJob}
              activeSubTab={
                currentTab === 'chain-overview'
                  ? 'OVERVIEW'
                  : currentTab === 'why'
                  ? 'WHY'
                  : 'MEMBERS'
              }
              onSubTabChange={tab => {
                if (tab === 'OVERVIEW') setCurrentTab('chain-overview')
                else if (tab === 'WHY') setCurrentTab('why')
                else if (tab === 'MEMBERS') setCurrentTab('members')
              }}
              onNavigateTab={setCurrentTab}
              onPairContextChange={setAssistantPair}
              reviewEpoch={reviewEpoch}
              refreshEpoch={chainDataRefreshEpoch}
              scheduleRefresh={scheduleRefresh}
              cancelRefresh={cancelRefresh}
            />
          )}

          {analysis && chainList && currentTab === 'structure' && (
            <AuditStructureView
              analysis={analysis}
              snapshotId={chainList.snapshot_id}
              snapshotVersion={chainList.snapshot_version}
              job={activeJob}
              auditVisualization={auditVisualization}
              onRunDeepDive={() => void runDeepDive()}
            />
          )}

          {analysis && (currentTab === 'review' || currentTab === 'validation') && (
            <RecommendationsView
              key={`${snapshotKey ?? 'NO_SNAPSHOT'}-${chainId}-${configEpoch}-${currentOverviewPreview?.review_analysis_identity?.input_fingerprint ?? 'NO_REVIEW_CONTEXT'}`}
              analysis={analysis}
              snapshotId={chainList?.snapshot_id ?? null}
              snapshotVersion={chainList?.snapshot_version ?? null}
              topologyVersion={chainList?.topology_version}
              expectedAnalysisIdentity={currentOverviewPreview?.review_analysis_identity ?? null}
              expectedArtifactRevision={currentOverviewPreview?.review_artifact_revision ?? null}
              initialSubTab={currentTab === 'validation' ? 'validation' : 'recommendations'}
              onOpenReviewLearning={() => handleOpenLearning('ranker')}
              onThresholdApplied={() => setConfigEpoch(e => e + 1)}
              onReviewSucceeded={handleReviewSucceeded}
            />
          )}


          {analysis && currentTab === 'evolution' && (
            <EvolutionView
              analysis={analysis}
              resourceKey={evolutionRefreshKey ?? undefined}
              refreshEpoch={evolutionRefreshEpoch}
              expectedSnapshotId={chainList?.snapshot_id}
              expectedSnapshotVersion={chainList?.snapshot_version}
              scheduleRefresh={scheduleRefresh}
              cancelRefresh={cancelRefresh}
              onLoadError={reportEvolutionIssue}
            />
          )}

          {analysis && currentTab === 'topology' && (
            <TopologyOverlayView
              analysis={analysis}
              snapshotKey={snapshotKey}
              snapshotContext={chainOverviewSnapshotContext}
              initialPathProjection={currentOverviewPreview}
              refreshEpoch={topologyRefreshEpoch + chainDataRefreshEpoch}
              scheduleRefresh={scheduleRefresh}
              cancelRefresh={cancelRefresh}
              topologyPayload={topologyPayload}
              onRootChange={setTopologyRootId}
            />
          )}
        </Suspense>
      </main>

      {/* 6. Modals & Drawers */}
      <Suspense fallback={null}>
        <AIAnalystDrawer
          isOpen={isDrawerOpen}
          onClose={() => setDrawerOpen(false)}
          onOpen={() => setDrawerOpen(true)}
          context={assistantContext}
          onNavigate={handleAssistantNavigation}
        />

        {learningModalOpen && (
          <LearningModal
            isOpen
            onClose={() => setLearningModalOpen(false)}
            defaultTab={learningModalTab}
            onConfigChanged={() => setConfigEpoch(e => e + 1)}
          />
        )}
      </Suspense>

      {/* 7. Footer Status Bar - clean, without redundant snapshot info or mock gateway */}
      <footer className="w-full h-8 bg-surface-container-lowest border-t border-surface-container-highest px-space-lg flex items-center justify-between text-[11px] font-code-sm text-on-surface-variant select-none">
        <div className="flex items-center gap-space-lg">
          <label className="cursor-pointer hover:text-secondary flex items-center gap-1.5 transition-colors">
            <span className="material-symbols-outlined text-[14px]">upload_file</span>
            <span>Load Snapshot JSON</span>
            <input
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) void uploadSnapshot(file)
              }}
            />
          </label>
        </div>
        <div className="flex items-center gap-space-lg">
          {apiStatus === 'offline' && (
            <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant text-[10px]">
              API OFFLINE
            </span>
          )}
          {apiStatus === 'checking' && <span>CHECKING API</span>}
          {apiStatus === 'online' && chainList && (
            <span className="flex items-center gap-1.5 text-on-surface">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary"></span>
              SNAPSHOT READY
            </span>
          )}
          {apiStatus === 'online' && !chainList && <span>NO SNAPSHOT LOADED</span>}
        </div>
      </footer>
    </div>
  )
}
