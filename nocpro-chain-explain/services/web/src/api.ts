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
  ChainOverviewCards,
  ChainList,
  ChainQualitySummary,
  AnalysisIdentity,
  ArtifactRevision,
  CounterfactualJob,
  EvidenceBundle,
  Evolution,
  EvolutionChanges,
  EvolutionEndpoint,
  Job,
  OperatorFeedback,
  PairWhy,
  ReasonPolicy,
  ReviewDecision,
  SimilarCaseRetrievalResult,
  CandidateDisplayEventItem,
  ManualCorrectionPayload,
  ReviewLearningStatus,
  ProposalClarityComparison,
  ThresholdExplainOptimization,
} from './types'
import type { TopologyTreePayload } from './TopologyTree'
import { clearReviewJobCache } from './reviewJobCache'
import { clearChainReadCache, getOrLoadChainRead } from './chainReadCache'
import {
  analysisIdentityMatches,
  artifactRevisionMatches,
  isAnalysisIdentity,
  isArtifactRevision,
} from './analysisIdentity'

export { clearChainReadCache } from './chainReadCache'


export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type ActiveSnapshotContext = {
  snapshotId: string
  snapshotVersion: string
  topologyVersion?: string | null
} | null

export type ChainOverviewSnapshotContext = {
  snapshot_id: string
  snapshot_version: string
  topology_version?: string | null
}

let activeSnapshotContext: ActiveSnapshotContext = null

export function setActiveSnapshotContext(
  snapshotId: string | null,
  snapshotVersion: string | null = null,
  topologyVersion?: string | null,
) {
  const nextContext = snapshotId && snapshotVersion
    ? { snapshotId, snapshotVersion, topologyVersion }
    : null
  if (JSON.stringify(activeSnapshotContext) !== JSON.stringify(nextContext)) {
    clearChainReadCache()
    clearReviewJobCache()
    clearCohesionCache()
    clearTopologySubgraphCache()
  }
  activeSnapshotContext = nextContext
}

