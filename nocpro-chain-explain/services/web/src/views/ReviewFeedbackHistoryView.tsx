import { Fragment, useEffect, useState, type FormEvent } from 'react'
import { api, type ChainOverviewSnapshotContext } from '../api'
import { ReviewFeedbackHistoryErrorNotice } from './ReviewFeedbackHistoryErrorNotice'
import type {
  ReviewDecision,
  ReviewFeedbackHistoryFilters,
  ReviewFeedbackHistoryItem,
  ReviewFeedbackHistoryPage,
  ReviewFeedbackLifecycleStatus,
} from '../types'

type ReviewFeedbackHistoryViewProps = {
  snapshotContext: ChainOverviewSnapshotContext | null
  onOpenChain: (item: ReviewFeedbackHistoryItem) => void
}

type DraftFilters = {
  search: string
  decision: string
  lifecycle_status: string
  reviewer: string
  since: string
  until: string
}

type LoadState =
  | { key: string; status: 'loading' }
  | { key: string; status: 'error'; message: string }
  | { key: string; status: 'ready'; page: ReviewFeedbackHistoryPage }

const EMPTY_FILTERS: DraftFilters = {
  search: '',
  decision: '',
  lifecycle_status: '',
  reviewer: '',
  since: '',
  until: '',
}

const LIFECYCLE_STYLE: Record<ReviewFeedbackLifecycleStatus, string> = {
  ACTIVE: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  SUPERSEDED: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  RETRACTED: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
}

const LIFECYCLE_RAIL: Record<ReviewFeedbackLifecycleStatus, string> = {
  ACTIVE: 'border-l-emerald-400',
  SUPERSEDED: 'border-l-amber-400',
  RETRACTED: 'border-l-slate-500',
}

function localDateTimeToIso(value: string): string | undefined {
  if (!value) return undefined
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
}

function displayDate(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('vi-VN', { dateStyle: 'medium', timeStyle: 'short' })
}

function displayDecision(decision: string): string {
  const labels: Record<string, string> = {
    APPROVE: 'Phê duyệt',
    APPROVED: 'Phê duyệt',
    REJECT: 'Từ chối',
    REJECTED: 'Từ chối',
    DEFER: 'Để xem xét',
    INSUFFICIENT_EVIDENCE: 'Thiếu bằng chứng',
    NONE_ACCEPTABLE: 'Không phương án nào phù hợp',
    MANUAL_CORRECTION: 'Chỉnh sửa thủ công',
  }
  return labels[decision] ?? decision
}

function displayLifecycle(status: ReviewFeedbackLifecycleStatus): string {
  if (status === 'ACTIVE') return 'Đang hiệu lực'
  if (status === 'SUPERSEDED') return 'Đã được thay thế'
  return 'Đã thu hồi'
}

