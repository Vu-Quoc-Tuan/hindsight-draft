import { useState } from 'react'
import type { ChainOverviewCards, ChainOverviewCardContext, ChainSummary } from '../types'
import { ChainQualityCard, RepresentativeMemberCard, TopologyCoverageCard } from './ChainQualityCards'
import { EvidenceDetails } from './EvidenceDetails'

function durationLabel(seconds: number | null): string {
  if (seconds == null) return 'N/A'
  if (seconds <= 0) return 'Đồng thời (0s)'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  if (minutes === 0) return `${remainder}s`
  return `${minutes}m ${remainder}s`
}

function compactTime(value: string | null): string {
  if (!value) return 'N/A'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function ChainOverviewPreview({
  chain,
  cards,
}: {
  chain: ChainSummary
  cards: ChainOverviewCards | null
}) {
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [evidenceIds, setEvidenceIds] = useState<string[] | null>(null)
  const openEvidence = (ids?: string[]) => {
    setEvidenceIds(ids?.length ? ids : null)
    setEvidenceOpen(true)
  }
  const status = cards?.status ?? 'PENDING'
  const context: ChainOverviewCardContext | null = status === 'READY'
    ? {
        representative_member: cards?.representative_member,
        topology: cards?.topology ?? undefined,
        quality_assessment: cards?.quality_assessment ?? undefined,
        recommendations: cards?.recommendations ?? undefined,
      }
    : null
  const duration = chain.duration_seconds
  const rate = duration && duration > 0
    ? `${(chain.member_count / (duration / 60)).toFixed(1)} /phút`
    : `${chain.member_count} tức thì`

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <section className="rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm" aria-live="polite">
        <div className="flex items-start justify-between gap-space-md">
          <div className="min-w-0">
            <p className="font-label-caps text-xs font-bold uppercase tracking-[0.14em] text-secondary">Tổng quan chain</p>
            <h2 className="mt-1 truncate font-headline-lg text-2xl font-bold text-on-surface" title={chain.title}>
              {chain.title || `Chain ${chain.chain_id}`}
            </h2>
            <p className="mt-1 font-code-sm text-xs text-on-surface-variant">
              {chain.member_count} cảnh báo · thẻ bằng chứng được tải độc lập
            </p>
            <button
              type="button"
              onClick={() => openEvidence()}
              disabled={status !== 'READY'}
              className="mt-2 rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 font-code-sm text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Mở chi tiết evidence
            </button>
          </div>
          <span className="shrink-0 rounded border border-secondary/30 bg-secondary/10 px-2 py-1 font-code-sm text-[10px] font-bold text-secondary">
            {status === 'READY' ? 'ĐÃ CÓ EVIDENCE' : status === 'PENDING' ? 'ĐANG TẢI EVIDENCE' : status}
          </span>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-space-md sm:grid-cols-2 xl:grid-cols-4">
        <RepresentativeMemberCard context={context} status={status} />
        <div className="flex flex-col justify-between rounded-lg border border-[#1b2b48] bg-[#0b1322] p-space-md shadow-sm">
          <div>
            <div className="mb-1.5 flex items-center justify-between font-label-caps text-xs text-on-surface-variant">
              <span className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-secondary">
                <span className="material-symbols-outlined text-[16px]">timer</span>
                Thời lượng quan sát
              </span>
              <span className="rounded border border-surface-container-highest bg-surface-container-high px-1.5 py-0.5 font-mono text-[10px] font-bold text-on-surface-variant">
                {duration == null ? 'N/A' : duration === 0 ? 'ĐỒNG THỜI' : 'KÉO DÀI'}
              </span>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="font-headline-lg text-2xl font-bold text-on-surface">{durationLabel(duration)}</span>
              <span className="font-mono text-xs text-on-surface-variant">({chain.member_count} cảnh báo)</span>
            </div>
            <p className="mt-2 font-mono text-xs text-on-surface-variant">
              {compactTime(chain.start_time)} → {compactTime(chain.end_time)}
            </p>
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-[#17233a] pt-2 font-mono text-xs text-on-surface-variant">
            <span>Nhịp độ:</span>
            <span className="font-bold text-secondary">{rate}</span>
          </div>
        </div>
        <TopologyCoverageCard context={context} status={status} />
        <ChainQualityCard
          context={context}
          status={status}
          onOpenEvidence={status === 'READY' ? openEvidence : undefined}
        />
      </div>

      <section className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-space-md py-space-sm font-code-sm text-xs text-on-surface-variant" role="status">
        <span className="material-symbols-outlined mr-1 align-middle text-[15px] text-cyan-300">progress_activity</span>
        Đang tải phần WHY/thành viên; nhận định AI chỉ chạy riêng sau khi evidence deterministic sẵn sàng.
      </section>
      {cards ? (
        <EvidenceDetails
          chainId={chain.chain_id}
          isOpen={evidenceOpen}
          onClose={() => {
            setEvidenceOpen(false)
            setEvidenceIds(null)
          }}
          evidenceIds={evidenceIds}
          expectedContext={{
            snapshot_id: cards.snapshot_id,
            snapshot_version: cards.snapshot_version,
            topology_version: cards.topology_version,
            analysis_identity: cards.analysis_identity ?? null,
          }}
        />
      ) : null}
    </div>
  )
}
