import { CounterfactualReview } from '../CounterfactualReview'
import type { ChainAnalysis } from '../types'

export function RecommendationsView({ analysis, readOnly = false }: { analysis: ChainAnalysis; readOnly?: boolean }) {
  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-md">
        <div className="flex flex-col gap-space-md p-space-lg lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">Bounded counterfactual evaluation</p>
            <h1 className="mt-1 font-headline-lg text-headline-lg font-bold">Recommendations · {analysis.chain_id}</h1>
            <p className="mt-space-xs max-w-2xl text-on-surface-variant">Counts, metrics and frontier state come only from Counterfactual Review v1. Every result remains proposal-only.</p>
          </div>
          <div className="inline-flex items-center gap-space-xs rounded-full border border-tertiary/30 bg-tertiary-container/15 px-space-sm py-space-xs font-code-sm text-tertiary"><span aria-hidden="true" className="material-symbols-outlined text-[16px]">shield</span>No automatic apply</div>
        </div>
        <div className="grid grid-cols-1 border-t border-surface-container-high sm:grid-cols-3">
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r"><small className="block uppercase tracking-wider text-on-surface-variant">Chain members</small><strong className="font-code-lg text-lg">{analysis.member_count}</strong></div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r"><small className="block uppercase tracking-wider text-on-surface-variant">Candidate source</small><strong className="font-code-sm text-secondary">Persisted Review v1</strong></div>
          <div className="px-space-md py-space-sm"><small className="block uppercase tracking-wider text-on-surface-variant">Analysis config</small><strong className="font-code-sm">{analysis.config_version}</strong></div>
        </div>
      </section>
      <div className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container shadow-md">
        <CounterfactualReview key={analysis.chain_id} chainId={analysis.chain_id} readOnly={readOnly} />
      </div>
    </div>
  )
}
