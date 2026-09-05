const FALLBACK_LABELS: Record<string, string> = {
  NOT_CONFIGURED: 'Not configured',
  HTTP_ERROR: 'Provider HTTP error',
  TIMEOUT: 'Provider timeout',
  INVALID_RESPONSE: 'Invalid provider response',
  PROVIDER_ERROR: 'Provider unavailable',
}

export function GroundedProviderBadge({
  model,
  providerStatus,
}: {
  model: string
  providerStatus: string
}) {
  if (providerStatus === 'OK') {
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
