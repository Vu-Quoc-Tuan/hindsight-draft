const FALLBACK_LABELS: Record<string, string> = {
  NOT_CONFIGURED: 'Chưa cấu hình provider',
  INVALID_CONFIGURATION: 'Cấu hình provider không hợp lệ',
  HTTP_ERROR: 'Provider trả lỗi HTTP',
  HTTP_BAD_REQUEST: 'Provider từ chối request',
  HTTP_AUTH_ERROR: 'Provider xác thực thất bại',
  HTTP_NOT_FOUND: 'Không tìm thấy endpoint hoặc model',
  HTTP_REQUEST_TOO_LARGE: 'Request gửi tới AI quá lớn',
  REQUEST_TOO_LARGE: 'Request grounded AI quá lớn',
  HTTP_RATE_LIMITED: 'Provider giới hạn tần suất',
  HTTP_UPSTREAM_ERROR: 'Provider gặp lỗi dịch vụ',
  TIMEOUT: 'Provider hết thời gian chờ',
  INVALID_RESPONSE: 'Response từ provider không hợp lệ',
  INCOMPLETE_RESPONSE: 'Response từ provider bị cắt ngắn',
  OUTPUT_TOO_LONG: 'AI trả lời quá dài để xử lý an toàn',
  PROVIDER_ERROR: 'Provider không khả dụng',
  TOOL_LOOP_LIMIT: 'Đã vượt giới hạn vòng gọi tool',
  INVALID_TOOL_CALL: 'Lệnh gọi tool không hợp lệ',
  GROUNDING_VIOLATION: 'Không vượt qua kiểm tra grounding',
  GROUNDING_REFUSAL: 'AI trả về lời từ chối',
  GROUNDING_FORBIDDEN_CLAIM: 'AI nêu khẳng định nhân quả chưa có bằng chứng',
  GROUNDING_UNSUPPORTED_CLAIM: 'AI thêm diễn giải chưa được evidence hỗ trợ',
  GROUNDING_IDENTIFIER_MISMATCH: 'AI thêm định danh không có trong evidence',
  GROUNDING_IP_MISMATCH: 'AI thêm địa chỉ IP không có trong evidence',
  GROUNDING_NUMBER_MISMATCH: 'AI thêm con số không có trong evidence',
  GROUNDING_UNSUPPORTED_RELATION: 'AI khẳng định quan hệ topology chưa được xác minh',
  GROUNDING_BYPASS: 'Grounding đang tắt trong dev; output chưa được kiểm tra',
  STALE_CONTEXT: 'Context workspace đã thay đổi',
  OUTPUT_REJECTED: 'Output AI không đạt ràng buộc nhận định',
}

export function GroundedProviderBadge({
  model,
  providerStatus,
  responseMode,
  hasProviderOutput = true,
}: {
  model: string
  providerStatus: string
  responseMode?: 'LLM_PRIMARY' | 'DETERMINISTIC_FALLBACK' | 'PROVIDER_UNAVAILABLE'
  hasProviderOutput?: boolean
}) {
  if (providerStatus === 'NOT_APPLIED') {
    return (
      <span className="pill pill--neutral" aria-label="Grounded AI rendering was not applicable">
        Deterministic · không áp dụng
      </span>
    )
  }

  if (providerStatus === 'GROUNDING_BYPASS') {
    return (
      <span
        className="pill pill--negative"
        aria-label="AI raw; kiểm tra grounding đang tắt trong môi trường dev"
      >
        AI raw · grounding tắt
      </span>
    )
  }

  const detail = FALLBACK_LABELS[providerStatus]
  const providerProseWasReturned =
    providerStatus.startsWith('GROUNDING_') && model && model !== 'DETERMINISTIC_EVIDENCE' && hasProviderOutput
  if (providerProseWasReturned) {
    return (
      <span
        className="pill pill--negative"
        aria-label={`AI raw; grounding cảnh báo${detail ? `: ${detail}` : ''}`}
      >
        AI raw · grounding cảnh báo{detail ? ` · ${detail}` : ''}
      </span>
    )
  }

  if (providerStatus.startsWith('GROUNDING_') && model && model !== 'DETERMINISTIC_EVIDENCE') {
    return (
      <span
        className="pill pill--negative"
        aria-label={`AI output bị chặn bởi grounding${detail ? `: ${detail}` : ''}`}
      >
        AI output bị chặn{detail ? ` · ${detail}` : ''}
      </span>
    )
  }

  if (providerStatus === 'OK' && (responseMode === 'LLM_PRIMARY' || !responseMode)) {
    return (
      <span className="pill pill--positive" aria-label={`Nhận định có AI hỗ trợ bằng ${model}`}>
        AI hỗ trợ · {model}
      </span>
    )
  }

  return (
    <span
      className="pill pill--neutral"
      aria-label={`AI chưa khả dụng${detail ? `: ${detail}` : ''}`}
    >
      AI chưa khả dụng{detail ? ` · ${detail}` : ''}
    </span>
  )
}
