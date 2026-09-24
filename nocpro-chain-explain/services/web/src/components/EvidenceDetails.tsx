import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../api'
import type { AnalysisIdentity, EvidenceBundle, EvidencePath, EvidenceRecord } from '../types'

export type EvidenceContextExpectation = {
  snapshot_id: string
  snapshot_version: string
  topology_version?: string | null
  analysis_identity?: AnalysisIdentity | null
}

export type EvidencePathSelector = {
  resource_a: string
  resource_b: string
  relation_type: string
}

type EvidenceLoadState = {
  contextKey: string
  status: 'LOADING' | 'AVAILABLE' | 'EMPTY' | 'ERROR'
  records: EvidenceRecord[]
  cursor: string | null
  message: string | null
  truncated: boolean
}

const MAX_AUTOMATIC_EVIDENCE_PAGES = 10

function sameIdentity(left: AnalysisIdentity, right: AnalysisIdentity): boolean {
  return left.identity_version === right.identity_version
    && left.snapshot_id === right.snapshot_id
    && left.snapshot_version === right.snapshot_version
    && left.chain_id === right.chain_id
    && left.topology_version === right.topology_version
    && left.analysis_config_version === right.analysis_config_version
    && left.review_config_version === right.review_config_version
    && left.pipeline_version === right.pipeline_version
    && left.input_fingerprint === right.input_fingerprint
}

function pathMatchesSelector(path: EvidencePath | null, selector: EvidencePathSelector): boolean {
  if (!path || path.relation_types.length !== path.hop_count) return false
  return path.resource_ids.slice(0, -1).some((resourceId, index) => {
    const nextResourceId = path.resource_ids[index + 1]
    const matchesEndpoints = (
      (resourceId === selector.resource_a && nextResourceId === selector.resource_b)
      || (resourceId === selector.resource_b && nextResourceId === selector.resource_a)
    )
    return matchesEndpoints && path.relation_types[index] === selector.relation_type
  })
}

function mappingStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    EXACT: 'Khớp chính xác',
    VERIFIED_ALIAS: 'Alias đã xác minh',
    EXACT_RESOURCE_ID: 'Resource ID chính xác',
    UNIQUE_SOURCE_FIELD_MATCH: 'Khớp duy nhất theo trường nguồn',
  }
  return labels[status] ?? status
}

function reasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    TOPOLOGY_SOURCE_PARTIAL: 'Nguồn topology hiện chỉ có dữ liệu một phần.',
    TOPOLOGY_ANALYSIS_TRUNCATED: 'Phân tích topology đã bị giới hạn/cắt bớt.',
    TOPOLOGY_MAPPING_NOT_VERIFIED: 'Mapping của đường này chưa đạt trạng thái xác minh được chấp nhận.',
    TOPOLOGY_PATH_INVALID: 'Witness đường topology không khớp cấu trúc hợp lệ.',
    NO_PATH_WITHIN_DECLARED_BOUND: 'Không ghi nhận witness trong giới hạn hop đã nêu; điều này không chứng minh không có đường dài hơn.',
    PAIR_TOPOLOGY_PATH_UNAVAILABLE: 'Dep_hop không có đường khả dụng trong lần đối sánh cặp này.',
    PAIR_TOPOLOGY_PATH_INCOMPLETE: 'Metadata Dep_hop chưa đủ để xác minh từng cạnh của witness.',
    NO_PATH_WITHIN_BOUND_DOES_NOT_PROVE_GLOBAL_DISCONNECTION: 'Không thấy đường trong giới hạn đang xét không chứng minh toàn topology bị ngắt.',
    AUDIT_NOT_EVALUATED: 'Structural Audit chưa được chạy cho identity này.',
    AUDIT_ARTIFACT_UNAVAILABLE: 'Không có Audit artifact tương thích để đối chiếu.',
    REVIEW_NOT_COMPLETED: 'Counterfactual Review chưa hoàn tất.',
    REVIEW_UNAVAILABLE: 'Counterfactual Review hiện không khả dụng.',
    MEMBERSHIP_EVIDENCE_UNAVAILABLE: 'Chưa có coverage đánh giá vai trò thành viên hợp lệ.',
    TOPOLOGY_MAPPING_UNAVAILABLE: 'Chưa có coverage mapping topology hợp lệ.',
  }
  return labels[reason] ?? reason.replaceAll('_', ' ').toLowerCase()
}

