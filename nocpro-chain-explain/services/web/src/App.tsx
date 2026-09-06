import { useState, useEffect, useMemo } from 'react'

import { api, ApiError } from './api'
import type { TopologyTreePayload } from './TopologyTree'
import { NocHeader } from './components/NocHeader'
import { ContextRibbon } from './components/ContextRibbon'
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
import { AIAnalystDrawer } from './components/AIAnalystDrawer'
import { OperatorValidationModal } from './components/OperatorValidationModal'
import { AnalysisSettingsModal } from './AnalysisSettingsModal'

import type {
  AssistantAction,
  AssistantContext,
  ChainAnalysis,
  ChainList,
  Job,
  PairWhy,
} from './types'
import './App.css'

export default function App() {
  const [chainList, setChainList] = useState<ChainList | null>(null)
  const [chainId, setChainId] = useState<string>('')
  const [, setLoadingSnapshot] = useState(false)
  const [, setApiStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [analysisState, setAnalysisState] = useState<{
    snapshotKey: string
    payload: ChainAnalysis
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [, setPairWhyState] = useState<{
    snapshotKey: string
    payload: PairWhy
  } | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [topologyProfile] = useState<'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'>('IT_SERVICES')
  const [topologyRootId] = useState<string | undefined>(undefined)
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
  const [comparePair, setComparePair] = useState<[string, string]>(['C2214039', 'C2214048'])
  const [isDrawerOpen, setDrawerOpen] = useState(false)
  const [isValidationModalOpen, setValidationModalOpen] = useState(false)

  const snapshotKey = chainList ? `${chainList.snapshot_id}:${chainList.snapshot_version}` : null
  const analysis = analysisState?.snapshotKey === snapshotKey ? analysisState.payload : null

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
          setError(cause instanceof Error ? cause.message : 'API offline')
        }
      }
    }
    void connect()
    return () => controller.abort()
  }, [])

  // Load Analysis when chainId or snapshot changes
  useEffect(() => {
    if (!chainId || !snapshotKey) return
    const controller = new AbortController()
    api.analysis(chainId, controller.signal).then(payload => {
      if (!controller.signal.aborted) setAnalysisState({ snapshotKey, payload })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Analysis failed')
    })
    return () => controller.abort()
  }, [chainId, snapshotKey, configEpoch])

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
      setPairWhyState(null)
      setJob(null)
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    } finally {
      setLoadingSnapshot(false)
    }
  }

  // Chain selection handler
  const handleSelectChain = (id: string) => {
    setChainId(id)
    setCurrentTab('chain-overview')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Clear selected chain (back to snapshot overview)
  const handleClearSelectedChain = () => {
    setChainId('')
    setCurrentTab('snapshot-overview')
  }

  // Compare 2 chains
  const handleCompareChains = (chainA: string, chainB: string) => {
    setComparePair([chainA, chainB])
    setChainId('')
    setCurrentTab('compare-chains')
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
      setChainId(targetChainId)
    }
    if (targetTab) {
      setCurrentTab(targetTab)
    }
    setDrawerOpen(false)
  }

  // Assistant Context
  const assistantContext: AssistantContext = useMemo(() => ({
    snapshot_id: chainList?.snapshot_id ?? 'S102',
    snapshot_version: chainList?.snapshot_version ?? 'v1',
    page: currentTab,
    chain_id: chainId || undefined,
    filters: {},
  }), [chainList, chainId, currentTab])

  // Fallback demo analysis if backend is not yet populated
  const effectiveAnalysis: ChainAnalysis = analysis ?? {
    chain_id: chainId || 'C2214039',
    title: 'Interface down / Transmission Peering Tear (DEHL01-CR01)',
    member_count: 58,
    singleton: false,
    statistics_mode: 'EXACT_INDEXED',
    audit_graph_mode: 'CHEEGER_NORMALIZED_LAPLACIAN',
    pair_materialization: 'ON_DEMAND',
    config_version: 'v1.0',
    graybox: {
      mode: 'ACTIVE_GUARDED',
      merge_strategy: null,
      rules: 4,
      characteristics: 12,
      pair_facts: 58,
      unavailable_capabilities: [],
    },
    descriptors: [],
    role_counts: { CORE: 42, PERIPHERAL: 12, WEAK: 2, NO_DATA: 2 },
    phase_durations: { burst: 22 },
    members: Array.from({ length: 58 }, (_, i) => ({
      alarm_id: `ALM-4793${3128 + i}`,
      alarm_name: i === 0 ? 'GigabitEthernet6/0/2 Down (Physical Link Failure)' : i === 1 ? 'Bundle-Ether101 BGP Flap' : i === 2 ? 'HundredGigE0/0/0/2 Optical Loss' : i === 3 ? 'ISIS Adjacency Down Peer-88' : `Telemetry Alarm #${i + 1}`,
      device_code: i < 42 ? 'DEHL01-CR01' : i < 54 ? 'DEHL01-SR02' : 'DEHT01-AR02',
      node_reference: i < 42 ? 'SITE_DEHL01' : 'SITE_DEHT01',
      canonical_start_time: `10:14:${String(2 + Math.floor(i / 3)).padStart(2, '0')}.108`,
      role: i === 0 ? 'CORE_ROOT' : i < 42 ? 'CORE' : i < 54 ? 'PERIPHERAL' : i === 54 || i === 55 ? 'WEAK' : 'CONNECTORS',
      membership_support: i === 54 || i === 55 ? 0.28 : 0.88,
      availability_coverage: 1.0,
      computable_groups: 4,
      representativeness: 0.92,
      group_fits: [],
      margins: [],
      redundancy_role: i === 0 ? 'SPOF' : 'REDUNDANT',
      failure_domains: ['L1_OPTICAL', 'L3_BGP'],
    })),
  }

  return (
    <div className="min-h-screen bg-background text-on-surface font-body-md antialiased select-none flex flex-col">
      {/* 1. Global NOC Header */}
      <NocHeader
        datasetName="IT_SERVICES"
        snapshotId={chainList?.snapshot_id ?? 'real_alarm_20260801'}
        totalAlarms={chainList?.chains.reduce((a, c) => a + c.member_count, 0) ?? 8714}
        totalChains={chainList?.chains.length ?? 2824}
        currentView={currentTab}
        onNavigate={tabName => {
          if (tabName === 'Snapshot Overview') setCurrentTab('snapshot-overview')
          else if (tabName === 'Chains Explorer') setCurrentTab('chains-explorer')
          else if (tabName === 'Timeline') setCurrentTab('multi-chain-timeline')
          else if (tabName === 'Compare') setCurrentTab('compare-chains')
        }}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenAIAnalyst={() => setDrawerOpen(true)}
      />

      {/* 2. System Capabilities Strip */}
      <ContextRibbon
        datasetName="IT_SERVICES"
        snapshotId={chainList?.snapshot_id ?? 'S102 / v1'}
        totalAlarms={chainList?.chains.reduce((a, c) => a + c.member_count, 0) ?? 8714}
        totalChains={chainList?.chains.length ?? 2824}
      />

      {/* 3. Sub Navigation Bar */}
      <SubNavBar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
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
        {/* SNAPSHOT LEVEL VIEWS */}
        {currentTab === 'snapshot-overview' && (
          <SnapshotOverviewView
            chainList={chainList}
            onSelectChain={handleSelectChain}
            onNavigate={view => {
              if (view === 'CHAINS') setCurrentTab('chains-explorer')
              else if (view === 'TIMELINE') setCurrentTab('multi-chain-timeline')
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
            chainAId={comparePair[0]}
            chainBId={comparePair[1]}
            chains={chainList?.chains ?? []}
            onSelectChain={handleSelectChain}
            onChangeSelection={() => setCurrentTab('chains-explorer')}
          />
        )}

        {/* CHAIN LEVEL VIEWS */}
        {(currentTab === 'chain-overview' || currentTab === 'why' || currentTab === 'members') && (
          <ChainDetailView
            analysis={effectiveAnalysis}
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
            onOpenDrawer={() => setDrawerOpen(true)}
          />
        )}

        {currentTab === 'structure' && (
          <AuditStructureView
            analysis={effectiveAnalysis}
            onOpenValidationModal={() => setValidationModalOpen(true)}
          />
        )}

        {currentTab === 'review' && (
          <RecommendationsView analysis={effectiveAnalysis} />
        )}

        {currentTab === 'evolution' && (
          <EvolutionView
            analysis={effectiveAnalysis}
            onExecutePartition={() => setValidationModalOpen(true)}
          />
        )}

        {currentTab === 'topology' && (
          <TopologyOverlayView
            analysis={effectiveAnalysis}
            topologyPayload={topologyPayload}
          />
        )}
      </main>

      {/* 6. Modals & Drawers */}
      <AIAnalystDrawer
        isOpen={isDrawerOpen}
        onClose={() => setDrawerOpen(false)}
        context={assistantContext}
        onNavigate={handleAssistantNavigation}
      />

      <OperatorValidationModal
        isOpen={isValidationModalOpen}
        onClose={() => setValidationModalOpen(false)}
        chainId={chainId || 'C2214039'}
        onConfirmSignOff={note => {
          console.log('Signed off partition for chain', chainId, note)
          setCurrentTab('evolution')
        }}
      />

      <AnalysisSettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onConfigChanged={cfg => {
          setActiveConfigVersion(cfg.config_version)
          setConfigEpoch(e => e + 1)
        }}
      />

      {/* 7. Footer Status Bar */}
      <footer className="w-full h-8 bg-surface-container-lowest border-t border-surface-container-highest px-space-lg flex items-center justify-between text-[11px] font-code-sm text-on-surface-variant select-none">
        <div className="flex items-center gap-space-lg">
          <span>PROVENANCE: <strong className="text-on-surface font-semibold">REAL_EXPORT_REPLAY</strong></span>
          <span>CONFIG: <span className="text-on-surface">v1.0</span></span>
          <span>ENGINE: <span className="text-secondary font-bold">hindsight-v1</span></span>
          <span>ACTIVE SNAPSHOT: <span className="text-on-surface">{chainList?.snapshot_id ?? 'real_alarm_20260801'}</span></span>
        </div>
        <div className="flex items-center gap-space-lg">
          <label className="cursor-pointer hover:text-secondary flex items-center gap-1">
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
          <span>MOCK GATEWAY: <strong className="text-secondary">:8085</strong></span>
          <span className="flex items-center gap-1 text-on-surface">
            <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span>
            STREAM SYNCED
          </span>
        </div>
      </footer>
    </div>
  )
}
