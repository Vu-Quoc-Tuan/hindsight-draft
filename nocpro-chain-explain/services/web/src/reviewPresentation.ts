import type { CounterfactualCandidate } from './types'

export function getConciseCandidateTitle(candidate: CounterfactualCandidate): string {
  if (candidate.operation === 'SPLIT_CHAIN') {
    const after = candidate.partition_delta?.after || []
    const sizes = after
      .map((entry) => (Array.isArray(entry[1]) ? entry[1].length : 0))
      .filter((size) => size > 0)
    if (sizes.length >= 2) return `Chia chain thành ${sizes.length} chain nhỏ (${sizes.join(' và ')} alarm)`
    return 'Chia chain thành các chain nhỏ'
  }

  if (candidate.operation === 'REMOVE_MEMBER') {
    const memberIds = candidate.member_ids || []
    if (memberIds.length === 1) return `Cắt ${memberIds[0]} ra khỏi chain`
    if (memberIds.length > 1) return `Cắt ${memberIds.length} alarm ra khỏi chain`
    const beforeAlarms = candidate.partition_delta?.before?.[0]?.[1] || []
    const afterAlarms = candidate.partition_delta?.after?.[0]?.[1] || []
    const diff = beforeAlarms.filter((alarm) => !afterAlarms.includes(alarm))
    if (diff.length === 1) return `Cắt ${diff[0]} ra khỏi chain`
    if (diff.length > 1) return `Cắt ${diff.length} alarm ra khỏi chain`
    return 'Cắt alarm ra khỏi chain'
  }

  if (candidate.operation === 'MOVE_MEMBER') {
    const member = candidate.member_ids?.[0] || 'alarm'
    const target = candidate.target_chain_id ? `chain ${candidate.target_chain_id}` : 'chain khác'
    return `Chuyển ${member} sang ${target}`
  }

  if (candidate.operation === 'MERGE_CHAINS') {
    const merged = candidate.merged_chain_ids || []
    if (merged.length >= 2) return `Gộp chain ${merged.join(' và ')}`
    return 'Gộp với chain lân cận'
  }

  return candidate.comparative_explanation?.summary_action || 'Điều chỉnh phân hoạch chuỗi sự cố'
}
