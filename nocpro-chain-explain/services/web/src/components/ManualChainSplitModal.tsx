import { useState, useMemo, useEffect } from 'react'
import { api } from '../api'
import {
  generatePartitionTicketReport,
  downloadPartitionDiffJson,
  copyToClipboard,
} from '../partitionExport'
import type { OperatorFeedback, ReviewDecision, ChainSummary } from '../types'

export interface AlarmItem {
  alarm_id: string
  alarm_name?: string | null
  device_code?: string | null
  location_code?: string | null
  role?: string | null
  membership_support?: number | null
  canonical_start_time?: string | null
}

export type ManualOperationType = 'SPLIT' | 'MERGE' | 'MOVE' | 'REMOVE'

export interface ManualChainSplitModalProps {
  isOpen: boolean
  onClose: () => void
  chainId: string
  alarms: AlarmItem[]
  jobId?: string
  initialOperation?: ManualOperationType
  onSaved?: (feedback: OperatorFeedback) => void
}

const OPERATION_TABS: Array<{
  op: ManualOperationType
  label: string
  icon: string
  desc: string
  badgeClass: string
}> = [
  {
    op: 'SPLIT',
    label: 'Tách Chuỗi (Split)',
    icon: 'alt_route',
    desc: 'Chia nhỏ chuỗi hiện tại thành 2 hoặc nhiều phân vùng độc lập',
    badgeClass: 'text-cyan-300 border-cyan-500/30 bg-cyan-500/15',
  },
  {
    op: 'MERGE',
    label: 'Ghép Chuỗi (Merge)',
    icon: 'merge_type',
    desc: 'Gộp toàn bộ chuỗi hiện tại với một chuỗi sự cố khác thành một chuỗi duy nhất',
    badgeClass: 'text-purple-300 border-purple-500/30 bg-purple-500/15',
  },
  {
    op: 'MOVE',
    label: 'Chuyển Cảnh Báo (Move)',
    icon: 'arrow_forward',
    desc: 'Chuyển một số cảnh báo được chọn sang một chuỗi sự cố đang tồn tại',
    badgeClass: 'text-blue-300 border-blue-500/30 bg-blue-500/15',
  },
  {
    op: 'REMOVE',
    label: 'Loại Bỏ Nhiễu (Remove)',
    icon: 'delete_sweep',
    desc: 'Loại bỏ các cảnh báo nhiễu ra khỏi chuỗi sự cố (đưa vào phân vùng UNASSIGNED)',
    badgeClass: 'text-rose-300 border-rose-500/30 bg-rose-500/15',
  },
]

const REASON_CODES: Array<{ code: string; label: string; desc: string }> = [
  {
    code: 'MANUAL_TOPOLOGY_SPLIT',
    label: 'Tô-pô mạng độc lập (Manual Topology Split)',
    desc: 'Thiết bị thuộc tuyến truyền dẫn hoặc cấu trúc liên kết mạng riêng rẽ',
  },
  {
    code: 'MANUAL_DOMAIN_PARTITION',
    label: 'Phân vùng mạng khác biệt (Manual Domain Partition)',
    desc: 'Cách ly miền quang (Optical), miền IP hoặc phân đoạn truy nhập BTS',
  },
  {
    code: 'MANUAL_CORE_REASSIGNMENT',
    label: 'Tái phân bổ vai trò cảnh báo (Manual Core Reassignment)',
    desc: 'Điều chỉnh căn cứ nguyên nhân gốc và cảnh báo phụ thuộc / cảnh báo nhiễu',
  },
]

