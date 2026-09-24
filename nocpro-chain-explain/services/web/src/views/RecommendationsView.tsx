import { useState } from 'react'
import { CounterfactualReview } from '../CounterfactualReview'

import { ValidationView } from './ValidationView'
import type { ChainAnalysis, CounterfactualJob } from '../types'
import { InfoTip } from '../components/InfoTip'
import { ExplainClarityComparisonModal } from '../components/ExplainClarityComparisonModal'
import { ManualChainSplitModal } from '../components/ManualChainSplitModal'

export function RecommendationsView({
  analysis,
  snapshotId,
  snapshotVersion,
  topologyVersion,
  readOnly = false,
  initialSubTab = 'recommendations',
  onOpenReviewLearning,
  onThresholdApplied,
  onReviewSucceeded,
}: {
  analysis: ChainAnalysis
  snapshotId?: string | null
  snapshotVersion?: string | null
  topologyVersion?: string | null
  readOnly?: boolean
  initialSubTab?: 'recommendations' | 'validation'
  onOpenReviewLearning?: () => void
  onThresholdApplied?: () => void
  onReviewSucceeded?: (job: CounterfactualJob) => void
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
      {/* Harmonized Single Header Card matching Overview, WHY, and Topology */}
      <section className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#0c1424] shadow-lg">
        <div className="flex flex-col gap-space-sm p-4 lg:flex-row lg:items-center lg:justify-between bg-[#080d17] border-b border-[#1b273e]">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-secondary/15 border border-secondary/30 shadow-sm">
              <span className="material-symbols-outlined text-secondary text-[22px]">alt_route</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <h1
                  className="font-headline-md text-base font-bold text-on-surface flex items-center gap-2"
                  title={`Recommendations · ${analysis.chain_id}`}
                >
                  <span>Phân hoạch Đối chứng &amp; Ký duyệt Vận hành</span>
                  <InfoTip text="Khám phá các phương án phân hoạch đối chứng (What-if) và tiếp nhận phản hồi phê duyệt từ Kỹ sư vận hành. Mọi kết quả là đề xuất giả định (Proposal-only, Zero live mutation)." />
                </h1>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 shrink-0">
            {!readOnly && (
              <button
                type="button"
                onClick={() => setShowManualSplitModal(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 font-code-sm text-xs text-cyan-300 hover:bg-cyan-500/25 hover:border-cyan-400 transition-all cursor-pointer font-semibold shadow-xs"
                title="Tự định nghĩa phân hoạch tách chuỗi sự cố theo nhận định của kỹ sư vận hành"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[15px]">alt_route</span>
                <span>✂️ Tự Tách Chuỗi Thủ Công</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowThresholdModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/15 px-3 py-1.5 font-code-sm text-xs text-sky-300 hover:bg-sky-500/25 hover:border-sky-400 transition-all cursor-pointer font-semibold shadow-xs"
              title="Tìm ngưỡng phân định cho lời giải thích rõ ràng và sắc nét nhất"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[15px]">tune</span>
              <span>🎯 Tối Ưu Lời Giải Thích (Tìm Ngưỡng Rõ Nhất)</span>
            </button>
          </div>
        </div>

        {/* Sub-view switcher tabs */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between px-4 py-2.5 bg-[#0c1424] gap-2">
          <div className="inline-flex rounded-lg bg-[#070e1d] p-1 border border-[#1b273e]">
            <button
              type="button"
              onClick={() => setActiveTab('recommendations')}
              className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === 'recommendations'
                  ? 'bg-secondary text-[#070e1d] shadow-sm font-bold'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-[#152033]'
              }`}
            >
              <span className="material-symbols-outlined text-[16px]">alt_route</span>
              <span>1. Đề xuất Đối chứng (Counterfactual)</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('validation')}
              className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === 'validation'
                  ? 'bg-secondary text-[#070e1d] shadow-sm font-bold'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-[#152033]'
              }`}
            >
              <span className="material-symbols-outlined text-[16px]">verified</span>
              <span>2. Ký duyệt &amp; Phân hoạch thủ công (Operator Sign-off)</span>
            </button>
          </div>
          <span className="font-code-sm text-xs text-on-surface-variant/80 hidden sm:inline">
            Fail-closed Safeguard · Zero Live Mutation
          </span>
        </div>
      </section>

      {activeTab === 'recommendations' ? (
        <div className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container shadow-md">
          <CounterfactualReview
            key={`${snapshotId ?? 'NO_SNAPSHOT'}@${snapshotVersion ?? 'NO_VERSION'}#${topologyVersion ?? 'NO_TOPOLOGY'}-${analysis.chain_id}-${reviewReloadKey}`}
            chainId={analysis.chain_id}
            snapshotId={snapshotId}
            snapshotVersion={snapshotVersion}
            topologyVersion={topologyVersion}
            readOnly={readOnly}
            hideHeader={true}
            onNavigateToValidation={() => setActiveTab('validation')}
            onOpenReviewLearning={onOpenReviewLearning}
            onOpenManualSplit={() => setShowManualSplitModal(true)}
            onReviewSucceeded={onReviewSucceeded}
          />
        </div>
      ) : (
        <ValidationView
          key={`${snapshotId ?? 'NO_SNAPSHOT'}@${snapshotVersion ?? 'NO_VERSION'}#${topologyVersion ?? 'NO_TOPOLOGY'}-${analysis.chain_id}`}
          analysis={analysis}
          snapshotId={snapshotId}
          snapshotVersion={snapshotVersion}
          topologyVersion={topologyVersion}
          onOpenManualSplit={() => setShowManualSplitModal(true)}
        />
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
