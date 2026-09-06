import { CounterfactualReview } from '../CounterfactualReview'
import type { ChainAnalysis } from '../types'

export function ValidationView({ analysis }: { analysis: ChainAnalysis }) {
  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="rounded-lg bg-surface-container-lowest p-space-md shadow-sm">
        <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Persisted operator feedback</p>
        <h1 className="font-headline-lg text-headline-lg font-bold">Validation · {analysis.chain_id}</h1>
        <p className="mt-space-xs text-on-surface-variant">
          Approved and rejected candidate feedback is evaluation data only. It does not apply a partition, provide multi-reviewer consensus, or guarantee rollback.
        </p>
      </section>
      <div className="rounded-lg bg-surface-container p-space-lg shadow-md">
        <CounterfactualReview key={analysis.chain_id} chainId={analysis.chain_id} readOnly />
      </div>
    </div>
  )
}
