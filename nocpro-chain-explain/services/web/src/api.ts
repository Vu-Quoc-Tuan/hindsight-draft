import type {
  AISuggestion,
  CohesionNarrativeView,
  AnalysisConfigView,
  AssistantContext,
  AssistantHistoryMessage,
  AssistantResponse,
  AuditVisualizationArtifact,
  CalibrationReport,
  ChainAnalysis,
  ChainList,
  CounterfactualJob,
  Evolution,
  Job,
  OperatorFeedback,
  PairWhy,
  ReasonPolicy,
  ReviewDecision,
  SimilarCaseRetrievalResult,
  CandidateDisplayEventItem,
  ManualCorrectionPayload,
} from './types'
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

export type TopologySearchResult = {
  resource_id: string
  resource_type: string
  display_name: string
}

export type TopologyNavigationResolution = {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  dataset_profile: 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'
  identifier: string
  resource_id: string | null
  mapping_status: 'EXACT_RESOURCE_ID' | 'EXACT_IDENTITY' | 'UNIQUE_SOURCE_FIELD_MATCH' | 'AMBIGUOUS' | 'UNMAPPED'
  source_field: string | null
  navigation_eligible: boolean
  p2_mapping_eligible: boolean
  dependency_semantics: 'UNVERIFIED' | 'UNAVAILABLE'
  reason?: string
}

function explainTopologyUrl(subpath: string): URL {
  const origin = typeof window !== 'undefined' && window.location ? window.location.origin : 'http://127.0.0.1:3000'
  return new URL(`/api/v1/topology/${subpath.replace(/^\//, '')}`, origin)
}

async function topologyProfilesRequest(
  signal?: AbortSignal,
): Promise<{ status: string; profiles: string[] }> {
  const url = explainTopologyUrl('profiles')
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  return (await response.json()) as { status: string; profiles: string[] }
}

async function topologyRequest(
  profileId: string,
  signal?: AbortSignal,
  rootId?: string,
): Promise<TopologyTreePayload> {
  const url = explainTopologyUrl('projection')
  url.searchParams.set('profile_id', profileId)
  if (rootId) url.searchParams.set('root_id', rootId)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  return (await response.json()) as TopologyTreePayload
}

async function topologySearchRequest(
  profileId: string,
  query: string,
  signal?: AbortSignal,
): Promise<TopologySearchResult[]> {
  if (!query.trim()) return []
  const url = explainTopologyUrl('search')
  url.searchParams.set('profile_id', profileId)
  url.searchParams.set('q', query)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  const payload = (await response.json()) as { status: string; results?: TopologySearchResult[] }
  return payload.status === 'AVAILABLE' ? payload.results ?? [] : []
}

async function topologyResolveRequest(
  profileId: string,
  identifier: string,
  signal?: AbortSignal,
): Promise<TopologyNavigationResolution> {
  const url = explainTopologyUrl('resolve')
  url.searchParams.set('profile_id', profileId)
  url.searchParams.set('identifier', identifier)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  return (await response.json()) as TopologyNavigationResolution
}


