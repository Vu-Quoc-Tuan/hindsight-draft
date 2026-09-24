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

const SnapshotOverviewView = lazy(() => import('./views/SnapshotOverviewView').then(m => ({ default: m.SnapshotOverviewView })))
const SnapshotsPortfolioView = lazy(() => import('./views/SnapshotsPortfolioView').then(m => ({ default: m.SnapshotsPortfolioView })))
const AllChainsView = lazy(() => import('./views/AllChainsView').then(m => ({ default: m.AllChainsView })))
const ChainDetailView = lazy(() => import('./views/ChainDetailView').then(m => ({ default: m.ChainDetailView })))
const AuditStructureView = lazy(() => import('./views/AuditStructureView').then(m => ({ default: m.AuditStructureView })))
const RecommendationsView = lazy(() => import('./views/RecommendationsView').then(m => ({ default: m.RecommendationsView })))
const EvolutionView = lazy(() => import('./views/EvolutionView').then(m => ({ default: m.EvolutionView })))
const TopologyOverlayView = lazy(() => import('./views/TopologyOverlayView').then(m => ({ default: m.TopologyOverlayView })))
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
  const topologyRequestKey = `${topologyProfile}\u0000${topologyRootId ?? ''}`
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
  const refreshedCohesionReviewId = useRef<string | null>(null)
  const [snapshotsCatalog, setSnapshotsCatalog] = useState<HeaderSnapshotItem[]>([])
  const [qualitySummaries, setQualitySummaries] = useState<ChainQualitySummary[]>([])
  const [qualitySummariesLoaded, setQualitySummariesLoaded] = useState(false)
  const [qualitySummarySnapshotKey, setQualitySummarySnapshotKey] = useState<string | null>(null)
  const [qualitySummaryError, setQualitySummaryError] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [selectingSnapshotId, setSelectingSnapshotId] = useState<string | null>(null)
  const snapshotSelectionGeneration = useRef(0)
  const snapshotSelectionAbort = useRef<AbortController | null>(null)
  const [overviewPreview, setOverviewPreview] = useState<{
    requestKey: string
    payload: ChainOverviewCards
  } | null>(null)

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
  const analysis = analysisMatchesContext(analysisState, currentAnalysisKey, chainId)
    ? analysisState!.payload
    : null
  const selectedChainSummary = chainList?.chains.find(chain => chain.chain_id === chainId) ?? null
  const overviewPreviewRequestKey = snapshotKey && chainId
    ? `${snapshotKey}\u0000${chainId}\u0000${configEpoch}`
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
          } else if (!(catalogResult.reason instanceof DOMException && catalogResult.reason.name === 'AbortError')) {
            setCatalogError(catalogResult.reason instanceof Error ? catalogResult.reason.message : 'Không đọc được catalog snapshot')
          }
          if (chainResult.status === 'fulfilled') {
            const existing = chainResult.value
            setChainList(existing)
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
  }, [])

  useEffect(() => () => snapshotSelectionAbort.current?.abort(), [])

  useEffect(() => {
    if (currentTab !== 'snapshot-overview' && currentTab !== 'snapshots-overview' && currentTab !== 'all-chains') return
    const controller = new AbortController()
    let inFlight = false
    const refresh = () => {
      if (controller.signal.aborted || document.hidden || inFlight) return
      inFlight = true
      api.snapshotQualitySummaries(controller.signal)
        .then(payload => {
          if (controller.signal.aborted) return
          setQualitySummaries(payload.summaries)
          setQualitySummarySnapshotKey(snapshotKey)
          setQualitySummaryError(null)
        })
        .catch(cause => {
          if (controller.signal.aborted) return
          setQualitySummaryError(cause instanceof Error ? cause.message : 'Không đọc được trạng thái đánh giá snapshot')
        })
        .finally(() => {
          inFlight = false
          if (!controller.signal.aborted) setQualitySummariesLoaded(true)
        })
    }
    refresh()
    const timer = window.setInterval(refresh, 4000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [currentTab, snapshotKey])

  // Kafka can advance the topology attached to an unpinned snapshot without
  // changing the snapshot ID/version. Refresh only the active chain catalog
  // identity so views and client caches move to that topology generation.
  useEffect(() => {
    if (chainListSnapshotId === null || chainListSnapshotVersion === null) return
    const requestedSnapshotId = chainListSnapshotId
    const requestedSnapshotVersion = chainListSnapshotVersion
    const controller = new AbortController()
    let inFlight = false
    const refresh = () => {
      if (controller.signal.aborted || document.hidden || inFlight) return
      inFlight = true
      api.chains(controller.signal)
        .then(updated => {
          if (
            controller.signal.aborted
            || updated.snapshot_id !== requestedSnapshotId
            || updated.snapshot_version !== requestedSnapshotVersion
          ) return
          setChainList(current => (
            current?.snapshot_id === requestedSnapshotId
            && current.snapshot_version === requestedSnapshotVersion
              ? updated
              : current
          ))
        })
        .catch(() => {
          // A 409 means another tab selected a different snapshot; keep this
          // tab's state and never replace it with that other workspace.
        })
        .finally(() => { inFlight = false })
    }
    const timer = window.setInterval(refresh, 6000)
    window.addEventListener('focus', refresh)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [chainListSnapshotId, chainListSnapshotVersion])

  // Auto-refresh snapshot catalog when tab is visible to detect newly pushed Kafka snapshots
  useEffect(() => {
    const refresh = () => {
      if (document.hidden) return
      api.listSnapshots().then(catalog => {
        setSnapshotsCatalog(catalog.snapshots as HeaderSnapshotItem[])
        setCatalogError(null)
      }).catch(cause => {
        if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
          setCatalogError(cause instanceof Error ? cause.message : 'Không làm mới được catalog snapshot')
        }
      })
    }
    const timer = window.setInterval(refresh, 6000)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [])

  // Load Analysis when chainId or snapshot changes
  useEffect(() => {
    if (!chainId || !snapshotKey || !currentAnalysisKey) return
    const controller = new AbortController()
    const requestKey = currentAnalysisKey
    api.analysis(chainId, controller.signal).then(payload => {
      if (controller.signal.aborted) return
      if (payload.chain_id !== chainId) {
        setAnalysisError({ requestKey, message: 'ANALYSIS_CONTEXT_MISMATCH' })
        return
      }
      setAnalysisState({ requestKey, payload })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        const msg = cause instanceof Error ? cause.message : 'Analysis failed'
        setAnalysisError({ requestKey, message: msg })
      }
    })
    return () => controller.abort()
  }, [chainId, snapshotKey, currentAnalysisKey])

  // Load the persisted deterministic Overview projection as soon as a chain
  // is selected.  This intentionally does not wait for Tier-1B analysis or
  // the LLM narrative, so the first paint is useful even on a cold chain.
  useEffect(() => {
    if (!['chain-overview', 'review', 'validation'].includes(currentTab) || !chainId || !overviewPreviewRequestKey) {
      return
    }
    const controller = new AbortController()
    const requestKey = overviewPreviewRequestKey
    let timer: number | null = null
    const load = () => {
      api.chainOverviewCards(
        chainId,
        controller.signal,
        expectedOverviewIdentity,
        expectedOverviewRevision,
        chainOverviewSnapshotContext,
      ).then(payload => {
        if (controller.signal.aborted) return
        setOverviewPreview({ requestKey, payload })
        if (payload.status === 'PENDING') {
          timer = window.setTimeout(load, 1200)
        }
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setOverviewPreview({
            requestKey,
            payload: {
              snapshot_id: chainList?.snapshot_id ?? 'active',
              snapshot_version: chainList?.snapshot_version ?? 'unknown',
              chain_id: chainId,
              status: 'UNAVAILABLE',
              projection_version: null,
              reason: cause instanceof Error ? cause.message : 'OVERVIEW_CARDS_REQUEST_FAILED',
              topology_version: null,
              representative_member: null,
              topology: null,
              quality_assessment: null,
              recommendations: null,
            },
          })
        }
      })
    }
    load()
    return () => {
      controller.abort()
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [
    chainId,
    chainList,
    currentTab,
    overviewPreviewRequestKey,
    configEpoch,
    reviewEpoch,
    expectedOverviewIdentity,
    expectedOverviewRevision,
    chainOverviewSnapshotContext,
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
    const controller = new AbortController()
    api.topologyProjection(topologyProfile, controller.signal, topologyRootId).then(payload => {
      if (!controller.signal.aborted) setLoadedTopology({ requestKey: topologyRequestKey, payload })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setLoadedTopology({
          requestKey: topologyRequestKey,
          payload: {
            status: 'UNAVAILABLE',
            profile: topologyProfile,
            topology_kind: 'UNAVAILABLE',
            reason: cause instanceof Error ? cause.message : 'TOPOLOGY_PROJECTION_UNAVAILABLE',
          },
        })
      }
    })
    return () => controller.abort()
  }, [currentTab, topologyProfile, topologyRequestKey, topologyRootId])

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
      setChainList(chains)
      setChainId('')
      setCurrentTab('snapshot-overview')
      setAnalysisState(null)
      setAnalysisError(null)
      setAssistantPair(null)
      setJob(null)
      setAuditVisualizationState(null)
      clearCohesionCache()
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    }
  }

  // Preset Snapshot selection handler
  const handleSelectSnapshot = async (id: string, profile: 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY', version?: string | null) => {
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
      if (controller.signal.aborted || generation !== snapshotSelectionGeneration.current) return
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
      setChainList(chains)
      setChainId('')
      setCurrentTab('snapshot-overview')
      setAnalysisState(null)
      setAnalysisError(null)
      setAssistantPair(null)
      setJob(null)
      setAuditVisualizationState(null)
      clearCohesionCache()
      setApiStatus('online')
      void api.listSnapshots().then(catalog => {
        setSnapshotsCatalog(catalog.snapshots as HeaderSnapshotItem[])
        setCatalogError(null)
      }).catch(cause => {
        if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
          setCatalogError(cause instanceof Error ? cause.message : 'Không làm mới được catalog snapshot')
        }
      })
    } catch (cause) {
      if (!controller.signal.aborted && generation === snapshotSelectionGeneration.current) {
        setError(cause instanceof Error ? cause.message : 'Snapshot selection failed')
      }
    } finally {
      if (generation === snapshotSelectionGeneration.current) {
        setSelectingSnapshotId(null)
        if (snapshotSelectionAbort.current === controller) snapshotSelectionAbort.current = null
      }
    }
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
      'snapshots-overview', 'snapshot-overview', 'all-chains', 'chain-overview',
      'why', 'members', 'structure', 'review', 'evolution', 'topology', 'validation',
    ]
    const targetTab = action.target.tab
    if (targetTab && !validTabs.includes(targetTab as SubNavTab)) {
      setError(`Assistant returned an unsupported workspace tab: ${targetTab}`)
      return
    }
    const normalizedTab = targetTab as SubNavTab | undefined
    const snapshotLevelTab = normalizedTab && ['snapshots-overview', 'snapshot-overview', 'all-chains'].includes(normalizedTab)
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
            setCurrentTab('all-chains')
          } else {
            setCurrentTab(tabName as SubNavTab)
          }
        }}
        onOpenLearning={handleOpenLearning}
      />

      {/* 2. Sub Navigation Bar (Chain-level IA: only when on a chain-level tab and a chain is selected) */}
      {!['snapshots-overview', 'snapshot-overview', 'all-chains'].includes(currentTab) && Boolean(chainId) && (
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
            <EvolutionView analysis={analysis} />
          )}

          {analysis && currentTab === 'topology' && (
            <TopologyOverlayView
              analysis={analysis}
              snapshotKey={snapshotKey}
              snapshotContext={chainOverviewSnapshotContext}
              initialPathProjection={currentOverviewPreview}
              topologyPayload={topologyPayload}
              topologyHypotheses={activeJob?.status === 'SUCCEEDED' ? activeJob.result?.topology_hypotheses : null}
              onRootChange={setTopologyRootId}
              onRunDeepDive={() => void runDeepDive()}
              isDeepDiveRunning={activeJob?.status === 'QUEUED' || activeJob?.status === 'RUNNING'}
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
