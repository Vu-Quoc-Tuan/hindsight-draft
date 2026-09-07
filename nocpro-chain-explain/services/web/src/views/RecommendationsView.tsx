import { CounterfactualReview } from '../CounterfactualReview'
import type { ChainAnalysis } from '../types'

export function RecommendationsView({ analysis, readOnly = false }: { analysis: ChainAnalysis; readOnly?: boolean }) {
  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="rounded-lg bg-surface-container-lowest p-space-md shadow-sm">
        <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Bounded counterfactual evaluation</p>
        <h1 className="font-headline-lg text-headline-lg font-bold">Recommendations · {analysis.chain_id}</h1>
        <p className="mt-space-xs text-on-surface-variant">
          Counts, metrics and frontier state below come from Counterfactual Review v1. Proposals are never applied automatically.
        </p>
      </section>
      <div className="rounded-lg bg-surface-container p-space-lg shadow-md">
        <CounterfactualReview key={analysis.chain_id} chainId={analysis.chain_id} readOnly={readOnly} />
      </div>
    </div>
  )
}