export const api = {
  health: (signal?: AbortSignal) =>
    request<{ status: string }>('/api/v1/health', { signal }),
  listSnapshots: (signal?: AbortSignal) =>
    request<{
      active_snapshot_id: string | null
      active_snapshot_version: string | null
      snapshots: Array<{
        snapshot_id: string
        name: string
        profile: 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'
        alarm_count: number
        chain_count: number
        description: string
        badge: string
        available?: boolean
        unavailable_reason?: string | null
      }>
    }>('/api/v1/snapshots', { signal }),
  selectSnapshot: (snapshotId: string, signal?: AbortSignal) =>
    request<{
      snapshot_id: string
      snapshot_version: string
      alarm_count: number
      chain_count: number
    }>('/api/v1/snapshots/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snapshot_id: snapshotId }),
      signal,
    }),
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
  latestDeepDive: (chainId: string, signal?: AbortSignal) =>
    request<Job | null>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/deep-dive`,
      { signal },
    ),
  job: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { signal }),
  auditVisualization: (chainId: string, signal?: AbortSignal) =>
    request<AuditVisualizationArtifact>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/audit-visualization`,
      { signal },
    ),
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
  reviewReasons: (signal?: AbortSignal) =>
    request<ReasonPolicy>('/api/v1/review-reasons', { signal }),
  recordDisplayEvents: (
    jobId: string,
    events: CandidateDisplayEventItem[],
    signal?: AbortSignal,
  ) =>
    request<{ recorded_events: number }>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/display-events`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events }),
        signal,
      },
    ),
  submitReviewFeedback: (
    jobId: string,
    payload: {
      candidate_id?: string | null
      decision: ReviewDecision
      confidence?: number | null
      reason?: string | null
      notes?: string | null
      reason_code?: string | null
      reason_codes?: string[]
      reason_policy_version?: string
      manual_correction?: ManualCorrectionPayload | null
    },
    headers?: Record<string, string>,
    signal?: AbortSignal,
  ) =>
    request<OperatorFeedback>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/feedback`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(headers || {}) },
        body: JSON.stringify(payload),
        signal,
      },
    ),
  supersedeFeedback: (
    jobId: string,
    feedbackId: string,
    payload: {
      candidate_id?: string | null
      decision: ReviewDecision
      confidence?: number | null
      reason?: string | null
      notes?: string | null
      reason_code?: string | null
      reason_codes?: string[]
      reason_policy_version?: string
      manual_correction?: ManualCorrectionPayload | null
    },
    headers?: Record<string, string>,
    signal?: AbortSignal,
  ) =>
    request<OperatorFeedback>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/feedback/${encodeURIComponent(feedbackId)}/supersede`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(headers || {}) },
        body: JSON.stringify(payload),
        signal,
      },
    ),
  retractFeedback: (
    jobId: string,
    feedbackId: string,
    reason?: string,
    headers?: Record<string, string>,
    signal?: AbortSignal,
  ) =>
    request<{ status: string; feedback_id: string }>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/feedback/${encodeURIComponent(feedbackId)}/retract`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(headers || {}) },
        body: JSON.stringify({ reason }),
        signal,
      },
    ),
  similarCases: (
    jobId: string,
    candidateId: string,
    topK: number = 5,
    signal?: AbortSignal,
  ) =>
    request<SimilarCaseRetrievalResult>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/candidates/${encodeURIComponent(candidateId)}/similar-cases?top_k=${topK}`,
      { signal },
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
  aiSuggestion: (chainId: string, signal?: AbortSignal, lang: string = 'vi') =>
    request<AISuggestion>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/ai-suggestion?lang=${encodeURIComponent(lang)}`,
      { signal },
    ),
  cohesionNarrative: (chainId: string, signal?: AbortSignal, lang: string = 'vi') =>
    request<CohesionNarrativeView>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/cohesion-narrative?lang=${encodeURIComponent(lang)}`,
      { signal },
    ),
  assistantQuery: (query: string, context: AssistantContext, history: AssistantHistoryMessage[] = [], signal?: AbortSignal) =>
    request<AssistantResponse>('/api/v1/assistant/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, context, history }),
      signal,
    }),
  topologyProfiles: (signal?: AbortSignal) =>
    topologyProfilesRequest(signal),
  topologyProjection: (profileId: string, signal?: AbortSignal, rootId?: string) =>
    topologyRequest(profileId, signal, rootId),
  topologySearch: (profileId: string, query: string, signal?: AbortSignal) =>
    topologySearchRequest(profileId, query, signal),
  topologyResolve: (profileId: string, identifier: string, signal?: AbortSignal) =>
    topologyResolveRequest(profileId, identifier, signal),
  getConfig: (signal?: AbortSignal) => request<AnalysisConfigView>('/api/v1/config', { signal }),
  updateConfig: (parameters: Record<string, number>, signal?: AbortSignal) =>
    request<AnalysisConfigView>('/api/v1/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parameters }),
      signal,
    }),
  resetConfig: (signal?: AbortSignal) =>
    request<AnalysisConfigView>('/api/v1/config/reset', {
      method: 'POST',
      signal,
    }),
  calibrateConfig: (signal?: AbortSignal) =>
    request<CalibrationReport>('/api/v1/config/calibrate', {
      method: 'POST',
      signal,
    }),
}