function contextMismatch(
  identity: AnalysisIdentity,
  chainId: string,
  expected?: EvidenceContextExpectation,
): boolean {
  if (identity.chain_id !== chainId) return true
  if (!expected) return false
  if (
    identity.snapshot_id !== expected.snapshot_id
    || identity.snapshot_version !== expected.snapshot_version
  ) return true
  if (
    expected.topology_version !== undefined
    && identity.topology_version !== expected.topology_version
  ) return true
  return Boolean(expected.analysis_identity && !sameIdentity(identity, expected.analysis_identity))
}

export function EvidenceRecordCard({ record }: { record: EvidenceRecord }) {
  const path = record.path
  const isOverviewPath = path?.traversal_semantic === 'UNDIRECTED_STRUCTURAL_CONNECTIVITY'
  const isPairPath = path?.traversal_semantic === 'STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL'

  return (
    <article className="rounded-lg border border-[#263753] bg-[#0b1424] p-3" data-testid={`evidence-record-${record.evidence_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-code-sm text-[10px] font-bold uppercase tracking-[0.12em] text-secondary">
            {record.kind} · {record.statement_kind === 'OBSERVED' ? 'quan sát' : 'suy ra có giới hạn'}
          </p>
          <h3 className="mt-1 text-sm font-semibold text-on-surface">{record.summary}</h3>
        </div>
        <span className={`rounded border px-2 py-0.5 font-code-sm text-[10px] font-bold ${
          record.status === 'AVAILABLE'
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
            : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
        }`}>
          {record.status === 'AVAILABLE' ? 'CÓ DỮ LIỆU' : record.status === 'NOT_EVALUATED' ? 'CHƯA ĐÁNH GIÁ' : 'CHƯA KHẢ DỤNG'}
        </span>
      </div>

      {path ? (
        <div className="mt-3 rounded-md border border-cyan-500/20 bg-cyan-950/20 p-3">
          <p className="break-all font-code-sm text-xs font-semibold text-cyan-100">
            {path.resource_ids.join(' → ')}
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-on-surface-variant">Giới hạn đường</dt>
              <dd className="mt-0.5 text-on-surface">
                {path.hop_count}/{path.max_hops} hop
                {isOverviewPath ? ' · Overview, kết nối cấu trúc vô hướng' : ''}
                {isPairPath ? ' · Pair WHY Dep_hop, chính sách riêng' : ''}
              </dd>
            </div>
            <div>
              <dt className="text-on-surface-variant">Topology version</dt>
              <dd className="mt-0.5 break-all font-code-sm text-on-surface">{path.topology_version || 'Không ghim version'}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-on-surface-variant">Quan hệ trên từng cạnh</dt>
              <dd className="mt-1 space-y-1">
                {path.relation_types.map((relation, index) => (
                  <div key={`${index}-${relation}`} className="font-code-sm text-on-surface">
                    {path.resource_ids[index]} — <span className="text-cyan-200">{relation}</span> → {path.resource_ids[index + 1]}
                  </div>
                ))}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-on-surface-variant">Mapping của endpoint</dt>
              <dd className="mt-0.5 text-on-surface">
                {path.mapping_statuses.length
                  ? path.mapping_statuses.map(mappingStatusLabel).join(' · ')
                  : 'Không có trạng thái mapping đủ để xác minh'}
              </dd>
            </div>
            {path.direction_policy ? (
              <div className="sm:col-span-2">
                <dt className="text-on-surface-variant">Chính sách chiều</dt>
                <dd className="mt-0.5 text-on-surface">
                  {path.direction_policy === 'SOURCE_EDGE_DIRECTION_PRESERVED'
                    ? 'Tôn trọng chiều cạnh nguồn khi tìm Dep_hop; đây vẫn là witness topology, không tự xác nhận nhân quả.'
                    : path.direction_policy === 'UNDIRECTED'
                      ? 'Duyệt cạnh vô hướng cho connectivity; không xác nhận chiều lan truyền.'
                      : path.direction_policy}
                </dd>
              </div>
            ) : null}
          </dl>
          {path.analysis_truncated ? (
            <p className="mt-2 rounded border border-amber-500/30 bg-amber-950/30 px-2 py-1.5 text-xs text-amber-100" role="note">
              Nguồn phân tích bị cắt giới hạn; witness này không đại diện cho toàn bộ topology.
            </p>
          ) : null}
        </div>
      ) : null}

      {record.reason_codes.length > 0 ? (
        <div className="mt-3" role="note">
          <p className="text-[10px] font-bold uppercase tracking-wide text-amber-200">Vì sao thiếu hoặc bị giới hạn</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-on-surface-variant">
            {record.reason_codes.map(reason => <li key={reason}>{reasonLabel(reason)}</li>)}
          </ul>
        </div>
      ) : null}

      {record.limitations.length > 0 ? (
        <details className="mt-2 text-xs text-on-surface-variant">
          <summary className="cursor-pointer select-none">Giới hạn diễn giải</summary>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {record.limitations.map(limitation => <li key={limitation}>{reasonLabel(limitation)}</li>)}
          </ul>
        </details>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-[#1a2940] pt-2 font-code-sm text-[10px] text-on-surface-variant">
        <span>Nguồn: {record.source_artifact_id ?? 'projection theo analysis identity'}</span>
        <span>Fingerprint: {record.source_fingerprint?.slice(0, 12) ?? 'N/A'}</span>
      </div>
    </article>
  )
}

export function EvidenceDetails({
  chainId,
  title = 'Chi tiết bằng chứng',
  isOpen,
  onClose,
  expectedContext,
  inlineRecords,
  pathSelector,
  evidenceIds,
}: {
  chainId: string
  title?: string
  isOpen: boolean
  onClose: () => void
  expectedContext?: EvidenceContextExpectation
  inlineRecords?: EvidenceRecord[]
  pathSelector?: EvidencePathSelector | null
  evidenceIds?: string[] | null
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)
  const titleId = useId()
  const inlineRecordsRef = useRef(inlineRecords)
  const pathSelectorRef = useRef(pathSelector)
  const expectedContextRef = useRef(expectedContext)
  const evidenceIdsRef = useRef(evidenceIds)
  const [loadState, setLoadState] = useState<EvidenceLoadState>({
    contextKey: '', status: 'LOADING', records: [], cursor: null, message: null, truncated: false,
  })
  const inlineKey = inlineRecords?.map(record => record.evidence_id).join(',') ?? null
  const contextKey = JSON.stringify({
    chainId,
    snapshot_id: expectedContext?.snapshot_id ?? null,
    snapshot_version: expectedContext?.snapshot_version ?? null,
    topology_version: expectedContext?.topology_version ?? null,
    analysis_identity: expectedContext?.analysis_identity ?? null,
    inlineKey,
    evidenceIdKey: evidenceIds == null ? null : [...evidenceIds].sort(),
  })
  const selectorKey = pathSelector
    ? `${pathSelector.resource_a}\u0000${pathSelector.resource_b}\u0000${pathSelector.relation_type}`
    : ''
  const evidenceIdKey = evidenceIds == null
    ? 'all'
    : evidenceIds.length
      ? [...evidenceIds].sort().join(',')
      : 'none'

  useEffect(() => {
    inlineRecordsRef.current = inlineRecords
    pathSelectorRef.current = pathSelector
    expectedContextRef.current = expectedContext
    evidenceIdsRef.current = evidenceIds
  }, [inlineRecords, pathSelector, expectedContext, evidenceIds])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (isOpen && !dialog.open) dialog.showModal()
    else if (!isOpen && dialog.open) dialog.close()
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const currentInlineRecords = inlineRecordsRef.current
    const currentPathSelector = pathSelectorRef.current
    const requestedEvidenceIds = evidenceIdsRef.current
    const requestedEvidenceIdSet = requestedEvidenceIds == null
      ? null
      : new Set(requestedEvidenceIds)
    if (currentInlineRecords !== undefined) {
      const selected = currentInlineRecords.filter(record =>
        (!currentPathSelector || pathMatchesSelector(record.path, currentPathSelector))
        && (!requestedEvidenceIdSet || requestedEvidenceIdSet.has(record.evidence_id)),
      )
      setLoadState({
        contextKey,
        status: selected.length ? 'AVAILABLE' : 'EMPTY',
        records: selected,
        cursor: null,
        message: null,
        truncated: false,
      })
      return
    }

    const controller = new AbortController()
    setLoadState({ contextKey, status: 'LOADING', records: [], cursor: null, message: null, truncated: false })

    const load = async () => {
      try {
        let cursor: string | undefined
        const records: EvidenceRecord[] = []
        let nextCursor: string | null = null
        let truncated = false
        for (let pageIndex = 0; pageIndex < MAX_AUTOMATIC_EVIDENCE_PAGES; pageIndex += 1) {
          const page: EvidenceBundle = await api.chainEvidence(
            chainId,
            { limit: 100, cursor },
            controller.signal,
          )
          if (controller.signal.aborted) return
          if (contextMismatch(page.analysis_identity, chainId, expectedContextRef.current)) {
            setLoadState({
              contextKey,
              status: 'ERROR',
              records: [],
              cursor: null,
              message: 'Bằng chứng trả về thuộc snapshot/topology khác; hãy tải lại trang chain hiện tại.',
              truncated: false,
            })
            return
          }
          records.push(...page.records)
          nextCursor = page.next_cursor
          if (!page.truncated || !nextCursor) {
            nextCursor = null
            break
          }
          cursor = nextCursor
          truncated = pageIndex === MAX_AUTOMATIC_EVIDENCE_PAGES - 1
        }
        const selected = records.filter(record =>
          (!currentPathSelector || pathMatchesSelector(record.path, currentPathSelector))
          && (!requestedEvidenceIdSet || requestedEvidenceIdSet.has(record.evidence_id)),
        )
        setLoadState({
          contextKey,
          status: selected.length ? 'AVAILABLE' : 'EMPTY',
          records: selected,
          cursor: truncated ? nextCursor : null,
          message: null,
          truncated,
        })
      } catch (cause) {
        if (controller.signal.aborted) return
        setLoadState({
          contextKey,
          status: 'ERROR',
          records: [],
          cursor: null,
          message: cause instanceof Error ? cause.message : 'Không tải được bằng chứng cho chain này.',
          truncated: false,
        })
      }
    }

    void load()
    return () => controller.abort()
  }, [isOpen, chainId, contextKey, inlineKey, selectorKey, evidenceIdKey])

  const visibleState = loadState.contextKey === contextKey
    ? loadState
    : { contextKey, status: 'LOADING' as const, records: [], cursor: null, message: null, truncated: false }
  const heading = title

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={event => {
        event.preventDefault()
        onClose()
      }}
      className="m-auto max-h-[min(90dvh,900px)] w-[min(960px,calc(100%-24px))] max-w-none overflow-hidden rounded-xl border border-[#314566] bg-[#0b1322] p-0 text-on-surface shadow-2xl backdrop:bg-slate-950/75"
      data-testid="evidence-details-dialog"
    >
      <div className="flex max-h-[min(90dvh,900px)] flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-[#243650] bg-[#101a2c] px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <p className="font-label-caps text-[10px] font-bold uppercase tracking-[0.16em] text-secondary">Evidence · {chainId}</p>
            <h2 id={titleId} className="mt-1 text-lg font-bold text-on-surface">{heading}</h2>
            <p className="mt-1 text-xs text-on-surface-variant">Đọc artifact đã có; không chạy lại phân tích hoặc tạo job.</p>
          </div>
          <button
            type="button"
            autoFocus
            onClick={onClose}
            aria-label="Đóng chi tiết bằng chứng"
            className="grid h-9 w-9 shrink-0 place-items-center rounded border border-[#344762] text-on-surface-variant hover:bg-[#1b2b43] hover:text-on-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </header>

        <div className="min-h-0 space-y-3 overflow-y-auto p-3 sm:p-5">
          {visibleState.status === 'LOADING' ? (
            <p role="status" className="rounded-lg border border-[#263753] bg-[#0b1424] p-5 text-sm text-on-surface-variant">Đang đọc evidence artifact đã lưu…</p>
          ) : null}
          {visibleState.status === 'ERROR' ? (
            <div role="alert" className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-4 text-sm text-amber-100">
              <p className="font-semibold">Chưa thể mở chi tiết evidence</p>
              <p className="mt-1 break-words text-xs">{visibleState.message}</p>
            </div>
          ) : null}
          {visibleState.status === 'EMPTY' ? (
            <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-4">
              <p className="text-sm font-semibold text-amber-100">
                {pathSelector
                  ? 'Không có witness phù hợp trong artifact hiện hành.'
                  : evidenceIds?.length
                    ? 'Các tham chiếu này không còn trong evidence bundle hiện hành.'
                    : 'Chưa có record evidence khả dụng cho phạm vi này.'}
              </p>
              <p className="mt-1 text-xs text-on-surface-variant">
                {pathSelector
                  ? 'Cần snapshot và topology version khớp, mapping được xác minh, cùng path nằm trong giới hạn hop của phép tính gốc. Không tìm thấy path trong giới hạn không chứng minh toàn topology bị ngắt.'
                  : evidenceIds?.length
                    ? 'Có thể artifact đã được cập nhật; hãy tải lại Overview để lấy tham chiếu mới nhất.'
                    : 'Thiếu dữ liệu nguồn tương thích; mở record sẽ không chạy lại phân tích hoặc tạo job.'}
              </p>
            </div>
          ) : null}
          {visibleState.records.map(record => <EvidenceRecordCard key={record.evidence_id} record={record} />)}
          {visibleState.truncated ? (
            <p role="status" className="text-xs text-amber-100">
              Còn nhiều bản ghi chưa tải tự động; hãy dùng phân trang API để tiếp tục tra cứu.
            </p>
          ) : null}
        </div>
      </div>
    </dialog>
  )
}
