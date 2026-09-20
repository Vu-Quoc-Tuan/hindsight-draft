export function percent(value: number | null | undefined): string {
  return value == null ? 'UNAVAILABLE' : `${Math.round(value * 100)}%`
}

export function compactTime(value: string | null): string {
  if (!value) return 'time unavailable'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return value
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(parsed)
}

export function duration(milliseconds: number | undefined): string {
  if (milliseconds == null) return '—'
  if (milliseconds < 1) return `${Math.round(milliseconds * 1000)}µs`
  return `${milliseconds.toFixed(milliseconds < 10 ? 1 : 0)}ms`
}

export function humanize(value: string): string {
  return value.toLowerCase().replaceAll('_', ' ')
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return 'Unavailable'
  if (seconds <= 0) return '0s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.round((seconds % 3600) / 60)
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`
}
