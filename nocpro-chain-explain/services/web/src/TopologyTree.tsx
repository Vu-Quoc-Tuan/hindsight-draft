import { useMemo, useState } from 'react'

export type TopologyTreeNode = {
  resource_id: string
  resource_type: string
  display_name: string
  relation_type: string | null
  source_table: string | null
  children: TopologyTreeNode[]
  hidden_child_count: number
  reference_kind: 'CYCLE' | 'MULTI_PARENT' | null
  linked_parent_count: number
}

export type TopologyTreePayload =
  | {
      status: 'AVAILABLE'
      profile: 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'
      topology_kind: 'UNDIRECTED_ADJACENCY' | 'DIRECTED_SOURCE_RELATIONS'
      direction_kind: 'NONE' | 'SOURCE_RELATION'
      dependency_semantics: 'UNVERIFIED'
      source_version: string
      semantic_notice: string
      tree: TopologyTreeNode
    }
  | {
      status: 'UNAVAILABLE'
      reason: string
      profile: 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'
      topology_kind: 'UNAVAILABLE' | 'UNDIRECTED_ADJACENCY' | 'DIRECTED_SOURCE_RELATIONS'
    }

const ICONS: Record<string, string> = {
  SERVICE: '◈', MODULE: '◇', INSTANCE: '◌', DATABASE: '▣', STORAGE: '▤', DEVICE: '⬡',
}

function titleFor(payload: Extract<TopologyTreePayload, { status: 'AVAILABLE' }>) {
  return payload.topology_kind === 'UNDIRECTED_ADJACENCY' ? 'Adjacency Tree Projection' : 'Relation Tree Projection'
}

function TreeRow({ node, depth, selectedId, onSelect, openIds, onToggle }: {
  node: TopologyTreeNode
  depth: number
  selectedId: string | null
  onSelect: (node: TopologyTreeNode) => void
  openIds: Set<string>
  onToggle: (id: string) => void
}) {
  const open = openIds.has(node.resource_id)
  const isReference = node.reference_kind !== null
  const hasChildren = node.children.length > 0 || node.hidden_child_count > 0
  return <li className={`topology-tree-row${isReference ? ' is-reference' : ''}${selectedId === node.resource_id ? ' is-selected' : ''}`}>
    <div className="topology-tree-line" style={{ paddingInlineStart: `${depth * 18}px` }}>
      {hasChildren && !isReference ? <button className="topology-tree-toggle" onClick={() => onToggle(node.resource_id)} aria-label={`${open ? 'Collapse' : 'Expand'} ${node.display_name}`}>{open ? '−' : '+'}</button> : <span className="topology-tree-stub" />}
      <button className="topology-tree-node" onClick={() => onSelect(node)} aria-pressed={selectedId === node.resource_id}>
        <span className={`topology-tree-icon type-${node.resource_type.toLowerCase()}`}>{ICONS[node.resource_type] ?? '○'}</span>
        <span className="topology-tree-label"><strong>{isReference ? `Linked to ${node.display_name}` : node.display_name}</strong><small>{isReference ? `${node.reference_kind === 'CYCLE' ? 'Cycle' : 'Also linked'} reference` : node.resource_type}</small></span>
        {node.reference_kind === 'MULTI_PARENT' && <span className="topology-tree-link-count">+{node.linked_parent_count}</span>}
      </button>
    </div>
    {!isReference && open && node.children.length > 0 && <ul className="topology-tree-children">{node.children.map((child, index) => <TreeRow key={`${child.resource_id}:${child.relation_type ?? 'root'}:${index}`} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} openIds={openIds} onToggle={onToggle} />)}</ul>}
    {!isReference && open && node.hidden_child_count > 0 && <p className="topology-tree-hidden" style={{ marginInlineStart: `${(depth + 1) * 18 + 30}px` }}>+ {node.hidden_child_count} more source relations</p>}
  </li>
}

export function TopologyTree({ payload }: { payload: TopologyTreePayload }) {
  const [selected, setSelected] = useState<TopologyTreeNode | null>(payload.status === 'AVAILABLE' ? payload.tree : null)
  const [openIds, setOpenIds] = useState<Set<string>>(() => payload.status === 'AVAILABLE'
    ? new Set([payload.tree.resource_id, ...payload.tree.children.filter((node) => node.reference_kind === null).map((node) => node.resource_id)])
    : new Set())
  const [query, setQuery] = useState('')
  const flattened = useMemo(() => payload.status === 'AVAILABLE' ? flatten(payload.tree) : [], [payload])
  if (payload.status === 'UNAVAILABLE') return <section className="topology-tree topology-tree--unavailable" aria-live="polite"><p className="kicker">Topology navigation</p><h2>Topology unavailable</h2><p>{payload.reason}</p><small>{payload.profile} supplies no usable topology source for this view.</small></section>
  const matches = query.trim() ? flattened.filter((node) => `${node.display_name} ${node.resource_id} ${node.resource_type}`.toLowerCase().includes(query.trim().toLowerCase())) : []
  const select = (node: TopologyTreeNode) => { setSelected(node); if (!node.reference_kind) setOpenIds((old) => new Set(old).add(node.resource_id)) }
  const toggle = (id: string) => setOpenIds((old) => { const next = new Set(old); next.has(id) ? next.delete(id) : next.add(id); return next })
  return <section className="topology-tree" aria-label="Topology navigation tree">
    <header className="topology-tree-header"><div><p className="kicker">Source navigation</p><h2>{titleFor(payload)}</h2></div><div className="topology-tree-badges"><span>{payload.profile.replace('_', ' ')}</span><span>{payload.direction_kind}</span></div></header>
    <p className="topology-tree-notice">{payload.semantic_notice}</p>
    <div className="topology-tree-toolbar"><label><span className="visually-hidden">Find a resource</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find service, module, database…" /></label><span>{payload.source_version.slice(0, 18)}…</span></div>
    {matches.length > 0 && <div className="topology-tree-matches">{matches.slice(0, 6).map((node) => <button key={`match:${node.resource_id}`} onClick={() => select(node)}>{node.display_name}<small>{node.resource_type}</small></button>)}</div>}
    <div className="topology-tree-layout"><div className="topology-tree-canvas"><ul><TreeRow node={payload.tree} depth={0} selectedId={selected?.resource_id ?? null} onSelect={select} openIds={openIds} onToggle={toggle} /></ul></div><aside className="topology-tree-inspector"><p className="kicker">Selected record</p>{selected ? <><h3>{selected.display_name}</h3><dl><div><dt>Type</dt><dd>{selected.resource_type}</dd></div><div><dt>Relation</dt><dd>{selected.relation_type ?? 'Projection root'}</dd></div><div><dt>Source table</dt><dd>{selected.source_table ?? 'Multiple / selected root'}</dd></div><div><dt>Direction</dt><dd>{payload.direction_kind}</dd></div></dl>{selected.reference_kind && <p className="topology-tree-reference-note">{selected.reference_kind === 'CYCLE' ? 'Cycle reference: this link is intentionally not expanded.' : 'Additional parent link: primary display location is a technical policy only.'}</p>}</> : <p>Select a resource to inspect its source relation.</p>}</aside></div>
  </section>
}

function flatten(node: TopologyTreeNode): TopologyTreeNode[] {
  return [node, ...node.children.flatMap(flatten)]
}
