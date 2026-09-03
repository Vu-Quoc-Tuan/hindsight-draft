import type { AISuggestion, ChainAnalysis, ChainList, CounterfactualJob, Evolution, Job, OperatorFeedback, PairWhy } from './types'
import type { TopologyTreePayload } from './TopologyTree'

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

async function topologyRequest(profileId: string, signal?: AbortSignal): Promise<TopologyTreePayload> {
  const base = import.meta.env.VITE_NOCPRO_MOCK_URL
  if (!base) return {
    status: 'UNAVAILABLE', profile: profileId as 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES', topology_kind: 'UNAVAILABLE',
    reason: 'MOCK_TOPOLOGY_ENDPOINT_NOT_CONFIGURED',
  }
  const url = new URL('/api/topology/projection', base)
  url.searchParams.set('profile_id', profileId)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  return (await response.json()) as TopologyTreePayload
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<{ status: string }>('/api/v1/health', { signal }),
  loadSnapshot: (payload: unknown) =>
    request<{
      snapshot_id: string
      snapshot_version: string
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
  evolution: (chainId: string, signal?: AbortSignal) =>
    request<Evolution>(`/api/v1/chains/${encodeURIComponent(chainId)}/evolution`, {
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
  submitReview: (chainId: string) =>
    request<{ job_id: string; cache_hit: boolean; deduplicated: boolean }>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/review`,
      { method: 'POST' },
    ),
  reviewJob: (jobId: string, signal?: AbortSignal) =>
    request<CounterfactualJob>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}`,
      { signal },
    ),
  latestReview: (chainId: string, signal?: AbortSignal) =>
    request<CounterfactualJob>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/review`,
      { signal },
    ),
  submitReviewFeedback: (
    jobId: string,
    payload: {
      candidate_id: string
      decision: 'APPROVED' | 'REJECTED'
      operator_id?: string
      reason?: string
      auto_apply?: boolean
    },
  ) =>
    request<OperatorFeedback>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/feedback`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  reviewFeedback: (jobId: string, signal?: AbortSignal) =>
    request<OperatorFeedback[]>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/feedback`,
      { signal },
    ),
  chainFeedback: (chainId: string, signal?: AbortSignal) =>
    request<OperatorFeedback[]>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/feedback`,
      { signal },
    ),
  aiSuggestion: (chainId: string, signal?: AbortSignal) =>
    request<AISuggestion>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/ai-suggestion`,
      { signal },
    ),
  topologyProjection: (profileId: string, signal?: AbortSignal) => topologyRequest(profileId, signal),
}
