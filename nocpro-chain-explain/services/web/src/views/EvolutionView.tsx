import { EvolutionPanel } from '../EvolutionPanel'
import type { ChainAnalysis } from '../types'

export function EvolutionView({ analysis }: { analysis: ChainAnalysis }) {
  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="rounded-lg bg-surface-container-lowest p-space-md shadow-sm">
        <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Persisted lineage only</p>
        <h1 className="font-headline-lg text-headline-lg font-bold">Evolution · {analysis.chain_id}</h1>
        <p className="mt-space-xs text-on-surface-variant">
          Timeline and transition facts are projected from one verified Evolution artifact. Missing sequential history remains unavailable.
        </p>
      </section>
      <div className="rounded-lg bg-surface-container p-space-lg shadow-md">
        <EvolutionPanel key={analysis.chain_id} chainId={analysis.chain_id} />
      </div>
    </div>
  )
}
