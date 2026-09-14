/**
 * Utilities for exporting partition diffs and generating NOC incident ticket reports (§UX Enhancement).
 */

export interface ExportPartitionParams {
  chainId: string
  operation: string
  operatorId: string
  createdAt?: string
  reasonCode?: string
  notes?: string
  partitionDelta?: {
    before?: [string, string[]][] | Record<string, string[]>
    after?: [string, string[]][] | Record<string, string[]>
  }
  alarmMap?: Record<string, { alarm_name?: string | null; device_code?: string | null; role?: string | null }>
}

/**
 * Generate human-readable plaintext / markdown report ready to paste into NOC ticketing systems (Jira / ITSM).
 */
export function generatePartitionTicketReport(params: ExportPartitionParams): string {
  const {
    chainId,
    operation,
    operatorId,
    createdAt = new Date().toISOString(),
    reasonCode = 'N/A',
    notes,
    partitionDelta,
    alarmMap = {},
  } = params

  const dateStr = new Date(createdAt).toLocaleString()

  let report = `======================================================================
📋 BÁO CÁO PHÂN HOẠCH SỰ CỐ NOCPRO (OPERATOR PARTITION DIFF REPORT)
======================================================================
• Mã chuỗi sự cố (Incident Chain) : ${chainId}
• Nghiệp vụ điều chỉnh (Operation) : ${operation}
• Kỹ sư thực hiện (Operator)      : ${operatorId}
• Thời gian ghi nhận (Timestamp)  : ${dateStr}
• Căn cứ nghiệp vụ (Reason Code)   : ${reasonCode}
• Ghi chú kỹ sư (Notes)            : ${notes || 'Không có ghi chú thêm'}
----------------------------------------------------------------------
📊 CẤU TRÚC PHÂN HOẠCH SAU KHI ĐIỀU CHỈNH (AFTER PARTITIONS):
`

  if (partitionDelta?.after) {
    const afterEntries: Array<[string, string[]]> = Array.isArray(partitionDelta.after)
      ? partitionDelta.after
      : Object.entries(partitionDelta.after)

    afterEntries.forEach(([pId, alarmIds], idx) => {
      report += `\n[Phân vùng ${idx + 1}]: ${pId} (${alarmIds.length} cảnh báo)\n`
      alarmIds.forEach((aid, aIdx) => {
        const info = alarmMap[aid]
        const dev = info?.device_code ? `[${info.device_code}] ` : ''
        const name = info?.alarm_name ? ` - ${info.alarm_name}` : ''
        const role = info?.role ? ` (${info.role})` : ''
        report += `   ${aIdx + 1}. ${aid} ${dev}${name}${role}\n`
      })
    })
  } else {
    report += `\n(Không có dữ liệu partition_delta.after)\n`
  }

  report += `----------------------------------------------------------------------
⚠️ LƯU Ý: Phân hoạch này được kỹ sư vận hành xác lập trên Hindsight NocPro
          theo nguyên tắc Zero Live Mutation (Bảo toàn số lượng cảnh báo).
======================================================================`

  return report
}

/**
 * Download partition diff as a formatted JSON artifact file.
 */
export function downloadPartitionDiffJson(params: ExportPartitionParams): void {
  if (typeof document === 'undefined') return

  const exportPayload = {
    export_schema: 'nocpro.partition_diff.v1',
    exported_at: new Date().toISOString(),
    incident_chain_id: params.chainId,
    operation: params.operation,
    operator: {
      id: params.operatorId,
      role: 'PRODUCT_OWNER',
    },
    governance: {
      reason_code: params.reasonCode,
      notes: params.notes,
      created_at: params.createdAt || new Date().toISOString(),
    },
    partition_delta: params.partitionDelta || {},
  }

  const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `partition_diff_${params.chainId}_${params.operation}_${timestamp}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Copy string content to clipboard with fallback.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof window !== 'undefined' && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
    if (typeof document !== 'undefined') {
      const textArea = document.createElement('textarea')
      textArea.value = text
      textArea.style.position = 'fixed'
      textArea.style.left = '-999999px'
      textArea.style.top = '-999999px'
      document.body.appendChild(textArea)
      textArea.focus()
      textArea.select()
      const successful = document.execCommand('copy')
      document.body.removeChild(textArea)
      return successful
    }
    return false
  } catch (err) {
    console.error('Failed to copy text to clipboard:', err)
    return false
  }
}
