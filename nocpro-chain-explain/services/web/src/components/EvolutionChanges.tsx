import { useEffect, useState } from 'react'

import { ApiError, api } from '../api'
import { humanize } from '../format'
import type { EvolutionChanges as Changes, EvolutionEndpoint, EvolutionReceiptChoice } from '../types'

type LoadError = { message: string; expected: boolean }
type Loaded = { key: string; value: Changes | null; error: LoadError | null }
type ReceiptOptions = { key: string; parent: EvolutionReceiptChoice[]; child: EvolutionReceiptChoice[] }

const missingData = 'Chưa có dữ liệu'

const reasonLabels: Record<string, string> = {
  PARENT_SELECTION_REQUIRED: 'Cần chọn một chuyển tiếp trước để xem chi tiết.',
  SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE: 'Chưa có snapshot trước để đối chiếu.',
  LINEAGE_EDGE_UNAVAILABLE: 'Không có bằng chứng lineage cho chuyển tiếp này.',
  SNAPSHOT_TIME_UNAVAILABLE: 'Thiếu thời điểm của một trong hai snapshot.',
  SNAPSHOT_TIME_OUT_OF_ORDER: 'Thời gian hai snapshot không xác lập được thứ tự trước–sau.',
  CANONICAL_MEMBERSHIP_UNAVAILABLE: 'Chưa đủ dữ liệu thành viên chain ở cả hai snapshot.',
  LINEAGE_OVERLAP_MISMATCH: 'Số thành viên không khớp với lineage đã lưu.',
  QUALITY_RECEIPT_UNAVAILABLE: 'Thiếu biên nhận đánh giá lịch sử.',
  QUALITY_NOT_READY: 'Một trong hai lần đánh giá chưa sẵn sàng.',
  PRECISE_SCORE_UNAVAILABLE: 'Thiếu điểm chính xác để so sánh.',
  QUALITY_METHOD_MISMATCH: 'Hai lần đánh giá dùng phương pháp khác nhau.',
  READINESS_POLICY_MISMATCH: 'Chính sách sẵn sàng đánh giá đã thay đổi.',
  ANALYSIS_CONFIG_MISMATCH: 'Cấu hình phân tích đã thay đổi.',
  REVIEW_CONFIG_MISMATCH: 'Cấu hình review đã thay đổi.',
  PIPELINE_MISMATCH: 'Phiên bản pipeline đã thay đổi.',
  TOPOLOGY_VERSION_MISMATCH: 'Phiên bản topology đã thay đổi.',
  RECEIPT_SELECTION_REQUIRED: 'Có nhiều biên nhận khác nhau; hãy chọn biên nhận cần đối chiếu.',
  RECEIPT_IDENTITY_MISMATCH: 'Biên nhận không khớp với snapshot hoặc chain đã chọn.',
}

function statusText(value: Changes) {
  const label = value.status === 'AVAILABLE'
    ? 'Đã có dữ liệu xác minh'
    : value.status === 'PARTIAL' ? 'Có một phần dữ liệu' : 'Chưa đủ dữ liệu'
  if (value.reason_codes.length) return `${label} · ${value.reason_codes.map(code => reasonLabels[code] ?? humanize(code)).join(' ')}`
  return value.status === 'AVAILABLE' ? `${label}.` : `${label} để đối chiếu.`
}

function loadError(cause: unknown): LoadError {
  if (cause instanceof ApiError) {
    if (cause.message === 'EVOLUTION_CHANGES_DISABLED') {
      return { message: 'Chức năng đối chiếu thay đổi chưa được bật trên máy chủ.', expected: true }
    }
    if (cause.message === 'EVOLUTION_REPOSITORY_UNAVAILABLE') {
      return { message: 'Kho lineage chưa sẵn sàng để đối chiếu.', expected: true }
    }
    if (cause.message === 'EVOLUTION_DATABASE_UNAVAILABLE') {
      return { message: 'Kho dữ liệu tạm thời không sẵn sàng; hãy thử lại sau.', expected: false }
    }
    if (cause.message === 'STALE_ANALYSIS_CONTEXT') {
      return { message: 'Snapshot đã đổi trong lúc tải; hãy mở lại phần Evolution.', expected: true }
    }
    return { message: 'Không tải được dữ liệu chuyển tiếp. Kiểm tra kết nối rồi thử lại.', expected: false }
  }
  return { message: cause instanceof Error ? cause.message : 'Không tải được dữ liệu chuyển tiếp.', expected: false }
}

