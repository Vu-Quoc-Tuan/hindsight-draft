import type { ChainAnalysis, ChainList, Job, PairWhy } from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Preserve the HTTP status text when the response is not JSON.
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<{ status: string }>('/api/v1/health', { signal }),
  loadSnapshot: (payload: unknown) =>
    request<{
      snapshot_id: string
      alarm_count: number
      chain_count: number
    }>('/api/v1/snapshots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  chains: (signal?: AbortSignal) =>
    request<ChainList>('/api/v1/chains', { signal }),
  analysis: (chainId: string, signal?: AbortSignal) =>
    request<ChainAnalysis>(`/api/v1/chains/${encodeURIComponent(chainId)}`, {
      signal,
    }),
  pairWhy: (
    chainId: string,
    alarmA: string,
    alarmB: string,
    signal?: AbortSignal,
  ) =>
    request<PairWhy>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/pairs/${encodeURIComponent(alarmA)}/${encodeURIComponent(alarmB)}`,
      { signal },
    ),
  submitDeepDive: (chainId: string) =>
    request<{ job_id: string; cache_hit: boolean; deduplicated: boolean }>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/deep-dive`,
      { method: 'POST' },
    ),
  job: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { signal }),
}