async function request<T>(
  path: string,
  init?: RequestInit,
  requestContext: ActiveSnapshotContext = activeSnapshotContext,
): Promise<T> {
  const headers = new Headers(init?.headers)
  if (requestContext) {
    headers.set('X-NocPro-Snapshot-Id', requestContext.snapshotId)
    headers.set('X-NocPro-Snapshot-Version', requestContext.snapshotVersion)
    if (requestContext.topologyVersion !== undefined) {
      headers.set('X-NocPro-Topology-Version', requestContext.topologyVersion ?? '')
    }
  }
  const response = await fetch(path, { ...init, headers })
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

function cacheableChainOverview(
  payload: ChainOverviewCards,
  chainId: string,
  context: NonNullable<ActiveSnapshotContext>,
): boolean {
  if (
    payload.chain_id !== chainId
    || payload.snapshot_id !== context.snapshotId
    || payload.snapshot_version !== context.snapshotVersion
  ) return false

  if (payload.status === 'NOT_APPLICABLE') {
    return payload.reason === 'SINGLETON_CHAIN'
  }
  if (payload.status !== 'READY') return false

  const identity = payload.analysis_identity
  const revision = payload.artifact_revision
  return typeof payload.projection_version === 'string'
    && payload.projection_version.length > 0
    && isAnalysisIdentity(identity)
    && isArtifactRevision(revision)
    && identity.snapshot_id === context.snapshotId
    && identity.snapshot_version === context.snapshotVersion
    && identity.chain_id === chainId
    && identity.topology_version === context.topologyVersion
    && payload.topology_version === context.topologyVersion
    && revision.resource_kind === 'chain_overview'
    && revision.fingerprint === identity.input_fingerprint
}

function cachedChainOverviewMatchesExpected(
  payload: ChainOverviewCards,
  chainId: string,
  context: NonNullable<ActiveSnapshotContext>,
  expectedIdentity?: AnalysisIdentity | null,
  expectedRevision?: ArtifactRevision | null,
): boolean {
  if (!cacheableChainOverview(payload, chainId, context)) return false
  if (payload.status === 'NOT_APPLICABLE') return true
  return isAnalysisIdentity(expectedIdentity)
    && isArtifactRevision(expectedRevision)
    && analysisIdentityMatches(payload.analysis_identity, expectedIdentity)
    && artifactRevisionMatches(payload.artifact_revision, expectedRevision)
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

export type TopologySubgraphNode = {
  id: string
  name: string
  type: string
  is_seed: boolean
  source_tables?: string[]
  attributes?: Record<string, any>
}

export type TopologySubgraphEdge = {
  id: string
  source: string
  target: string
  relation: string
  direction_kind?: string
  dependency_semantics?: string
}

export type TopologySubgraphResult = {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  profile_id: string
  topology_version?: string
  nodes: TopologySubgraphNode[]
  edges: TopologySubgraphEdge[]
  reason?: string
  requested_seed_count?: number
  resolved_seed_count?: number
  retained_seed_count?: number
  dropped_seed_count?: number
  truncated?: boolean
  truncation_reasons?: string[]
}

type TopologySubgraphCacheEntry = {
  result: TopologySubgraphResult
  expiresAt: number
}

const SUBGRAPH_CACHE_TTL_MS = 30_000
const _subgraphCache = new Map<string, TopologySubgraphCacheEntry>()
const _subgraphVersionByRequest = new Map<string, string>()

export const clearTopologySubgraphCache = () => {
  _subgraphCache.clear()
  _subgraphVersionByRequest.clear()
}

async function topologySubgraphRequest(
  profileId: string,
  seeds: string[],
  hops: number = 2,
  signal?: AbortSignal,
  version?: string,
): Promise<TopologySubgraphResult> {
  if (![1, 2, 3, 4].includes(hops)) {
    throw new RangeError('Topology subgraph hops must be between 1 and 4')
  }
  const requestKey = `${profileId}:${seeds.slice().sort().join(',')}:${hops}:${version ?? 'active'}`
  const knownVersion = _subgraphVersionByRequest.get(requestKey)
  const cacheKey = knownVersion ? `${requestKey}:${knownVersion}` : undefined
  const cached = cacheKey ? _subgraphCache.get(cacheKey) : undefined
  if (cached && cached.expiresAt > Date.now()) {
    return cached.result
  }
  if (cacheKey) {
    _subgraphCache.delete(cacheKey)
    _subgraphVersionByRequest.delete(requestKey)
  }
  const url = explainTopologyUrl('subgraph')
  url.searchParams.set('profile_id', profileId)
  if (seeds.length > 0) url.searchParams.set('seeds', seeds.join(','))
  url.searchParams.set('hops', String(hops))
  if (version) url.searchParams.set('version', version)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  const result = (await response.json()) as TopologySubgraphResult
  // UNAVAILABLE is a transient topology-ingestion state and must remain
  // retryable.  An AVAILABLE response is short-lived and version-scoped.
  if (result.status === 'AVAILABLE' && result.topology_version) {
    const versionedCacheKey = `${requestKey}:${result.topology_version}`
    _subgraphCache.set(versionedCacheKey, {
      result,
      expiresAt: Date.now() + SUBGRAPH_CACHE_TTL_MS,
    })
    _subgraphVersionByRequest.set(requestKey, result.topology_version)
  }
  return result
}

// Unpinned snapshots can bind a newer Kafka topology without changing their ID.
// Keep the fast repeat-click path, but never retain provider prose for minutes.
const COHESION_CACHE_TTL_MS = 4_000
const _cohesionCache = new Map<string, { result: CohesionNarrativeView; expiresAt: number }>()

const cohesionCacheKey = (chainId: string, lang: string) =>
  `${chainId}\u0000${activeSnapshotContext?.snapshotId ?? 'NO_SNAPSHOT'}\u0000${activeSnapshotContext?.snapshotVersion ?? 'NO_VERSION'}\u0000${activeSnapshotContext?.topologyVersion ?? 'UNKNOWN_TOPOLOGY'}\u0000${lang}`

const LEGACY_COHESION_FALLBACK_PREFIXES = [
  'Chưa tạo được nhận định AI đáp ứng kiểm tra grounding.',
  'No AI investigation insight passed grounding validation.',
]

export const isProviderCohesion = (result: CohesionNarrativeView): boolean => {
  const narrative = result.narrative?.trim() ?? ''
  const isLegacyFallback = LEGACY_COHESION_FALLBACK_PREFIXES.some((prefix) => narrative.startsWith(prefix))
  return Boolean(narrative) && Boolean(result.model?.trim()) && result.model !== 'DETERMINISTIC_EVIDENCE' && !isLegacyFallback
}

/**
 * Prevent rows written by older builds from being rendered as current AI
 * prose. The evidence context and diagnostic status remain available.
 */
export const sanitizeCohesionNarrative = (result: CohesionNarrativeView): CohesionNarrativeView =>
  isProviderCohesion(result) ? result : { ...result, narrative: '' }

export const sanitizeAssistantResponse = (result: AssistantResponse): AssistantResponse => {
  const isLegacyDeterministicMessage =
    result.response_mode === 'DETERMINISTIC_FALLBACK' || result.model === 'DETERMINISTIC_EVIDENCE'
  return isLegacyDeterministicMessage ? { ...result, message: '' } : result
}

export const cachedCohesionNarrative = (
  chainId: string,
  lang: string = 'vi',
): CohesionNarrativeView | null => {
  const key = cohesionCacheKey(chainId, lang)
  const cached = _cohesionCache.get(key)
  if (!cached) return null
  if (cached.expiresAt <= Date.now()) {
    _cohesionCache.delete(key)
    return null
  }
  return isProviderCohesion(cached.result) ? cached.result : null
}

export const clearCohesionCache = (chainId?: string) => {
  if (!chainId) {
    _cohesionCache.clear()
    return
  }
  const prefix = `${chainId}\u0000`
  for (const key of _cohesionCache.keys()) {
    if (key.startsWith(prefix)) _cohesionCache.delete(key)
  }
}

export const shouldForceCohesionRefresh = (explicitReloadCount: number) => explicitReloadCount > 0

export const api = {
  health: (signal?: AbortSignal) =>
    request<{ status: string }>('/api/v1/health', { signal }),
  listSnapshots: (signal?: AbortSignal) =>
    request<{
      active_snapshot_id: string | null
      active_snapshot_version: string | null
      snapshots: Array<{
        snapshot_id: string
        snapshot_version?: string | null
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
  selectSnapshot: (snapshotId: string, snapshotVersion?: string | null, signal?: AbortSignal) =>
    request<{
      snapshot_id: string
      snapshot_version: string
      topology_version?: string | null
      alarm_count: number
      chain_count: number
      chains?: ChainList['chains']
    }>('/api/v1/snapshots/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snapshot_id: snapshotId, ...(snapshotVersion ? { snapshot_version: snapshotVersion } : {}) }),
      signal,
    }),
  loadSnapshot: (payload: unknown) =>
    request<{
      snapshot_id: string
      snapshot_version: string
      topology_version?: string | null
      alarm_count: number
      chain_count: number
    }>('/api/v1/snapshots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  chains: (signal?: AbortSignal) =>
    request<ChainList>('/api/v1/chains', { signal }),
  snapshotQualitySummaries: (signal?: AbortSignal) =>
    request<{ summaries: ChainQualitySummary[] }>('/api/v1/snapshots/quality-summaries', { signal }),
  analysis: (chainId: string, signal?: AbortSignal) =>
    request<ChainAnalysis>(`/api/v1/chains/${encodeURIComponent(chainId)}`, {
      signal,
    }),
  chainOverviewCards: (
    chainId: string,
    signal?: AbortSignal,
    expectedIdentity?: AnalysisIdentity | null,
    expectedRevision?: ArtifactRevision | null,
    snapshotContext?: ChainOverviewSnapshotContext,
  ) => {
    const path = `/api/v1/chains/${encodeURIComponent(chainId)}/overview-cards`
    const context: ActiveSnapshotContext = snapshotContext
      ? {
          snapshotId: snapshotContext.snapshot_id,
          snapshotVersion: snapshotContext.snapshot_version,
          topologyVersion: snapshotContext.topology_version,
        }
      : activeSnapshotContext
    // Without an explicit topology version, an unpinned snapshot can resolve
    // against different active Kafka states between reads. Keep it uncached.
    if (!context || context.topologyVersion === undefined) {
      return request<ChainOverviewCards>(path, { signal }, context)
    }

    const key = JSON.stringify([
      'chain-overview-v1',
      context.snapshotId,
      context.snapshotVersion,
      context.topologyVersion === null
        ? { topology: 'NONE' }
        : { topology: 'VERSION', version: context.topologyVersion },
      chainId,
    ])
    return getOrLoadChainRead(
      key,
      signal,
      sharedSignal => request<ChainOverviewCards>(path, { signal: sharedSignal }, context),
      payload => cacheableChainOverview(payload, chainId, context),
      payload => cachedChainOverviewMatchesExpected(
        payload,
        chainId,
        context,
        expectedIdentity,
        expectedRevision,
      ),
    )
  },
  chainEvidence: (
    chainId: string,
    options: { limit?: number; cursor?: string } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams({ limit: String(options.limit ?? 100) })
    if (options.cursor) query.set('cursor', options.cursor)
    return request<EvidenceBundle>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/evidence?${query.toString()}`,
      { signal },
    )
  },
  evolution: (chainId: string, signal?: AbortSignal) =>
    request<Evolution>(`/api/v1/chains/${encodeURIComponent(chainId)}/evolution`, {
      signal,
    }),
  evolutionChanges: (
    chainId: string,
    selection: { parent?: EvolutionEndpoint; parentReceiptId?: string; childReceiptId?: string } = {},
    signal?: AbortSignal,
    snapshotContext?: ChainOverviewSnapshotContext,
  ) => {
    const query = new URLSearchParams()
    if (selection.parent) {
      query.set('parent_snapshot_id', selection.parent.snapshot_id)
      query.set('parent_snapshot_version', selection.parent.snapshot_version)
      query.set('parent_chain_id', selection.parent.chain_id)
    }
    if (selection.parentReceiptId) query.set('parent_receipt_id', selection.parentReceiptId)
    if (selection.childReceiptId) query.set('child_receipt_id', selection.childReceiptId)
    const context: ActiveSnapshotContext = snapshotContext
      ? { snapshotId: snapshotContext.snapshot_id, snapshotVersion: snapshotContext.snapshot_version }
      : activeSnapshotContext
    const suffix = query.size ? `?${query.toString()}` : ''
    return request<EvolutionChanges>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/evolution/changes${suffix}`,
      { signal },
      context,
    )
  },
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
  cohesionNarrative: async (
    chainId: string,
    signal?: AbortSignal,
    lang: string = 'vi',
    forceRefresh: boolean = false
  ): Promise<CohesionNarrativeView> => {
    if (!forceRefresh) {
      const cached = cachedCohesionNarrative(chainId, lang)
      if (cached) return cached
    }
    const url = `/api/v1/chains/${encodeURIComponent(chainId)}/cohesion-narrative?lang=${encodeURIComponent(lang)}${forceRefresh ? '&force_refresh=true' : ''}`
    const result = sanitizeCohesionNarrative(await request<CohesionNarrativeView>(url, { signal }))
    if (isProviderCohesion(result)) {
      _cohesionCache.set(cohesionCacheKey(chainId, lang), {
        result,
        expiresAt: Date.now() + COHESION_CACHE_TTL_MS,
      })
    } else {
      _cohesionCache.delete(cohesionCacheKey(chainId, lang))
    }
    return result
  },
  assistantQuery: async (query: string, context: AssistantContext, history: AssistantHistoryMessage[] = [], signal?: AbortSignal) =>
    sanitizeAssistantResponse(await request<AssistantResponse>('/api/v1/assistant/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, context, history }),
      signal,
    })),
  topologyProfiles: (signal?: AbortSignal) =>
    topologyProfilesRequest(signal),
  topologyProjection: (profileId: string, signal?: AbortSignal, rootId?: string) =>
    topologyRequest(profileId, signal, rootId),
  topologySearch: (profileId: string, query: string, signal?: AbortSignal) =>
    topologySearchRequest(profileId, query, signal),
  topologyResolve: (profileId: string, identifier: string, signal?: AbortSignal) =>
    topologyResolveRequest(profileId, identifier, signal),
  topologySubgraph: (profileId: string, seeds: string[], hops?: number, signal?: AbortSignal, version?: string) =>
    topologySubgraphRequest(profileId, seeds, hops, signal, version),
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
  reviewLearningStatus: (signal?: AbortSignal) =>
    request<ReviewLearningStatus>('/api/v1/review-learning/status', { signal }),
  getProposalClarityComparison: (jobId: string, lang: string = 'vi', signal?: AbortSignal) =>
    request<ProposalClarityComparison>(
      `/api/v1/review-jobs/${encodeURIComponent(jobId)}/compare-proposals-clarity?lang=${encodeURIComponent(lang)}`,
      { signal },
    ),
  optimizeExplainThreshold: (chainId: string, signal?: AbortSignal) =>
    request<ThresholdExplainOptimization>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/optimize-explain-threshold`,
      {
        method: 'POST',
        signal,
      },
    ),
  applyExplainThreshold: (chainId: string, parameters: Record<string, number>, signal?: AbortSignal) =>
    request<{ chain_id: string; status: string; applied_parameters: Record<string, number>; message: string }>(
      `/api/v1/chains/${encodeURIComponent(chainId)}/apply-explain-threshold`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters }),
        signal,
      },
    ),
}
