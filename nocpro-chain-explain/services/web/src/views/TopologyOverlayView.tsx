import { api } from '../api'
import { TopologyTree, type TopologyTreePayload } from '../TopologyTree'
import type { ChainAnalysis } from '../types'

interface TopologyOverlayViewProps {
  analysis: ChainAnalysis
  topologyPayload?: TopologyTreePayload | null
  onRootChange?: (resourceId: string) => void
}

export function TopologyOverlayView({ analysis, topologyPayload, onRootChange }: TopologyOverlayViewProps) {
  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="rounded-lg bg-surface-container-lowest p-space-md shadow-sm">
        <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Structural navigation · no P2 promotion</p>
        <h1 className="font-headline-lg text-headline-lg font-bold">Topology · {analysis.chain_id}</h1>
        <p className="mt-space-xs text-on-surface-variant">
          Source relations and adjacency are navigation facts only. Directed display edges do not establish operational dependency, propagation or root cause.
        </p>
      </section>

      {!topologyPayload ? (
        <section role="status" className="rounded-lg border border-surface-container-highest bg-surface-container p-space-xl text-center">
          Loading topology projection…
        </section>
      ) : (
        <TopologyTree
          key={`${topologyPayload.profile}:${topologyPayload.status === 'AVAILABLE' ? topologyPayload.tree.resource_id : topologyPayload.reason}`}
          payload={topologyPayload}
          onSearchSource={query => api.topologySearch(topologyPayload.profile, query)}
          onResolveSource={identifier => api.topologyResolve(topologyPayload.profile, identifier)}
          onRootChange={onRootChange}
        />
      )}
    </div>
  )
}
