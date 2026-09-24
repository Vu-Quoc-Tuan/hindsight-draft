export function getFocusNodeIds(
  focusNodeId: string | null,
  edges: Array<Pick<{ sourceId: string; targetId: string }, 'sourceId' | 'targetId'>>,
): Set<string> | null {
  if (!focusNodeId) return null
  const ids = new Set<string>([focusNodeId])
  edges.forEach(edge => {
    if (edge.sourceId === focusNodeId) ids.add(edge.targetId)
    if (edge.targetId === focusNodeId) ids.add(edge.sourceId)
  })
  return ids
}

export function compactHopLabel(hopDistance: number | null | undefined): string {
  if (!hopDistance) return 'Seed'
  return `${hopDistance}-Hop`
}

export type AlarmConnectorNode = { id: string }

export type AlarmConnectorEdge = {
  id: string
  sourceId: string
  targetId: string
  relationType: string | null
}

export type EvidenceTopologyPath = {
  source: string
  target: string
  hop_count: number
  relation_type: string
  path: string[]
}

export type AlarmConnectorConnection = {
  sourceId: string
  targetId: string
  hops: number
  relationType: string
}

export type AlarmConnector = {
  nodeIds: Set<string>
  edgeIds: Set<string>
  connections: AlarmConnectorConnection[]
  terminalCount: number
  linkedTerminalCount: number
  componentCount: number
  maxConnectionHops: number
  unrenderedPathCount: number
  unrenderedTerminalCount: number
  missingPathNodeCount: number
  missingPathEdgeCount: number
  invalidPathCount: number
}

/**
 * Select only backend-derived path witnesses whose original relation edges
 * are present in the loaded graph. This is a renderer, not a path finder.
 */
export function buildAlarmConnector(
  nodes: AlarmConnectorNode[],
  edges: AlarmConnectorEdge[],
  terminalResourceIds: string[],
  paths: EvidenceTopologyPath[],
): AlarmConnector {
  const knownNodeIds = new Set(nodes.map(node => node.id))
  const terminals = Array.from(new Set(terminalResourceIds))
    .filter(id => knownNodeIds.has(id))
    .sort()
  const nodeIds = new Set(terminals)
  const edgeIds = new Set<string>()
  const connections: AlarmConnectorConnection[] = []
  let unrenderedPathCount = 0
  let missingPathNodeCount = 0
  let missingPathEdgeCount = 0
  let invalidPathCount = 0

  paths.forEach(rawPath => {
    const path = rawPath as EvidenceTopologyPath | null | undefined
    const pathNodes = Array.isArray(path?.path) ? path.path : null
    const validShape =
      Boolean(pathNodes) &&
      pathNodes!.length >= 2 &&
      typeof path?.source === 'string' &&
      typeof path?.target === 'string' &&
      path.source !== path.target &&
      pathNodes![0] === path.source &&
      pathNodes![pathNodes!.length - 1] === path.target &&
      Number.isInteger(path?.hop_count) &&
      path?.hop_count === pathNodes!.length - 1 &&
      typeof path?.relation_type === 'string' &&
      path.relation_type.length > 0 &&
      pathNodes!.every((id): id is string => typeof id === 'string' && id.length > 0) &&
      new Set(pathNodes!).size === pathNodes!.length &&
      terminals.includes(path.source) &&
      terminals.includes(path.target)
    if (!validShape) {
      unrenderedPathCount += 1
      invalidPathCount += 1
      return
    }
    const validPath = path!
    const validNodes = pathNodes!

    if (validNodes.some(id => !knownNodeIds.has(id))) {
      unrenderedPathCount += 1
      missingPathNodeCount += 1
      return
    }

    const pathEdgeIds: string[] = []
    for (let index = 0; index < validNodes.length - 1; index += 1) {
      const sourceId = validNodes[index]
      const targetId = validNodes[index + 1]
      const edge = edges
        .filter(candidate =>
          candidate.relationType === path.relation_type &&
          ((candidate.sourceId === sourceId && candidate.targetId === targetId) ||
            (candidate.sourceId === targetId && candidate.targetId === sourceId)),
        )
        .sort((left, right) => left.id.localeCompare(right.id))[0]
      if (!edge) {
        unrenderedPathCount += 1
        missingPathEdgeCount += 1
        return
      }
      pathEdgeIds.push(edge.id)
    }

    validNodes.forEach(id => nodeIds.add(id))
    pathEdgeIds.forEach(id => edgeIds.add(id))
    connections.push({
      sourceId: validPath.source,
      targetId: validPath.target,
      hops: validPath.hop_count,
      relationType: validPath.relation_type,
    })
  })

  const parent = new Map(terminals.map(id => [id, id]))
  const find = (id: string): string => {
    let root = id
    while (parent.get(root) !== root) root = parent.get(root)!
    let current = id
    while (parent.get(current) !== root) {
      const next = parent.get(current)!
      parent.set(current, root)
      current = next
    }
    return root
  }
  connections.forEach(({ sourceId, targetId }) => {
    const sourceRoot = find(sourceId)
    const targetRoot = find(targetId)
    if (sourceRoot !== targetRoot) parent.set(targetRoot, sourceRoot)
  })

  const terminalGroupSizes = new Map<string, number>()
  terminals.forEach(id => {
    const root = find(id)
    terminalGroupSizes.set(root, (terminalGroupSizes.get(root) ?? 0) + 1)
  })
  const linkedTerminalCount = Array.from(terminalGroupSizes.values())
    .filter(size => size > 1)
    .reduce((sum, size) => sum + size, 0)

  return {
    nodeIds,
    edgeIds,
    connections,
    terminalCount: terminals.length,
    linkedTerminalCount,
    componentCount: terminalGroupSizes.size,
    maxConnectionHops: connections.reduce((max, connection) => Math.max(max, connection.hops), 0),
    unrenderedPathCount,
    unrenderedTerminalCount: new Set(terminalResourceIds).size - terminals.length,
    missingPathNodeCount,
    missingPathEdgeCount,
    invalidPathCount,
  }
}
