import { useState, useMemo, useEffect, useRef } from 'react'
import type { ChainAnalysis, Member, TopologyHypothesesResult } from '../types'

import type { TopologyTreePayload } from '../TopologyTree'
import { TopologyHypotheses } from '../TopologyHypotheses'
import { InfoTip } from '../components/InfoTip'
import { api, type TopologySubgraphResult } from '../api'

interface TopologyOverlayViewProps {
  analysis: ChainAnalysis
  topologyPayload?: TopologyTreePayload | null
  topologyHypotheses?: TopologyHypothesesResult | null
  subgraphData?: TopologySubgraphResult | null
  onRootChange?: (resourceId: string) => void
  onRunDeepDive?: () => void
  isDeepDiveRunning?: boolean
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
}

const EVIDENCE_TIER_LABELS: Record<string, string> = {
  EXACT: 'Exact topology identity',
  STRUCTURED_FIELD_UNIQUE: 'Structured-field unique match',
  TEXT_MATCH_CANDIDATE: 'Raw-text candidate',
  AMBIGUOUS: 'Ambiguous',
  UNMAPPED: 'Unmapped',
  VERIFIED_ALIAS: 'Verified alias',
}

export function TopologyOverlayView({
  analysis,
  topologyPayload,
  topologyHypotheses,
  subgraphData: externalSubgraph,
  onRootChange: _onRootChange,
  onRunDeepDive,
  isDeepDiveRunning,
}: TopologyOverlayViewProps) {
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [showAlarmsLayer, setShowAlarmsLayer] = useState(true)
  const [showLinksLayer, setShowLinksLayer] = useState(true)
  const [showNeighborsLayer, setShowNeighborsLayer] = useState(true)
  const [showModulesDetail, setShowModulesDetail] = useState(false)
  const [hopDistance, setHopDistance] = useState<number>(2)
  const [summaryNode, setSummaryNode] = useState<NetworkNode | null>(null)
  const [alarmFilter, setAlarmFilter] = useState<'ALL' | 'EXACT' | 'CANDIDATE'>('ALL')

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSummaryNode(null)
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
  const activeDevice = selectedDeviceId || dominantDevice

  const alarmMap = useMemo(() => {
    const map = new Map<string, Member[]>()
    deviceGroups.forEach(([dev, alarms]) => map.set(dev, alarms))
    return map
  }, [deviceGroups])

  // Subgraph state (live fetched from /api/v1/topology/subgraph around seed devices)
  const [fetchedSubgraph, setFetchedSubgraph] = useState<TopologySubgraphResult | null>(null)
  const [isLoadingSubgraph, setIsLoadingSubgraph] = useState<boolean>(false)

  const distinctDevicesKey = useMemo(() => distinctDevices.slice().sort().join(','), [distinctDevices])

  useEffect(() => {
    let cancelled = false
    if (!distinctDevicesKey) return
    setIsLoadingSubgraph(true)
    api.topologySubgraph(activeProfile, distinctDevices, hopDistance)
      .then(res => {
        if (!cancelled && res.status === 'AVAILABLE') {
          setFetchedSubgraph(res)
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setIsLoadingSubgraph(false)
      })
    return () => { cancelled = true }
  }, [activeProfile, distinctDevicesKey, hopDistance])

  const activeSubgraph = externalSubgraph || fetchedSubgraph

  function getDeviceRoleInfo(devCode: string, resourceType?: string) {
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
  }

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

      // Incident hosts filter (keeps seed/alarm hosts when there are hundreds of shared storage hosts in 2-hop)
      const isIncidentHost = (n: typeof rawNodes[0]) => {
        if (n.type !== 'INSTANCE') return false
        const cleanName = n.name.replace(/\/\d+$/, '').trim()
        return n.is_seed || distinctDevices.some(d => cleanName.includes(d) || d.includes(cleanName))
      }

      const allInstances = deduplicatedNodes.filter(n => n.type === 'INSTANCE')
      const incidentInstances = allInstances.filter(isIncidentHost)
      const visibleInstances = incidentInstances.length > 0 && allInstances.length > 12
        ? incidentInstances
        : allInstances

      // Modules filter: show modules with alarms or all modules if detail toggle is on
      const allModules = deduplicatedNodes.filter(n => n.type === 'MODULE')
      const modulesWithAlarms = allModules.filter(m => (moduleAlarmsMap.get(m.id) || []).length > 0)
      
      let visibleModules: typeof rawNodes = []
      if (showModulesDetail) {
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
        const tier2 = visibleInstances
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

      if (!showModulesDetail && hasServices && visibleModules.length === 0) {
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
          })
        }
      })

      return { nodes, edges }
    }

    // 2. Fallback if subgraph not yet returned
    if (isITChain) {
      if (hopDistance === 1) {
        // 1-Hop Fallback: Inferred Modules (Top) <-> Incident Hosts (Middle) <-> Storage (Bottom)
        const inferredModules = [
          { id: 'mod:nova-compute', name: 'nova-compute (Module)', roleName: 'Compute Agent' },
          { id: 'mod:neutron-ovs', name: 'neutron-openvswitch-agent', roleName: 'Network Agent' },
          { id: 'mod:fluentd', name: 'fluentd (Logging)', roleName: 'Logging Container' },
        ]
        const modSpacing = 260
        const modStartX = 500 - ((inferredModules.length - 1) * modSpacing) / 2
        inferredModules.forEach((mod, idx) => {
          const initX = Math.round(modStartX + idx * modSpacing)
          const initY = 120
          const posX = nodePositions[mod.id]?.x ?? initX
          const posY = nodePositions[mod.id]?.y ?? initY
          nodes.push({
            id: mod.id,
            name: mod.name,
            x: posX,
            y: posY,
            tier: 1,
            roleCode: 'DEV',
            roleName: mod.roleName,
            alarmCount: 1,
            exactAlarmCount: 0,
            candidateAlarmCount: 1,
            isDominant: false,
            isAlarmBearer: true,
            isExactBearer: false,
            isCandidateOnly: true,
            badgeColor: 'text-indigo-300',
            icon: 'extension',
            alarms: [],
          })
        })

        const hostSpacing = Math.max(210, 1000 / Math.max(1, distinctDevices.length))
        const hostStartX = 500 - ((distinctDevices.length - 1) * hostSpacing) / 2
        distinctDevices.forEach((dev, idx) => {
          const devAlarms = alarmMap.get(dev) || []
          const initX = Math.round(hostStartX + idx * hostSpacing)
          const initY = 280
          const posX = nodePositions[dev]?.x ?? initX
          const posY = nodePositions[dev]?.y ?? initY
          nodes.push({
            id: dev,
            name: dev,
            x: posX,
            y: posY,
            tier: 2,
            roleCode: 'HOST',
            roleName: 'Máy chủ / Host',
            alarmCount: devAlarms.length,
            exactAlarmCount: devAlarms.length,
            candidateAlarmCount: 0,
            isDominant: dev === dominantDevice,
            isAlarmBearer: devAlarms.length > 0,
            isExactBearer: devAlarms.length > 0,
            isCandidateOnly: false,
            badgeColor: 'text-emerald-300',
            icon: 'dns',
            alarms: devAlarms,
          })

          const primMod = nodes[idx % inferredModules.length]
          edges.push({
            id: `edge-${primMod.id}-${dev}`,
            sourceId: primMod.id,
            targetId: dev,
            sourceX: primMod.x,
            sourceY: primMod.y,
            targetX: posX,
            targetY: posY,
            label: 'MODULE',
            isAlarmPath: true,
          })
        })

        // Inferred Storage at bottom
        const storageNode = {
          id: 'storage:vsp',
          name: 'VSP-G1000 SAN Storage',
          x: 500,
          y: 450,
          tier: 3,
          roleCode: 'SAN',
          roleName: 'Hạ tầng Lưu trữ',
          alarmCount: 0,
          exactAlarmCount: 0,
          candidateAlarmCount: 0,
          isDominant: false,
          isAlarmBearer: false,
          isExactBearer: false,
          isCandidateOnly: false,
          badgeColor: 'text-rose-300',
          icon: 'hard_drive',
          alarms: [],
        }
        nodes.push(storageNode)
        distinctDevices.forEach(dev => {
          const hNode = nodes.find(n => n.id === dev)
          if (hNode) {
            edges.push({
              id: `edge-${dev}-${storageNode.id}`,
              sourceId: dev,
              targetId: storageNode.id,
              sourceX: hNode.x,
              sourceY: hNode.y,
              targetX: storageNode.x,
              targetY: storageNode.y,
              label: 'SAN',
              isAlarmPath: false,
            })
          }
        })

        return { nodes, edges }
      }

      // 2-Hop Fallback: Cloud Services (Top) <-> Hosts (Bottom)
      const inferredServices = [
        { id: 'svc:nova', name: 'OpenStack NOVA Cloud', roleCode: 'CORE', roleName: 'Compute Service' },
        { id: 'svc:neutron', name: 'Neutron Network', roleCode: 'CORE', roleName: 'Network Service' },
        { id: 'svc:ovs', name: 'OpenvSwitch Mesh', roleCode: 'CORE', roleName: 'Virtual Switch' },
      ]

      const svcSpacing = 280
      const svcStartX = 500 - ((inferredServices.length - 1) * svcSpacing) / 2
      inferredServices.forEach((svc, idx) => {
        const initX = Math.round(svcStartX + idx * svcSpacing)
        const initY = 100
        const posX = nodePositions[svc.id]?.x ?? initX
        const posY = nodePositions[svc.id]?.y ?? initY

        nodes.push({
          id: svc.id,
          name: svc.name,
          x: posX,
          y: posY,
          tier: 0,
          roleCode: svc.roleCode,
          roleName: svc.roleName,
          alarmCount: 0,
          exactAlarmCount: 0,
          candidateAlarmCount: 0,
          isDominant: false,
          isAlarmBearer: false,
          isExactBearer: false,
          isCandidateOnly: false,
          badgeColor: 'text-cyan-300',
          icon: 'hub',
          alarms: [],
        })
      })

      const hostSpacing = Math.max(250, 1100 / Math.max(1, distinctDevices.length))
      const hostStartX = 500 - ((distinctDevices.length - 1) * hostSpacing) / 2

      distinctDevices.forEach((dev, idx) => {
        const devAlarms = alarmMap.get(dev) || []
        const initX = Math.round(hostStartX + idx * hostSpacing)
        const initY = 370
        const posX = nodePositions[dev]?.x ?? initX
        const posY = nodePositions[dev]?.y ?? initY

        nodes.push({
          id: dev,
          name: dev,
          x: posX,
          y: posY,
          tier: 2,
          roleCode: 'HOST',
          roleName: 'Máy chủ / Host',
          alarmCount: devAlarms.length,
          exactAlarmCount: devAlarms.length,
          candidateAlarmCount: 0,
          isDominant: dev === dominantDevice,
          isAlarmBearer: devAlarms.length > 0,
          isExactBearer: devAlarms.length > 0,
          isCandidateOnly: false,
          badgeColor: 'text-emerald-300',
          icon: 'dns',
          alarms: devAlarms,
        })

        // Connect each host to primary cloud service
        const primSvc = nodes[idx % inferredServices.length]
        edges.push({
          id: `edge-${primSvc.id}-${dev}`,
          sourceId: primSvc.id,
          targetId: dev,
          sourceX: primSvc.x,
          sourceY: primSvc.y,
          targetX: posX,
          targetY: posY,
          label: 'IT_CLUSTER',
          isAlarmPath: true,
        })
      })

      return { nodes, edges }
    }

    // IP Network fallback: Multi-tier placement if multiple telecom classes present
    const devList = distinctDevices.map(dev => ({
      dev,
      alarms: alarmMap.get(dev) || [],
      role: getDeviceRoleInfo(dev),
    }))

    const coreDevs = devList.filter(d => d.role.roleCode === 'CORE')
    const aggDevs = devList.filter(d => d.role.roleCode === 'AGG')
    const oltDevs = devList.filter(d => d.role.roleCode === 'OLT')
    const srtDevs = devList.filter(d => d.role.roleCode !== 'CORE' && d.role.roleCode !== 'AGG' && d.role.roleCode !== 'OLT')

    const layers = [coreDevs, aggDevs, srtDevs, oltDevs].filter(l => l.length > 0)
    const yStarts = layers.length === 4 ? [80, 210, 360, 510]
      : layers.length === 3 ? [110, 290, 470]
      : layers.length === 2 ? [160, 390]
      : [240]

    layers.forEach((layer, layerIdx) => {
      const y = yStarts[layerIdx]
      const count = layer.length
      const spacing = Math.max(250, Math.min(320, 1000 / Math.max(1, count)))
      const startX = 500 - ((count - 1) * spacing) / 2
      layer.forEach((item, idx) => {
        const posX = nodePositions[item.dev]?.x ?? Math.round(startX + idx * spacing)
        const posY = nodePositions[item.dev]?.y ?? y

        nodes.push({
          id: item.dev,
          name: item.dev,
          x: posX,
          y: posY,
          tier: item.role.tier,
          roleCode: item.role.roleCode,
          roleName: item.role.roleName,
          alarmCount: item.alarms.length,
          exactAlarmCount: item.alarms.length,
          candidateAlarmCount: 0,
          isDominant: item.dev === dominantDevice,
          isAlarmBearer: item.alarms.length > 0,
          isExactBearer: item.alarms.length > 0,
          isCandidateOnly: false,
          badgeColor: item.role.badgeColor,
          icon: item.role.icon,
          alarms: item.alarms,
          hopDistance: 0,
        })
      })
    })

    return { nodes, edges }
  }, [activeSubgraph, showModulesDetail, isITChain, distinctDevices, nodePositions, dominantDevice, alarmMap, hopDistance])

  const neighborAlarmsCount = useMemo(() => {
    return networkGraph.nodes
      .filter(n => !n.isAlarmBearer)
      .reduce((acc, n) => acc + n.alarmCount, 0)
  }, [networkGraph.nodes])

  const displayedNodes = useMemo(() => {
    if (showNeighborsLayer) return networkGraph.nodes
    return networkGraph.nodes.filter(n => n.isAlarmBearer || n.alarmCount > 0)
  }, [networkGraph.nodes, showNeighborsLayer])

  const displayedNodeIds = useMemo(() => new Set(displayedNodes.map(n => n.id)), [displayedNodes])

  const displayedEdges = useMemo(() => {
    if (!showLinksLayer) return []
    return networkGraph.edges.filter(e => displayedNodeIds.has(e.sourceId) && displayedNodeIds.has(e.targetId))
  }, [networkGraph.edges, displayedNodeIds, showLinksLayer])

  const maxSvgHeight = useMemo(() => {
    let maxY = 600
    displayedNodes.forEach(n => {
      if (n.y + 70 > maxY) maxY = n.y + 70
    })
    return Math.max(620, maxY + 20)
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
  }

  return (
    <div className="flex flex-col gap-space-md w-full animate-fade-in select-none">
      {/* 1. Header Toolbar */}
      <section className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex items-center justify-between">
        <div className="flex items-center gap-space-sm">
          <div className="w-9 h-9 rounded-lg bg-secondary/15 flex items-center justify-center text-secondary border border-secondary/20">
            <span className="material-symbols-outlined text-[20px]">hub</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-headline-sm text-sm font-bold text-on-surface">
                Topology Graph tương tác &amp; Mở rộng Láng giềng
              </h2>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-primary-container text-on-primary-container border border-primary/30">
                {activeProfile}
              </span>
              <InfoTip text="Đồ thị mạng tương tác kiểu Neo4j: Có thể kéo thả di chuyển từng node, cuộn chuột để zoom và rê chuột để di chuyển canvas." />
            </div>
            <p className="font-body-sm text-xs text-on-surface-variant flex items-center gap-2">
              <span>{networkGraph.nodes.length} nodes • {networkGraph.edges.length} edges • {totalAlarms} cảnh báo • Mở rộng láng giềng từ {distinctDevices.length} seed thiết bị</span>
              {isLoadingSubgraph && (
                <span className="inline-flex items-center gap-1 text-[11px] text-cyan-400 font-semibold px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 animate-pulse">
                  <span className="material-symbols-outlined text-xs animate-spin">sync</span>
                  <span>Đang tải {hopDistance}-Hop...</span>
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Controls Toolbar */}
        <div className="flex items-center gap-space-xs">
          {isITChain && (
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
              {showModulesDetail ? 'Thu gọn Modules' : 'Hiện đầy đủ Modules (84)'}
            </button>
          )}

          <div className="flex items-center rounded border border-[#1b273e] bg-[#080d17] p-0.5">
            <button
              type="button"
              onClick={() => setHopDistance(1)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 1 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title={
                isITChain
                  ? '1-Hop: Láng giềng 1 bước từ Server (Lên Module Container & Xuống Hạ tầng Storage/DB)'
                  : '1-Hop: Chỉ hiển thị các thiết bị Router/Switch kết nối vật lý trực tiếp với thiết bị sự cố'
              }
            >
              {isITChain ? '1-Hop (Lên Module & Xuống Storage/DB)' : '1-Hop (Láng giềng trực tiếp)'}
            </button>
            <button
              type="button"
              onClick={() => setHopDistance(2)}
              className={`px-2 py-1 text-[11px] rounded font-bold transition-colors ${
                hopDistance === 2 ? 'bg-secondary text-on-secondary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
              }`}
              title={
                isITChain
                  ? '2-Hop: Mở rộng 2 bước vươn lên Service đám mây lõi (Service đám mây ↔ Module ↔ Server ↔ Storage/DB)'
                  : '2-Hop: Mở rộng 2 bước láng giềng kề để bao quát toàn bộ vành đai Ring / Aggregation lân cận'
              }
            >
              {isITChain ? '2-Hop (Lên Service đám mây)' : '2-Hop (Mở rộng láng giềng cấp 2)'}
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
          {/* Main Interactive Neo4j-style Canvas */}
          <div className="w-full flex flex-col bg-[#0c1424] rounded-xl border border-[#1b273e] shadow-md overflow-hidden h-[680px] relative">
            {/* Header info bar: Title and LỚP HIỂN THỊ on the SAME row */}
            <div className="min-h-10 px-space-md py-1.5 bg-[#080d17] border-b border-[#1b273e] flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[18px]">device_hub</span>
                <span className="font-headline-md text-xs font-bold text-on-surface">
                  Phân bố cảnh báo theo Topology &amp; Mạng lưới kề
                </span>
                <span className="text-[11px] text-on-surface-variant hidden xl:inline">
                  (Click và kéo để di chuyển node)
                </span>
              </div>

              {/* LỚP HIỂN THỊ Controls on the same row */}
              <div className="flex items-center gap-2 font-code-sm text-xs flex-wrap">
                <span className="font-label-caps text-[11px] uppercase text-[#ffb4a2] font-bold tracking-wider mr-0.5">
                  LỚP HIỂN THỊ:
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

                {/* Node kề mạng */}
                <button
                  type="button"
                  onClick={() => setShowNeighborsLayer(!showNeighborsLayer)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-code-sm transition-colors cursor-pointer ${
                    showNeighborsLayer
                      ? 'bg-[#132238] text-[#8bc4ff] border-[#243754]'
                      : 'bg-[#080d17] text-on-surface-variant/60 border-[#1b273e] hover:bg-[#121c2e]'
                  }`}
                  title="Bật/tắt node láng giềng kề"
                >
                  <span className="material-symbols-outlined text-[15px]">
                    {showNeighborsLayer ? 'check_box' : 'check_box_outline_blank'}
                  </span>
                  <span>Node kề mạng ({neighborAlarmsCount} cảnh báo)</span>
                </button>
              </div>
            </div>

            {/* SVG Canvas Area */}
            <div
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
                viewBox={`0 0 1000 ${maxSvgHeight}`}
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
                  {/* EDGES LAYER */}
                  {showLinksLayer &&
                    displayedEdges.map(edge => {
                      const startX = edge.sourceX
                      const startY = edge.sourceY
                      const endX = edge.targetX
                      const endY = edge.targetY
                      const midX = (startX + endX) / 2
                      const midY = (startY + endY) / 2

                      // Cubic bezier smooth curve
                      const dy = endY - startY
                      const pathD = `M ${startX} ${startY} C ${startX} ${startY + dy * 0.5}, ${endX} ${endY - dy * 0.5}, ${endX} ${endY}`

                      return (
                        <g key={edge.id} className="pointer-events-none">
                          <path
                            d={pathD}
                            stroke={
                              edge.label.includes('KỀ VẬT LÝ')
                                ? (edge.isAlarmPath ? '#38bdf8' : '#0284c7')
                                : edge.label === 'SAN'
                                ? '#f43f5e'
                                : edge.label === 'DATABASE' || edge.label === 'DB_LINK'
                                ? '#f59e0b'
                                : edge.isAlarmPath
                                ? '#38bdf8'
                                : '#334155'
                            }
                            strokeWidth={edge.label.includes('KỀ VẬT LÝ') ? (edge.isAlarmPath ? '2.2' : '1.6') : edge.label === 'SAN' || edge.label === 'DATABASE' ? '1.8' : edge.isAlarmPath ? '2.2' : '1.4'}
                            strokeDasharray={edge.isAlarmPath || edge.label.includes('KỀ VẬT LÝ') ? undefined : '5 4'}
                            opacity="0.85"
                          />
                          {/* Midpoint relation label with dynamic pill width */}
                          {(() => {
                            const isPhysicalAdjacency = edge.label.includes('KỀ VẬT LÝ')
                            const labelWidth = Math.max(76, edge.label.length * 6.5 + 16)
                            return (
                              <g>
                                <rect
                                  x={midX - labelWidth / 2}
                                  y={midY - 9}
                                  width={labelWidth}
                                  height="18"
                                  rx="4"
                                  fill="#070e1d"
                                  stroke={
                                    isPhysicalAdjacency
                                      ? '#0284c7'
                                      : edge.label === 'SAN'
                                      ? '#881337'
                                      : edge.label === 'DATABASE' || edge.label === 'DB_LINK'
                                      ? '#78350f'
                                      : '#1b273e'
                                  }
                                  strokeWidth="1"
                                  opacity="0.95"
                                />
                                <text
                                  x={midX}
                                  y={midY + 3.5}
                                  fill={
                                    isPhysicalAdjacency
                                      ? '#38bdf8'
                                      : edge.label === 'SAN'
                                      ? '#fda4af'
                                      : edge.label === 'DATABASE' || edge.label === 'DB_LINK'
                                      ? '#fcd34d'
                                      : edge.isAlarmPath
                                      ? '#7bd0ff'
                                      : '#94a3b8'
                                  }
                                  fontFamily="JetBrains Mono"
                                  fontSize="8.5"
                                  fontWeight="600"
                                  textAnchor="middle"
                                >
                                  {edge.label}
                                </text>
                              </g>
                            )
                          })()}
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
                          setSelectedDeviceId(node.id)
                          setSummaryNode(node)
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
                            ) : (
                              <g>
                                <rect
                                  x="-26"
                                  y="-10"
                                  width="34"
                                  height="20"
                                  rx="10"
                                  fill="#10b981"
                                  stroke="#080d17"
                                  strokeWidth="1.5"
                                />
                                <text
                                  x="-9"
                                  y="3.5"
                                  fill="#ffffff"
                                  fontFamily="JetBrains Mono"
                                  fontSize="9"
                                  fontWeight="800"
                                  textAnchor="middle"
                                >
                                  🟢 0
                                </text>
                              </g>
                            )}
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

          {/* Topology Hypotheses */}
          {topologyHypotheses ? (
            <TopologyHypotheses
              topology_hypotheses={topologyHypotheses}
              action={
                onRunDeepDive && (
                  <button
                    type="button"
                    onClick={onRunDeepDive}
                    disabled={isDeepDiveRunning}
                    className="inline-flex items-center gap-space-xs rounded bg-secondary-container px-space-sm py-1 text-xs font-semibold text-on-secondary-container shadow-sm transition-colors hover:bg-secondary-container/80 disabled:opacity-50"
                  >
                    <span aria-hidden="true" className={`material-symbols-outlined text-[14px] ${isDeepDiveRunning ? 'animate-spin' : ''}`}>
                      {isDeepDiveRunning ? 'sync' : 'refresh'}
                    </span>
                    {isDeepDiveRunning ? 'Đang phân tích...' : 'Làm mới Deep Dive'}
                  </button>
                )
              }
            />
          ) : (
            <section className="bg-[#0c1424] rounded-xl border border-[#1b273e] p-space-md shadow-md flex flex-col gap-space-sm">
              <div className="flex items-center justify-between pb-space-xs border-b border-[#1b273e]">
                <div className="flex items-center gap-space-xs">
                  <span className="material-symbols-outlined text-secondary text-[18px]">account_tree</span>
                  <span className="font-label-caps text-xs uppercase text-secondary font-bold tracking-wider">
                    GIẢ THUYẾT TOPOLOGY &amp; LAN TRUYỀN PHỤ THUỘC
                  </span>
                </div>
                <span className="font-code-sm text-xs text-on-surface-variant">
                  Nút thống trị P2 &amp; Lan truyền có hướng
                </span>
              </div>
              {isDeepDiveRunning ? (
                <div className="py-space-lg text-center text-on-surface-variant text-sm flex flex-col items-center justify-center gap-3">
                  <span className="material-symbols-outlined animate-spin text-secondary text-[28px]">progress_activity</span>
                  <div className="flex flex-col gap-1">
                    <span className="font-semibold text-on-surface text-sm">Đang phân tích giả thuyết Topology P2 &amp; lan truyền...</span>
                    <span className="text-xs font-code-sm text-on-surface-variant">
                      Tính toán cây thống trị Dominator, bước ngẫu nhiên RWR và phạm vi ảnh hưởng phụ thuộc
                    </span>
                  </div>
                </div>
              ) : (
                <div className="py-space-md text-center text-on-surface-variant text-sm flex flex-col items-center gap-2">
                  <span>Chưa có dữ liệu phân tích Deep Dive cho chuỗi này.</span>
                  {onRunDeepDive && (
                    <button
                      type="button"
                      onClick={onRunDeepDive}
                      className="inline-flex items-center gap-space-xs rounded bg-primary px-space-md py-space-xs text-sm font-semibold text-on-primary shadow-sm hover:bg-primary/90"
                    >
                      <span className="material-symbols-outlined text-[16px]">query_stats</span>
                      <span>Chạy Deep Dive</span>
                    </button>
                  )}
                </div>
              )}
            </section>
          )}
        </>
      )}

      {/* ===== NODE SUMMARY MODAL ===== */}
      {summaryNode !== null && (() => {
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

        const hopLabel =
          node.hopDistance === 0 ? 'Gốc cảnh báo (Seed)'
          : node.hopDistance === 1 ? 'Láng giềng kề trực tiếp (1-Hop)'
          : `${node.hopDistance}-Hop (Vành đai mở rộng)`

        const tierLabel = isITChain
          ? (node.tier === 0 ? 'IT Service lõi'
             : node.tier === 1 ? 'Module Container'
             : node.tier === 3 ? (node.roleCode === 'SAN' ? 'Storage SAN' : 'Database DB')
             : 'Máy chủ / Host')
          : (node.roleCode === 'CORE' ? 'Core Router (Lõi mạng IP)'
             : node.roleCode === 'AGG' ? 'Aggregation Router (Gom huyện/PE)'
             : node.roleCode === 'OLT' ? 'GPON OLT (Thiết bị truy nhập quang)'
             : node.roleCode === 'SRT' ? 'Site Router (Trạm/Xã kề vật lý)'
             : 'Thiết bị mạng IP')

        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            onClick={() => setSummaryNode(null)}
            role="dialog"
            aria-modal="true"
            aria-labelledby="node-summary-title"
          >
            <div
              className="relative z-10 w-full max-w-2xl max-h-[88vh] flex flex-col rounded-2xl border border-[#1e2e4a] bg-[#090f1d] text-on-surface shadow-[0_25px_60px_-15px_rgba(0,0,0,0.95)] overflow-hidden"
              onClick={e => e.stopPropagation()}
            >
              {/* Modal Header */}
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
                    <span className="text-[11px] text-on-surface-variant font-mono">
                      {node.roleCode} · {tierLabel} · {hopLabel}
                    </span>
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
                      {isITChain ? '🟢 Không có lỗi' : `🟢 Láng giềng ${node.hopDistance ?? 1}-Hop (Bình thường)`}
                    </span>
                  )}
                  <button
                    onClick={() => setSummaryNode(null)}
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
                              {mainRes.confidence !== undefined && mainRes.confidence !== null && (
                                <>
                                  <span className="text-on-surface-variant">·</span>
                                  <span className="text-on-surface-variant">Độ tin cậy:</span>
                                  <span className="font-mono text-slate-400">
                                    {Math.round((mainRes.confidence || 0) * 100)}% (heuristic)
                                  </span>
                                </>
                              )}
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
                  onClick={() => setSummaryNode(null)}
                  className="px-3 py-1 rounded bg-surface-container text-on-surface text-xs hover:bg-surface-container-high transition-colors cursor-pointer"
                >
                  Đóng
                </button>
              </footer>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
