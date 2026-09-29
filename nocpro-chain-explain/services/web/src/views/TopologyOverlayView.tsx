import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import type { ChainAnalysis, ChainOverviewCards, Member } from '../types'

import type { TopologyTreePayload } from '../TopologyTree'
import type { RefreshTask } from '../liveUpdates'
import { InfoTip } from '../components/InfoTip'
import { EvidenceDetails, type EvidencePathSelector } from '../components/EvidenceDetails'
import { api, type ChainOverviewSnapshotContext, type TopologySubgraphResult } from '../api'
import { serializeAnalysisIdentity } from '../analysisIdentity'
import {
  buildAlarmConnector,
  compactHopLabel,
  getFocusNodeIds,
  type EvidenceTopologyPath,
} from '../topologyGraph'

interface TopologyOverlayViewProps {
  analysis: ChainAnalysis
  topologyPayload?: TopologyTreePayload | null
  subgraphData?: TopologySubgraphResult | null
  snapshotKey?: string | null
  snapshotContext?: ChainOverviewSnapshotContext
  initialPathProjection?: ChainOverviewCards | null
  refreshEpoch?: number
  scheduleRefresh?: (key: string, task: RefreshTask) => boolean
  cancelRefresh?: (key: string) => void
  onRootChange?: (resourceId: string) => void
}

interface NetworkNode {
  id: string
  name: string
  x: number
  y: number
  tier: number // 0: Service / Core, 1: Module / Aggregation, 2: Site Router / Host
  roleCode: string
  roleName: string
  alarmCount: number
  exactAlarmCount: number
  candidateAlarmCount: number
  isDominant: boolean
  isAlarmBearer: boolean
  isAlarmTerminal: boolean
  isExactBearer: boolean
  isCandidateOnly: boolean
  badgeColor: string
  icon: string
  alarms: Member[]
  hopDistance?: number
}

interface NetworkEdge {
  id: string
  sourceId: string
  targetId: string
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  label: string
  isAlarmPath: boolean
  isAlarmConnector?: boolean
  relationType: string | null
  pathHops?: number
}

type SubgraphLoadState = 'loading' | 'available' | 'unavailable' | 'error'

type SubgraphRequestState = {
  requestKey: string
  status: 'available' | 'unavailable' | 'error'
  result: TopologySubgraphResult | null
  error: string | null
}

type OverviewPathRequestState = {
  requestKey: string
  payload: ChainOverviewCards | null
  error: string | null
}

type ContextBoundSelection<T> = {
  requestKey: string
  value: T
}

const EVIDENCE_TIER_LABELS: Record<string, string> = {
  EXACT: 'Exact topology identity',
  STRUCTURED_FIELD_UNIQUE: 'Structured-field unique match',
  TEXT_MATCH_CANDIDATE: 'Raw-text candidate',
  AMBIGUOUS: 'Ambiguous',
  UNMAPPED: 'Unmapped',
  VERIFIED_ALIAS: 'Verified alias',
}

const MATCH_STRENGTH_LABELS: Record<string, string> = {
  EXACT: 'Đối sánh xác thực',
  VERIFIED_ALIAS: 'Alias đã xác thực',
  STRUCTURED_FIELD_UNIQUE: 'Khớp duy nhất theo trường cấu trúc',
  TEXT_MATCH_CANDIDATE: 'Ứng viên từ văn bản',
  AMBIGUOUS: 'Chưa phân giải duy nhất',
  UNMAPPED: 'Chưa ánh xạ',
}

const EMPTY_CANONICAL_PATHS: EvidenceTopologyPath[] = []
const EMPTY_CANONICAL_TERMINALS: string[] = []