function explanationText(code: string, facts: Changes) {
  switch (code) {
    case 'MEMBERS_ENTERED_CHAIN': return `${facts.membership?.added_count ?? 0} alarm được thêm vào chain.`
    case 'MEMBERS_LEFT_CHAIN': return `${facts.membership?.removed_count ?? 0} alarm rời chain; điều này không đồng nghĩa alarm đã clear.`
    case 'CONTEXT_CHANGED': return `Bối cảnh đối chiếu thay đổi: ${facts.context_changes.map(change => humanize(change.field)).join(', ')}.`
    case 'QUALITY_NOT_COMPARABLE': return 'Không thể so sánh trực tiếp điểm vì dữ liệu hoặc cấu hình đánh giá không tương thích.'
    case 'TIME_ORDER_UNAVAILABLE': return 'Chưa xác lập được thứ tự thời gian giữa hai snapshot.'
    default: return 'Có dữ kiện giải thích bổ sung từ API.'
  }
}

function endpointKey(endpoint: EvolutionEndpoint) {
  return JSON.stringify([endpoint.snapshot_id, endpoint.snapshot_version, endpoint.chain_id])
}

function endpointLabel(endpoint: EvolutionEndpoint) {
  return `${endpoint.chain_id} · ${endpoint.snapshot_id}@${endpoint.snapshot_version}`
}

function ReceiptPicker({ label, choices, truncated, selected, onSelect }: {
  label: string
  choices: EvolutionReceiptChoice[]
  truncated: boolean
  selected: string | null
  onSelect: (id: string) => void
}) {
  if (choices.length === 0) return null
  return <div className="evolution-changes__receipt">
    <label>Biên nhận {label}
      <select value={selected ?? ''} onChange={event => onSelect(event.target.value)}>
        <option value="">Chọn biên nhận lịch sử</option>
        {choices.map(choice => <option key={choice.receipt_id} value={choice.receipt_id}>
          {choice.receipt_id} · {choice.artifact_revision} · {choice.created_at}
        </option>)}
      </select>
    </label>
    {truncated ? <small>Danh sách biên nhận bị cắt; chỉ hiển thị 100 mục đầu.</small> : null}
  </div>
}

export function EvolutionChanges({ child, refreshEpoch = 0 }: { child: EvolutionEndpoint; refreshEpoch?: number }) {
  const { snapshot_id, snapshot_version, chain_id } = child
  const childKey = JSON.stringify([snapshot_id, snapshot_version, chain_id])
  const fetchKey = JSON.stringify([childKey, refreshEpoch])
  const [discovery, setDiscovery] = useState<Loaded>({ key: '', value: null, error: null })
  const [parent, setParent] = useState<EvolutionEndpoint | null>(null)
  const [parentReceiptId, setParentReceiptId] = useState<string | null>(null)
  const [childReceiptId, setChildReceiptId] = useState<string | null>(null)
  const [selected, setSelected] = useState<Loaded>({ key: '', value: null, error: null })
  const [receiptOptions, setReceiptOptions] = useState<ReceiptOptions>({ key: '', parent: [], child: [] })
  const parentKey = parent ? endpointKey(parent) : ''
  const selectionKey = JSON.stringify([fetchKey, parentKey, parentReceiptId, childReceiptId])

  useEffect(() => {
    const controller = new AbortController()
    let ignore = false
    void api.evolutionChanges(chain_id, {}, controller.signal, { snapshot_id, snapshot_version })
      .then(value => {
        if (ignore) return
        if (endpointKey(value.child) !== childKey || value.parent !== null) throw new Error('EVOLUTION_CONTEXT_MISMATCH')
        setDiscovery({ key: fetchKey, value, error: null })
      })
      .catch(cause => {
        if (ignore) return
        setDiscovery({ key: fetchKey, value: null, error: loadError(cause) })
      })
    return () => { ignore = true; controller.abort() }
  }, [chain_id, snapshot_id, snapshot_version, childKey, fetchKey])

  useEffect(() => {
    if (!parent) return
    const controller = new AbortController()
    let ignore = false
    void api.evolutionChanges(chain_id, {
      parent,
      ...(parentReceiptId ? { parentReceiptId } : {}),
      ...(childReceiptId ? { childReceiptId } : {}),
    }, controller.signal, { snapshot_id, snapshot_version })
      .then(value => {
        if (ignore) return
        if (endpointKey(value.child) !== childKey || !value.parent || endpointKey(value.parent) !== parentKey) {
          throw new Error('EVOLUTION_CONTEXT_MISMATCH')
        }
        if (!parentReceiptId && !childReceiptId) {
          setReceiptOptions({ key: parentKey, parent: value.parent_receipt_choices, child: value.child_receipt_choices })
        }
        setSelected({ key: selectionKey, value, error: null })
      })
      .catch(cause => {
        if (ignore) return
        setSelected({ key: selectionKey, value: null, error: loadError(cause) })
      })
    return () => { ignore = true; controller.abort() }
  }, [chain_id, snapshot_id, snapshot_version, childKey, parent, parentKey, parentReceiptId, childReceiptId, selectionKey])

  const discovered = discovery.key === fetchKey ? discovery : null
  const current = selected.key === selectionKey ? selected : null
  const savedOptions = receiptOptions.key === parentKey ? receiptOptions : null

  return <EvolutionChangesContent child={child} discovered={discovered} current={current} parent={parent}
    receiptOptions={savedOptions} parentReceiptId={parentReceiptId} childReceiptId={childReceiptId}
    onSelectParent={next => { setParent(next); setParentReceiptId(null); setChildReceiptId(null) }}
    onSelectParentReceipt={setParentReceiptId} onSelectChildReceipt={setChildReceiptId} />
}

