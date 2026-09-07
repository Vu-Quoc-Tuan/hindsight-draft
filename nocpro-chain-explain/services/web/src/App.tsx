import { useState, useEffect, useMemo } from 'react'

import { api, ApiError } from './api'
import type { TopologyTreePayload } from './TopologyTree'
import { NocHeader } from './components/NocHeader'
import { SubNavBar, type SubNavTab } from './components/SubNavBar'
import { SnapshotOverviewView } from './views/SnapshotOverviewView'
import { ChainsExplorerView } from './views/ChainsExplorerView'
import { MultiChainTimelineView } from './views/MultiChainTimelineView'
import { CompareChainsView } from './views/CompareChainsView'
import { ChainDetailView } from './views/ChainDetailView'
import { AuditStructureView } from './views/AuditStructureView'
import { RecommendationsView } from './views/RecommendationsView'
import { EvolutionView } from './views/EvolutionView'
import { TopologyOverlayView } from './views/TopologyOverlayView'
import { ValidationView } from './views/ValidationView'
import { AIAnalystDrawer } from './components/AIAnalystDrawer'
import { AnalysisSettingsModal } from './AnalysisSettingsModal'
import {
  analysisContextKey,
  analysisMatchesContext,
  type AnalysisState,
} from './appContext'

import type {
  AssistantAction,
  AssistantContext,
  AuditVisualizationArtifact,
  ChainList,
  Job,
  PairWhy,
} from './types'
import './App.css'

