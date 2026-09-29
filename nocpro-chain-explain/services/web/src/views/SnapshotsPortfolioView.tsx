import { useCallback, useMemo } from 'react'

import type { HeaderSnapshotItem } from '../components/NocHeader'
import type { ChainQualitySummary } from '../types'

interface SnapshotsPortfolioViewProps {
  snapshots: HeaderSnapshotItem[]
  summaries: ChainQualitySummary[]
  activeSnapshotId: string | null
  activeSnapshotVersion?: string | null
  selectingSnapshotId: string | null
  qualitySummaryError?: string | null
  catalogError?: string | null
  onSelectSnapshot: (snapshotId: string, profile: HeaderSnapshotItem['profile'], snapshotVersion?: string | null) => void
}

function processingProgress(summary: ChainQualitySummary | undefined): { processed: number; percent: number } {
  if (!summary) return { processed: 0, percent: 0 }
  const processed = summary.sturdy_count + summary.review_count + (summary.unavailable_count ?? 0)
  const percent = summary.eligible_chain_count > 0
    ? Math.min(100, Math.round((processed / summary.eligible_chain_count) * 100))
    : 0
  return { processed, percent }
}

type SnapshotPortfolioStatus = 'HEALTHY' | 'REVIEW' | 'RUNNING' | 'INSUFFICIENT'

function classifySnapshot(summary: ChainQualitySummary | undefined): SnapshotPortfolioStatus {
  if (!summary) return 'INSUFFICIENT'
  if (summary.review_count > 0) return 'REVIEW'
  if (summary.evaluating_count > 0 || summary.unevaluated_count > 0) return 'RUNNING'

  const unavailable = summary.unavailable_count ?? 0
  const completed = summary.sturdy_count + summary.review_count
  if (summary.eligible_chain_count === 0 || completed === 0 || unavailable > 0) return 'INSUFFICIENT'
  return completed === summary.eligible_chain_count ? 'HEALTHY' : 'INSUFFICIENT'
}

const STATUS_META: Record<SnapshotPortfolioStatus, { label: string; shortLabel: string; color: string; segment: string }> = {
  HEALTHY: { label: 'Ổn', shortLabel: 'ỔN', color: 'text-emerald-300', segment: 'bg-emerald-400' },
  REVIEW: { label: 'Cần xem', shortLabel: 'CẦN XEM', color: 'text-amber-300', segment: 'bg-amber-400' },
  RUNNING: { label: 'Đang đánh giá', shortLabel: 'ĐANG ĐÁNH GIÁ', color: 'text-cyan-300', segment: 'bg-cyan-400' },
  INSUFFICIENT: { label: 'Chưa đủ dữ liệu', shortLabel: 'CHƯA ĐỦ DỮ LIỆU', color: 'text-slate-300', segment: 'bg-slate-400' },
}