export function EvolutionChangesContent({ child, discovered, current, parent, receiptOptions, parentReceiptId, childReceiptId,
  onSelectParent, onSelectParentReceipt, onSelectChildReceipt }: {
  child: EvolutionEndpoint
  discovered: Loaded | null
  current: Loaded | null
  parent: EvolutionEndpoint | null
  receiptOptions: ReceiptOptions | null
  parentReceiptId: string | null
  childReceiptId: string | null
  onSelectParent: (parent: EvolutionEndpoint) => void
  onSelectParentReceipt: (id: string) => void
  onSelectChildReceipt: (id: string) => void
}) {
  const childKey = endpointKey(child)
  const parentKey = parent ? endpointKey(parent) : ''
  const choices = discovered?.value?.predecessor_choices ?? []
  const facts = current?.value ?? null
  const parentChoices = receiptOptions?.parent ?? facts?.parent_receipt_choices ?? []
  const childChoices = receiptOptions?.child ?? facts?.child_receipt_choices ?? []

  return <section className="evolution-changes" aria-label="Dữ kiện chuyển tiếp đã chọn">
    <header className="evolution-changes__heading">
      <div><p className="kicker">Cạnh lineage đã lưu</p><h3>Thay đổi qua snapshot</h3></div>
      <small>Chain hiện tại: {endpointLabel(child)}</small>
    </header>
    {!discovered ? <p role="status">Đang tải các chuyển tiếp trước…</p> : null}
    {discovered?.error ? <p className={discovered.error.expected ? 'evolution-changes__notice' : 'evolution-changes__error'} role={discovered.error.expected ? 'status' : 'alert'}>{discovered.error.message}</p> : null}
    {discovered?.value ? <>
      <p className="evolution-changes__notice" role="status">{statusText(discovered.value)}</p>
      {choices.length ? <fieldset className="evolution-changes__parents">
        <legend>Chọn chuyển tiếp trước</legend>
        {choices.map(choice => {
          const key = endpointKey(choice.parent)
          return <label key={key} className="evolution-changes__choice">
            <input type="radio" name={`evolution-parent-${childKey}`} checked={parentKey === key} onChange={() => onSelectParent(choice.parent)} />
            <span><strong>{endpointLabel(choice.parent)} → {endpointLabel(child)}</strong>
              <small>Sự kiện: {choice.event_type} · Nguồn trước: {choice.parent_source_kind ? humanize(choice.parent_source_kind) : missingData} · Nguồn sau: {choice.child_source_kind ? humanize(choice.child_source_kind) : missingData}</small>
            </span>
          </label>
        })}
      </fieldset> : <p>Không có chuyển tiếp trước đã xác minh cho chain này.</p>}
      {discovered.value.predecessor_choices_truncated ? <p>Danh sách chuyển tiếp bị cắt; chỉ hiển thị 100 mục đầu.</p> : null}
    </> : null}
    {parent && discovered?.value && choices.some(choice => endpointKey(choice.parent) === parentKey) ? <div className="evolution-changes__details">
      {!current ? <p role="status">Đang tải dữ kiện chuyển tiếp đã chọn…</p> : null}
      {current?.error ? <p className={current.error.expected ? 'evolution-changes__notice' : 'evolution-changes__error'} role={current.error.expected ? 'status' : 'alert'}>{current.error.message}</p> : null}
      {facts ? <>
        <p className="evolution-changes__notice" role="status">{statusText(facts)}</p>
        <div className="evolution-changes__rail" aria-label="Chuyển tiếp đã chọn">
          <span><small>Trước · {facts.parent_source_kind ? humanize(facts.parent_source_kind) : missingData}</small><strong>{endpointLabel(parent)}</strong></span>
          <span className="evolution-changes__arrow" aria-hidden="true">→</span>
          <span><small>Sau · {facts.child_source_kind ? humanize(facts.child_source_kind) : missingData}</small><strong>{endpointLabel(child)}</strong></span>
          <span className="evolution-changes__event">{facts.event_type ?? missingData}</span>
        </div>
        <div className="evolution-changes__receipts">
          <ReceiptPicker label="trước" choices={parentChoices} truncated={facts.parent_receipt_choices_truncated} selected={parentReceiptId} onSelect={onSelectParentReceipt} />
          <ReceiptPicker label="sau" choices={childChoices} truncated={facts.child_receipt_choices_truncated} selected={childReceiptId} onSelect={onSelectChildReceipt} />
        </div>
        {facts.membership ? <div className="evolution-changes__facts">
          <h4>Thành viên chain</h4>
          <div className="evolution-changes__ledger">
            <span>Thêm <strong>{facts.membership.added_count}</strong></span>
            <span>Rời chain <strong>{facts.membership.removed_count}</strong></span>
            <span>Giữ lại <strong>{facts.membership.retained_count}</strong></span>
          </div>
          <p>ID thêm: {facts.membership.added_alarm_ids.join(', ') || 'Không có trong danh sách trả về'}</p>
          <p>ID rời chain: {facts.membership.removed_alarm_ids.join(', ') || 'Không có trong danh sách trả về'}</p>
          {facts.membership.truncated ? <p className="evolution-changes__notice">Danh sách alarm ID bị cắt ở 100 ID mỗi phía; số lượng vẫn là số chính xác.</p> : null}
        </div> : <p className="evolution-changes__notice">Chưa đủ dữ liệu thành viên chain để đối chiếu.</p>}
        <div className="evolution-changes__facts">
          <h4>Bối cảnh và chất lượng</h4>
          {facts.context_changes.length ? <ul>{facts.context_changes.map((change, index) => <li key={`${change.field}-${index}`}>
            {humanize(change.field)}: {change.before ?? missingData} → {change.after ?? missingData}
          </li>)}</ul> : <p>Không ghi nhận thay đổi bối cảnh trong dữ liệu hiện có.</p>}
          <p>Điểm trước: {facts.quality.before_score ?? missingData} · Điểm sau: {facts.quality.after_score ?? missingData}</p>
          <p>Sao trước: {facts.quality.before_stars ?? missingData} · Sao sau: {facts.quality.after_stars ?? missingData}</p>
          <p>Biên nhận trước: {facts.quality.before_receipt_id ?? missingData} · Biên nhận sau: {facts.quality.after_receipt_id ?? missingData}</p>
          <p>{facts.quality.comparable && facts.quality.delta !== null
            ? `Chênh lệch điểm có thể so sánh: ${facts.quality.delta}`
            : `Chưa đủ dữ liệu so sánh chênh lệch điểm · ${facts.quality.reason_codes.map(code => reasonLabels[code] ?? humanize(code)).join(' ') || 'Thiếu biên nhận đánh giá tương thích.'}`}</p>
        </div>
        {facts.explanations.length ? <div className="evolution-changes__facts"><h4>Giải thích từ API</h4>
          <ul>{facts.explanations.map((item, index) => <li key={`${item.code}-${index}`}>
            {explanationText(item.code, facts)} · Bằng chứng: {item.evidence_ids.join(', ') || 'không có'}
          </li>)}</ul>
        </div> : null}
      </> : null}
    </div> : null}
  </section>
}
