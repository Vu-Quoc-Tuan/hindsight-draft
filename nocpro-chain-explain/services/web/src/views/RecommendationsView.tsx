import { useState } from 'react'
import { CounterfactualReview } from '../CounterfactualReview'

import { ValidationView } from './ValidationView'
import type { ChainAnalysis } from '../types'
import { InfoTip } from '../components/InfoTip'
import { ExplainClarityComparisonModal } from '../components/ExplainClarityComparisonModal'
import { ManualChainSplitModal } from '../components/ManualChainSplitModal'

export function RecommendationsView({
  analysis,
  readOnly = false,
  initialSubTab = 'recommendations',
  onOpenReviewLearning,
  onThresholdApplied,
}: {
  analysis: ChainAnalysis
  readOnly?: boolean
  initialSubTab?: 'recommendations' | 'validation'
  onOpenReviewLearning?: () => void
  onThresholdApplied?: () => void
}) {
  const [prevInitialSubTab, setPrevInitialSubTab] = useState(initialSubTab)
  const [activeTab, setActiveTab] = useState<'recommendations' | 'validation'>(initialSubTab)
  const [showThresholdModal, setShowThresholdModal] = useState(false)
  const [showManualSplitModal, setShowManualSplitModal] = useState(false)
  const [reviewReloadKey, setReviewReloadKey] = useState(0)

  if (initialSubTab !== prevInitialSubTab) {
    setPrevInitialSubTab(initialSubTab)
    setActiveTab(initialSubTab)
  }


  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-md">
        <div className="flex flex-col gap-space-sm p-space-md lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-secondary text-[20px]">recommend</span>
            <h1
              className="font-headline-md text-base font-semibold text-on-surface flex items-center gap-2"
              title={`Recommendations · ${analysis.chain_id}`}
            >
              <span>Recommendations &amp; Validation</span>
              <InfoTip text="Khám phá các phương án phân hoạch đối chứng (What-if) và tiếp nhận phản hồi phê duyệt từ Kỹ sư vận hành. Mọi kết quả là đề xuất giả định (Proposal-only, Zero live mutation)." />
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-space-xs shrink-0">
            {!readOnly && (
              <button
                type="button"
                onClick={() => setShowManualSplitModal(true)}
                className="inline-flex items-center gap-space-xs rounded-full border border-cyan-500/40 bg-cyan-500/15 px-space-sm py-0.5 font-code-sm text-xs text-cyan-300 hover:bg-cyan-500/25 transition-all cursor-pointer font-medium"
                title="Tự định nghĩa phân hoạch tách chuỗi sự cố theo nhận định của kỹ sư vận hành"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[14px]">alt_route</span>
                ✂️ Tự Tách Chuỗi Thủ Công
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowThresholdModal(true)}
              className="inline-flex items-center gap-space-xs rounded-full border border-sky-500/40 bg-sky-500/15 px-space-sm py-0.5 font-code-sm text-xs text-sky-300 hover:bg-sky-500/25 transition-all cursor-pointer font-medium"
              title="Tìm ngưỡng phân định cho lời giải thích rõ ràng và sắc nét nhất"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[14px]">tune</span>
              🎯 Tối Ưu Lời Giải Thích (Tìm Ngưỡng Rõ Nhất)
            </button>
            <div className="inline-flex items-center gap-space-xs rounded-full border border-tertiary/30 bg-tertiary-container/15 px-space-sm py-0.5 font-code-sm text-xs text-tertiary">
              <span aria-hidden="true" className="material-symbols-outlined text-[14px]">shield</span>
              Proposal-only
            </div>
            <div className="inline-flex items-center gap-space-xs rounded-full border border-emerald-500/30 bg-emerald-500/15 px-space-sm py-0.5 font-code-sm text-xs text-emerald-300">
              <span aria-hidden="true" className="material-symbols-outlined text-[14px]">verified</span>
              Hard Gates: Enforced
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 border-t border-surface-container-high sm:grid-cols-4 bg-surface-container-low/30">
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Chain members</small>
            <strong className="font-code-lg text-base">{analysis.member_count} alarms</strong>
          </div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Candidate source</small>
            <strong className="font-code-sm text-secondary">Persisted Review v1</strong>
          </div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Execution Boundary</small>
            <strong className="font-code-sm text-emerald-400">Zero Live Mutation</strong>
          </div>
          <div className="px-space-md py-space-sm">
            <small className="block uppercase tracking-wider text-on-surface-variant text-[10px] font-bold">Analysis config</small>
            <strong className="font-code-sm text-on-surface">{analysis.config_version}</strong>
          </div>
        </div>

        {/* Sub-view switcher tabs */}
        <div className="flex items-center justify-between border-t border-surface-container-high px-space-md py-space-xs bg-surface-container-lowest">
          <div className="inline-flex rounded-lg bg-surface-container-high p-0.5 border border-surface-container-highest">
            <button
              type="button"
              onClick={() => setActiveTab('recommendations')}
              className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === 'recommendations'
                  ? 'bg-secondary text-[#070e1d] shadow-sm font-bold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">compare_arrows</span>
              <span>1. Đề xuất Phân hoạch (Counterfactual Review)</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('validation')}
              className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === 'validation'
                  ? 'bg-secondary text-[#070e1d] shadow-sm font-bold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">verified</span>
              <span>2. Phê duyệt &amp; Ký duyệt (Operator Sign-off)</span>
            </button>
          </div>
          <span className="font-code-sm text-xs text-on-surface-variant hidden sm:inline">
            Fail-closed Safeguard · Zero Live Mutation
          </span>
        </div>
      </section>

      {activeTab === 'recommendations' ? (
        <div className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container shadow-md">
          <CounterfactualReview
            key={`${analysis.chain_id}-${reviewReloadKey}`}
            chainId={analysis.chain_id}
            readOnly={readOnly}
            onNavigateToValidation={() => setActiveTab('validation')}
            onOpenReviewLearning={onOpenReviewLearning}
            onOpenManualSplit={() => setShowManualSplitModal(true)}
          />
        </div>
      ) : (
        <ValidationView analysis={analysis} />
      )}

      {showThresholdModal && (
        <ExplainClarityComparisonModal
          isOpen={showThresholdModal}
          onClose={() => setShowThresholdModal(false)}
          mode="threshold"
          chainId={analysis.chain_id}
          onThresholdApplied={onThresholdApplied}
        />
      )}

      {showManualSplitModal && (
        <ManualChainSplitModal
          isOpen={showManualSplitModal}
          onClose={() => setShowManualSplitModal(false)}
          chainId={analysis.chain_id}
          alarms={analysis.members}
          onSaved={() => setReviewReloadKey((k) => k + 1)}
        />
      )}

    </div>
  )
}