export function ManualChainSplitModal({
  isOpen,
  onClose,
  chainId,
  alarms,
  jobId,
  initialOperation = 'SPLIT',
  onSaved,
}: ManualChainSplitModalProps) {
  const [operation, setOperation] = useState<ManualOperationType>(initialOperation)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [targetChainId, setTargetChainId] = useState<string>(`${chainId}::partition_custom_1`)
  const [selectedReasonCode, setSelectedReasonCode] = useState<string>('MANUAL_TOPOLOGY_SPLIT')
  const [notes, setNotes] = useState<string>('')
  const [operatorId, setOperatorId] = useState<string>('viettel_operator')
  const [searchTerm, setSearchTerm] = useState<string>('')

  // Other chains in snapshot for MERGE and MOVE
  const [otherChains, setOtherChains] = useState<ChainSummary[]>([])
  const [selectedMergeTargetChainId, setSelectedMergeTargetChainId] = useState<string>('')
  const [targetChainAlarms, setTargetChainAlarms] = useState<string[]>([])
  const [loadingTargetChain, setLoadingTargetChain] = useState<boolean>(false)
  const [chainFilterTerm, setChainFilterTerm] = useState<string>('')
  const [suggestedTargetChainIds, setSuggestedTargetChainIds] = useState<string[]>([])

  // Load review suggestions
  useEffect(() => {
    if (!isOpen) return
    const controller = new AbortController()
    api.latestReview(chainId, controller.signal)
      .then((review) => {
        if (review && review.result) {
          const suggested = new Set<string>()
          for (const cand of review.result.merge?.candidates || []) {
            for (const id of cand.merged_chain_ids || []) {
              if (id !== chainId) suggested.add(id)
            }
          }
          for (const cand of review.result.move?.candidates || []) {
            if (cand.target_chain_id && cand.target_chain_id !== chainId) {
              suggested.add(cand.target_chain_id)
            }
          }
          setSuggestedTargetChainIds(Array.from(suggested))
        }
      })
      .catch(() => {
        // Silently ignore if review not ready
      })
    return () => controller.abort()
  }, [isOpen, chainId])

  const filteredOtherChains = useMemo(() => {
    if (!chainFilterTerm.trim()) return otherChains
    const q = chainFilterTerm.toLowerCase().trim()
    return otherChains.filter(
      (c) =>
        c.chain_id.toLowerCase().includes(q) ||
        (c.title && c.title.toLowerCase().includes(q)),
    )
  }, [otherChains, chainFilterTerm])

  const topSuggestedChains = useMemo(() => {
    // Priority 1: From AI Review
    const aiCandidates = otherChains.filter((c) => suggestedTargetChainIds.includes(c.chain_id))
    if (aiCandidates.length > 0) return aiCandidates.slice(0, 4)

    // Priority 2: Heuristic relatedness (same location or device prefix)
    const targetLocs = new Set(alarms.map((a) => a.location_code).filter(Boolean))
    const heuristic = otherChains.filter((c) => {
      if (c.title && Array.from(targetLocs).some((loc) => loc && c.title.includes(loc))) return true
      const pA = chainId.split(/[:_-]/)[0]
      const pB = c.chain_id.split(/[:_-]/)[0]
      return pA && pA === pB
    })
    if (heuristic.length > 0) return heuristic.slice(0, 4)

    return otherChains.slice(0, 3)
  }, [otherChains, suggestedTargetChainIds, alarms, chainId])

  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successResult, setSuccessResult] = useState<OperatorFeedback | null>(null)

  // Load other chains on mount or when opening
  useEffect(() => {
    if (!isOpen) return
    const controller = new AbortController()
    api.chains(controller.signal)
      .then((res) => {
        const others = (res.chains || []).filter((c) => c.chain_id !== chainId)
        setOtherChains(others)
        if (others.length > 0 && !selectedMergeTargetChainId) {
          setSelectedMergeTargetChainId(others[0].chain_id)
        }
      })
      .catch(() => {
        // Fallback gracefully
      })
    return () => controller.abort()
  }, [isOpen, chainId, selectedMergeTargetChainId])

  // Load target chain alarms when selectedMergeTargetChainId changes
  useEffect(() => {
    if (!selectedMergeTargetChainId) {
      setTargetChainAlarms([])
      return
    }
    let active = true
    setLoadingTargetChain(true)
    api.analysis(selectedMergeTargetChainId)
      .then((res) => {
        if (active) {
          setTargetChainAlarms(res.members.map((m) => m.alarm_id))
        }
      })
      .catch(() => {
        if (active) {
          // If analysis call fails, fallback to empty list
          setTargetChainAlarms([])
        }
      })
      .finally(() => {
        if (active) setLoadingTargetChain(false)
      })
    return () => {
      active = false
    }
  }, [selectedMergeTargetChainId])

  // Filter alarms by search term
  const filteredAlarms = useMemo(() => {
    if (!searchTerm.trim()) return alarms
    const q = searchTerm.toLowerCase().trim()
    return alarms.filter(
      (a) =>
        a.alarm_id.toLowerCase().includes(q) ||
        (a.alarm_name && a.alarm_name.toLowerCase().includes(q)) ||
        (a.device_code && a.device_code.toLowerCase().includes(q)) ||
        (a.role && a.role.toLowerCase().includes(q)),
    )
  }, [alarms, searchTerm])

  const [displayLimit, setDisplayLimit] = useState<number>(100)

  // Reset displayLimit on search or tab change
  useEffect(() => {
    setDisplayLimit(100)
  }, [searchTerm, operation])

  // Accessibility: close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const displayedAlarms = useMemo(() => {
    return filteredAlarms.slice(0, displayLimit)
  }, [filteredAlarms, displayLimit])

  if (!isOpen) return null

  const allAlarmIds = alarms.map((a) => a.alarm_id)
  const selectedCount = selectedIds.size
  const remainingCount = alarms.length - selectedCount

  // Validation rules per operation
  const isValidSplit =
    selectedCount > 0 &&
    remainingCount > 0 &&
    targetChainId.trim().length > 0 &&
    targetChainId.trim() !== chainId

  const isValidMerge =
    selectedMergeTargetChainId.trim().length > 0 &&
    selectedMergeTargetChainId !== chainId &&
    targetChainAlarms.length > 0 &&
    !loadingTargetChain

  const isValidMove =
    selectedCount > 0 &&
    remainingCount > 0 &&
    selectedMergeTargetChainId.trim().length > 0 &&
    selectedMergeTargetChainId !== chainId &&
    targetChainAlarms.length > 0 &&
    !loadingTargetChain

  const isValidRemove = selectedCount > 0 && remainingCount > 0

  const isCurrentOpValid =
    operation === 'SPLIT'
      ? isValidSplit
      : operation === 'MERGE'
      ? isValidMerge
      : operation === 'MOVE'
      ? isValidMove
      : isValidRemove

  const handleToggleAlarm = (alarmId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(alarmId)) {
        next.delete(alarmId)
      } else {
        next.add(alarmId)
      }
      return next
    })
  }

  const handleSelectWeak = () => {
    const weakIds = alarms
      .filter((a) => a.role === 'WEAK' || (a.membership_support != null && a.membership_support < 0.6))
      .map((a) => a.alarm_id)
    setSelectedIds(new Set(weakIds))
  }

  const handleSelectAll = () => {
    setSelectedIds(new Set(allAlarmIds))
  }

  const handleClearAll = () => {
    setSelectedIds(new Set())
  }

  const handleInvert = () => {
    const next = new Set<string>()
    for (const id of allAlarmIds) {
      if (!selectedIds.has(id)) next.add(id)
    }
    setSelectedIds(next)
  }

  const [isDragOverTarget, setIsDragOverTarget] = useState(false)
  const [isDragOverSource, setIsDragOverSource] = useState(false)
  const [draggedAlarmId, setDraggedAlarmId] = useState<string | null>(null)
  const [copiedReportMsg, setCopiedReportMsg] = useState(false)

  const currentPartitionDelta = useMemo(() => {
    const splitList = Array.from(selectedIds)
    const remainingList = allAlarmIds.filter((id) => !selectedIds.has(id))
    const target = targetChainId.trim()
    if (operation === 'SPLIT') {
      return {
        before: [[chainId, allAlarmIds] as [string, string[]]],
        after: [
          [chainId, remainingList] as [string, string[]],
          [target, splitList] as [string, string[]],
        ],
      }
    } else if (operation === 'MERGE') {
      return {
        before: [
          [chainId, allAlarmIds] as [string, string[]],
          [selectedMergeTargetChainId, targetChainAlarms] as [string, string[]],
        ],
        after: [
          [selectedMergeTargetChainId, allAlarmIds.concat(targetChainAlarms)] as [string, string[]],
        ],
      }
    } else if (operation === 'MOVE') {
      return {
        before: [
          [chainId, allAlarmIds] as [string, string[]],
          [selectedMergeTargetChainId, targetChainAlarms] as [string, string[]],
        ],
        after: [
          [chainId, remainingList] as [string, string[]],
          [selectedMergeTargetChainId, targetChainAlarms.concat(splitList)] as [string, string[]],
        ],
      }
    } else {
      return {
        before: [[chainId, allAlarmIds] as [string, string[]]],
        after: [
          [chainId, remainingList] as [string, string[]],
          ['UNASSIGNED', splitList] as [string, string[]],
        ],
      }
    }
  }, [allAlarmIds, chainId, operation, selectedIds, selectedMergeTargetChainId, targetChainAlarms, targetChainId])

  const alarmMap = useMemo(() => {
    const map: Record<string, { alarm_name?: string | null; device_code?: string | null; role?: string | null }> = {}
    for (const a of alarms) {
      map[a.alarm_id] = { alarm_name: a.alarm_name, device_code: a.device_code, role: a.role }
    }
    return map
  }, [alarms])

  const handleCopyTicketReport = async () => {
    const report = generatePartitionTicketReport({
      chainId,
      operation: `MANUAL_${operation}`,
      operatorId,
      createdAt: new Date().toISOString(),
      reasonCode: selectedReasonCode,
      notes: notes || undefined,
      partitionDelta: currentPartitionDelta,
      alarmMap,
    })
    const success = await copyToClipboard(report)
    if (success) {
      setCopiedReportMsg(true)
      setTimeout(() => setCopiedReportMsg(false), 2500)
    }
  }

  const handleDownloadDiffJson = () => {
    downloadPartitionDiffJson({
      chainId,
      operation: `MANUAL_${operation}`,
      operatorId,
      createdAt: new Date().toISOString(),
      reasonCode: selectedReasonCode,
      notes: notes || undefined,
      partitionDelta: currentPartitionDelta,
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!isCurrentOpValid) return

    setSubmitting(true)
    setError(null)
    setSuccessResult(null)

    try {
      let activeJobId = jobId
      if (!activeJobId) {
        const sub = await api.submitReview(chainId)
        activeJobId = sub.job_id
      }

      const splitList = Array.from(selectedIds)
      const remainingList = allAlarmIds.filter((id) => !selectedIds.has(id))
      const target = targetChainId.trim()

      let manualCorrectionPayload: {
        operation: string
        target_chain_id?: string
        partition_delta: {
          before?: [string, string[]][]
          after?: [string, string[]][]
        }
        edit_summary?: string
      }

      if (operation === 'SPLIT') {
        manualCorrectionPayload = {
          operation: 'MANUAL_SPLIT',
          partition_delta: {
            before: [[chainId, allAlarmIds] as [string, string[]]],
            after: [
              [chainId, remainingList] as [string, string[]],
              [target, splitList] as [string, string[]],
            ],
          },
          edit_summary:
            notes ||
            `Kỹ sư ${operatorId} tách thủ công: giữ lại ${remainingList.length} cảnh báo trong ${chainId}, chuyển ${splitList.length} cảnh báo sang ${target}`,
        }
      } else if (operation === 'MERGE') {
        manualCorrectionPayload = {
          operation: 'MANUAL_MERGE',
          target_chain_id: selectedMergeTargetChainId,
          partition_delta: {
            before: [
              [chainId, allAlarmIds] as [string, string[]],
              [selectedMergeTargetChainId, targetChainAlarms] as [string, string[]],
            ],
            after: [
              [selectedMergeTargetChainId, allAlarmIds.concat(targetChainAlarms)] as [string, string[]],
            ],
          },
          edit_summary:
            notes ||
            `Kỹ sư ${operatorId} ghép chuỗi thủ công: gộp chuỗi ${chainId} (${allAlarmIds.length} cảnh báo) vào chuỗi ${selectedMergeTargetChainId} (${targetChainAlarms.length} cảnh báo)`,
        }
      } else if (operation === 'MOVE') {
        manualCorrectionPayload = {
          operation: 'MANUAL_MOVE',
          target_chain_id: selectedMergeTargetChainId,
          partition_delta: {
            before: [
              [chainId, allAlarmIds] as [string, string[]],
              [selectedMergeTargetChainId, targetChainAlarms] as [string, string[]],
            ],
            after: [
              [chainId, remainingList] as [string, string[]],
              [selectedMergeTargetChainId, targetChainAlarms.concat(splitList)] as [string, string[]],
            ],
          },
          edit_summary:
            notes ||
            `Kỹ sư ${operatorId} chuyển thủ công ${splitList.length} cảnh báo từ ${chainId} sang chuỗi ${selectedMergeTargetChainId}`,
        }
      } else {
        // REMOVE
        manualCorrectionPayload = {
          operation: 'MANUAL_REMOVE',
          partition_delta: {
            before: [[chainId, allAlarmIds] as [string, string[]]],
            after: [
              [chainId, remainingList] as [string, string[]],
              ['UNASSIGNED', splitList] as [string, string[]],
            ],
          },
          edit_summary:
            notes ||
            `Kỹ sư ${operatorId} loại bỏ thủ công ${splitList.length} cảnh báo nhiễu ra khỏi chuỗi ${chainId}`,
        }
      }

      const payload = {
        candidate_id: null,
        decision: 'MANUAL_CORRECTION' as ReviewDecision,
        confidence: 1.0,
        reason_code: selectedReasonCode,
        reason_codes: [selectedReasonCode],
        reason_policy_version: 'review-reasons-v1',
        notes: notes || manualCorrectionPayload.edit_summary,
        manual_correction: manualCorrectionPayload,
      }

      const feedback = await api.submitReviewFeedback(
        activeJobId,
        payload,
        {
          'X-Dev-Operator-Id': operatorId,
          'X-Dev-Operator-Role': 'PRODUCT_OWNER',
          'X-Dev-Domain-Scope': 'IP_NETWORK',
        },
      )

      setSuccessResult(feedback)
      if (onSaved) {
        onSaved(feedback)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Không thể lưu phương án phân hoạch thủ công')
    } finally {
      setSubmitting(false)
    }
  }

  const currentOpMeta = OPERATION_TABS.find((t) => t.op === operation) || OPERATION_TABS[0]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn"
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-split-title"
    >
      <div className="relative flex flex-col w-full max-w-4xl max-h-[92vh] rounded-2xl border border-[#233554] bg-[#0b1325] text-slate-100 shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-[#1e2e4a] bg-[#111c33] px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/15 border border-cyan-500/30 text-cyan-300">
              <span className="material-symbols-outlined text-[24px]">{currentOpMeta.icon}</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-cyan-950/80 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300 border border-cyan-700/50 uppercase tracking-wide">
                  Operator Partition Studio
                </span>
                <span className="text-xs text-slate-400 font-mono">Chuỗi đang xem: {chainId}</span>
              </div>
              <h2 id="manual-split-title" className="text-base font-bold text-white mt-0.5">
                🛠️ Tùy Chỉnh Phân Hoạch Chuỗi Sự Cố (Manual Partition)
              </h2>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white transition-colors cursor-pointer"
            aria-label="Đóng"
          >
            ✕
          </button>
        </div>

        {/* Operation Selector Tabs */}
        {!successResult && (
          <div className="flex items-center gap-2 border-b border-[#1e2e4a] bg-[#090f1d] px-6 py-2 overflow-x-auto">
            {OPERATION_TABS.map((tab) => {
              const isActive = operation === tab.op
              return (
                <button
                  key={tab.op}
                  type="button"
                  onClick={() => {
                    setOperation(tab.op)
                    setError(null)
                  }}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
                    isActive
                      ? 'bg-secondary text-[#070e1d] font-bold shadow-sm'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {successResult ? (
            <div className="p-6 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-center space-y-4 animate-fadeIn">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300 mx-auto border border-emerald-500/30">
                <span className="material-symbols-outlined text-[32px]">check_circle</span>
              </div>
              <div className="space-y-1">
                <h3 className="text-lg font-bold text-emerald-200">
                  Đã Lưu Phương Án {currentOpMeta.label} Thành Công!
                </h3>
                <p className="text-xs text-emerald-300/80 max-w-lg mx-auto">
                  Phương án phân hoạch thủ công của kỹ sư đã được ghi nhận vào kho dữ liệu nhãn vận hành (PO-asserted Ground Truth) và sẽ tham gia huấn luyện trực tiếp cho mô hình xếp hạng XGBRanker.
                </p>
              </div>
              <div className="p-3 rounded-lg bg-[#070e1d] border border-emerald-900/60 inline-flex flex-col gap-1 text-xs font-mono text-slate-300 text-left min-w-[320px]">
                <div>Feedback ID: <strong className="text-cyan-300">{successResult.feedback_id}</strong></div>
                <div>Quyết định: <strong className="text-emerald-400">{successResult.decision}</strong></div>
                <div>Thao tác: <strong className="text-amber-300">{successResult.operation}</strong></div>
                <div>Kỹ sư: <strong className="text-slate-200">{successResult.operator_id}</strong></div>
              </div>
              <div className="flex flex-wrap justify-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleCopyTicketReport}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-sky-500/20 border border-sky-400/40 text-sky-200 text-xs font-semibold hover:bg-sky-500/30 transition-colors cursor-pointer"
                  title="Sao chép nội dung báo cáo phân hoạch để dán vào Ticket NOC"
                >
                  <span className="material-symbols-outlined text-[15px]">
                    {copiedReportMsg ? 'check' : 'content_copy'}
                  </span>
                  <span>{copiedReportMsg ? 'Đã sao chép Ticket!' : '📋 Sao Chép Ticket NOC'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadDiffJson}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-xs font-semibold hover:bg-slate-700 transition-colors cursor-pointer"
                  title="Tải file JSON diff để lưu trữ hoặc đính kèm"
                >
                  <span className="material-symbols-outlined text-[15px]">download</span>
                  <span>📥 Tải File JSON Diff</span>
                </button>
              </div>
              <div className="pt-2 flex justify-center gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-5 py-2 rounded-lg bg-secondary text-[#070e1d] font-bold text-xs hover:brightness-110 cursor-pointer shadow-md transition-all"
                >
                  Hoàn tất &amp; Đóng
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSuccessResult(null)
                    setSelectedIds(new Set())
                  }}
                  className="px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-xs hover:bg-slate-700 cursor-pointer transition-all"
                >
                  Thiết lập thao tác khác
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Instructions banner */}
              <div className="flex items-start gap-2.5 p-3 rounded-xl bg-cyan-950/25 border border-cyan-800/40 text-xs text-cyan-200/90">
                <span className="material-symbols-outlined text-[18px] text-cyan-400 shrink-0 mt-0.5">info</span>
                <div>
                  <strong>{currentOpMeta.label}:</strong> {currentOpMeta.desc}. Hệ thống tự động đảm bảo tính toàn vẹn và bảo toàn số lượng cảnh báo trong vũ trụ sự cố (Conservation Invariant).
                </div>
              </div>

              {/* Operation Specific Config Cards */}
              {operation === 'MERGE' ? (
                /* MERGE UI: Select target chain to merge into */
                <div className="p-4 rounded-xl bg-[#0e172a] border border-purple-800/50 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-purple-400 text-[20px]">merge_type</span>
                      <h4 className="text-xs font-bold text-purple-200 uppercase tracking-wider">
                        Chọn Chuỗi Sự Cố Cần Ghép (Merge Target Chain)
                      </h4>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/30">
                      Gộp toàn bộ 2 chuỗi
                    </span>
                  </div>

                  {/* Quick-Select Suggestions */}
                  {topSuggestedChains.length > 0 && (
                    <div className="space-y-1.5 pb-1">
                      <div className="flex items-center justify-between text-[10px] text-purple-300 font-semibold uppercase tracking-wider">
                        <div className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[13px] text-amber-400">auto_awesome</span>
                          <span>Chuỗi ứng viên gợi ý nhanh (1-Click chọn ngay):</span>
                        </div>
                        <span className="text-slate-400 font-normal lowercase">click để đổi đích</span>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-1.5">
                        {topSuggestedChains.map((c) => {
                          const isSelected = selectedMergeTargetChainId === c.chain_id
                          const isAi = suggestedTargetChainIds.includes(c.chain_id)
                          return (
                            <button
                              key={c.chain_id}
                              type="button"
                              onClick={() => setSelectedMergeTargetChainId(c.chain_id)}
                              className={`p-2 rounded-lg text-left transition-all border flex flex-col justify-between cursor-pointer ${
                                isSelected
                                  ? 'bg-purple-950/70 border-purple-400 shadow-[0_0_12px_rgba(168,85,247,0.35)] ring-1 ring-purple-400'
                                  : 'bg-[#070e1d] border-slate-800 hover:border-slate-600 text-slate-300 hover:bg-slate-900/50'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className={`font-mono text-xs font-bold truncate ${isSelected ? 'text-purple-200' : 'text-slate-200'}`}>
                                  {c.chain_id}
                                </span>
                                {isAi ? (
                                  <span className="px-1.5 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40 shrink-0">
                                    AI Đề xuất
                                  </span>
                                ) : (
                                  <span className="px-1.5 py-0.2 rounded text-[9px] bg-slate-800 text-slate-400 shrink-0">
                                    Khả dụng
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center justify-between mt-1 text-[11px] text-slate-400">
                                <span className="truncate max-w-[120px]">{c.title || 'Sự cố'}</span>
                                <span className="font-mono text-[10px] text-cyan-300 shrink-0 font-medium">
                                  {c.member_count} alarm
                                </span>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-slate-300">
                      <label htmlFor="merge-target-select">
                        Hoặc tìm kiếm trong toàn bộ snapshot:
                      </label>
                      <span className="text-[10px] text-slate-400 font-mono">
                        {filteredOtherChains.length} / {otherChains.length} chuỗi
                      </span>
                    </div>

                    {otherChains.length > 5 && (
                      <div className="relative">
                        <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 text-[14px]">
                          search
                        </span>
                        <input
                          type="text"
                          placeholder="Lọc theo mã chuỗi hoặc tiêu đề..."
                          value={chainFilterTerm}
                          onChange={(e) => setChainFilterTerm(e.target.value)}
                          className="w-full pl-7 pr-3 py-1 text-xs rounded-md bg-[#070e1d] border border-purple-900/60 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-400 font-mono"
                        />
                      </div>
                    )}

                    {otherChains.length === 0 ? (
                      <p className="text-xs text-amber-400 italic">
                        Không tìm thấy chuỗi sự cố nào khác trong snapshot hiện tại để ghép.
                      </p>
                    ) : filteredOtherChains.length === 0 ? (
                      <p className="text-xs text-slate-400 italic py-1">
                        Không tìm thấy chuỗi nào khớp với từ khóa "{chainFilterTerm}".
                      </p>
                    ) : (
                      <select
                        id="merge-target-select"
                        value={selectedMergeTargetChainId}
                        onChange={(e) => setSelectedMergeTargetChainId(e.target.value)}
                        className="w-full rounded-lg bg-[#070e1d] border border-purple-700/80 px-3 py-2 text-xs text-purple-200 focus:outline-none focus:border-purple-400 font-mono"
                      >
                        {filteredOtherChains.map((c) => (
                          <option key={c.chain_id} value={c.chain_id}>
                            {c.chain_id} — {c.title || 'Sự cố'} ({c.member_count} cảnh báo)
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  {/* Merge Preview */}
                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-700/60 text-center font-mono text-xs">
                    <div className="p-2 rounded bg-[#070e1d] border border-slate-800">
                      <span className="text-[10px] text-slate-400 block">Chuỗi gốc ({chainId})</span>
                      <strong className="text-blue-300 text-sm">{alarms.length} cảnh báo</strong>
                    </div>
                    <div className="p-2 rounded bg-[#070e1d] border border-slate-800">
                      <span className="text-[10px] text-slate-400 block">Chuỗi đích ({selectedMergeTargetChainId || '...'})</span>
                      <strong className="text-purple-300 text-sm">
                        {loadingTargetChain ? '...' : `${targetChainAlarms.length} cảnh báo`}
                      </strong>
                    </div>
                    <div className="p-2 rounded bg-purple-950/40 border border-purple-700/60">
                      <span className="text-[10px] text-purple-300 block">Sau khi ghép hợp nhất</span>
                      <strong className="text-emerald-300 text-sm">
                        {loadingTargetChain ? '...' : `${alarms.length + targetChainAlarms.length} cảnh báo`}
                      </strong>
                    </div>
                  </div>
                </div>
              ) : operation === 'MOVE' ? (
                /* MOVE UI: Target chain selection for moving selected alarms */
                <div className="p-3.5 rounded-xl bg-[#0e172a] border border-blue-800/50 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-blue-400 text-[18px]">arrow_forward</span>
                      <h4 className="text-xs font-bold text-blue-200 uppercase tracking-wider">
                        Chọn Chuỗi Sự Cố Tiếp Nhận (Move Target Chain)
                      </h4>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-blue-500/15 text-blue-300 border border-blue-500/30">
                      Chuyển {selectedCount} cảnh báo
                    </span>
                  </div>

                  {/* Quick-Select Suggestions for MOVE */}
                  {topSuggestedChains.length > 0 && (
                    <div className="space-y-1.5 pb-1">
                      <div className="flex items-center justify-between text-[10px] text-blue-300 font-semibold uppercase tracking-wider">
                        <div className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[13px] text-amber-400">auto_awesome</span>
                          <span>Chuỗi tiếp nhận gợi ý nhanh (1-Click chọn ngay):</span>
                        </div>
                        <span className="text-slate-400 font-normal lowercase">click để đổi đích</span>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-1.5">
                        {topSuggestedChains.map((c) => {
                          const isSelected = selectedMergeTargetChainId === c.chain_id
                          const isAi = suggestedTargetChainIds.includes(c.chain_id)
                          return (
                            <button
                              key={c.chain_id}
                              type="button"
                              onClick={() => setSelectedMergeTargetChainId(c.chain_id)}
                              className={`p-2 rounded-lg text-left transition-all border flex flex-col justify-between cursor-pointer ${
                                isSelected
                                  ? 'bg-blue-950/70 border-blue-400 shadow-[0_0_12px_rgba(59,130,246,0.35)] ring-1 ring-blue-400'
                                  : 'bg-[#070e1d] border-slate-800 hover:border-slate-600 text-slate-300 hover:bg-slate-900/50'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className={`font-mono text-xs font-bold truncate ${isSelected ? 'text-blue-200' : 'text-slate-200'}`}>
                                  {c.chain_id}
                                </span>
                                {isAi ? (
                                  <span className="px-1.5 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40 shrink-0">
                                    AI Đề xuất
                                  </span>
                                ) : (
                                  <span className="px-1.5 py-0.2 rounded text-[9px] bg-slate-800 text-slate-400 shrink-0">
                                    Khả dụng
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center justify-between mt-1 text-[11px] text-slate-400">
                                <span className="truncate max-w-[120px]">{c.title || 'Sự cố'}</span>
                                <span className="font-mono text-[10px] text-cyan-300 shrink-0 font-medium">
                                  {c.member_count} alarm
                                </span>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-slate-300">
                      <span>Hoặc tìm kiếm trong toàn bộ snapshot:</span>
                      <span className="text-[10px] text-slate-400 font-mono">
                        {filteredOtherChains.length} / {otherChains.length} chuỗi
                      </span>
                    </div>

                    {otherChains.length > 5 && (
                      <div className="relative">
                        <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 text-[14px]">
                          search
                        </span>
                        <input
                          type="text"
                          placeholder="Lọc chuỗi tiếp nhận..."
                          value={chainFilterTerm}
                          onChange={(e) => setChainFilterTerm(e.target.value)}
                          className="w-full pl-7 pr-3 py-1 text-xs rounded-md bg-[#070e1d] border border-blue-900/60 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-400 font-mono"
                        />
                      </div>
                    )}

                    {otherChains.length === 0 ? (
                      <p className="text-xs text-amber-400 italic">
                        Không tìm thấy chuỗi sự cố nào khác trong snapshot.
                      </p>
                    ) : filteredOtherChains.length === 0 ? (
                      <p className="text-xs text-slate-400 italic py-1">
                        Không tìm thấy chuỗi nào khớp với từ khóa "{chainFilterTerm}".
                      </p>
                    ) : (
                      <select
                        value={selectedMergeTargetChainId}
                        onChange={(e) => setSelectedMergeTargetChainId(e.target.value)}
                        className="w-full rounded-lg bg-[#070e1d] border border-blue-700/80 px-3 py-1.5 text-xs text-blue-200 focus:outline-none focus:border-blue-400 font-mono"
                      >
                        {filteredOtherChains.map((c) => (
                          <option key={c.chain_id} value={c.chain_id}>
                            {c.chain_id} — {c.title || 'Sự cố'} ({c.member_count} cảnh báo hiện tại)
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                </div>
              ) : operation === 'REMOVE' ? (
                /* REMOVE UI: Explaining unassigned noise pool */
                <div className="p-3.5 rounded-xl bg-[#1a111a] border border-rose-800/50 space-y-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-rose-400 text-[18px]">delete_sweep</span>
                      <h4 className="text-xs font-bold text-rose-200 uppercase tracking-wider">
                        Phân vùng Cảnh báo Nhiễu (UNASSIGNED POOL)
                      </h4>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-rose-500/15 text-rose-300 border border-rose-500/30">
                      Loại bỏ {selectedCount} cảnh báo
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-300 leading-relaxed">
                    Tích chọn các cảnh báo ngẫu nhiên hoặc cảnh báo nhiễu bên dưới để đưa vào phân vùng UNASSIGNED, làm sạch chuỗi sự cố gốc.
                  </p>
                </div>
              ) : (
                /* SPLIT UI: Side-by-side preview */
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="p-3.5 rounded-xl bg-[#0e172a] border border-slate-700/60 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-blue-400"></span>
                        <span className="text-xs font-bold text-blue-200">Nhóm 1: Giữ lại chuỗi gốc</span>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-blue-500/15 text-blue-300 border border-blue-500/30">
                        {remainingCount} cảnh báo
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-400 truncate" title={chainId}>
                      Mã chuỗi: <strong className="text-slate-200">{chainId}</strong>
                    </div>
                  </div>
                  <div className="p-3.5 rounded-xl bg-[#0c1a2e] border border-cyan-700/50 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse"></span>
                        <span className="text-xs font-bold text-cyan-200">Nhóm 2: Tách sang chuỗi mới</span>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                        {selectedCount} cảnh báo
                      </span>
                    </div>
                    <div className="space-y-1">
                      <label htmlFor="target-chain-id-input" className="block text-[11px] text-cyan-300/80 font-medium">
                        Mã chuỗi mới (Target Chain ID):
                      </label>
                      <input
                        id="target-chain-id-input"
                        type="text"
                        value={targetChainId}
                        onChange={(e) => setTargetChainId(e.target.value)}
                        placeholder="VD: chain_123::partition_optical"
                        className="w-full rounded bg-[#070e1d] border border-cyan-800/80 px-2.5 py-1 text-xs font-mono text-cyan-200 focus:outline-none focus:border-cyan-400"
                        required
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Alarm Selection Section (Only for SPLIT, MOVE, and REMOVE) */}
              {operation !== 'MERGE' && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                        {operation === 'REMOVE'
                          ? `Chọn Cảnh báo Cần Loại Bỏ (${alarms.length})`
                          : `Chọn Cảnh báo (${alarms.length})`}
                      </h3>
                      {selectedCount > 0 && (
                        <span className="px-2 py-0.2 rounded-full bg-cyan-500/20 text-cyan-300 text-[11px] font-semibold border border-cyan-500/30">
                          Đã chọn {selectedCount}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <button
                        type="button"
                        onClick={handleSelectWeak}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-[11px] font-medium transition-colors cursor-pointer"
                        title="Chọn nhanh các cảnh báo có vai trò WEAK hoặc độ gắn kết thấp"
                      >
                        <span className="material-symbols-outlined text-[13px]">bolt</span>
                        <span>Chọn cảnh báo yếu (WEAK)</span>
                      </button>
                      <button
                        type="button"
                        onClick={handleInvert}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-[11px] transition-colors cursor-pointer"
                      >
                        Đảo chọn
                      </button>
                      <button
                        type="button"
                        onClick={handleSelectAll}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-[11px] transition-colors cursor-pointer"
                      >
                        Chọn hết
                      </button>
                      <button
                        type="button"
                        onClick={handleClearAll}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-[11px] transition-colors cursor-pointer"
                      >
                        Bỏ chọn
                      </button>
                    </div>
                  </div>

                  {/* Interactive Drag & Drop Target Drop Zone */}
                  <div
                    onDragOver={(e) => {
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'move'
                      setIsDragOverTarget(true)
                    }}
                    onDragLeave={() => setIsDragOverTarget(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setIsDragOverTarget(false)
                      const aid = e.dataTransfer.getData('text/plain')
                      if (aid) {
                        setSelectedIds((prev) => new Set(prev).add(aid))
                      }
                    }}
                    className={`p-2.5 rounded-xl border transition-all ${
                      isDragOverTarget
                        ? 'border-cyan-400 bg-cyan-950/60 shadow-[0_0_15px_rgba(6,182,212,0.4)] ring-2 ring-cyan-400'
                        : selectedCount > 0
                        ? 'border-cyan-700/60 bg-[#070e1d]'
                        : 'border-dashed border-cyan-800/60 bg-[#070e1d]/70'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-cyan-300">
                        <span className="material-symbols-outlined text-[15px]">drive_file_move</span>
                        <span>
                          {operation === 'SPLIT'
                            ? `Phân vùng mới: ${targetChainId || '...'}`
                            : operation === 'MOVE'
                            ? `Chuỗi tiếp nhận: ${selectedMergeTargetChainId || '...'}`
                            : 'Phân vùng loại bỏ: UNASSIGNED'}
                        </span>
                        <span className="text-[10px] text-slate-400 font-normal italic">
                          (Kéo thả cảnh báo vào đây hoặc dùng checkbox bên dưới)
                        </span>
                      </div>
                      <span className="text-[10px] text-cyan-400 font-mono font-bold">
                        {selectedCount} cảnh báo
                      </span>
                    </div>

                    {selectedCount === 0 ? (
                      <div className="py-2.5 text-center text-xs text-slate-400 border border-dashed border-slate-700/60 rounded-lg bg-slate-950/40">
                        <span className="material-symbols-outlined text-[18px] text-cyan-400/80 inline-block align-middle mr-1">
                          drag_indicator
                        </span>
                        <span className="align-middle">
                          Kéo cảnh báo từ danh sách dưới và <strong>thả vào đây</strong> để chuyển
                        </span>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto p-1 rounded-lg bg-slate-950/50 border border-slate-800">
                        {Array.from(selectedIds).map((aid) => {
                          const item = alarms.find((a) => a.alarm_id === aid)
                          return (
                            <span
                              key={aid}
                              draggable={true}
                              onDragStart={(e) => {
                                e.dataTransfer.setData('text/plain', aid)
                                e.dataTransfer.effectAllowed = 'move'
                                setDraggedAlarmId(aid)
                              }}
                              onDragEnd={() => setDraggedAlarmId(null)}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/80 border border-cyan-500/40 text-cyan-200 cursor-grab active:cursor-grabbing hover:border-cyan-400 transition-colors"
                              title="Kéo thả ngược lại bảng để bỏ gán"
                            >
                              <span className="material-symbols-outlined text-[11px] text-slate-400">drag_indicator</span>
                              <strong className="truncate max-w-[140px]">
                                {item?.device_code ? `[${item.device_code}] ` : ''}{item?.alarm_name || aid}
                              </strong>
                              <button
                                type="button"
                                onClick={() => handleToggleAlarm(aid)}
                                className="ml-0.5 text-cyan-400 hover:text-rose-400 transition-colors cursor-pointer"
                                title="Bỏ gán khỏi phân vùng đích"
                              >
                                ✕
                              </button>
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  {/* Search Bar */}
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-2.5 top-2 text-[16px] text-slate-400 pointer-events-none">
                      search
                    </span>
                    <input
                      type="text"
                      placeholder="Tìm theo mã cảnh báo, tên cảnh báo, mã thiết bị..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full rounded-lg bg-[#070e1d] border border-slate-700/80 pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  {/* Alarms Table */}
                  <div
                    onDragOver={(e) => {
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'move'
                      setIsDragOverSource(true)
                    }}
                    onDragLeave={() => setIsDragOverSource(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setIsDragOverSource(false)
                      const aid = e.dataTransfer.getData('text/plain')
                      if (aid) {
                        setSelectedIds((prev) => {
                          const next = new Set(prev)
                          next.delete(aid)
                          return next
                        })
                      }
                    }}
                    className={`max-h-52 overflow-y-auto rounded-xl border transition-all ${
                      isDragOverSource
                        ? 'border-cyan-400 bg-slate-900 ring-2 ring-cyan-500/40'
                        : 'border-slate-700/70 bg-[#070e1d]'
                    }`}
                  >
                    <table className="w-full text-left text-xs text-slate-300 border-collapse">
                      <thead className="sticky top-0 bg-[#0e172a] text-[11px] font-semibold text-slate-400 border-b border-slate-700 uppercase tracking-wider">
                        <tr>
                          <th className="w-12 px-3 py-2 text-center">Chọn</th>
                          <th className="px-3 py-2">Thiết bị</th>
                          <th className="px-3 py-2">Tên Cảnh Báo</th>
                          <th className="px-3 py-2">Vai trò / Hỗ trợ</th>
                          <th className="px-3 py-2">Thời gian</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/80">
                        {filteredAlarms.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="px-4 py-6 text-center text-slate-500 italic">
                              Không tìm thấy cảnh báo phù hợp với từ khóa.
                            </td>
                          </tr>
                        ) : (
                          <>
                            {displayedAlarms.map((alarm) => {
                              const isSelected = selectedIds.has(alarm.alarm_id)
                              const isWeak =
                                alarm.role === 'WEAK' ||
                                (alarm.membership_support != null && alarm.membership_support < 0.6)
                              return (
                                <tr
                                  key={alarm.alarm_id}
                                  draggable={true}
                                  onDragStart={(e) => {
                                    e.dataTransfer.setData('text/plain', alarm.alarm_id)
                                    e.dataTransfer.effectAllowed = 'move'
                                    setDraggedAlarmId(alarm.alarm_id)
                                  }}
                                  onDragEnd={() => setDraggedAlarmId(null)}
                                  onClick={() => handleToggleAlarm(alarm.alarm_id)}
                                  className={`cursor-pointer transition-colors ${
                                    draggedAlarmId === alarm.alarm_id ? 'opacity-40' : ''
                                  } ${
                                    isSelected
                                      ? 'bg-cyan-950/40 text-white font-medium hover:bg-cyan-950/60'
                                      : 'hover:bg-slate-800/50'
                                  }`}
                                >
                                  <td className="px-3 py-2 text-center" onClick={(e) => e.stopPropagation()}>
                                    <div className="flex items-center justify-center gap-1">
                                      <span
                                        className="material-symbols-outlined text-[13px] text-slate-500 cursor-grab active:cursor-grabbing hover:text-slate-300"
                                        title="Kéo cảnh báo này thả vào vùng phân vùng đích ở trên"
                                      >
                                        drag_indicator
                                      </span>
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleToggleAlarm(alarm.alarm_id)}
                                        className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-500 cursor-pointer"
                                      />
                                    </div>
                                  </td>
                                  <td className="px-3 py-2 font-mono text-[11px] text-slate-200">
                                    {alarm.device_code || '—'}
                                  </td>
                                  <td className="px-3 py-2 font-medium truncate max-w-xs" title={alarm.alarm_name ?? alarm.alarm_id}>
                                    {alarm.alarm_name || alarm.alarm_id}
                                  </td>
                                  <td className="px-3 py-2">
                                    <span
                                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                        isWeak
                                          ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                                          : alarm.role === 'PRIMARY' || alarm.role === 'ROOT'
                                          ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                                          : 'bg-slate-700/60 text-slate-300'
                                      }`}
                                    >
                                      {alarm.role || 'MEMBER'}
                                      {alarm.membership_support != null && (
                                        <span className="font-mono">
                                          ({(alarm.membership_support * 100).toFixed(0)}%)
                                        </span>
                                      )}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2 text-slate-400 font-mono text-[11px] whitespace-nowrap">
                                    {alarm.canonical_start_time
                                      ? new Date(alarm.canonical_start_time).toLocaleTimeString()
                                      : '—'}
                                  </td>
                                </tr>
                              )
                            })}
                            {filteredAlarms.length > displayLimit && (
                              <tr>
                                <td colSpan={5} className="px-4 py-2 text-center bg-[#070e1d] border-t border-slate-800 text-[11px] text-slate-400">
                                  Đang hiển thị <strong>{displayLimit}</strong> / <strong>{filteredAlarms.length}</strong> cảnh báo.
                                  <button
                                    type="button"
                                    onClick={() => setDisplayLimit((prev) => prev + 100)}
                                    className="ml-2 px-2.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 font-semibold cursor-pointer border border-cyan-500/30 transition-colors"
                                  >
                                    Xem thêm 100
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setDisplayLimit(filteredAlarms.length)}
                                    className="ml-1.5 px-2.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold cursor-pointer border border-slate-700 transition-colors"
                                  >
                                    Hiển thị tất cả ({filteredAlarms.length})
                                  </button>
                                </td>
                              </tr>
                            )}
                          </>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Justification & Governance Fields */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                {/* Reason Code */}
                <div>
                  <label htmlFor="reason-code-select" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                    Căn Cứ Nghiệp Vụ (Reason Policy)
                  </label>
                  <select
                    id="reason-code-select"
                    value={selectedReasonCode}
                    onChange={(e) => setSelectedReasonCode(e.target.value)}
                    className="w-full rounded-lg bg-[#070e1d] border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                  >
                    {REASON_CODES.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-[10px] text-slate-400">
                    {REASON_CODES.find((r) => r.code === selectedReasonCode)?.desc}
                  </p>
                </div>

                {/* Operator ID */}
                <div>
                  <label htmlFor="operator-id-input" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                    Mã Kỹ Sư Vận Hành
                  </label>
                  <input
                    id="operator-id-input"
                    type="text"
                    value={operatorId}
                    onChange={(e) => setOperatorId(e.target.value)}
                    placeholder="Mã nhân viên / tài khoản vận hành"
                    className="w-full rounded-lg bg-[#070e1d] border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                    required
                  />
                </div>
              </div>

              {/* Note / Edit summary */}
              <div>
                <label htmlFor="notes-textarea" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                  Ghi Chú Giải Thích Chi Tiết (Audit Rationale)
                </label>
                <textarea
                  id="notes-textarea"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="VD: Căn cứ tô-pô mạng thực tế, điều chỉnh gom hoặc tách nhóm cảnh báo để tối ưu điều hành ứng cứu..."
                  rows={2}
                  className="w-full rounded-lg bg-[#070e1d] border border-slate-700 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
                />
              </div>

              {/* Invariant Warning Messages */}
              {operation !== 'MERGE' && selectedCount === 0 && (
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-amber-950/40 border border-amber-700/50 text-xs text-amber-300">
                  <span className="material-symbols-outlined text-[16px]">warning</span>
                  <span>Vui lòng chọn ít nhất 1 cảnh báo để thực hiện thao tác {currentOpMeta.label}.</span>
                </div>
              )}
              {operation !== 'MERGE' && selectedCount === alarms.length && alarms.length > 0 && (
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-rose-950/40 border border-rose-700/50 text-xs text-rose-300">
                  <span className="material-symbols-outlined text-[16px]">error</span>
                  <span>
                    Không thể chuyển toàn bộ cảnh báo! Chuỗi gốc phải giữ lại ít nhất 1 cảnh báo. (Nếu muốn gộp toàn bộ, hãy dùng thao tác <strong>Ghép Chuỗi (Merge)</strong>).
                  </span>
                </div>
              )}
              {error && (
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-rose-950/50 border border-rose-600 text-xs text-rose-300">
                  <span className="material-symbols-outlined text-[16px]">error</span>
                  <span>{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Modal Footer */}
        {!successResult && (
          <div className="flex items-center justify-between border-t border-[#1e2e4a] bg-[#0c1424] px-6 py-3.5">
            <div className="text-xs text-slate-400">
              {isCurrentOpValid ? (
                <span className="text-cyan-300 font-medium">
                  ✓ Sẵn sàng lưu phương án {currentOpMeta.label}
                </span>
              ) : (
                <span>Vui lòng hoàn tất cấu hình phân hoạch hợp lệ trước khi lưu</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyTicketReport}
                disabled={!isCurrentOpValid}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                title="Sao chép bản tóm tắt phân hoạch hiện tại vào clipboard để dán Ticket"
              >
                <span className="material-symbols-outlined text-[14px]">
                  {copiedReportMsg ? 'check' : 'content_copy'}
                </span>
                <span>{copiedReportMsg ? 'Đã sao chép!' : '📋 Copy Ticket'}</span>
              </button>
              <button
                type="button"
                onClick={handleDownloadDiffJson}
                disabled={!isCurrentOpValid}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                title="Tải cấu hình phân hoạch dưới dạng file JSON diff"
              >
                <span className="material-symbols-outlined text-[14px]">download</span>
                <span>JSON</span>
              </button>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs font-semibold hover:bg-slate-700 transition-colors cursor-pointer"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!isCurrentOpValid || submitting}
                className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg font-bold text-xs transition-all shadow-md cursor-pointer ${
                  isCurrentOpValid && !submitting
                    ? 'bg-cyan-500 hover:bg-cyan-400 text-[#070e1d]'
                    : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
                }`}
              >
                {submitting ? (
                  <>
                    <span className="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>
                    <span>Đang lưu…</span>
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined text-[16px]">save</span>
                    <span>Lưu Phương Án ({currentOpMeta.op})</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