export function TopologyOverlayView({
  analysis,
  topologyPayload,
  subgraphData: externalSubgraph,
  snapshotKey = null,
  snapshotContext,
  initialPathProjection = null,
  refreshEpoch = 0,
  scheduleRefresh,
  cancelRefresh,
  onRootChange: _onRootChange,
}: TopologyOverlayViewProps) {
  const [selectedDeviceSelection, setSelectedDeviceSelection] = useState<ContextBoundSelection<string> | null>(null)
  const [hoveredEdgeSelection, setHoveredEdgeSelection] = useState<ContextBoundSelection<string> | null>(null)
  const [showAlarmsLayer, setShowAlarmsLayer] = useState(true)
  const [showLinksLayer, setShowLinksLayer] = useState(true)
  const [showNeighborsLayer, setShowNeighborsLayer] = useState(false)
  const [showModulesDetail, setShowModulesDetail] = useState(false)
  const [hopDistance, setHopDistance] = useState<number>(2)
  const [summaryNodeSelection, setSummaryNodeSelection] = useState<ContextBoundSelection<NetworkNode> | null>(null)
  const [evidenceDetailsOpen, setEvidenceDetailsOpen] = useState(false)
  const [evidencePathSelector, setEvidencePathSelector] = useState<EvidencePathSelector | null>(null)
  const [alarmFilter, setAlarmFilter] = useState<'ALL' | 'EXACT' | 'CANDIDATE'>('ALL')
  const [canvasElement, setCanvasElement] = useState<HTMLDivElement | null>(null)

  const closeNodeFocus = () => {
    setSummaryNodeSelection(null)
    setSelectedDeviceSelection(null)
    setHoveredEdgeSelection(null)
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeNodeFocus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Neo4j-style interactive canvas state
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({})
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [zoom, setZoom] = useState<number>(1.0)
  const [draggingNode, setDraggingNode] = useState<{
    id: string
    startMouseX: number
    startMouseY: number
    initialNodeX: number
    initialNodeY: number
  } | null>(null)
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const svgRef = useRef<SVGSVGElement | null>(null)

  const members: Member[] = useMemo(() => analysis.members || [], [analysis.members])
  const totalAlarms = members.length || analysis.member_count || 1

  // Detect whether chain is IT or IP
  const isITChain = useMemo(() => {
    return members.some(m => {
      const code = m.device_code || m.node_reference || ''
      const name = m.alarm_name || ''
      return /^\d+\.\d+\.\d+\.\d+/.test(code) || name.includes('Container ') || name.includes('cloud ') || name.includes('nova_')
    })
  }, [members])

  const activeProfile = isITChain ? 'IT_SERVICES' : 'IP_NETWORK'

  // Group alarms by device/host
  const deviceGroups = useMemo(() => {
    const map = new Map<string, Member[]>()
    members.forEach(m => {
      const dev = m.device_code || m.node_reference || 'UNKNOWN_HOST'
      if (!map.has(dev)) {
        map.set(dev, [])
      }
      map.get(dev)!.push(m)
    })
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [members])

  const distinctDevices = useMemo(() => deviceGroups.map(([dev]) => dev), [deviceGroups])
  const dominantDevice = distinctDevices[0] || 'DOMINANT_NODE'

  const alarmMap = useMemo(() => {
    const map = new Map<string, Member[]>()
    deviceGroups.forEach(([dev, alarms]) => map.set(dev, alarms))
    return map
  }, [deviceGroups])

  // Subgraph state (live fetched from /api/v1/topology/subgraph around seed devices)
  const [subgraphRequest, setSubgraphRequest] = useState<SubgraphRequestState | null>(null)
  const [overviewPathRequest, setOverviewPathRequest] = useState<OverviewPathRequestState | null>(null)
  const [overviewPathPollEpoch, setOverviewPathPollEpoch] = useState(0)
  const overviewPathRetryTimer = useRef<number | null>(null)
  const overviewPathRequestKey = `${snapshotKey ?? 'active'}\u0000${analysis.chain_id}`
  const overviewPathRefreshKey = JSON.stringify(['topology-overview-path', overviewPathRequestKey])
  const currentOverviewPathRequest = useMemo(() => (
    overviewPathRequest?.requestKey === overviewPathRequestKey
      ? overviewPathRequest
      : initialPathProjection?.chain_id === analysis.chain_id &&
          (snapshotKey === null || (
            initialPathProjection.snapshot_id === snapshotKey.split(':')[0] &&
            initialPathProjection.snapshot_version === snapshotKey.split(':')[1]
          ))
        ? { requestKey: overviewPathRequestKey, payload: initialPathProjection, error: null }
        : null
  ), [analysis.chain_id, initialPathProjection, overviewPathRequest, overviewPathRequestKey, snapshotKey])
  const currentOverviewPathRequestRef = useRef(currentOverviewPathRequest)
  useEffect(() => {
    currentOverviewPathRequestRef.current = currentOverviewPathRequest
  }, [currentOverviewPathRequest])
  const requestedTopologyVersion = currentOverviewPathRequest?.payload?.status === 'READY'
    ? currentOverviewPathRequest.payload.topology_version
    : null
  const expectedOverviewIdentityKey = serializeAnalysisIdentity(
    currentOverviewPathRequest?.payload?.analysis_identity,
  )
  const expectedOverviewIdentity = useMemo(
    () => expectedOverviewIdentityKey
      ? JSON.parse(expectedOverviewIdentityKey) as NonNullable<ChainOverviewCards['analysis_identity']>
      : null,
    [expectedOverviewIdentityKey],
  )
  const expectedOverviewResourceKind = currentOverviewPathRequest?.payload?.artifact_revision?.resource_kind ?? null
  const expectedOverviewFingerprint = currentOverviewPathRequest?.payload?.artifact_revision?.fingerprint ?? null
  const expectedOverviewRevision = useMemo(
    () => expectedOverviewResourceKind && expectedOverviewFingerprint
      ? {
          resource_kind: expectedOverviewResourceKind,
          fingerprint: expectedOverviewFingerprint,
        } as NonNullable<ChainOverviewCards['artifact_revision']>
      : null,
    [expectedOverviewResourceKind, expectedOverviewFingerprint],
  )
  const distinctDevicesKey = useMemo(() => distinctDevices.slice().sort().join(','), [distinctDevices])
  const subgraphRequestKey = JSON.stringify([
    snapshotKey,
    analysis.chain_id,
    activeProfile,
    distinctDevicesKey,
    hopDistance,
    requestedTopologyVersion ?? 'active',
  ])
  const subgraphRefreshKey = JSON.stringify(['topology-subgraph', subgraphRequestKey])
  const selectedDeviceId = selectedDeviceSelection?.requestKey === subgraphRequestKey
    ? selectedDeviceSelection.value
    : null
  const activeDevice = selectedDeviceId
  const hoveredEdgeId = hoveredEdgeSelection?.requestKey === subgraphRequestKey
    ? hoveredEdgeSelection.value
    : null
  const summaryNode = summaryNodeSelection?.requestKey === subgraphRequestKey
    ? summaryNodeSelection.value
    : null

  useEffect(() => {
    const task: RefreshTask = async signal => {
      try {
        const payload = await api.chainOverviewCards(
          analysis.chain_id,
          signal,
          expectedOverviewIdentity,
          expectedOverviewRevision,
          snapshotContext,
        )
        if (signal.aborted) return
        const [expectedSnapshotId, expectedSnapshotVersion] = snapshotKey?.split(':') ?? []
        if (
          payload.chain_id !== analysis.chain_id ||
          (snapshotKey !== null && (
            payload.snapshot_id !== expectedSnapshotId ||
            payload.snapshot_version !== expectedSnapshotVersion
          ))
        ) {
          setOverviewPathRequest({
            requestKey: overviewPathRequestKey,
            payload: currentOverviewPathRequestRef.current?.payload ?? null,
            error: 'OVERVIEW_PATH_CONTEXT_MISMATCH',
          })
          return
        }
        setOverviewPathRequest({ requestKey: overviewPathRequestKey, payload, error: null })
        if (payload.status === 'PENDING') {
          if (overviewPathRetryTimer.current !== null) window.clearTimeout(overviewPathRetryTimer.current)
          overviewPathRetryTimer.current = window.setTimeout(() => {
            overviewPathRetryTimer.current = null
            setOverviewPathPollEpoch(epoch => epoch + 1)
          }, 4000)
        } else if (overviewPathRetryTimer.current !== null) {
          window.clearTimeout(overviewPathRetryTimer.current)
          overviewPathRetryTimer.current = null
        }
      } catch (cause) {
        if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
        setOverviewPathRequest({
          requestKey: overviewPathRequestKey,
          payload: currentOverviewPathRequestRef.current?.payload ?? null,
          error: cause instanceof Error ? cause.message : 'TOPOLOGY_PATH_PROJECTION_REQUEST_FAILED',
        })
      }
    }
    if (scheduleRefresh) {
      scheduleRefresh(overviewPathRefreshKey, task)
      return
    }
    const controller = new AbortController()
    void task(controller.signal)
    return () => controller.abort()
  }, [
    analysis.chain_id,
    expectedOverviewIdentity,
    expectedOverviewRevision,
    overviewPathPollEpoch,
    overviewPathRefreshKey,
    overviewPathRequestKey,
    refreshEpoch,
    scheduleRefresh,
    snapshotContext,
    snapshotKey,
  ])

  useEffect(() => () => {
    cancelRefresh?.(overviewPathRefreshKey)
    if (overviewPathRetryTimer.current !== null) window.clearTimeout(overviewPathRetryTimer.current)
    overviewPathRetryTimer.current = null
  }, [cancelRefresh, overviewPathRefreshKey])

  useEffect(() => {
    if (externalSubgraph !== undefined) return
    if (!distinctDevicesKey) {
      return
    }
    const task: RefreshTask = async signal => {
      try {
        const res = await api.topologySubgraph(
          activeProfile,
          distinctDevices,
          hopDistance,
          signal,
          requestedTopologyVersion ?? undefined,
        )
        if (signal.aborted) return
        if (res.status === 'AVAILABLE' && res.nodes.length > 0) {
          setSubgraphRequest({ requestKey: subgraphRequestKey, status: 'available', result: res, error: null })
        } else {
          setSubgraphRequest({ requestKey: subgraphRequestKey, status: 'unavailable', result: res, error: null })
        }
      } catch (error) {
        if (signal.aborted || (error as { name?: string })?.name === 'AbortError') return
        setSubgraphRequest({
          requestKey: subgraphRequestKey,
          status: 'error',
          result: null,
          error: error instanceof Error ? error.message : 'Không thể tải topology',
        })
      }
    }
    if (scheduleRefresh) {
      scheduleRefresh(subgraphRefreshKey, task)
      return
    }
    const controller = new AbortController()
    void task(controller.signal)
    return () => controller.abort()
  }, [
    activeProfile,
    distinctDevices,
    distinctDevicesKey,
    externalSubgraph,
    hopDistance,
    refreshEpoch,
    requestedTopologyVersion,
    scheduleRefresh,
    subgraphRefreshKey,
    subgraphRequestKey,
  ])

  useEffect(() => () => {
    if (externalSubgraph === undefined) cancelRefresh?.(subgraphRefreshKey)
  }, [cancelRefresh, externalSubgraph, subgraphRefreshKey])

  const currentSubgraphRequest = subgraphRequest?.requestKey === subgraphRequestKey ? subgraphRequest : null
  const activeSubgraph = externalSubgraph !== undefined ? externalSubgraph : currentSubgraphRequest?.result ?? null
  const effectiveSubgraphState: SubgraphLoadState = externalSubgraph !== undefined
    ? externalSubgraph?.status === 'AVAILABLE' && externalSubgraph.nodes.length > 0
      ? 'available'
      : 'unavailable'
    : !distinctDevicesKey
      ? 'unavailable'
      : currentSubgraphRequest?.status ?? 'loading'
  const subgraphError = currentSubgraphRequest?.error ?? null
  const isLoadingSubgraph = effectiveSubgraphState === 'loading'
  const getDeviceRoleInfo = useCallback((devCode: string, resourceType?: string) => {
    const code = (devCode || '').toUpperCase()
    const type = (resourceType || '').toUpperCase()

    if (type === 'SERVICE' || type === 'CORE_ROUTER' || (!type && (code.includes('CORE') || code.includes('BACKBONE')))) {
      return {
        roleCode: 'CORE',
        roleName: isITChain ? 'IT Service / Lõi' : 'Core Router (Lõi)',
        tier: 0,
        badgeColor: 'text-cyan-300',
        bgFill: '#083344',
        icon: 'hub',
      }
    }
    if (type === 'AGG_DISTRICT' || (type !== 'MODULE' && code.includes('AGG')) || code.includes('PE-')) {
      return {
        roleCode: 'AGG',
        roleName: 'Aggregation (Gom PE)',
        tier: 1,
        badgeColor: 'text-indigo-300',
        bgFill: '#1e1b4b',
        icon: 'alt_route',
      }
    }
    if (type === 'MODULE') {
      return {
        roleCode: 'MOD',
        roleName: 'Module dịch vụ',
        tier: 1,
        badgeColor: 'text-indigo-300',
        bgFill: '#1e1b4b',
        icon: 'alt_route',
      }
    }
    if (type === 'SITE_ROUTER' || code.includes('SRT') || code.includes('RTR') || code.includes('ROUTER')) {
      return {
        roleCode: 'SRT',
        roleName: 'Site Router (Trạm)',
        tier: 2,
        badgeColor: 'text-sky-300',
        bgFill: '#0c2d48',
        icon: 'router',
      }
    }
    if (type === 'GPON_OLT' || code.includes('OLT') || code.includes('XGS')) {
      return {
        roleCode: 'OLT',
        roleName: 'GPON OLT (Truy nhập)',
        tier: 3,
        badgeColor: 'text-amber-300',
        bgFill: '#451a03',
        icon: 'settings_ethernet',
      }
    }
    if (type === 'INSTANCE' || code.includes('HOST') || code.includes('SRV') || /^\d+\.\d+\.\d+\.\d+/.test(code)) {
      return { roleCode: 'HOST', roleName: 'Máy chủ / Host', tier: 2, badgeColor: 'text-emerald-300', bgFill: '#064e3b', icon: 'dns' }
    }
    if (type === 'DATABASE' || code.includes('DATABASE') || code.includes('MYSQL') || code.includes('ORACLE') || code.includes('POSTGRES')) {
      return { roleCode: 'DB', roleName: 'Cơ sở dữ liệu (DB)', tier: 3, badgeColor: 'text-amber-300', bgFill: '#451a03', icon: 'database' }
    }
    if (type === 'STORAGE' || code.includes('STORAGE') || code.includes('VSP') || code.includes('SAN')) {
      return { roleCode: 'SAN', roleName: 'Hạ tầng Lưu trữ (Storage)', tier: 3, badgeColor: 'text-rose-300', bgFill: '#4c0519', icon: 'hard_drive' }
    }
    return { roleCode: 'DEV', roleName: 'Thiết bị mạng', tier: 2, badgeColor: 'text-slate-300', bgFill: '#1e293b', icon: 'memory' }
  }, [isITChain])

  // Build the complete topology graph
  const networkGraph = useMemo(() => {
    const nodes: NetworkNode[] = []
    const edges: NetworkEdge[] = []

    if (activeSubgraph && activeSubgraph.nodes.length > 0) {
      // 1. Render from REAL topology subgraph
      const rawNodes = activeSubgraph.nodes
      const rawEdges = activeSubgraph.edges

      // 1. Map container alarms to individual modules and child modules to services
      const moduleAlarmsMap = new Map<string, Member[]>()
      const serviceChildModules = new Map<string, string[]>()

      rawEdges.forEach(e => {
        if (e.relation.includes('SERVICE_HAS_MODULE')) {
          if (!serviceChildModules.has(e.source)) serviceChildModules.set(e.source, [])
          serviceChildModules.get(e.source)!.push(e.target)
        }
      })

      // Match members to modules using Backend Topology-aware Alarm Entity Resolutions
      members.forEach(m => {
        const resList = m.entity_resolutions || []
        // Look for candidate or verified affected component in entity_resolutions
        const compRes = resList.find(
          r => r.resource_id && (r.entity_role === 'AFFECTED_COMPONENT_CANDIDATE' || r.entity_role === 'MODULE')
        )
        if (compRes?.resource_id) {
          if (!moduleAlarmsMap.has(compRes.resource_id)) moduleAlarmsMap.set(compRes.resource_id, [])
          moduleAlarmsMap.get(compRes.resource_id)!.push(m)
        }
      })

      // Deduplicate INSTANCE nodes: Map multiple instance IDs for the same physical server (e.g. storage.csv vs service_module_server.csv) to a canonical node ID
      const canonicalInstanceMap = new Map<string, string>()
      const seenInstanceIps = new Map<string, typeof rawNodes[0]>()
      const deduplicatedNodes: typeof rawNodes = []

      rawNodes.forEach(n => {
        if (n.type === 'INSTANCE') {
          const cleanIp = n.name.replace(/\/\d+$/, '').trim()
          if (!seenInstanceIps.has(cleanIp)) {
            seenInstanceIps.set(cleanIp, n)
            canonicalInstanceMap.set(n.id, n.id)
            deduplicatedNodes.push(n)
          } else {
            const canonical = seenInstanceIps.get(cleanIp)!
            canonicalInstanceMap.set(n.id, canonical.id)
          }
        } else {
          deduplicatedNodes.push(n)
        }
      })

      // Check if services exist in rawNodes (2-hop has services, 1-hop does not)
      const hasServices = rawNodes.some(n => n.type === 'SERVICE')

      const allInstances = deduplicatedNodes.filter(n => n.type === 'INSTANCE')

      // Modules filter: show modules with alarms or all modules if detail toggle is on
      const allModules = deduplicatedNodes.filter(n => n.type === 'MODULE')
      const modulesWithAlarms = allModules.filter(m => (moduleAlarmsMap.get(m.id) || []).length > 0)
      
      let visibleModules: typeof rawNodes = []
      if (showNeighborsLayer || showModulesDetail) {
        visibleModules = allModules
      } else if (hopDistance === 1 || !hasServices) {
        // In 1-Hop: show the modules with alarms (or top 10 if none have alarms)
        visibleModules = modulesWithAlarms.length > 0 ? modulesWithAlarms : allModules.slice(0, 10)
      } else {
        // In 2-Hop with detail off: modules are collapsed into direct Service <-> Host links
        visibleModules = []
      }

      // Calculate hop distance from seeds for every node in the graph
      const hopDistanceMap = new Map<string, number>()
      deduplicatedNodes.forEach(n => {
        const cleanName = n.name.replace(/\/\d+$/, '').trim()
        if (
          n.is_seed ||
          distinctDevices.some(d => cleanName.includes(d) || d.includes(cleanName)) ||
          (alarmMap.get(cleanName) || []).length > 0
        ) {
          hopDistanceMap.set(n.id, 0)
        }
      })
      const queue = Array.from(hopDistanceMap.keys())
      let head = 0
      while (head < queue.length) {
        const currId = queue[head++]
        const dist = hopDistanceMap.get(currId)!
        rawEdges.forEach(e => {
          const s = canonicalInstanceMap.get(e.source) || e.source
          const t = canonicalInstanceMap.get(e.target) || e.target
          let nextId: string | null = null
          if (s === currId) nextId = t
          else if (t === currId) nextId = s
          if (nextId && !hopDistanceMap.has(nextId)) {
            hopDistanceMap.set(nextId, dist + 1)
            queue.push(nextId)
          }
        })
      }

      // Calculate initial layout coordinates with spacious gap (>=240px)
      // Calculate initial layout coordinates with spacious multi-row grid wrapping
      const placeTier = (list: typeof rawNodes, tierStartY: number, maxPerRow = 5) => {
        const count = list.length
        if (count === 0) return tierStartY

        const rowCount = Math.ceil(count / maxPerRow)
        const rowHeight = 85 // cardHeight (60px) + 25px gap

        for (let r = 0; r < rowCount; r++) {
          const rowNodes = list.slice(r * maxPerRow, (r + 1) * maxPerRow)
          const rowCountItems = rowNodes.length
          const spacing = Math.max(210, Math.min(260, 960 / Math.max(1, rowCountItems)))
          const startX = 500 - ((rowCountItems - 1) * spacing) / 2
          const currentY = tierStartY + r * rowHeight

          rowNodes.forEach((item, idx) => {
            const role = getDeviceRoleInfo(item.name, item.type)
            const cleanName = item.name.replace(/\/\d+$/, '')

            let nodeAlarms: Member[] = []
            if (item.type === 'MODULE') {
              // Module gets its direct container alarm(s)
              nodeAlarms = moduleAlarmsMap.get(item.id) || []
            } else if (item.type === 'SERVICE') {
              // Service aggregates alarms from all its child modules
              const childModIds = serviceChildModules.get(item.id) || []
              const aggregated = new Map<string, Member>()
              childModIds.forEach(modId => {
                (moduleAlarmsMap.get(modId) || []).forEach(m => aggregated.set(m.alarm_id, m))
              })
              nodeAlarms = Array.from(aggregated.values())
            } else if (item.type === 'INSTANCE' || item.type === 'DEVICE' || !item.type) {
              // Host / Router / Device: gets host alarms. If modules are visible, exclude container alarms that are already shown on their respective modules!
              const allHostAlarms = alarmMap.get(cleanName) || alarmMap.get(item.name) || alarmMap.get(item.id) || []
              if (visibleModules.length > 0) {
                const assignedAlarmIds = new Set<string>()
                visibleModules.forEach((modNode: typeof rawNodes[0]) => {
                  (moduleAlarmsMap.get(modNode.id) || []).forEach(m => assignedAlarmIds.add(m.alarm_id))
                })
                nodeAlarms = allHostAlarms.filter(m => !assignedAlarmIds.has(m.alarm_id))
              } else {
                nodeAlarms = allHostAlarms
              }
            } else {
              // Storage or Database: direct alarms if any
              nodeAlarms = alarmMap.get(cleanName) || alarmMap.get(item.name) || alarmMap.get(item.id) || []
            }

            let exactCount = 0
            let candidateCount = 0

            nodeAlarms.forEach(m => {
              const resolutions = m.entity_resolutions || []
              const compRes = resolutions.find(
                r => (r.entity_role === 'AFFECTED_COMPONENT_CANDIDATE' || r.entity_role === 'MODULE') &&
                     r.resource_id === item.id
              )
              if (compRes) {
                if (compRes.status === 'TEXT_MATCH_CANDIDATE') {
                  candidateCount++
                } else {
                  exactCount++
                }
              } else {
                const isCandComp = resolutions.some(
                  r => (r.entity_role === 'AFFECTED_COMPONENT_CANDIDATE' || r.entity_role === 'MODULE') &&
                       r.status === 'TEXT_MATCH_CANDIDATE'
                )

                if (item.type === 'MODULE') {
                  if (isCandComp) candidateCount++
                  else exactCount++
                } else if (item.type === 'SERVICE') {
                  if (isCandComp) candidateCount++
                  else exactCount++
                } else if (item.type === 'INSTANCE' || item.type === 'DEVICE' || !item.type) {
                  if (visibleModules.length === 0 && isCandComp) {
                    candidateCount++
                  } else {
                    exactCount++
                  }
                } else {
                  exactCount++
                }
              }
            })

            const isExactBearer = exactCount > 0
            const isCandidateOnly = candidateCount > 0 && exactCount === 0

            const initX = Math.round(startX + idx * spacing)
            const initY = currentY
            const posX = nodePositions[item.id]?.x ?? initX
            const posY = nodePositions[item.id]?.y ?? initY

            nodes.push({
              id: item.id,
              name: item.name,
              x: posX,
              y: posY,
              tier: role.tier,
              roleCode: role.roleCode,
              roleName: role.roleName,
              alarmCount: nodeAlarms.length,
              exactAlarmCount: exactCount,
              candidateAlarmCount: candidateCount,
              isDominant: cleanName === dominantDevice || item.name === dominantDevice,
              isAlarmBearer: nodeAlarms.length > 0 || item.is_seed,
              isAlarmTerminal: item.is_seed || (item.type !== 'SERVICE' && nodeAlarms.length > 0),
              isExactBearer,
              isCandidateOnly,
              badgeColor: role.badgeColor,
              icon: role.icon,
              alarms: nodeAlarms,
              hopDistance: hopDistanceMap.get(item.id) ?? (item.is_seed ? 0 : 1),
            })
          })
        }

        return tierStartY + rowCount * rowHeight
      }

      if (isITChain) {
        // IT Cloud Stack Profile (Service -> Module -> Host -> Storage/DB)
        const tier0 = deduplicatedNodes.filter(n => n.type === 'SERVICE')
        const tier1 = visibleModules
        const tier2 = allInstances
        const tier3 = deduplicatedNodes.filter(n => n.type === 'STORAGE' || n.type === 'DATABASE')

        let currentY = 80
        if (tier0.length > 0) currentY = placeTier(tier0, currentY, 4) + 60
        if (tier1.length > 0) currentY = placeTier(tier1, currentY, 6) + 60
        if (tier2.length > 0) currentY = placeTier(tier2, currentY, 5) + 60
        if (tier3.length > 0) placeTier(tier3, currentY, 4)
      } else {
        // IP Network Profile: Telecommunications Hierarchy & Hop-Neighborhood Layout!
        const ipCoreNodes = deduplicatedNodes.filter(n => getDeviceRoleInfo(n.name, n.type).roleCode === 'CORE')
        const ipAggNodes = deduplicatedNodes.filter(n => getDeviceRoleInfo(n.name, n.type).roleCode === 'AGG')
        const ipAccessNodes = deduplicatedNodes.filter(n => getDeviceRoleInfo(n.name, n.type).roleCode === 'OLT')
        const ipStationNodes = deduplicatedNodes.filter(n => {
          const r = getDeviceRoleInfo(n.name, n.type).roleCode
          return r !== 'CORE' && r !== 'AGG' && r !== 'OLT'
        })

        const telecomLayers = [
          { list: ipCoreNodes, name: 'CORE' },
          { list: ipAggNodes, name: 'AGG' },
          { list: ipStationNodes, name: 'STATION' },
          { list: ipAccessNodes, name: 'ACCESS' },
        ].filter(l => l.list.length > 0)

        if (telecomLayers.length >= 2) {
          // North-to-South Telecom Hierarchy: Core (top) -> Aggregation -> Site Routers -> Access OLT
          let currentY = 80
          telecomLayers.forEach(layer => {
            currentY = placeTier(layer.list, currentY, 5) + 65
          })
        } else {
          // Hop-Neighborhood layout around Incident Seeds (Seed Routers -> 1-Hop Neighbors -> 2-Hop Ring)
          const seedNodes = deduplicatedNodes.filter(n => (hopDistanceMap.get(n.id) ?? 0) === 0)
          const hop1Nodes = deduplicatedNodes.filter(n => (hopDistanceMap.get(n.id) ?? 0) === 1)
          const hop2Nodes = deduplicatedNodes.filter(n => (hopDistanceMap.get(n.id) ?? 0) >= 2)

          let currentY = 100
          currentY = placeTier(seedNodes, currentY, 4) + 70
          if (hop1Nodes.length > 0) {
            currentY = placeTier(hop1Nodes, currentY, 5) + 70
          }
          if (hopDistance >= 2 && hop2Nodes.length > 0) {
            placeTier(hop2Nodes, currentY, 5)
          }
        }
      }

      const nodeMap = new Map<string, NetworkNode>()
      nodes.forEach(n => nodeMap.set(n.id, n))

      const addedEdgeKeys = new Set<string>()

      if (!showNeighborsLayer && !showModulesDetail && hasServices && visibleModules.length === 0) {
        // 2-Hop collapsed: synthesize direct Service <-> Host links across modules
        const moduleToService = new Map<string, string>()
        const moduleToInstance = new Map<string, string>()

        rawEdges.forEach(e => {
          const src = canonicalInstanceMap.get(e.source) || e.source
          const tgt = canonicalInstanceMap.get(e.target) || e.target
          if (e.relation.includes('SERVICE_HAS_MODULE')) moduleToService.set(tgt, src)
          if (e.relation.includes('MODULE_HAS_INSTANCE')) moduleToInstance.set(src, tgt)
        })

        rawEdges.forEach(e => {
          if (e.relation.includes('MODULE_HAS_INSTANCE')) {
            const src = canonicalInstanceMap.get(e.source) || e.source
            const inst = canonicalInstanceMap.get(e.target) || e.target
            const svc = moduleToService.get(src)
            if (svc && inst) {
              const edgeKey = `${svc}->${inst}`
              if (!addedEdgeKeys.has(edgeKey)) {
                addedEdgeKeys.add(edgeKey)
                const srcNode = nodeMap.get(svc)
                const tgtNode = nodeMap.get(inst)
                if (srcNode && tgtNode) {
                  edges.push({
                    id: `edge-${svc}-${inst}`,
                    sourceId: svc,
                    targetId: inst,
                    sourceX: srcNode.x,
                    sourceY: srcNode.y,
                    targetX: tgtNode.x,
                    targetY: tgtNode.y,
                    label: 'SERVICE_CLUSTER',
                    isAlarmPath: tgtNode.isAlarmBearer,
                    relationType: null,
                    pathHops: 2,
                  })
                }
              }
            }
          }
        })
      }

      // Render all direct edges between nodes present in nodeMap (Host <-> Storage, Host <-> Module, Service <-> Module, Host <-> DB)
      rawEdges.forEach(e => {
        const srcId = canonicalInstanceMap.get(e.source) || e.source
        const tgtId = canonicalInstanceMap.get(e.target) || e.target
        if (srcId === tgtId) return

        const edgeKey = `${srcId}->${tgtId}->${e.relation}`
        if (addedEdgeKeys.has(edgeKey)) return

        const srcNode = nodeMap.get(srcId)
        const tgtNode = nodeMap.get(tgtId)
        if (srcNode && tgtNode) {
          addedEdgeKeys.add(edgeKey)
          let label = e.relation
            .replace('SERVICE_HAS_MODULE', 'MODULE')
            .replace('MODULE_HAS_INSTANCE', 'HOST')
            .replace('INSTANCE_LINKS_STORAGE', 'SAN')
            .replace('DATABASE_LINKS_INSTANCE', 'DATABASE')
            .replace('MODULE_LINKS_DATABASE', 'DB_LINK')
            .replace('DATABASE_LINKS_SERVICE', 'DB_SERVICE')
            .replace('IP_ADJACENCY', 'ADJACENT')

          if (!isITChain) {
            if (label === 'ADJACENT' || label.includes('ADJACENT') || label === 'CONNECTED_TO' || label === 'NONE') {
              label = 'KỀ VẬT LÝ (1-HOP)'
            }
          }

          edges.push({
            id: `edge-${srcId}-${tgtId}-${edges.length}`,
            sourceId: srcId,
            targetId: tgtId,
            sourceX: srcNode.x,
            sourceY: srcNode.y,
            targetX: tgtNode.x,
            targetY: tgtNode.y,
            label,
            isAlarmPath: srcNode.isAlarmBearer || tgtNode.isAlarmBearer,
            relationType: e.relation,
            pathHops: 1,
          })
        }
      })

      return { nodes, edges }
    }

    return { nodes, edges }
  }, [activeSubgraph, showModulesDetail, showNeighborsLayer, isITChain, distinctDevices, nodePositions, dominantDevice, alarmMap, hopDistance, getDeviceRoleInfo, members])

  const hasRenderableSubgraph = effectiveSubgraphState === 'available' && networkGraph.nodes.length > 0
  const pathCards = currentOverviewPathRequest?.payload
  const pathTopology = pathCards?.status === 'READY' ? pathCards.topology : null
  const topologyVersionMatches = Boolean(
    pathCards?.status === 'READY' &&
    pathCards.topology_version &&
    activeSubgraph?.topology_version &&
    pathCards.topology_version === activeSubgraph.topology_version,
  )
  const hasCanonicalPathProjection = Boolean(
    topologyVersionMatches &&
    Array.isArray(pathTopology?.mapped_resources) &&
    Array.isArray(pathTopology?.display_paths) &&
    typeof pathTopology?.display_paths_truncated === 'boolean',
  )
  const canonicalPaths = hasCanonicalPathProjection
    ? pathTopology!.display_paths as EvidenceTopologyPath[]
    : EMPTY_CANONICAL_PATHS
  const canonicalTerminals = hasCanonicalPathProjection
    ? pathTopology!.mapped_resources as string[]
    : EMPTY_CANONICAL_TERMINALS
  const requiredPathHops = canonicalPaths.reduce((maxHops, path) => (
    Number.isInteger(path?.hop_count)
      ? Math.max(maxHops, Math.min(4, path.hop_count))
      : maxHops
  ), 0)
  const recommendedPathHops = Math.min(4, Math.max(hopDistance + 1, requiredPathHops))

  const alarmConnector = useMemo(
    () => buildAlarmConnector(
      networkGraph.nodes.map(node => ({ id: node.id })),
      networkGraph.edges.map(edge => ({
        id: edge.id,
        sourceId: edge.sourceId,
        targetId: edge.targetId,
        relationType: edge.relationType,
      })),
      canonicalTerminals,
      canonicalPaths,
    ),
    [canonicalPaths, canonicalTerminals, networkGraph.edges, networkGraph.nodes],
  )
  const canRenderEvidencePaths = hasCanonicalPathProjection &&
    canonicalPaths.length > 0 &&
    pathTopology?.display_paths_truncated === false &&
    alarmConnector.unrenderedPathCount === 0 &&
    alarmConnector.unrenderedTerminalCount === 0

  const moduleCount = useMemo(
    () => activeSubgraph?.nodes.filter(node => node.type === 'MODULE').length ?? 0,
    [activeSubgraph],
  )

  const focusNodeIds = useMemo(
    () => getFocusNodeIds(selectedDeviceId, networkGraph.edges),
    [selectedDeviceId, networkGraph.edges],
  )
  const displayedNodes = useMemo(() => {
    const layerNodes = showNeighborsLayer || !canRenderEvidencePaths
      ? networkGraph.nodes
      : networkGraph.nodes.filter(node => alarmConnector.nodeIds.has(node.id))
    if (!focusNodeIds) return layerNodes
    return layerNodes.filter(node => focusNodeIds.has(node.id))
  }, [alarmConnector.nodeIds, canRenderEvidencePaths, focusNodeIds, networkGraph.nodes, showNeighborsLayer])

  const displayedNodeIds = useMemo(() => new Set(displayedNodes.map(n => n.id)), [displayedNodes])

  const displayedEdges = useMemo(() => {
    if (!showLinksLayer) return []
    const scopeEdges = showNeighborsLayer || !canRenderEvidencePaths
      ? networkGraph.edges
      : networkGraph.edges.filter(edge => alarmConnector.edgeIds.has(edge.id))
    return scopeEdges.filter(e => {
      if (!displayedNodeIds.has(e.sourceId) || !displayedNodeIds.has(e.targetId)) return false
      if (!focusNodeIds) return true
      return focusNodeIds.has(e.sourceId) && focusNodeIds.has(e.targetId)
    }).map(edge => ({ ...edge, isAlarmConnector: alarmConnector.edgeIds.has(edge.id) }))
  }, [alarmConnector.edgeIds, canRenderEvidencePaths, networkGraph.edges, displayedNodeIds, focusNodeIds, showLinksLayer, showNeighborsLayer])

  const maxSvgHeight = useMemo(() => {
    let maxY = 600
    displayedNodes.forEach(n => {
      if (n.y + 70 > maxY) maxY = n.y + 70
    })
    return Math.max(620, maxY + 20)
  }, [displayedNodes])

  const svgHorizontalBounds = useMemo(() => {
    if (displayedNodes.length === 0) return { minX: 0, width: 1000 }
    const rawMinX = Math.min(...displayedNodes.map(node => node.x)) - 120
    const rawMaxX = Math.max(...displayedNodes.map(node => node.x)) + 120
    const contentWidth = rawMaxX - rawMinX
    const width = Math.max(1000, contentWidth)
    const centerX = (rawMinX + rawMaxX) / 2
    return { minX: centerX - width / 2, width }
  }, [displayedNodes])

  // Mouse handlers for dragging nodes and panning canvas
  const handleNodeMouseDown = (nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const node = displayedNodes.find(n => n.id === nodeId)
    if (!node) return

    setDraggingNode({
      id: nodeId,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      initialNodeX: node.x,
      initialNodeY: node.y,
    })
  }

  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).tagName === 'svg' || (e.target as HTMLElement).id === 'canvas-bg') {
      setIsPanning(true)
      setPanStart({ x: e.clientX, y: e.clientY })
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (draggingNode) {
      const dx = (e.clientX - draggingNode.startMouseX) / zoom
      const dy = (e.clientY - draggingNode.startMouseY) / zoom
      setNodePositions(prev => ({
        ...prev,
        [draggingNode.id]: {
          x: Math.round(draggingNode.initialNodeX + dx),
          y: Math.round(draggingNode.initialNodeY + dy),
        },
      }))
      return
    }

    if (isPanning) {
      const dx = e.clientX - panStart.x
      const dy = e.clientY - panStart.y
      setPan(prev => ({ x: prev.x + dx, y: prev.y + dy }))
      setPanStart({ x: e.clientX, y: e.clientY })
    }
  }

  const handleMouseUp = () => {
    setDraggingNode(null)
    setIsPanning(false)
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.92 : 1.08
    setZoom(z => Math.min(2.5, Math.max(0.4, z * factor)))
  }

  const handleResetView = () => {
    setPan({ x: 0, y: 0 })
    setZoom(1.0)
    setNodePositions({})
    closeNodeFocus()
  }

  return (
    <div className="relative flex flex-col gap-space-md w-full animate-fade-in select-none">
      {/* 1. Header Toolbar */}
      <section className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-sm md:p-space-md shadow-md flex flex-col gap-space-sm lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-space-sm">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-secondary/20 bg-secondary/15 text-secondary md:h-9 md:w-9">
            <span className="material-symbols-outlined text-[20px]">hub</span>
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate font-headline-sm text-sm font-bold text-on-surface">
                Kết nối topology giữa các thiết bị có cảnh báo
              </h2>
              <span className="shrink-0 rounded border border-primary/30 bg-primary-container px-2 py-0.5 text-[10px] font-bold text-on-primary-container">
                {activeProfile}
              </span>
              <InfoTip text="Đường được tô lấy từ path projection của Overview và chỉ xuất hiện khi các cạnh topology gốc cùng relation có trong vùng đang tải. Đây là kết nối cấu trúc, không chứng minh hướng phụ thuộc hay nguyên nhân. Kéo node để sắp xếp, cuộn để zoom." />
            </div>
            <p className="flex min-w-0 items-center gap-2 truncate font-body-sm text-xs text-on-surface-variant">
              <span className="truncate">{displayedNodes.length} node • {displayedEdges.length} liên kết • {totalAlarms} cảnh báo • {activeSubgraph?.requested_seed_count ?? distinctDevices.length} thiết bị đầu vào</span>
              {isLoadingSubgraph && (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-950/60 px-2 py-0.5 text-[11px] font-semibold text-cyan-400 animate-pulse">
                  <span className="material-symbols-outlined text-xs animate-spin">sync</span>
                  <span>Đang tải {hopDistance}-Hop...</span>
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Controls Toolbar */}
        <div className="flex max-w-full flex-wrap items-center justify-start gap-space-xs lg:justify-end">
          {isITChain && !showNeighborsLayer && (
            <button
              type="button"
              onClick={() => setShowModulesDetail(!showModulesDetail)}
              className={`px-space-sm py-1 rounded text-xs font-semibold border transition-all ${
                showModulesDetail
                  ? 'bg-indigo-600/30 text-indigo-200 border-indigo-500/50'
                  : 'bg-[#080d17] text-on-surface-variant border-[#1b273e] hover:bg-[#121c2e]'
              }`}
              title="Xem tất cả các module container trên các máy chủ"
            >
              {showModulesDetail ? 'Thu gọn Modules' : `Modules (${moduleCount})`}
            </button>
          )}

          <div className="flex items-center rounded border border-[#1b273e] bg-[#080d17] p-0.5">
            <button
              type="button"
              onClick={() => setHopDistance(1)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 1 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title="Mở rộng tới 1-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"
            >
              1-Hop
            </button>
            <button
              type="button"
              onClick={() => setHopDistance(2)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 2 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title="Mở rộng tới 2-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"
            >
              2-Hop
            </button>
            <button
              type="button"
              onClick={() => setHopDistance(3)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 3 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title="Mở rộng tới 3-Hop quanh từng thiết bị alarm; chỉ path backend mới là bằng chứng đường nối"
            >
              3-Hop
            </button>
            <button
              type="button"
              onClick={() => setHopDistance(4)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 4 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title="Mở rộng tới 4-Hop quanh từng thiết bị alarm; giới hạn node có thể làm vùng topology bị cắt"
            >
              4-Hop
            </button>
          </div>

          <div className="flex items-center gap-1 bg-[#080d17] border border-[#1b273e] rounded p-0.5 ml-2">
            <button
              type="button"
              title="Phóng to"
              onClick={() => setZoom(z => Math.min(2.5, z * 1.15))}
              className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-[#1b273e] rounded"
            >
              <span className="material-symbols-outlined text-[16px]">zoom_in</span>
            </button>
            <button
              type="button"
              title="Thu nhỏ"
              onClick={() => setZoom(z => Math.max(0.4, z * 0.85))}
              className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-[#1b273e] rounded"
            >
              <span className="material-symbols-outlined text-[16px]">zoom_out</span>
            </button>
            <button
              type="button"
              title="Căn giữa đồ thị"
              onClick={handleResetView}
              className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-[#1b273e] rounded"
            >
              <span className="material-symbols-outlined text-[16px]">crop_free</span>
            </button>
          </div>
        </div>
      </section>

      {/* Loading State when topologyPayload is explicitly null */}
      {topologyPayload === null ? (
        <section
          role="status"
          aria-live="polite"
          className="p-space-xl bg-[#0c1424] border border-[#1b273e] rounded-xl flex items-center justify-center gap-space-sm text-on-surface-variant text-sm shadow-md"
        >
          <span
            aria-hidden="true"
            className="w-4 h-4 rounded-full border-2 border-primary border-t-transparent animate-spin"
          />
          Loading topology projection…
        </section>
      ) : (
        <>
          {isLoadingSubgraph ? (
            <section
              role="status"
              aria-live="polite"
              className="p-space-xl bg-[#0c1424] border border-[#1b273e] rounded-xl flex items-center justify-center gap-space-sm text-on-surface-variant text-sm shadow-md"
            >
              <span aria-hidden="true" className="w-4 h-4 rounded-full border-2 border-secondary border-t-transparent animate-spin" />
              Đang tải topology thật {hopDistance}-Hop…
            </section>
          ) : !hasRenderableSubgraph ? (
            <section
              role="status"
              aria-live="polite"
              className="p-space-xl bg-[#0c1424] border border-[#1b273e] rounded-xl flex flex-col items-center justify-center gap-space-sm text-center text-sm shadow-md"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-3xl text-on-surface-variant">cloud_off</span>
              <span className="font-semibold text-on-surface">Chưa có dữ liệu topology</span>
              <span className="max-w-2xl text-xs text-on-surface-variant">
                {effectiveSubgraphState === 'error'
                  ? `Không thể tải subgraph hiện hành${subgraphError ? `: ${subgraphError}` : '.'}`
                  : activeSubgraph?.reason
                    ? `Nguồn topology báo trạng thái ${activeSubgraph.reason}.`
                    : 'Không tìm thấy node topology đã ingest cho các seed hiện tại.'}
                {' '}Hệ thống không dựng node hoặc liên kết suy diễn.
              </span>
            </section>
          ) : (
            <>
              {activeSubgraph?.truncated && (
                <section
                  role="status"
                  className="rounded-xl border border-amber-500/40 bg-amber-950/30 px-space-md py-space-sm text-xs text-amber-100 shadow-sm"
                >
                  <span className="font-bold">Topology đang được hiển thị có giới hạn.</span>{' '}
                  Đã phân giải {activeSubgraph.resolved_seed_count ?? 0}/{activeSubgraph.requested_seed_count ?? distinctDevices.length} seed
                  và giữ {activeSubgraph.retained_seed_count ?? 0}/{activeSubgraph.resolved_seed_count ?? 0} seed đã phân giải;
                  một số node hoặc liên kết có thể chưa xuất hiện.
                </section>
              )}

              {/* Main Interactive Neo4j-style Canvas */}
              <div className="w-full flex flex-col bg-[#0c1424] rounded-xl border border-[#1b273e] shadow-md overflow-hidden h-[680px] relative">
            {/* Header info bar: Title and LỚP HIỂN THỊ on the SAME row */}
            <div className="min-h-10 px-space-md py-1.5 bg-[#080d17] border-b border-[#1b273e] flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[18px]">device_hub</span>
                <span className="font-headline-md text-xs font-bold text-on-surface">
                  Đường nối topology giữa các thiết bị alarm
                </span>
                <span className="text-[11px] text-on-surface-variant hidden xl:inline">
                  (Click và kéo để di chuyển node)
                </span>
              </div>

              {/* LỚP HIỂN THỊ Controls on the same row */}
              <div className="flex items-center gap-2 font-code-sm text-xs flex-wrap">
                <span className="font-label-caps text-[11px] uppercase text-[#ffb4a2] font-bold tracking-wider mr-0.5">
                  PHẠM VI:
                </span>

                {/* Huy hiệu Cảnh báo */}
                <button
                  type="button"
                  onClick={() => setShowAlarmsLayer(!showAlarmsLayer)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-code-sm transition-colors cursor-pointer ${
                    showAlarmsLayer
                      ? 'bg-[#132238] text-[#8bc4ff] border-[#243754]'
                      : 'bg-[#080d17] text-on-surface-variant/60 border-[#1b273e] hover:bg-[#121c2e]'
                  }`}
                  title="Bật/tắt huy hiệu cảnh báo"
                >
                  <span className="material-symbols-outlined text-[15px]">
                    {showAlarmsLayer ? 'check_box' : 'check_box_outline_blank'}
                  </span>
                  <span>Huy hiệu Cảnh báo ({totalAlarms})</span>
                </button>

                {/* Tuyến liên kết */}
                <button
                  type="button"
                  onClick={() => setShowLinksLayer(!showLinksLayer)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-code-sm transition-colors cursor-pointer ${
                    showLinksLayer
                      ? 'bg-[#132238] text-[#8bc4ff] border-[#243754]'
                      : 'bg-[#080d17] text-on-surface-variant/60 border-[#1b273e] hover:bg-[#121c2e]'
                  }`}
                  title="Bật/tắt tuyến liên kết"
                >
                  <span className="material-symbols-outlined text-[15px]">
                    {showLinksLayer ? 'check_box' : 'check_box_outline_blank'}
                  </span>
                  <span>
                    Tuyến liên kết {isITChain ? 'IT_SERVICE' : 'IP_ADJACENCY'}
                  </span>
                </button>

                {canRenderEvidencePaths && (
                  <button
                    type="button"
                    onClick={() => {
                      closeNodeFocus()
                      setShowNeighborsLayer(current => !current)
                    }}
                    aria-pressed={showNeighborsLayer}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-code-sm transition-colors cursor-pointer ${
                      showNeighborsLayer
                        ? 'bg-[#132238] text-[#8bc4ff] border-[#243754]'
                        : 'bg-secondary/15 text-secondary border-secondary/40 hover:bg-secondary/20'
                    }`}
                    title={showNeighborsLayer
                      ? 'Chỉ hiển thị các đường backend đã tính trong Overview'
                      : 'Mở toàn bộ topology đã tải, gồm cả các cạnh ngoài đường bằng chứng'}
                  >
                    <span className="material-symbols-outlined text-[15px]">
                      {showNeighborsLayer ? 'account_tree' : 'route'}
                    </span>
                    <span>{showNeighborsLayer
                      ? `Toàn bộ topology (${networkGraph.nodes.length} node)`
                      : `Đường evidence (${alarmConnector.nodeIds.size} node)`}</span>
                  </button>
                )}
              </div>
            </div>

            <div
              role="status"
              aria-live="polite"
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[#1b273e] bg-[#0a1220] px-space-md py-1.5 text-[11px] text-on-surface-variant"
            >
              {canRenderEvidencePaths ? (
                <>
                  <span className="font-semibold text-on-surface">
                    {alarmConnector.terminalCount === 0
                      ? 'Không có resource đã mapping nằm trong topology đang tải.'
                      : `${alarmConnector.linkedTerminalCount}/${alarmConnector.terminalCount} resource được nối bằng các đường Overview; ${alarmConnector.componentCount} nhóm.`}
                  </span>
                  {alarmConnector.maxConnectionHops > 0 && (
                    <span>Đường backend dài nhất đang hiển thị: {alarmConnector.maxConnectionHops} hop</span>
                  )}
                  {!showNeighborsLayer && networkGraph.nodes.length > alarmConnector.nodeIds.size && (
                    <span>{networkGraph.nodes.length - alarmConnector.nodeIds.size} node ngoài đường bằng chứng đang thu gọn</span>
                  )}
                </>
              ) : (
                <span className="font-semibold text-amber-200">
                  {alarmConnector.unrenderedPathCount > 0 || alarmConnector.unrenderedTerminalCount > 0
                    ? pathTopology?.display_paths_truncated
                      ? 'Display forest của Overview đã chạm giới hạn 100 đường đại diện; tạm hiển thị toàn bộ topology đã tải, nên chưa thể xác nhận toàn bộ path evidence.'
                      : activeSubgraph?.truncated
                      ? `Topology ${hopDistance}-Hop bị cắt (${(activeSubgraph.truncation_reasons ?? []).join(', ') || 'giới hạn tải'}); chưa đủ dữ liệu để vẽ ${alarmConnector.unrenderedPathCount} đường Overview. Đang hiển thị toàn bộ phần đã tải, không tự tính đường thay thế.`
                      : alarmConnector.missingPathNodeCount > 0
                        ? `Thiếu ${alarmConnector.missingPathNodeCount} node thuộc path Overview trong vùng ${hopDistance}-Hop đang tải; tạm hiển thị toàn bộ topology đã tải.`
                        : alarmConnector.missingPathEdgeCount > 0
                          ? `Thiếu ${alarmConnector.missingPathEdgeCount} cạnh topology gốc khớp path Overview; tạm hiển thị toàn bộ topology đã tải, không tự tính đường thay thế.`
                          : alarmConnector.invalidPathCount > 0
                            ? 'Path projection của Overview có dữ liệu không hợp lệ; tạm hiển thị toàn bộ topology đã tải.'
                            : `Có ${alarmConnector.unrenderedPathCount} đường hoặc ${alarmConnector.unrenderedTerminalCount} resource không nằm đầy đủ trong vùng ${hopDistance}-Hop; đang hiển thị toàn bộ topology đã tải, không tự tính đường thay thế.`
                    : pathCards?.status === 'PENDING'
                      ? 'Đang chờ path projection của Overview; tạm hiển thị toàn bộ topology đã tải.'
                    : pathCards?.status === 'READY' && !topologyVersionMatches
                        ? 'Topology version của graph và Overview không trùng; tạm hiển thị toàn bộ topology đã tải.'
                        : pathTopology?.display_paths_truncated
                          ? 'Display forest của Overview đã chạm giới hạn 100 đường đại diện; tạm hiển thị toàn bộ topology đã tải để tránh trình bày path thiếu.'
                        : hasCanonicalPathProjection && canonicalPaths.length === 0
                          ? 'Overview không ghi nhận cặp resource nào có đường transit trong giới hạn 4 hop; điều này không chứng minh topology ngoài vùng đã tải không kết nối.'
                        : pathCards?.status === 'READY' && topologyVersionMatches
                          ? 'Overview chưa có path projection hợp lệ; tạm hiển thị toàn bộ topology đã tải.'
                        : pathCards?.status === 'UNAVAILABLE'
                          ? 'Overview chưa có path projection khả dụng; tạm hiển thị toàn bộ topology đã tải.'
                          : currentOverviewPathRequest?.error
                            ? 'Không tải được path projection của Overview; tạm hiển thị toàn bộ topology đã tải.'
                            : 'Đang tải path projection của Overview; tạm hiển thị toàn bộ topology đã tải.'}
                </span>
              )}
              <span className="text-on-surface-variant/80">
                {hopDistance}-Hop là vùng topology hiện tải; việc chưa vẽ được một path không phủ định khả năng có đường ngoài vùng đó.
              </span>
              {!canRenderEvidencePaths &&
                hasCanonicalPathProjection &&
                pathTopology?.display_paths_truncated === false &&
                alarmConnector.missingPathNodeCount > 0 &&
                !activeSubgraph?.truncated &&
                hopDistance < 4 && (
                  <button
                    type="button"
                    onClick={() => {
                      closeNodeFocus()
                      setHopDistance(recommendedPathHops)
                    }}
                    className="rounded border border-cyan-700/50 bg-cyan-950/40 px-2 py-1 text-cyan-200 hover:bg-cyan-900/50"
                  >
                    Tải vùng {recommendedPathHops}-Hop để lấy đủ node path
                  </button>
                )}
            </div>

            {/* SVG Canvas Area */}
            <div
              ref={setCanvasElement}
              id="canvas-bg"
              className="relative flex-1 bg-[#070e1d] overflow-hidden cursor-grab active:cursor-grabbing"
              onMouseDown={handleCanvasMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onWheel={handleWheel}
            >
              {/* Subtle Dot Grid */}
              <div className="absolute inset-0 opacity-20 pointer-events-none bg-[radial-gradient(#3a4f73_1px,transparent_1px)] [background-size:24px_24px]" />

              {/* Floating Status Indicator */}
              {isLoadingSubgraph && (
                <div className="absolute top-3 right-3 z-30 flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#091326]/90 border border-cyan-500/40 text-cyan-300 text-xs shadow-xl backdrop-blur-sm pointer-events-none animate-fadeIn">
                  <span className="material-symbols-outlined text-sm animate-spin text-cyan-400">sync</span>
                  <span className="font-medium">Đang mở rộng láng giềng {hopDistance}-Hop...</span>
                </div>
              )}

              <svg
                ref={svgRef}
                className="w-full h-full"
                viewBox={`${svgHorizontalBounds.minX} 0 ${svgHorizontalBounds.width} ${maxSvgHeight}`}
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <defs>
                  <filter id="glow-cyan" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="5" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="glow-coral" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="5" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="glow-amber" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="glow-purple" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="5" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>

                {/* Transformable Canvas Layer (Pan & Zoom) */}
                <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
                  {showLinksLayer &&
                    displayedEdges.map(edge => {
                      const startX = edge.sourceX
                      const startY = edge.sourceY
                      const endX = edge.targetX
                      const endY = edge.targetY
                      const midX = (startX + endX) / 2
                      const midY = (startY + endY) / 2
                      const isHovered = hoveredEdgeId === edge.id
                      const canOpenEvidenceForEdge = Boolean(edge.isAlarmConnector && edge.relationType)
                      const edgeDescription = edge.label === 'SERVICE_CLUSTER'
                        ? 'Service–Host qua module đã thu gọn (2 hop)'
                        : edge.label

                      // Cubic bezier smooth curve. Relation text is intentionally
                      // rendered only for the edge currently under the pointer.
                      const dy = endY - startY
                      const pathD = `M ${startX} ${startY} C ${startX} ${startY + dy * 0.5}, ${endX} ${endY - dy * 0.5}, ${endX} ${endY}`
                      const isPhysicalAdjacency = edge.label.includes('KỀ VẬT LÝ')
                      const edgeColor = edge.isAlarmConnector
                        ? '#67e8f9'
                        : isPhysicalAdjacency
                        ? (edge.isAlarmPath ? '#38bdf8' : '#0284c7')
                        : edge.label === 'SAN'
                        ? '#f43f5e'
                        : edge.label === 'DATABASE' || edge.label === 'DB_LINK'
                        ? '#f59e0b'
                        : edge.isAlarmPath
                        ? '#38bdf8'
                        : '#64748b'
                      const edgeWidth = edge.isAlarmConnector
                        ? '2.2'
                        : isPhysicalAdjacency
                        ? (edge.isAlarmPath ? '2' : '1.4')
                        : edge.label === 'SAN' || edge.label === 'DATABASE'
                        ? '1.7'
                        : edge.isAlarmPath ? '1.8' : '1.2'
                      const labelWidth = Math.max(76, edgeDescription.length * 6.5 + 16)

                      return (
                        <g
                          key={edge.id}
                          data-testid={`topology-edge-${edge.id}`}
                          role={canOpenEvidenceForEdge ? 'button' : undefined}
                          tabIndex={canOpenEvidenceForEdge ? 0 : undefined}
                          aria-label={edgeDescription}
                          aria-description={canOpenEvidenceForEdge
                            ? `Mở evidence của cạnh ${edge.sourceId} đến ${edge.targetId}, ${edge.relationType}`
                            : undefined}
                          aria-haspopup={canOpenEvidenceForEdge ? 'dialog' : undefined}
                          onClick={canOpenEvidenceForEdge ? () => {
                            setEvidencePathSelector({
                              resource_a: edge.sourceId,
                              resource_b: edge.targetId,
                              relation_type: edge.relationType!,
                            })
                            setEvidenceDetailsOpen(true)
                          } : undefined}
                          onKeyDown={canOpenEvidenceForEdge ? event => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              setEvidencePathSelector({
                                resource_a: edge.sourceId,
                                resource_b: edge.targetId,
                                relation_type: edge.relationType!,
                              })
                              setEvidenceDetailsOpen(true)
                            }
                          } : undefined}
                          onMouseEnter={() => setHoveredEdgeSelection({ requestKey: subgraphRequestKey, value: edge.id })}
                          onMouseLeave={() => setHoveredEdgeSelection(null)}
                        >
                          <path
                            d={pathD}
                            stroke={edgeColor}
                            strokeWidth={edgeWidth}
                            strokeDasharray={edge.isAlarmConnector || edge.isAlarmPath || isPhysicalAdjacency ? undefined : '5 4'}
                            opacity={focusNodeIds ? 0.9 : edge.isAlarmConnector ? 0.82 : edge.isAlarmPath ? 0.5 : 0.24}
                            fill="none"
                            pointerEvents="stroke"
                          />
                          <path
                            d={pathD}
                            stroke="transparent"
                            strokeWidth="12"
                            fill="none"
                            pointerEvents="stroke"
                          />
                          {isHovered && (
                            <g pointerEvents="none">
                              <rect
                                x={midX - labelWidth / 2}
                                y={midY - 9}
                                width={labelWidth}
                                height="18"
                                rx="4"
                                fill="#070e1d"
                                stroke={isPhysicalAdjacency ? '#0284c7' : edgeColor}
                                strokeWidth="1"
                                opacity="0.98"
                              />
                              <text
                                x={midX}
                                y={midY + 3.5}
                                fill={isPhysicalAdjacency ? '#38bdf8' : edgeColor}
                                fontFamily="JetBrains Mono"
                                fontSize="8.5"
                                fontWeight="700"
                                textAnchor="middle"
                              >
                                {edgeDescription}
                              </text>
                            </g>
                          )}
                        </g>
                      )
                    })}

                  {/* NODES LAYER */}
                  {displayedNodes.map(node => {
                    const isSelected = activeDevice === node.id || activeDevice === node.name
                    const cardWidth = 186
                    const cardHeight = 62
                    const cardX = node.x - cardWidth / 2
                    const cardY = node.y - cardHeight / 2

                    return (
                      <g
                        key={`node-${node.id}`}
                        className="cursor-pointer"
                        onMouseDown={e => handleNodeMouseDown(node.id, e)}
                        onClick={() => {
                          setSelectedDeviceSelection({ requestKey: subgraphRequestKey, value: node.id })
                          setSummaryNodeSelection({ requestKey: subgraphRequestKey, value: node })
                          setAlarmFilter('ALL')
                        }}
                      >
                        <title>{`${node.name} (${node.roleName})\nTổng cảnh báo: ${node.alarmCount} (🔴 Xác thực: ${node.exactAlarmCount}, 🟣 Suy đoán: ${node.candidateAlarmCount})\n[Click để mở bảng tóm tắt chi tiết]${
                          node.alarms.length > 0
                            ? '\n-- Entity Resolutions --\n' +
                              node.alarms
                                .map(a => {
                                  const comp = (a.entity_resolutions || []).find(
                                    r => r.resource_id === node.id || (r.candidate_resource_ids || []).includes(node.id)
                                  )
                                  if (comp) {
                                    return `• ${a.alarm_name || a.alarm_id}: [${comp.status}] ${comp.matched_text || comp.raw_value} via ${comp.source_field} (${Math.round((comp.confidence || 0) * 100)}%)`
                                  }
                                  return `• ${a.alarm_name || a.alarm_id}`
                                })
                                .join('\n')
                            : ''
                        }`}</title>
                        {/* Halo glow if selected, exact bearer (red), or candidate only (purple) */}
                        {isSelected ? (
                          <rect
                            x={cardX - 5}
                            y={cardY - 5}
                            width={cardWidth + 10}
                            height={cardHeight + 10}
                            rx="10"
                            fill="#38bdf8"
                            fillOpacity="0.18"
                            className="animate-pulse pointer-events-none"
                          />
                        ) : node.isExactBearer ? (
                          <rect
                            x={cardX - 5}
                            y={cardY - 5}
                            width={cardWidth + 10}
                            height={cardHeight + 10}
                            rx="10"
                            fill="#ef4444"
                            fillOpacity="0.16"
                            className="animate-pulse pointer-events-none"
                          />
                        ) : node.isCandidateOnly ? (
                          <rect
                            x={cardX - 5}
                            y={cardY - 5}
                            width={cardWidth + 10}
                            height={cardHeight + 10}
                            rx="10"
                            fill="#a855f7"
                            fillOpacity="0.18"
                            className="animate-pulse pointer-events-none"
                          />
                        ) : null}

                        {/* Node Card Box: RED for Host/Exact, PURPLE for Candidate Module Regex */}
                        <rect
                          x={cardX}
                          y={cardY}
                          width={cardWidth}
                          height={cardHeight}
                          rx="8"
                          fill={isSelected ? '#12233f' : node.isExactBearer ? '#180d14' : node.isCandidateOnly ? '#150d24' : '#080e1a'}
                          stroke={
                            isSelected
                              ? '#38bdf8'
                              : node.isExactBearer
                              ? '#ef4444' // ĐỎ cho lỗi Host / Lỗi xác thực
                              : node.isCandidateOnly
                              ? '#a855f7' // TÍM cho lỗi suy đoán Module qua Regex
                              : node.tier === 3
                              ? (node.roleCode === 'SAN' ? '#e11d48' : '#d97706')
                              : '#1e293b'
                          }
                          strokeWidth={isSelected ? '2.4' : (node.isExactBearer || node.isCandidateOnly) ? '2' : '1.2'}
                          strokeDasharray={node.isCandidateOnly ? '5 3' : undefined}
                          filter={isSelected ? 'url(#glow-cyan)' : node.isExactBearer ? 'url(#glow-coral)' : node.isCandidateOnly ? 'url(#glow-purple)' : undefined}
                        />

                        {/* Icon/Tier badge */}
                        <rect
                          x={cardX + 10}
                          y={node.y - 17}
                          width="36"
                          height="34"
                          rx="6"
                          fill={
                            node.roleCode === 'SRT'
                              ? '#0c2d48'
                              : node.tier === 0
                              ? '#083344'
                              : node.tier === 1
                              ? '#1e1b4b'
                              : node.tier === 3
                              ? (node.roleCode === 'SAN' ? '#4c0519' : '#451a03')
                              : '#064e3b'
                          }
                          stroke="#334155"
                          strokeWidth="1"
                        />
                        <text
                          x={cardX + 28}
                          y={node.y + 4}
                          fill={
                            node.roleCode === 'SRT'
                              ? '#38bdf8'
                              : node.tier === 0
                              ? '#22d3ee'
                              : node.tier === 1
                              ? '#818cf8'
                              : node.tier === 3
                              ? (node.roleCode === 'SAN' ? '#fb7185' : '#f59e0b')
                              : '#34d399'
                          }
                          fontFamily="JetBrains Mono"
                          fontSize="9.5"
                          fontWeight="800"
                          textAnchor="middle"
                        >
                          {node.roleCode}
                        </text>

                        {/* Device / Service Name */}
                        <text
                          x={cardX + 54}
                          y={node.y - 4}
                          fill="#ffffff"
                          fontFamily="JetBrains Mono"
                          fontSize="10"
                          fontWeight="700"
                        >
                          {node.name.length > 15 ? `${node.name.slice(0, 14)}…` : node.name}
                        </text>

                        {/* Role / Type description + Hop Proximity */}
                        <text
                          x={cardX + 54}
                          y={node.y + 11}
                          fill={node.isAlarmBearer ? '#94a3b8' : '#64748b'}
                          fontFamily="JetBrains Mono"
                          fontSize="8"
                          fontWeight="500"
                        >
                          {!isITChain
                            ? `${node.roleName} · ${node.hopDistance === 0 ? 'Seed' : `${node.hopDistance}-Hop`}`
                            : node.roleName}
                        </text>

                        {/* Alarm count badge */}
                        {showAlarmsLayer && (
                          <g transform={`translate(${cardX + cardWidth - 12}, ${cardY - 2})`}>
                            {node.exactAlarmCount > 0 && node.candidateAlarmCount > 0 ? (
                              <g>
                                {/* Exact Red Badge */}
                                <rect
                                  x="-82"
                                  y="-10"
                                  width="40"
                                  height="20"
                                  rx="10"
                                  fill="#ef4444"
                                  stroke="#080d17"
                                  strokeWidth="1.5"
                                  filter="url(#glow-coral)"
                                />
                                <text
                                  x="-62"
                                  y="3.5"
                                  fill="#ffffff"
                                  fontFamily="JetBrains Mono"
                                  fontSize="8.5"
                                  fontWeight="800"
                                  textAnchor="middle"
                                >
                                  {`🚨 ${node.exactAlarmCount}`}
                                </text>

                                {/* Candidate Purple Badge */}
                                <rect
                                  x="-38"
                                  y="-10"
                                  width="40"
                                  height="20"
                                  rx="10"
                                  fill="#a855f7"
                                  stroke="#080d17"
                                  strokeWidth="1.5"
                                  filter="url(#glow-purple)"
                                />
                                <text
                                  x="-18"
                                  y="3.5"
                                  fill="#ffffff"
                                  fontFamily="JetBrains Mono"
                                  fontSize="8.5"
                                  fontWeight="800"
                                  textAnchor="middle"
                                >
                                  {`🟣 ${node.candidateAlarmCount}`}
                                </text>
                              </g>
                            ) : node.exactAlarmCount > 0 ? (
                              <g>
                                <rect
                                  x="-44"
                                  y="-10"
                                  width="52"
                                  height="20"
                                  rx="10"
                                  fill="#ef4444"
                                  stroke="#080d17"
                                  strokeWidth="1.5"
                                  filter="url(#glow-coral)"
                                />
                                <text
                                  x="-18"
                                  y="3.5"
                                  fill="#ffffff"
                                  fontFamily="JetBrains Mono"
                                  fontSize="9"
                                  fontWeight="800"
                                  textAnchor="middle"
                                >
                                  {`🚨 ${node.exactAlarmCount}`}
                                </text>
                              </g>
                            ) : node.candidateAlarmCount > 0 ? (
                              <g>
                                <rect
                                  x="-44"
                                  y="-10"
                                  width="52"
                                  height="20"
                                  rx="10"
                                  fill="#a855f7"
                                  stroke="#080d17"
                                  strokeWidth="1.5"
                                  filter="url(#glow-purple)"
                                />
                                <text
                                  x="-18"
                                  y="3.5"
                                  fill="#ffffff"
                                  fontFamily="JetBrains Mono"
                                  fontSize="9"
                                  fontWeight="800"
                                  textAnchor="middle"
                                >
                                  {`🟣 ${node.candidateAlarmCount}`}
                                </text>
                              </g>
                            ) : null}
                          </g>
                        )}

                        {/* Status pill: Candidate vs Exact */}
                        {node.isCandidateOnly ? (
                          <g transform={`translate(${cardX + cardWidth - 84}, ${cardY + cardHeight - 14})`}>
                            <rect
                              x="0"
                              y="0"
                              width="78"
                              height="12"
                              rx="3"
                              fill="#2e1065"
                              stroke="#a855f7"
                              strokeWidth="0.8"
                            />
                            <text
                              x="39"
                              y="8.5"
                              fill="#e9d5ff"
                              fontFamily="JetBrains Mono"
                              fontSize="6.5"
                              fontWeight="700"
                              textAnchor="middle"
                            >
                              🟣 CANDIDATE
                            </text>
                          </g>
                        ) : node.isExactBearer && node.candidateAlarmCount > 0 ? (
                          <g transform={`translate(${cardX + cardWidth - 92}, ${cardY + cardHeight - 14})`}>
                            <rect
                              x="0"
                              y="0"
                              width="86"
                              height="12"
                              rx="3"
                              fill="#1f1127"
                              stroke="#c084fc"
                              strokeWidth="0.8"
                            />
                            <text
                              x="43"
                              y="8.5"
                              fill="#f5d0fe"
                              fontFamily="JetBrains Mono"
                              fontSize="6.5"
                              fontWeight="700"
                              textAnchor="middle"
                            >
                              🔴 EXACT + 🟣 CAND
                            </text>
                          </g>
                        ) : node.isExactBearer ? (
                          <g transform={`translate(${cardX + cardWidth - 76}, ${cardY + cardHeight - 14})`}>
                            <rect
                              x="0"
                              y="0"
                              width="70"
                              height="12"
                              rx="3"
                              fill="#450a0a"
                              stroke="#ef4444"
                              strokeWidth="0.8"
                            />
                            <text
                              x="35"
                              y="8.5"
                              fill="#fca5a5"
                              fontFamily="JetBrains Mono"
                              fontSize="6.5"
                              fontWeight="700"
                              textAnchor="middle"
                            >
                              {isITChain ? '🔴 EXACT HOST' : '🔴 GỐC SỰ CỐ'}
                            </text>
                          </g>
                        ) : !isITChain && (node.hopDistance ?? 0) > 0 ? (
                          <g transform={`translate(${cardX + cardWidth - 76}, ${cardY + cardHeight - 14})`}>
                            <rect
                              x="0"
                              y="0"
                              width="70"
                              height="12"
                              rx="3"
                              fill="#082f49"
                              stroke="#0284c7"
                              strokeWidth="0.8"
                            />
                            <text
                              x="35"
                              y="8.5"
                              fill="#bae6fd"
                              fontFamily="JetBrains Mono"
                              fontSize="6.5"
                              fontWeight="700"
                              textAnchor="middle"
                            >
                              {node.hopDistance === 1 ? '🔗 1-HOP KỀ' : `🌐 ${node.hopDistance}-HOP`}
                            </text>
                          </g>
                        ) : null}
                      </g>
                    )
                  })}
                </g>
              </svg>

              {/* Legend overlay */}
              <div className="absolute bottom-3 left-3 bg-[#080d17]/95 backdrop-blur-md p-2.5 rounded-lg border border-[#1b273e] font-code-sm text-[11px] shadow-lg flex flex-col gap-1.5 max-w-xs pointer-events-none">
                <span className="font-label-caps text-[9px] uppercase text-on-surface-variant font-bold tracking-wider">
                  CHÚ THÍCH {isITChain ? 'HẠ TẦNG CLOUD IT' : 'MẠNG TRUYỀN DẪN IP'}
                </span>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-on-surface text-[10px]">
                  <div className="flex items-center gap-1.5">
                    <span className="w-5 border-t-2 border-cyan-300 shrink-0" />
                    <span>Đường nối alarm (đại diện)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-red-500 shrink-0" />
                    <span>{isITChain ? '🚨 Xác thực (Exact Host)' : '🚨 Thiết bị sự cố (Gốc)'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-purple-500 shrink-0" />
                    <span>{isITChain ? '🟣 Suy đoán (Candidate)' : '🟣 Cảnh báo suy đoán'}</span>
                  </div>
                  {isITChain ? (
                    <>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/40 font-bold text-[8px]">CORE</span>
                        <span>IT Service lõi</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-500/40 font-bold text-[8px]">MOD</span>
                        <span>Module Container</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/40 font-bold text-[8px]">HOST</span>
                        <span>Máy chủ / Host</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-500/40 font-bold text-[8px]">SAN</span>
                        <span>Lưu trữ SAN / DB</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/40 font-bold text-[8px]">CORE</span>
                        <span>Core Router (Lõi)</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-500/40 font-bold text-[8px]">AGG</span>
                        <span>Aggregation (PE)</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-sky-950 text-sky-300 border border-sky-500/40 font-bold text-[8px]">SRT</span>
                        <span>Site Router (Trạm)</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="px-1 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-500/40 font-bold text-[8px]">OLT</span>
                        <span>GPON OLT (Quang)</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
              </div>
            </>
          )}

        </>
      )}

      {/* ===== FIXED NODE ALARM PANEL ===== */}
      {summaryNode !== null && canvasElement !== null && createPortal((() => {
        const node = summaryNode
        const isExact = (m: Member) => {
          const resolutions = m.entity_resolutions || []
          const compRes = resolutions.find(
            r => (r.entity_role === 'AFFECTED_COMPONENT_CANDIDATE' || r.entity_role === 'MODULE') &&
                 (r.resource_id === node.id || (r.candidate_resource_ids || []).includes(node.id))
          )
          if (compRes) return compRes.status !== 'TEXT_MATCH_CANDIDATE'
          return !resolutions.some(
            r => (r.entity_role === 'AFFECTED_COMPONENT_CANDIDATE' || r.entity_role === 'MODULE') &&
                 r.status === 'TEXT_MATCH_CANDIDATE'
          )
        }

        const exactAlarms = node.alarms.filter(m => isExact(m))
        const candidateAlarms = node.alarms.filter(m => !isExact(m))

        const displayedAlarms =
          alarmFilter === 'EXACT' ? exactAlarms
          : alarmFilter === 'CANDIDATE' ? candidateAlarms
          : node.alarms

        const hopLabel = compactHopLabel(node.hopDistance)

        return (
          <div
            className="absolute right-4 top-4 z-40 flex max-h-[calc(100%_-_2rem)] w-[calc(100%_-_2rem)] max-w-[360px] flex-col overflow-hidden rounded-2xl border border-[#1e2e4a] bg-[#090f1d]/98 text-on-surface shadow-[0_25px_60px_-15px_rgba(0,0,0,0.95)]"
            onClick={closeNodeFocus}
            role="dialog"
            aria-labelledby="node-summary-title"
          >
            <div
              className="flex min-h-0 flex-1 flex-col overflow-hidden"
              onClick={e => e.stopPropagation()}
            >
              {/* Fixed panel header */}
              <header className="flex items-center justify-between border-b border-[#182640] bg-[#0c1424] px-5 py-3 shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`w-3 h-3 rounded-full shrink-0 ${
                      node.isExactBearer && node.candidateAlarmCount > 0
                        ? 'bg-gradient-to-br from-red-500 to-purple-500'
                        : node.isExactBearer
                        ? 'bg-red-500'
                        : node.isCandidateOnly
                        ? 'bg-purple-500'
                        : 'bg-emerald-500'
                    }`}
                  />
                  <div className="flex flex-col min-w-0">
                    <h2
                      id="node-summary-title"
                      className="text-sm font-bold text-on-surface font-mono truncate"
                    >
                      {node.name}
                    </h2>
                    <span className="text-[11px] text-on-surface-variant font-mono">{hopLabel}</span>
                  </div>
                </div>

                {/* Aggregate badges */}
                <div className="flex items-center gap-2 shrink-0">
                  {node.exactAlarmCount > 0 && (
                    <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-950 text-red-300 border border-red-500/40 text-xs font-bold">
                      🚨 {node.exactAlarmCount} {isITChain ? 'Xác thực' : 'Cảnh báo trực tiếp'}
                    </span>
                  )}
                  {node.candidateAlarmCount > 0 && (
                    <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-purple-950 text-purple-300 border border-purple-500/40 text-xs font-bold">
                      🟣 {node.candidateAlarmCount} Suy đoán
                    </span>
                  )}
                  {node.alarmCount === 0 && (
                    <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-500/40 text-xs font-bold">
                      {isITChain ? '🟢 Không có lỗi' : `🟢 ${node.hopDistance ?? 1}-Hop (Bình thường)`}
                    </span>
                  )}
                  <button
                    onClick={closeNodeFocus}
                    className="rounded-lg p-1 text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors cursor-pointer ml-2"
                    aria-label="Đóng"
                  >
                    <span className="material-symbols-outlined text-[18px]">close</span>
                  </button>
                </div>
              </header>

              {/* Filter tabs */}
              {node.alarms.length > 0 && (
                <div className="flex items-center gap-1.5 px-5 py-2 bg-[#0a1120] border-b border-[#182640] shrink-0">
                  {(['ALL', 'EXACT', 'CANDIDATE'] as const).map(f => (
                    <button
                      key={f}
                      onClick={() => setAlarmFilter(f)}
                      className={`flex items-center gap-1 px-3 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
                        alarmFilter === f
                          ? f === 'EXACT'
                            ? 'bg-red-900/60 text-red-200 border border-red-500/50'
                            : f === 'CANDIDATE'
                            ? 'bg-purple-900/60 text-purple-200 border border-purple-500/50'
                            : 'bg-secondary/15 text-secondary border border-secondary/40'
                          : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container/50'
                      }`}
                    >
                      {f === 'ALL'
                        ? `Tất cả (${node.alarms.length})`
                        : f === 'EXACT'
                        ? `🚨 Xác thực (${exactAlarms.length})`
                        : `🟣 Suy đoán (${candidateAlarms.length})`}
                    </button>
                  ))}
                  <span className="ml-auto text-[10px] text-on-surface-variant font-mono">
                    ESC để đóng
                  </span>
                </div>
              )}

              {/* Alarm list */}
              <div className="flex-1 overflow-y-auto px-5 py-3 flex flex-col gap-2">
                {displayedAlarms.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-10 text-on-surface-variant text-sm gap-2">
                    <span className="material-symbols-outlined text-[32px] text-emerald-500">check_circle</span>
                    <span>
                      {node.alarmCount === 0
                        ? 'Không có cảnh báo nào trên node này'
                        : 'Không có cảnh báo khớp bộ lọc'}
                    </span>
                  </div>
                ) : (
                  displayedAlarms.map((alarm, idx) => {
                    const exact = isExact(alarm)
                    const resolutions = alarm.entity_resolutions || []
                    const mainRes = resolutions.find(
                      r => r.resource_id === node.id ||
                           (r.candidate_resource_ids || []).includes(node.id)
                    ) || resolutions[0]

                    return (
                      <div
                        key={alarm.alarm_id || idx}
                        className={`rounded-lg border p-3 flex flex-col gap-1.5 text-xs ${
                          exact
                            ? 'bg-red-950/40 border-red-800/50'
                            : 'bg-purple-950/40 border-purple-800/50'
                        }`}
                      >
                        {/* Alarm header */}
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className="text-base shrink-0">{exact ? '🚨' : '🟣'}</span>
                            <span className="font-bold text-on-surface font-mono truncate">
                              {alarm.alarm_name || alarm.alarm_id}
                            </span>
                          </div>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${
                              exact
                                ? 'bg-red-900 text-red-200'
                                : 'bg-purple-900 text-purple-200'
                            }`}
                          >
                            {exact ? 'EXACT' : 'CANDIDATE'}
                          </span>
                        </div>

                        {/* Device + timing */}
                        <div className="flex items-center gap-3 text-on-surface-variant">
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px]">dns</span>
                            {alarm.device_code || alarm.node_reference || '—'}
                          </span>
                          {alarm.canonical_start_time && (
                            <span className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-[12px]">schedule</span>
                              {alarm.canonical_start_time}
                            </span>
                          )}
                        </div>

                        {/* Entity resolution detail */}
                        {mainRes && (
                          <div className="mt-1 rounded bg-[#080d17] border border-[#1b273e] p-2 font-mono text-[10px] flex flex-col gap-0.5">
                            <div className="flex items-center gap-2">
                              <span className="text-on-surface-variant">Nguồn:</span>
                              <span className="text-sky-300 font-bold">{mainRes.source_field || '—'}</span>
                              <span className="text-on-surface-variant">·</span>
                              <span className="text-on-surface-variant">Khớp:</span>
                              <span className="text-amber-300 font-bold">
                                {mainRes.matched_text || mainRes.raw_value || '—'}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-on-surface-variant">Trạng thái:</span>
                              <span
                                className={`font-bold ${
                                  mainRes.status === 'EXACT'
                                    ? 'text-emerald-300'
                                    : mainRes.status === 'STRUCTURED_FIELD_UNIQUE'
                                    ? 'text-sky-300'
                                    : mainRes.status === 'TEXT_MATCH_CANDIDATE'
                                    ? 'text-purple-300'
                                    : mainRes.status === 'AMBIGUOUS'
                                    ? 'text-amber-300'
                                    : 'text-rose-300'
                                }`}
                              >
                                {EVIDENCE_TIER_LABELS[mainRes.status] || mainRes.status}
                              </span>
                              <span className="text-on-surface-variant">·</span>
                              <span className="text-on-surface-variant">Mức ánh xạ:</span>
                              <span className="font-mono text-slate-400">
                                {MATCH_STRENGTH_LABELS[mainRes.status] || 'Chưa phân loại'}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })
                )}
              </div>

              {/* Footer */}
              <footer className="px-5 py-2.5 bg-[#0a1120] border-t border-[#182640] flex items-center justify-between text-[11px] text-on-surface-variant shrink-0">
                <span className="font-mono">
                  {node.name} · {node.alarmCount} cảnh báo tổng cộng
                </span>
                <button
                  onClick={closeNodeFocus}
                  className="px-3 py-1 rounded bg-surface-container text-on-surface text-xs hover:bg-surface-container-high transition-colors cursor-pointer"
                >
                  Đóng
                </button>
              </footer>
            </div>
          </div>
        )
      })(), canvasElement)}
      <EvidenceDetails
        chainId={analysis.chain_id}
        title="Witness topology từ đường Overview"
        isOpen={evidenceDetailsOpen}
        onClose={() => setEvidenceDetailsOpen(false)}
        expectedContext={pathCards ? {
          snapshot_id: pathCards.snapshot_id,
          snapshot_version: pathCards.snapshot_version,
          topology_version: pathCards.topology_version,
          analysis_identity: pathCards.analysis_identity ?? null,
        } : undefined}
        pathSelector={evidencePathSelector}
      />
    </div>
  )
}