function formatConfidence(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(value * 100)}%`
}

export function ReviewFeedbackHistoryView({
  snapshotContext,
  onOpenChain,
}: ReviewFeedbackHistoryViewProps) {
  const [draft, setDraft] = useState<DraftFilters>(EMPTY_FILTERS)
  const [filters, setFilters] = useState<ReviewFeedbackHistoryFilters>({ limit: 50 })
  const [cursor, setCursor] = useState<string | undefined>()
  const [previousCursors, setPreviousCursors] = useState<Array<string | undefined>>([])
  const [reloadEpoch, setReloadEpoch] = useState(0)
  const [expandedFeedbackId, setExpandedFeedbackId] = useState<string | null>(null)
  const requestKey = JSON.stringify({
    snapshotContext,
    filters,
    cursor,
    reloadEpoch,
  })
  const [loadState, setLoadState] = useState<LoadState>({ key: '', status: 'loading' })
  const activeLoadState = loadState.key === requestKey
    ? loadState
    : { key: requestKey, status: 'loading' as const }
  const page = activeLoadState.status === 'ready' ? activeLoadState.page : null
  const loading = activeLoadState.status === 'loading'
  const error = activeLoadState.status === 'error' ? activeLoadState.message : null

  useEffect(() => {
    if (!snapshotContext) {
      return
    }

    const controller = new AbortController()
    api.reviewFeedbackHistory(
      { ...filters, cursor },
      snapshotContext,
      controller.signal,
    )
      .then(result => {
        if (controller.signal.aborted) return
        setLoadState({ key: requestKey, status: 'ready', page: result })
      })
      .catch(cause => {
        if (controller.signal.aborted) return
        setLoadState({
          key: requestKey,
          status: 'error',
          message: cause instanceof Error ? cause.message : 'Không tải được lịch sử ký duyệt',
        })
      })

    return () => controller.abort()
  }, [filters, cursor, snapshotContext, reloadEpoch, requestKey])

  const setDraftField = (field: keyof DraftFilters, value: string) => {
    setDraft(current => ({ ...current, [field]: value }))
  }

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextFilters: ReviewFeedbackHistoryFilters = {
      limit: 50,
      search: draft.search.trim() || undefined,
      reviewer: draft.reviewer.trim() || undefined,
      decision: (draft.decision || undefined) as ReviewDecision | undefined,
      lifecycle_status: (draft.lifecycle_status || undefined) as ReviewFeedbackLifecycleStatus | undefined,
      since: localDateTimeToIso(draft.since),
      until: localDateTimeToIso(draft.until),
    }
    setFilters(nextFilters)
    setCursor(undefined)
    setPreviousCursors([])
  }

  const openNextPage = () => {
    if (!page?.next_cursor || loading) return
    setPreviousCursors(current => [...current, cursor])
    setCursor(page.next_cursor)
  }

  const openPreviousPage = () => {
    if (previousCursors.length === 0 || loading) return
    setCursor(previousCursors[previousCursors.length - 1])
    setPreviousCursors(current => current.slice(0, -1))
  }

  return (
    <section className="mx-auto w-full max-w-[1500px] space-y-space-md">
      <section className="overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-col gap-space-md border-b border-[#1a253c] bg-[#0f1728] px-space-lg py-space-md">
          <div>
            <div className="flex items-center gap-2 text-secondary">
              <span className="material-symbols-outlined text-[22px]">history_edu</span>
              <span className="font-label-caps text-xs font-bold uppercase tracking-[0.16em]">Review history</span>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <h1 className="font-headline-lg text-2xl font-bold text-on-surface">Lịch sử ký duyệt</h1>
              <span
                className="material-symbols-outlined cursor-help text-[18px] text-on-surface-variant transition-colors hover:text-secondary"
                title="Tra cứu quyết định đã lưu và mở lại đúng snapshot cùng chain để xem trong Validation."
              >
                help
              </span>
            </div>
            <p className="mt-1 max-w-3xl text-sm text-on-surface-variant">
              Tra cứu quyết định đã lưu và mở lại đúng snapshot cùng chain để xem trong Validation.
            </p>
          </div>
        </div>
      </section>

      {!snapshotContext ? (
        <div className="rounded-xl border border-[#283752] bg-[#0d1525] px-space-lg py-space-xl text-center">
          <span className="material-symbols-outlined text-3xl text-secondary">inventory_2</span>
          <h2 className="mt-2 font-semibold text-on-surface">Chọn snapshot để xem lịch sử</h2>
          <p className="mt-1 text-sm text-on-surface-variant">
            Lịch sử được giới hạn theo nguồn dữ liệu và profile của snapshot đang mở.
          </p>
        </div>
      ) : (
        <>
          <form
            onSubmit={applyFilters}
            className="grid grid-cols-1 gap-3 rounded-xl border border-[#202e47] bg-[#0c1424] p-space-md sm:grid-cols-2 xl:grid-cols-6"
          >
            <label className="space-y-1 xl:col-span-2">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Chain / phương án</span>
              <input
                value={draft.search}
                onChange={event => setDraftField('search', event.target.value)}
                placeholder="Mã chain hoặc operation"
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface placeholder:text-[#697994] focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
              />
            </label>
            <label className="space-y-1">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Quyết định</span>
              <select
                value={draft.decision}
                onChange={event => setDraftField('decision', event.target.value)}
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface focus:border-secondary focus:outline-none"
              >
                <option value="">Tất cả</option>
                <option value="APPROVE">Phê duyệt</option>
                <option value="REJECT">Từ chối</option>
                <option value="DEFER">Để xem xét</option>
                <option value="INSUFFICIENT_EVIDENCE">Thiếu bằng chứng</option>
                <option value="NONE_ACCEPTABLE">Không phương án nào phù hợp</option>
                <option value="MANUAL_CORRECTION">Chỉnh sửa thủ công</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Vòng đời</span>
              <select
                value={draft.lifecycle_status}
                onChange={event => setDraftField('lifecycle_status', event.target.value)}
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface focus:border-secondary focus:outline-none"
              >
                <option value="">Tất cả</option>
                <option value="ACTIVE">Đang hiệu lực</option>
                <option value="SUPERSEDED">Đã được thay thế</option>
                <option value="RETRACTED">Đã thu hồi</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Người duyệt</span>
              <input
                value={draft.reviewer}
                onChange={event => setDraftField('reviewer', event.target.value)}
                placeholder="Tên / tài khoản"
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface placeholder:text-[#697994] focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
              />
            </label>
            <label className="space-y-1 sm:col-span-1 xl:col-span-2">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Từ thời điểm</span>
              <input
                type="datetime-local"
                value={draft.since}
                onChange={event => setDraftField('since', event.target.value)}
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface focus:border-secondary focus:outline-none"
              />
            </label>
            <label className="space-y-1 sm:col-span-1 xl:col-span-2">
              <span className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Đến thời điểm</span>
              <input
                type="datetime-local"
                value={draft.until}
                onChange={event => setDraftField('until', event.target.value)}
                className="w-full rounded-md border border-[#2a3a56] bg-[#101a2d] px-3 py-2 text-sm text-on-surface focus:border-secondary focus:outline-none"
              />
            </label>
            <div className="flex items-end xl:col-span-2">
              <button
                type="submit"
                className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-cyan-950/30 transition hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-[#0c1424]"
              >
                <span className="material-symbols-outlined text-[17px]">filter_alt</span>
                Áp dụng bộ lọc
              </button>
            </div>
          </form>

          {page && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#1c2b43] bg-[#0b1321] px-3 py-2 text-xs text-on-surface-variant">
              <span>
                <span className="font-semibold text-on-surface">{page.items.length}</span> quyết định trên trang
                <span className="mx-2 text-[#40516d]">·</span>
                Profile <span className="font-code-sm text-secondary">{page.profile_id}</span>
              </span>
              <span className="font-code-sm text-[10px]">
                {page.history_scope === 'IN_MEMORY_ACTIVE_SNAPSHOT'
                  ? 'Nguồn: bộ nhớ phiên hiện tại'
                  : page.history_scope === 'PERSISTED_SOURCE_PROFILE_PLUS_ACTIVE'
                    ? 'Nguồn: dữ liệu đã lưu + snapshot hiện tại'
                    : 'Nguồn: dữ liệu đã lưu cùng nguồn/profile'}
              </span>
            </div>
          )}

          {error && (
            <ReviewFeedbackHistoryErrorNotice
              message={error}
              onRetry={() => setReloadEpoch(epoch => epoch + 1)}
              variant="alert"
            />
          )}

          <div className="overflow-hidden rounded-xl border border-[#202e47] bg-[#0c1424]">
            <div className="flex items-center justify-between border-b border-[#1b2940] px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.55)]" />
                <h2 className="text-sm font-bold text-on-surface">Các quyết định đã lưu</h2>
              </div>
              <span className="font-code-sm text-[10px] uppercase tracking-wider text-on-surface-variant">Mới nhất trước</span>
            </div>

            {loading ? (
              <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-on-surface-variant" role="status">
                <span className="material-symbols-outlined animate-spin text-secondary">progress_activity</span>
                Đang đọc lịch sử ký duyệt…
              </div>
            ) : error && !page ? (
              <ReviewFeedbackHistoryErrorNotice
                message={error}
                onRetry={() => setReloadEpoch(epoch => epoch + 1)}
                variant="status"
              />
            ) : page && page.items.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1060px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#1b2940] bg-[#080e19] font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                      <th className="px-4 py-3">Thời điểm / snapshot</th>
                      <th className="px-4 py-3">Chain / phương án</th>
                      <th className="px-4 py-3">Quyết định</th>
                      <th className="px-4 py-3">Người duyệt</th>
                      <th className="px-4 py-3">Trạng thái</th>
                      <th className="px-4 py-3 text-right">Mở</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#17243a]">
                    {page.items.map(item => {
                      const expanded = expandedFeedbackId === item.feedback_id
                      return (
                        <Fragment key={item.feedback_id}>
                        <tr className="group align-top hover:bg-[#111b2d]/70">
                          <td className={`border-l-2 px-4 py-3 ${LIFECYCLE_RAIL[item.lifecycle_status]}`}>
                            <div className="font-medium text-on-surface">{displayDate(item.created_at)}</div>
                            <div className="mt-1 font-code-sm text-[11px] text-on-surface-variant">
                              {item.snapshot_id}<span className="text-[#7c8da8]">@{item.snapshot_version}</span>
                            </div>
                          </td>
                          <td className="max-w-[300px] px-4 py-3">
                            <div className="truncate font-code-sm font-bold text-secondary" title={item.chain_id}>{item.chain_id}</div>
                            <div className="mt-1 truncate text-xs text-on-surface-variant" title={item.operation || 'Không có operation'}>
                              {item.operation || 'Không ghi operation'}
                              {item.candidate_id && <span className="text-[#73839d]"> · {item.candidate_id}</span>}
                            </div>
                            {item.reason && <p className="mt-2 line-clamp-2 max-w-[300px] text-xs leading-relaxed text-[#c0ccdd]">{item.reason}</p>}
                          </td>
                          <td className="px-4 py-3">
                            <span className="inline-flex rounded border border-[#30415f] bg-[#152138] px-2 py-1 text-xs font-semibold text-on-surface">
                              {displayDecision(item.decision)}
                            </span>
                            <span className="mt-1 block text-[11px] text-on-surface-variant">Tin cậy {formatConfidence(item.confidence)}</span>
                          </td>
                          <td className="px-4 py-3">
                            <div className="max-w-[170px] truncate text-sm text-on-surface" title={item.reviewer_subject}>{item.reviewer_subject}</div>
                            <div className="mt-1 text-[11px] text-on-surface-variant">{item.reviewer_role}</div>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex whitespace-nowrap rounded border px-2 py-1 text-[11px] font-semibold ${LIFECYCLE_STYLE[item.lifecycle_status]}`}>
                              <span className="mr-1.5" aria-hidden="true">{item.lifecycle_status === 'ACTIVE' ? '●' : item.lifecycle_status === 'SUPERSEDED' ? '↻' : '○'}</span>
                              {displayLifecycle(item.lifecycle_status)}
                            </span>
                            <button
                              type="button"
                              onClick={() => setExpandedFeedbackId(expanded ? null : item.feedback_id)}
                              aria-expanded={expanded}
                              className="mt-2 block text-left text-[11px] text-cyan-300 underline decoration-cyan-800 underline-offset-2 hover:text-cyan-200 focus:outline-none focus:ring-1 focus:ring-cyan-300"
                            >
                              {expanded ? 'Ẩn chi tiết' : 'Chi tiết bản ghi'}
                            </button>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              onClick={() => onOpenChain(item)}
                              className="inline-flex items-center gap-1.5 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 transition hover:border-cyan-300/70 hover:bg-cyan-400/15 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                              title={`Mở ${item.chain_id} trong snapshot ${item.snapshot_id}@${item.snapshot_version}`}
                            >
                              <span className="material-symbols-outlined text-[15px]">open_in_new</span>
                              Mở chain
                            </button>
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-t border-[#1b2940] bg-[#09111e]">
                            <td colSpan={6} className="px-4 py-4">
                              <div className="grid gap-4 text-xs md:grid-cols-3">
                                <div>
                                  <p className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Lý do / ghi chú</p>
                                  <p className="mt-1 whitespace-pre-wrap leading-relaxed text-on-surface">{item.reason || 'Không có ghi chú.'}</p>
                                  {item.reason_codes.length > 0 && <p className="mt-2 text-on-surface-variant">Mã lý do: {item.reason_codes.join(', ')}</p>}
                                </div>
                                <div>
                                  <p className="font-code-sm text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Vòng đời</p>
                                  <p className="mt-1 text-on-surface">{displayLifecycle(item.lifecycle_status)}</p>
                                  {item.lifecycle_at && <p className="mt-1 text-on-surface-variant">Thời điểm: {displayDate(item.lifecycle_at)}</p>}
                                  {item.lifecycle_reason && <p className="mt-1 text-on-surface-variant">Lý do: {item.lifecycle_reason}</p>}
                                  {item.superseded_by_id && <p className="mt-1 break-all text-amber-300">Bản thay thế: {item.superseded_by_id}</p>}
                                </div>
                                <div className="space-y-1 font-code-sm text-[10px] text-on-surface-variant">
                                  <p>Feedback: <span className="break-all text-on-surface">{item.feedback_id}</span></p>
                                  <p>Review: <span className="break-all text-on-surface">{item.review_id}</span></p>
                                  <p>Job: <span className="break-all text-on-surface">{item.job_id}</span></p>
                                  {item.candidate_id && <p>Candidate: <span className="break-all text-on-surface">{item.candidate_id}</span></p>}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex min-h-44 flex-col items-center justify-center px-6 py-10 text-center">
                <span className="material-symbols-outlined text-3xl text-[#60728f]">manage_search</span>
                <h3 className="mt-2 font-semibold text-on-surface">Chưa có quyết định phù hợp</h3>
                <p className="mt-1 max-w-lg text-sm text-on-surface-variant">
                  Thử bỏ bớt bộ lọc hoặc chọn một snapshot khác cùng nguồn dữ liệu.
                </p>
              </div>
            )}

            <footer className="flex items-center justify-between gap-3 border-t border-[#1b2940] px-4 py-3">
              <button
                type="button"
                disabled={previousCursors.length === 0 || loading}
                onClick={openPreviousPage}
                className="rounded-md border border-[#2a3a56] px-3 py-2 text-xs font-semibold text-on-surface-variant transition hover:bg-[#152238] hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-40"
              >
                Trang trước
              </button>
              <span className="font-code-sm text-[10px] text-on-surface-variant">Tối đa 50 quyết định mỗi trang</span>
              <button
                type="button"
                disabled={!page?.next_cursor || loading}
                onClick={openNextPage}
                className="inline-flex items-center gap-1 rounded-md border border-[#2a3a56] px-3 py-2 text-xs font-semibold text-on-surface-variant transition hover:bg-[#152238] hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-40"
              >
                Trang sau <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
              </button>
            </footer>
          </div>
        </>
      )}
    </section>
  )
}
