import { useEffect, useState } from 'react'
import { api, type ChainOverviewSnapshotContext } from '../api'
import type { RecurrentAlarmHistory } from '../types'

type LoadState =
  | { key: string; status: 'loading' }
  | { key: string; status: 'error' }
  | { key: string; status: 'ready'; payload: RecurrentAlarmHistory }

function formatUtc(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, timeZone: 'UTC',
  }).format(date)} UTC`
}

export function RecurrentAlarmHistoryPanel({
  chainId,
  snapshotContext,
  refreshEpoch = 0,
}: {
  chainId: string
  snapshotContext?: ChainOverviewSnapshotContext
  refreshEpoch?: number
}) {
  const snapshotId = snapshotContext?.snapshot_id ?? ''
  const snapshotVersion = snapshotContext?.snapshot_version ?? ''
  const topologyVersion = snapshotContext?.topology_version ?? null
  const requestKey = `${snapshotId}:${snapshotVersion}:${chainId}:${refreshEpoch}`
  const [state, setState] = useState<LoadState>({ key: requestKey, status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    const context = snapshotId && snapshotVersion
      ? {
          snapshot_id: snapshotId,
          snapshot_version: snapshotVersion,
          topology_version: topologyVersion,
        }
      : undefined

    void api.chainRecurrentAlarms(chainId, controller.signal, context)
      .then(payload => {
        if (!controller.signal.aborted) setState({ key: requestKey, status: 'ready', payload })
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ key: requestKey, status: 'error' })
      })

    return () => controller.abort()
  }, [chainId, requestKey, snapshotId, snapshotVersion, topologyVersion])

  const activeState = state.key === requestKey ? state : { key: requestKey, status: 'loading' as const }

  return (
    <section className="rounded-lg border border-[#1b2b48] bg-[#0b1322] p-space-md">
      <div className="mb-3 flex items-center gap-2">
        <span className="material-symbols-outlined text-secondary">history</span>
        <div>
          <h3 className="font-headline-sm text-sm font-bold text-on-surface">
            Lịch sử cùng thiết bị và mã lỗi
          </h3>
          <p className="text-xs text-on-surface-variant">
            Đếm theo device_code + fault_id; mỗi alarm nguồn chỉ tính một lần.
          </p>
        </div>
      </div>

      {activeState.status === 'loading' && (
        <p role="status" className="text-sm text-on-surface-variant">Đang đọc alarm lịch sử…</p>
      )}
      {activeState.status === 'error' && (
        <p role="status" className="text-sm text-on-surface-variant">
          Chưa đọc được dữ liệu lịch sử cho chain này.
        </p>
      )}
      {activeState.status === 'ready' && (
        <>
          <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-on-surface-variant">
            <span>
              {activeState.payload.history_scope === 'MATCHING_PERSISTED_SNAPSHOTS'
                ? `Đã xét ${activeState.payload.snapshot_count} snapshot cùng nguồn/profile.`
                : 'Chỉ có dữ liệu của snapshot đang mở.'}
            </span>
            {activeState.payload.assumed_utc_count > 0 && (
              <span>Timestamp IP thiếu múi giờ được diễn giải là UTC theo pipeline hiện tại.</span>
            )}
            {activeState.payload.history_issue && (
              <span>Kho snapshot lịch sử chưa đọc được; kết quả hiện chỉ gồm snapshot đang mở.</span>
            )}
            {activeState.payload.skipped_observations > 0 && (
              <span>
                Bỏ qua {activeState.payload.skipped_observations} alarm không có thời điểm hợp lệ hoặc bị đánh dấu outlier.
              </span>
            )}
            {activeState.payload.unmatched_chain_alarm_count > 0 && (
              <span>
                {activeState.payload.unmatched_chain_alarm_count} alarm trong chain thiếu device_code hoặc fault_id.
              </span>
            )}
          </div>

          {activeState.payload.groups.length === 0 ? (
            <p className="text-sm text-on-surface-variant">
              {activeState.payload.reason === 'NO_DEVICE_FAULT_PAIRS_IN_CHAIN'
                ? 'Chain chưa có đủ device_code và fault_id để đối chiếu.'
                : 'Không có alarm lịch sử với timestamp hợp lệ để đếm.'}
            </p>
          ) : (
            <div className="space-y-2">
              {activeState.payload.groups.map(group => (
                <details
                  key={`${group.device_code}\u0000${group.fault_id}`}
                  className="rounded border border-[#1b2b48] bg-[#080d17] px-3 py-2"
                >
                  <summary className="cursor-pointer list-none text-sm text-on-surface">
                    <span className="font-semibold text-secondary">{group.device_code}</span>
                    <span className="mx-2 text-on-surface-variant">·</span>
                    <span>Mã lỗi {group.fault_id}</span>
                    <span className="ml-3 rounded bg-secondary/10 px-2 py-0.5 font-mono text-secondary">
                      {group.count} lần
                    </span>
                  </summary>
                  <div className="mt-2 space-y-1 border-t border-[#17233a] pt-2">
                    <p className="text-xs text-on-surface-variant">
                      Ghi nhận từ {formatUtc(group.first_seen)} đến {formatUtc(group.last_seen)}.
                    </p>
                    {group.occurrences.map((occurrence, index) => (
                      <div
                        key={`${occurrence.source_id}:${occurrence.alarm_id}:${occurrence.occurred_at}:${index}`}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-on-surface-variant"
                      >
                        <time dateTime={occurrence.occurred_at} className="font-mono text-on-surface">
                          {formatUtc(occurrence.occurred_at)}
                        </time>
                        <span>Alarm nguồn: <code className="text-cyan-200">{occurrence.alarm_id}</code></span>
                        <span>Nguồn: {occurrence.source_id}</span>
                        <span>
                          {occurrence.snapshots.map(ref => `${ref.snapshot_id}@${ref.snapshot_version}`).join(', ')}
                        </span>
                      </div>
                    ))}
                    {group.occurrences_truncated && (
                      <p className="text-xs text-on-surface-variant">
                        Đang hiện {group.occurrences.length} alarm gần nhất trong tổng số {group.count}.
                      </p>
                    )}
                  </div>
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