export default function App() {
  const [chainList, setChainList] = useState<ChainList | null>(null)
  const [chainId, setChainId] = useState<string>('')
  const [, setLoadingSnapshot] = useState(false)
  const [apiStatus, setApiStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [analysisState, setAnalysisState] = useState<AnalysisState | null>(null)
  const [analysisError, setAnalysisError] = useState<{ requestKey: string; message: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [auditVisualizationState, setAuditVisualizationState] = useState<{
    requestKey: string
    payload: AuditVisualizationArtifact
  } | null>(null)
  const [, setPairWhyState] = useState<{
    snapshotKey: string
    payload: PairWhy
  } | null>(null)
  const [topologyProfile, setTopologyProfile] = useState<'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'>('IP_NETWORK')
  const [topologyRootId, setTopologyRootId] = useState<string | undefined>(undefined)
  const topologyRequestKey = `${topologyProfile}\u0000${topologyRootId ?? ''}`
  const [loadedTopology, setLoadedTopology] = useState<{
    requestKey: string
    payload: TopologyTreePayload
  } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [configEpoch, setConfigEpoch] = useState(0)
  const [, setActiveConfigVersion] = useState<string | null>(null)

  // Navigation & Drawer UI states
  const [currentTab, setCurrentTab] = useState<SubNavTab>('snapshot-overview')
  const [comparePair, setComparePair] = useState<[string, string]>(['', ''])
  const [isDrawerOpen, setDrawerOpen] = useState(false)
  const [assistantPair, setAssistantPair] = useState<[string, string] | null>(null)
  const [reviewReadOnly, setReviewReadOnly] = useState(false)

  const snapshotKey = chainList ? `${chainList.snapshot_id}:${chainList.snapshot_version}` : null
  const currentAnalysisKey = snapshotKey && chainId
    ? analysisContextKey(snapshotKey, chainId, configEpoch)
    : null
  const analysis = analysisMatchesContext(analysisState, currentAnalysisKey, chainId)
    ? analysisState!.payload
    : null
  const availableChainIds = chainList?.chains.map(chain => chain.chain_id) ?? []
  const resolvedComparePair: [string, string] = (
    availableChainIds.includes(comparePair[0])
    && availableChainIds.includes(comparePair[1])
    && comparePair[0] !== comparePair[1]
  )
    ? comparePair
    : [availableChainIds[0] ?? '', availableChainIds[1] ?? '']

  // Initial Connect & API Health Check
  useEffect(() => {
    const controller = new AbortController()
    async function connect() {
      try {
        await api.health(controller.signal)
        setApiStatus('online')
        api.getConfig(controller.signal).then(cfg => {
          setActiveConfigVersion(cfg.config_version)
        }).catch(() => {})
        try {
          const existing = await api.chains(controller.signal)
          setChainList(existing)
          if (existing.chains.length > 0) {
            setChainId(existing.chains[0].chain_id)
          }
        } catch (cause) {
          if (!(cause instanceof ApiError && cause.status === 409)) throw cause
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
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

  // Job Polling
  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.job(job.job_id, controller.signal).then(setJob).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Job polling failed')
      })
    }, 450)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [job])

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
    setLoadingSnapshot(true)
    setError(null)
    try {
      const payload = JSON.parse(await file.text()) as unknown
      await api.loadSnapshot(payload)
      const chains = await api.chains()
      setChainList(chains)
      if (chains.chains.length > 0) {
        setChainId(chains.chains[0].chain_id)
      }
      setAnalysisState(null)
      setAnalysisError(null)
      setPairWhyState(null)
      setAssistantPair(null)
      setJob(null)
      setAuditVisualizationState(null)
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    } finally {
      setLoadingSnapshot(false)
    }
  }

  // Chain selection handler
  const handleSelectChain = (id: string) => {
    setAssistantPair(null)
    setReviewReadOnly(false)
    setChainId(id)
    setCurrentTab('chain-overview')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Clear selected chain (back to snapshot overview)
  const handleClearSelectedChain = () => {
    setAssistantPair(null)
    setReviewReadOnly(false)
    setChainId('')
    setCurrentTab('snapshot-overview')
  }

  // Compare 2 chains
  const handleCompareChains = (chainA: string, chainB: string) => {
    setAssistantPair(null)
    setReviewReadOnly(false)
    setComparePair([chainA, chainB])
    setChainId('')
    setCurrentTab('compare-chains')
  }

  async function runDeepDive() {
    if (!chainId) return
    setError(null)
    try {
      const submission = await api.submitDeepDive(chainId)
      const submittedJob = await api.job(submission.job_id)
      if (submittedJob.chain_id !== chainId) {
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
    const targetTab = action.target.tab as SubNavTab | undefined
    if (targetChainId) {
      if (targetChainId !== chainId) setAssistantPair(null)
      setChainId(targetChainId)
    }
    if (action.target.pair_alarm_id_a && action.target.pair_alarm_id_b) {
      setAssistantPair([action.target.pair_alarm_id_a, action.target.pair_alarm_id_b])
    }
    if (targetTab) {
      setReviewReadOnly(targetTab === 'review')
      setCurrentTab(targetTab)
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
    <div className="min-h-screen bg-background text-on-surface font-body-md antialiased select-none flex flex-col">
      {/* 1. Global NOC Header */}
      <NocHeader
        datasetName={topologyProfile}
        snapshotId={chainList ? `${chainList.snapshot_id}@${chainList.snapshot_version}` : 'NO_SNAPSHOT'}
        currentView={currentTab}
        onChangeDatasetProfile={profile => {
          setTopologyProfile(profile)
          setTopologyRootId(undefined)
        }}
        onNavigate={tabName => {
          if (tabName === 'Snapshot Overview' || tabName === 'snapshot-overview' || tabName === 'overview') {
            setChainId('')
            setCurrentTab('snapshot-overview')
          } else if (tabName === 'Chains Explorer' || tabName === 'chains-explorer' || tabName === 'chains' || tabName === 'CHAINS') {
            setChainId('')
            setCurrentTab('chains-explorer')
          } else if (tabName === 'Timeline' || tabName === 'multi-chain-timeline' || tabName === 'timeline' || tabName === 'TIMELINE') {
            setCurrentTab('multi-chain-timeline')
          } else if (tabName === 'Compare' || tabName === 'compare-chains' || tabName === 'compare') {
            setCurrentTab('compare-chains')
          } else {
            setCurrentTab(tabName as SubNavTab)
          }
        }}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {/* 2. Sub Navigation Bar (Chain-level IA: 05 Overview, 06-09 WHY, 10 Members, 11-13 Audit, 14 Recommendations, 15-16 Evolution, 17 Topology, 18 Validation) */}
      <SubNavBar
        currentTab={currentTab}
        onSelectTab={tab => {
          if (tab === 'review') setReviewReadOnly(false)
          setCurrentTab(tab)
        }}
        selectedChainId={chainId || null}
        onClearSelectedChain={handleClearSelectedChain}
      />

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
      <main className="flex-1 w-full px-space-lg py-space-md">
        {chainViewNeedsAnalysis && !analysis && (
          <section
            className="mx-auto max-w-3xl rounded-lg border border-surface-container-highest bg-surface-container p-space-xl text-center shadow-sm"
            role={selectedAnalysisError ? 'alert' : 'status'}
            aria-live="polite"
          >
            <span className="material-symbols-outlined text-3xl text-on-surface-variant">
              {analysisIsLoading ? 'progress_activity' : 'database_off'}
            </span>
            <h2 className="mt-space-sm font-headline-md text-headline-md font-bold text-on-surface">
              {analysisIsLoading ? `Loading analysis for ${chainId}…` : 'Chain analysis unavailable'}
            </h2>
            <p className="mt-space-xs font-code-sm text-code-sm text-on-surface-variant">
              {selectedAnalysisError ?? 'No compatible analysis artifact is available for the selected snapshot and chain.'}
            </p>
          </section>
        )}
        {/* SNAPSHOT LEVEL VIEWS */}
        {currentTab === 'snapshot-overview' && (
          <SnapshotOverviewView
            chainList={chainList}
            onSelectChain={handleSelectChain}
            onNavigate={view => {
              if (view === 'CHAINS' || view === 'chains-explorer') setCurrentTab('chains-explorer')
              else if (view === 'TIMELINE' || view === 'multi-chain-timeline') setCurrentTab('multi-chain-timeline')
              else if (view === 'COMPARE' || view === 'compare-chains') setCurrentTab('compare-chains')
              else setCurrentTab(view as SubNavTab)
            }}
          />
        )}

        {currentTab === 'chains-explorer' && (
          <ChainsExplorerView
            chainList={chainList}
            onSelectChain={handleSelectChain}
            onCompareChains={ids => {
              if (ids.length >= 2) handleCompareChains(ids[0], ids[1])
            }}
          />
        )}

        {currentTab === 'multi-chain-timeline' && (
          <MultiChainTimelineView
            chains={chainList?.chains ?? []}
            onSelectChain={handleSelectChain}
            onCompareChains={handleCompareChains}
            selectedChainId={chainId}
          />
        )}

        {currentTab === 'compare-chains' && (
          <CompareChainsView
            chainAId={resolvedComparePair[0]}
            chainBId={resolvedComparePair[1]}
            chains={chainList?.chains ?? []}
            onSelectChain={handleSelectChain}
            onChangeSelection={() => setCurrentTab('chains-explorer')}
          />
        )}

        {/* CHAIN LEVEL VIEWS */}
        {analysis && (currentTab === 'chain-overview' || currentTab === 'why' || currentTab === 'members') && (
          <ChainDetailView
            key={analysis.chain_id}
            analysis={analysis}
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
            onPairContextChange={setAssistantPair}
          />
        )}

        {analysis && currentTab === 'structure' && (
          <AuditStructureView
            analysis={analysis}
            job={job}
            auditVisualization={auditVisualization}
            onRunDeepDive={() => void runDeepDive()}
          />
        )}

        {analysis && currentTab === 'review' && (
          <RecommendationsView analysis={analysis} readOnly={reviewReadOnly} />
        )}

        {analysis && currentTab === 'evolution' && (
          <EvolutionView analysis={analysis} />
        )}

        {analysis && currentTab === 'topology' && (
          <TopologyOverlayView
            analysis={analysis}
            topologyPayload={topologyPayload}
            onRootChange={setTopologyRootId}
          />
        )}

        {analysis && currentTab === 'validation' && (
          <ValidationView
            analysis={analysis}
          />
        )}
      </main>

      {/* 6. Modals & Drawers */}
      <AIAnalystDrawer
        isOpen={isDrawerOpen}
        onClose={() => setDrawerOpen(false)}
        onOpen={() => setDrawerOpen(true)}
        context={assistantContext}
        onNavigate={handleAssistantNavigation}
      />

      {settingsOpen && (
        <AnalysisSettingsModal
          isOpen
          onClose={() => setSettingsOpen(false)}
          onConfigChanged={cfg => {
            setActiveConfigVersion(cfg.config_version)
            setConfigEpoch(e => e + 1)
          }}
        />
      )}

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
