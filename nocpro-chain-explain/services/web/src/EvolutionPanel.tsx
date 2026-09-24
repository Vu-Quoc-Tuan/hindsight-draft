import { useEffect, useState } from 'react'

import { api } from './api'
import { compactTime, humanize, percent } from './format'
import type { RefreshTask } from './liveUpdates'
import type { Evolution } from './types'

function productionLabel(value: Evolution['production_validation']) {
  return value === 'ELIGIBLE' ? 'Production sequence eligible' : 'Production validation not established'
}

export interface EvolutionPanelProps {
  chainId: string
  initialResult?: Evolution | null
  resourceKey?: string
  refreshEpoch?: number
  expectedSnapshotId?: string | null
  expectedSnapshotVersion?: string | null
  scheduleRefresh?: (key: string, task: RefreshTask) => boolean
  cancelRefresh?: (key: string) => void
  onLoadError?: (message: string | null) => void
}

export function EvolutionPanel({
  chainId,
  initialResult = null,
  resourceKey = `evolution:${chainId}`,
  refreshEpoch = 0,
  expectedSnapshotId,
  expectedSnapshotVersion,
  scheduleRefresh,
  cancelRefresh,
  onLoadError,
}: EvolutionPanelProps) {
  const [loaded, setLoaded] = useState<{
    resourceKey: string
    result: Evolution | null
    error: string | null
  }>({ resourceKey: initialResult?.chain_id === chainId ? resourceKey : '', result: initialResult, error: null })

  useEffect(() => {
    if (initialResult?.chain_id === chainId) return
    const task: RefreshTask = async signal => {
      try {
        const result = await api.evolution(chainId, signal)
        if (signal.aborted) return
        if (
          result.chain_id !== chainId
          || (expectedSnapshotId != null && result.snapshot_id !== expectedSnapshotId)
          || (expectedSnapshotVersion != null && result.snapshot_version !== expectedSnapshotVersion)
        ) {
          throw new Error('EVOLUTION_CONTEXT_MISMATCH')
        }
        setLoaded({ resourceKey, result, error: null })
        onLoadError?.(null)
      } catch (cause: unknown) {
        if (signal.aborted || (cause instanceof Error && cause.name === 'AbortError')) return
        const message = cause instanceof Error ? cause.message : 'Evolution unavailable'
        setLoaded(current => current.resourceKey === resourceKey
          ? { ...current, error: message }
          : { resourceKey, result: null, error: message })
        onLoadError?.(message)
      }
    }
    if (scheduleRefresh) {
      scheduleRefresh(resourceKey, task)
    } else {
      const controller = new AbortController()
      void task(controller.signal)
      return () => controller.abort()
    }
  }, [
    chainId,
    expectedSnapshotId,
    expectedSnapshotVersion,
    initialResult,
    onLoadError,
    refreshEpoch,
    resourceKey,
    scheduleRefresh,
  ])

  useEffect(() => () => cancelRefresh?.(resourceKey), [cancelRefresh, resourceKey])

  const initial = initialResult?.chain_id === chainId ? initialResult : null
  const result = initial ?? (loaded.resourceKey === resourceKey ? loaded.result : null)
  const error = initial ? null : (loaded.resourceKey === resourceKey ? loaded.error : null)

  if (error && !result) return <section className="unavailable-card" role="alert"><span>UNAVAILABLE</span><h2>Evolution could not be loaded.</h2><p>{error}</p></section>
  if (!result) return <section className="evolution-panel evolution-loading"><p>Loading persisted lineage artifact…</p></section>
  if (result.status !== 'AVAILABLE') {
    return <section className="unavailable-card" aria-label="Evolution unavailable">
      <span>UNAVAILABLE</span><h2>Sequential snapshots are not available.</h2>
      <p>{humanize(result.reason ?? 'SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE')}</p>
    </section>
  }

  return <section className="evolution-panel" aria-label="Persisted chain evolution">
    {error ? <p className="unavailable-card" role="alert">Refresh failed; showing the previously loaded evolution. {error}</p> : null}
    <header className="evolution-heading">
      <div><p className="kicker">Persisted episode DAG</p><h2>Chain evolution</h2><p>Verified lineage artifact; this view does not recompute lifecycle at request time.</p></div>
      <div><span className="review-state review-state--available">{result.sequence_status}</span><small>{result.source_kind ?? 'UNKNOWN_SOURCE'}</small></div>
    </header>
    <div className="evolution-provenance">
      <span>{result.source_kind === 'SYNTHETIC_TEST' ? 'Synthetic test sequence' : 'Verified real sequence'}</span>
      <span>{productionLabel(result.production_validation)}</span>
      <span>Component {result.lineage_component_id}</span>
      <span>Branch {result.branch_id}</span>
    </div>
    <ol className="evolution-nodes">
      {result.nodes.map((node) => <li key={`${node.snapshot_id}@${node.snapshot_version}:${node.chain_id}`} className={node.chain_id === result.chain_id && node.snapshot_id === result.snapshot_id && node.snapshot_version === result.snapshot_version ? 'is-current' : ''}>
        <span>{compactTime(node.snapshot_time)}</span><strong>{node.chain_id}</strong><small>{node.snapshot_id}@{node.snapshot_version} · {node.branch_id}</small>
      </li>)}
    </ol>
    <div className="evolution-edge-list" role="table" aria-label="Chronological lineage edges">
      {result.edges.length === 0 ? (
        <p className="text-xs text-on-surface-variant py-2 px-1">
          Chuỗi này chưa có chuyển tiếp cross-snapshot — chỉ xuất hiện trong 1 snapshot.
        </p>
      ) : (
        <>
          <div className="evolution-edge evolution-edge--head" role="row"><span>Parent</span><span>Event</span><span>Child</span><span>Overlap</span><span>Containment</span></div>
          {result.edges.map((edge) => <div className="evolution-edge" role="row" key={`${edge.parent_snapshot_id}@${edge.parent_snapshot_version}:${edge.parent_chain_id}-${edge.child_snapshot_id}@${edge.child_snapshot_version}:${edge.child_chain_id}`}>
            <span>{edge.parent_chain_id}<small>{edge.parent_snapshot_id}@{edge.parent_snapshot_version}</small></span>
            <strong>{edge.event_type}</strong>
            <span>{edge.child_chain_id}<small>{edge.child_snapshot_id}@{edge.child_snapshot_version}</small></span>
            <span>{edge.overlap_count}</span>
            <span>{percent(edge.contain_parent)} / {percent(edge.contain_child)}</span>
          </div>)}
        </>
      )}
    </div>
  </section>
}
