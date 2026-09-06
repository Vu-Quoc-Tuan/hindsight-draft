import type { ChainAnalysis } from '../types'
import { CounterfactualReview } from '../CounterfactualReview'

interface RecommendationsViewProps {
  analysis: ChainAnalysis
}

export function RecommendationsView({
  analysis,
}: RecommendationsViewProps) {
  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* KPI / Counterfactual High-Luminance Strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-space-md">
        <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">CANDIDATES GENERATED</span>
            <span className="material-symbols-outlined text-[16px] text-secondary">tune</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-xl text-headline-xl text-on-surface font-bold">5</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Ops Synthesized</span>
          </div>
          <div className="flex items-center gap-space-xs font-code-sm text-code-sm">
            <span className="text-secondary font-semibold">2 Recommended</span>
            <span className="text-on-surface-variant">•</span>
            <span className="text-tertiary">2 Marginal</span>
            <span className="text-on-surface-variant">•</span>
            <span className="text-primary">1 Rejected</span>
          </div>
        </div>

        <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">MAX MODULARITY GAIN</span>
            <span className="material-symbols-outlined text-[16px] text-secondary">insights</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-xl text-headline-xl text-secondary font-bold">+0.142</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">ΔQ Score</span>
          </div>
          <div className="w-full bg-surface-container-low h-1 rounded overflow-hidden">
            <div className="bg-secondary h-full" style={{ width: '78%' }}></div>
          </div>
        </div>

        <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">FALSE CORRELATION CUT</span>
            <span className="material-symbols-outlined text-[16px] text-secondary">filter_alt_off</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-xl text-headline-xl text-on-surface font-bold">99.4%</span>
            <span className="font-code-sm text-code-sm text-secondary font-semibold">Filtered Noise</span>
          </div>
          <span className="font-code-sm text-code-sm text-on-surface-variant">Prunes 4 cross-layer phantom links</span>
        </div>

        <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">REVERSIBLE GUARANTEE</span>
            <span className="material-symbols-outlined text-[16px] text-tertiary">history</span>
          </div>
          <div className="flex items-baseline gap-space-xs my-space-xs">
            <span className="font-headline-xl text-headline-xl text-tertiary font-bold">30 min</span>
            <span className="font-code-sm text-code-sm text-on-surface-variant">Staging window</span>
          </div>
          <span className="font-code-sm text-code-sm text-on-surface-variant">Fail-closed zero disruption SLA</span>
        </div>
      </div>

      {/* Embedded CounterfactualReview Component */}
      <div className="bg-surface-container rounded-lg p-space-lg shadow-md">
        <CounterfactualReview chainId={analysis.chain_id} />
      </div>
    </div>
  )
}
