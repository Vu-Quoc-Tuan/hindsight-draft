const FALLBACK_LABELS: Record<string, string> = {
  NOT_CONFIGURED: 'Not configured',
  INVALID_CONFIGURATION: 'Invalid provider configuration',
  HTTP_ERROR: 'Provider HTTP error',
  TIMEOUT: 'Provider timeout',
  INVALID_RESPONSE: 'Invalid provider response',
  PROVIDER_ERROR: 'Provider unavailable',
  TOOL_LOOP_LIMIT: 'Tool loop limit reached',
  INVALID_TOOL_CALL: 'Invalid tool call',
  GROUNDING_VIOLATION: 'Grounding validation failed',
  STALE_CONTEXT: 'Workspace context changed',
  OUTPUT_REJECTED: 'AI output exceeded briefing constraints',
}

export function GroundedProviderBadge({
  model,
  providerStatus,
  responseMode,
}: {
  model: string
  providerStatus: string
  responseMode?: 'LLM_PRIMARY' | 'DETERMINISTIC_FALLBACK'
}) {
  if (responseMode === 'LLM_PRIMARY' || (!responseMode && providerStatus === 'OK')) {
    return (
      <span className="pill pill--positive" aria-label={`AI-assisted narrative using ${model}`}>
        AI-assisted · {model}
      </span>
    )
  }

  if (providerStatus === 'NOT_APPLIED') {
    return (
      <span className="pill pill--neutral" aria-label="Grounded AI rendering was not applicable">
        Deterministic · not applied
      </span>
    )
  }

  const detail = FALLBACK_LABELS[providerStatus]
  return (
    <span
      className="pill pill--neutral"
      aria-label={`Deterministic fallback${detail ? `: ${detail}` : ''}`}
    >
      Deterministic fallback{detail ? ` · ${detail}` : ''}
    </span>
  )
}