export function SnapshotsPortfolioView({
  snapshots,
  summaries,
  activeSnapshotId,
  activeSnapshotVersion,
  selectingSnapshotId,
  onSelectSnapshot,
  qualitySummaryError,
  catalogError,
}: SnapshotsPortfolioViewProps) {
  const summaryBySnapshot = useMemo(() => {
    const result = new Map<string, ChainQualitySummary>()
    for (const summary of summaries) {
      result.set(`${summary.snapshot_id}\u0000${summary.snapshot_version}`, summary)
      // Older catalog fixtures and rolling deployments may not expose the
      // version yet. Keep an ID-only compatibility key without allowing it
      // to override an exact versioned identity.
      if (!result.has(summary.snapshot_id)) result.set(summary.snapshot_id, summary)
    }
    return result
  }, [summaries])

  const summaryForSnapshot = useCallback((snapshot: HeaderSnapshotItem) => (
    summaryBySnapshot.get(`${snapshot.snapshot_id}\u0000${snapshot.snapshot_version ?? ''}`)
    ?? (!snapshot.snapshot_version ? summaryBySnapshot.get(snapshot.snapshot_id) : undefined)
  ), [summaryBySnapshot])

  const statusCounts = useMemo(() => {
    const counts: Record<SnapshotPortfolioStatus, number> = { HEALTHY: 0, REVIEW: 0, RUNNING: 0, INSUFFICIENT: 0 }
    for (const snapshot of snapshots) {
      counts[classifySnapshot(summaryForSnapshot(snapshot))] += 1
    }
    return counts
  }, [snapshots, summaryForSnapshot])
  const totalSnapshots = snapshots.length
  const percentage = (status: SnapshotPortfolioStatus) => totalSnapshots > 0 ? (statusCounts[status] / totalSnapshots) * 100 : 0
  const statusOrder: SnapshotPortfolioStatus[] = ['HEALTHY', 'REVIEW', 'RUNNING', 'INSUFFICIENT']

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn">
      <section className="overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-col gap-space-md border-b border-[#1a253c] bg-[#0f1728] px-space-lg py-space-md lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-secondary">
              <span className="material-symbols-outlined text-[22px]">dataset</span>
              <span className="font-label-caps text-xs font-bold uppercase tracking-[0.16em]">Snapshot portfolio</span>
            </div>
            <h1 className="mt-2 font-headline-lg text-2xl font-bold text-on-surface">Toàn bộ dữ liệu đã tiếp nhận</h1>
            <p className="mt-1 max-w-3xl text-sm text-on-surface-variant">
              Theo dõi tiến độ đánh giá deterministic của từng snapshot; việc đánh giá chạy nền, không phụ thuộc snapshot đang mở.
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-2 font-code-sm text-xs">
            <div className="rounded-lg border border-[#22304c] bg-[#080d17] px-3 py-2">
              <span className="block text-on-surface-variant">Snapshot</span>
              <strong className="text-lg text-on-surface">{totalSnapshots.toLocaleString()}</strong>
            </div>
            <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/5 px-3 py-2">
              <span className="block text-cyan-300">Đang đánh giá</span>
              <strong className="text-lg text-cyan-300">{statusCounts.RUNNING.toLocaleString()}</strong>
            </div>
          </div>
        </div>
      </section>

      {(qualitySummaryError || catalogError) ? (
        <section className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-space-md py-space-sm text-sm text-amber-200" role="alert">
          <div className="flex items-start gap-2">
            <span className="material-symbols-outlined text-[18px]">warning</span>
            <div>
              <strong>Không thể cập nhật đầy đủ dữ liệu tổng quan.</strong>
              {qualitySummaryError ? <p className="mt-1 font-code-sm text-xs">Kết quả đánh giá: {qualitySummaryError}</p> : null}
              {catalogError ? <p className="mt-1 font-code-sm text-xs">Catalog snapshot: {catalogError}</p> : null}
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm" aria-label="Snapshot status summary">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-headline-md text-lg font-bold text-on-surface">Tổng quan trạng thái snapshot</h2>
            <p className="mt-1 text-xs text-on-surface-variant">Tỷ lệ tính trên toàn bộ snapshot đang có trong catalog; trạng thái tự cập nhật khi catalog hoặc kết quả đánh giá thay đổi.</p>
          </div>
          <span className="font-code-sm text-xs text-on-surface-variant">{totalSnapshots} snapshot</span>
        </div>
        <div className="mt-space-md grid grid-cols-2 gap-2 md:grid-cols-4">
          {statusOrder.map(status => (
            <div key={status} className="rounded-lg border border-[#22304c] bg-[#080d17] px-3 py-2">
              <span className={`block text-xs ${STATUS_META[status].color}`}>{STATUS_META[status].label}</span>
              <strong className={`mt-1 block text-2xl ${STATUS_META[status].color}`}>{statusCounts[status]}</strong>
              <span className="font-code-sm text-[11px] text-on-surface-variant">{percentage(status).toFixed(1)}%</span>
            </div>
          ))}
        </div>
        <div className="mt-space-md">
          <div className="flex h-3 overflow-hidden rounded-full bg-[#080d17]" aria-label={statusOrder.map(status => `${STATUS_META[status].label}: ${statusCounts[status]} (${percentage(status).toFixed(1)}%)`).join(', ')}>
            {statusOrder.map(status => <span key={status} className={`${STATUS_META[status].segment} transition-all duration-500`} style={{ width: `${percentage(status)}%` }} />)}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-code-sm text-[11px]">
            {statusOrder.map(status => <span key={status} className={STATUS_META[status].color}>● {STATUS_META[status].label}: {statusCounts[status]} ({percentage(status).toFixed(1)}%)</span>)}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-space-md xl:grid-cols-2" aria-label="Snapshot processing status">
        {snapshots.map(snapshot => {
          const summary = summaryForSnapshot(snapshot)
          const status = classifySnapshot(summary)
          const active = snapshot.snapshot_id === activeSnapshotId && (
            !snapshot.snapshot_version || !activeSnapshotVersion || snapshot.snapshot_version === activeSnapshotVersion
          )
          const loading = `${snapshot.snapshot_id}@${snapshot.snapshot_version ?? 'latest'}` === selectingSnapshotId
          const assessed = summary ? summary.sturdy_count + summary.review_count : 0
          const { processed, percent } = processingProgress(summary)
          const unresolved = summary ? summary.evaluating_count + summary.unevaluated_count : 0
          const sturdyShare = summary?.eligible_chain_count ? summary.sturdy_count / summary.eligible_chain_count * 100 : 0
          const reviewShare = summary?.eligible_chain_count ? summary.review_count / summary.eligible_chain_count * 100 : 0
          const unavailableShare = summary?.eligible_chain_count ? (summary.unavailable_count ?? 0) / summary.eligible_chain_count * 100 : 0
          const evaluatingShare = summary?.eligible_chain_count ? summary.evaluating_count / summary.eligible_chain_count * 100 : 0
          return (
            <article key={`${snapshot.snapshot_id}@${snapshot.snapshot_version ?? 'unknown'}`} className={`rounded-xl border bg-[#0c1322] p-space-md shadow-sm transition-colors ${active ? 'border-secondary/60' : 'border-[#1e2b44] hover:border-[#344870]'}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate font-headline-md text-lg font-bold text-on-surface" title={snapshot.name}>{snapshot.name}</h2>
                    {active ? <span className="rounded border border-secondary/30 bg-secondary/10 px-2 py-0.5 font-code-sm text-[10px] font-bold text-secondary">ĐANG MỞ</span> : null}
                    <span className="rounded border border-[#293754] bg-[#141d30] px-2 py-0.5 font-code-sm text-[10px] text-on-surface-variant">{snapshot.profile}</span>
                    <span className={`rounded border border-current/30 bg-current/10 px-2 py-0.5 font-code-sm text-[10px] font-bold ${STATUS_META[status].color}`}>{STATUS_META[status].shortLabel}</span>
                  </div>
                  <p className="mt-1 truncate font-code-sm text-xs text-primary" title={snapshot.snapshot_id}>{snapshot.snapshot_id}{summary ? `@${summary.snapshot_version}` : ''}</p>
                </div>
                <button
                  type="button"
                  disabled={!snapshot.available || loading || active}
                  onClick={() => onSelectSnapshot(snapshot.snapshot_id, snapshot.profile, snapshot.snapshot_version)}
                  className="shrink-0 rounded-lg border border-secondary/40 bg-secondary/10 px-3 py-1.5 font-code-sm text-xs font-bold text-secondary transition-colors hover:bg-secondary hover:text-[#07101d] disabled:cursor-default disabled:opacity-50"
                >
                  {loading ? 'Đang mở…' : active ? 'Đang xem' : 'Mở snapshot →'}
                </button>
              </div>

              <div className="mt-space-md grid grid-cols-3 gap-2 font-code-sm text-xs">
                <div><span className="block text-on-surface-variant">Cảnh báo</span><strong className="text-base text-on-surface">{snapshot.alarm_count.toLocaleString()}</strong></div>
                <div><span className="block text-on-surface-variant">Chain</span><strong className="text-base text-on-surface">{snapshot.chain_count.toLocaleString()}</strong></div>
                <div><span className="block text-on-surface-variant">Đã xử lý</span><strong className="text-base text-on-surface">{summary ? `${processed}/${summary.eligible_chain_count}` : 'Chưa nạp'}</strong></div>
              </div>

              {summary ? (
                <div className="mt-space-md border-t border-[#1a253c] pt-space-sm">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-on-surface-variant">Tiến độ xử lý chain nhiều cảnh báo</span>
                    <strong className="font-code-sm text-on-surface">{percent}%</strong>
                  </div>
                  <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-[#080d17]" aria-label={`${processed} of ${summary.eligible_chain_count} eligible chains processed; ${assessed} scored, ${summary.unavailable_count ?? 0} unavailable`}>
                    <span className="bg-emerald-400" style={{ width: `${sturdyShare}%` }} />
                    <span className="bg-amber-400" style={{ width: `${reviewShare}%` }} />
                    <span className="bg-slate-400" style={{ width: `${unavailableShare}%` }} />
                    <span className="bg-cyan-400/70" style={{ width: `${evaluatingShare}%` }} />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-code-sm text-[11px]">
                    <span className="text-on-surface-variant">● {assessed} có điểm</span>
                    <span className="text-emerald-300">● {summary.sturdy_count} vững</span>
                    <span className="text-amber-300">● {summary.review_count} cần xem</span>
                    <span className="text-cyan-300">● {summary.evaluating_count} đang chạy</span>
                    <span className="text-on-surface-variant">○ {summary.unevaluated_count} chờ đánh giá</span>
                    <span className="text-[#94a3b8]">◌ {summary.unavailable_count ?? 0} thiếu evidence</span>
                    <span className="text-[#64748b]">{summary.not_applicable_count} singleton không chấm</span>
                  </div>
                </div>
              ) : (
                <p className="mt-space-md border-t border-[#1a253c] pt-space-sm text-xs text-on-surface-variant">
                  Chưa có dữ liệu đánh giá được lưu cho snapshot này.
                </p>
              )}
              <p className="mt-2 line-clamp-2 text-xs text-on-surface-variant">{snapshot.description}</p>
              {unresolved > 0 && summary?.evaluating_count ? <span className="sr-only">Background evaluation is running</span> : null}
            </article>
          )
        })}
      </section>
    </div>
  )
}
