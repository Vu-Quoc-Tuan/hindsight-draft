import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  clearChainReadCache,
  clearCohesionCache,
  clearTopologySubgraphCache,
  setActiveSnapshotContext,
} from './api'

const overviewIdentity = {
  identity_version: 'analysis-identity-v1' as const,
  snapshot_id: 'S1',
  snapshot_version: '001',
  chain_id: 'C1',
  topology_version: 'topology-v1',
  analysis_config_version: 'analysis-config-v1',
  review_config_version: 'review-config-v1',
  pipeline_version: 'pipeline-v1',
  input_fingerprint: 'overview-fingerprint',
}

const readyOverview = (overrides: Record<string, unknown> = {}) => ({
  snapshot_id: 'S1',
  snapshot_version: '001',
  chain_id: 'C1',
  status: 'READY',
  projection_version: 'CHAIN_OVERVIEW_V6',
  reason: null,
  topology_version: 'topology-v1',
  representative_member: null,
  topology: null,
  quality_assessment: null,
  recommendations: null,
  analysis_identity: overviewIdentity,
  artifact_revision: { resource_kind: 'chain_overview', fingerprint: 'overview-fingerprint' },
  ...overrides,
})

const available = (version: string) => ({
  status: 'AVAILABLE' as const,
  profile_id: 'IP_NETWORK',
  topology_version: version,
  nodes: [],
  edges: [],
})

describe('topology subgraph cache', () => {
  afterEach(() => {
    clearChainReadCache()
    clearTopologySubgraphCache()
    clearCohesionCache()
    setActiveSnapshotContext(null)
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('does not cache retryable unavailable responses', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'UNAVAILABLE', profile_id: 'IP_NETWORK', nodes: [], edges: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify(available('v2'))))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.topologySubgraph('IP_NETWORK', ['A'])).status).toBe('UNAVAILABLE')
    expect((await api.topologySubgraph('IP_NETWORK', ['A'])).topology_version).toBe('v2')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('uses an available version only until its TTL expires', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-20T00:00:00Z'))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(available('v1'))))
      .mockResolvedValueOnce(new Response(JSON.stringify(available('v2'))))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.topologySubgraph('IP_NETWORK', ['A'])).topology_version).toBe('v1')
    expect((await api.topologySubgraph('IP_NETWORK', ['A'])).topology_version).toBe('v1')
    vi.advanceTimersByTime(30_001)
    expect((await api.topologySubgraph('IP_NETWORK', ['A'])).topology_version).toBe('v2')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it.each([0, 5])('rejects unsupported %i-hop requests before fetch', async (hops) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.topologySubgraph('IP_NETWORK', ['A'], hops)).rejects.toThrow(
      'Topology subgraph hops must be between 1 and 4',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requests a pinned four-hop topology subgraph when needed for a backend path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(available('v4'))))
    vi.stubGlobal('fetch', fetchMock)

    await api.topologySubgraph('IP_NETWORK', ['A'], 4, undefined, 'topology-v4')

    const requestUrl = fetchMock.mock.calls[0][0] as URL
    expect(requestUrl.searchParams.get('hops')).toBe('4')
    expect(requestUrl.searchParams.get('version')).toBe('topology-v4')
  })

  it('forwards the abort signal to the subgraph request', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(available('v1'))))
    vi.stubGlobal('fetch', fetchMock)

    await api.topologySubgraph('IP_NETWORK', ['A'], 2, controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(expect.any(URL), { signal: controller.signal })
  })

  it('reuses cohesion while valid and revalidates after explicit invalidation', async () => {
    const response = (narrative: string) => ({
      chain_id: 'C1',
      narrative,
      model: 'test-model',
      provider_status: 'OK',
      context: { has_p2: true },
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(response('before review'))))
      .mockResolvedValueOnce(new Response(JSON.stringify(response('after review'))))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.cohesionNarrative('C1')).narrative).toBe('before review')
    expect((await api.cohesionNarrative('C1')).narrative).toBe('before review')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    clearCohesionCache('C1')
    expect((await api.cohesionNarrative('C1')).narrative).toBe('after review')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not render or cache a legacy deterministic fallback narrative', async () => {
    const response = (model: string, narrative: string, provider_status: string) => ({
      chain_id: 'C1',
      narrative,
      model,
      provider_status,
      context: { has_p2: true },
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(response(
        'test-model',
        'Chưa tạo được nhận định AI đáp ứng kiểm tra grounding. Evidence vẫn còn ở các tab.',
        'GROUNDING_VIOLATION',
      ))))
      .mockResolvedValueOnce(new Response(JSON.stringify(response(
        'test-model',
        'Output AI mới',
        'OK',
      ))))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.cohesionNarrative('C1')).narrative).toBe('')
    expect((await api.cohesionNarrative('C1')).narrative).toBe('Output AI mới')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('persisted chain overview request cache', () => {
  afterEach(() => {
    clearChainReadCache()
    setActiveSnapshotContext(null)
    vi.unstubAllGlobals()
  })

  it('deduplicates and caches a READY projection with matching exact identity', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    let resolveFetch!: (response: Response) => void
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    const first = api.chainOverviewCards('C1')
    const second = api.chainOverviewCards('C1')
    await Promise.resolve()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, requestInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = new Headers(requestInit.headers)
    expect(headers.get('X-NocPro-Snapshot-Id')).toBe('S1')
    expect(headers.get('X-NocPro-Topology-Version')).toBe('topology-v1')

    resolveFetch(new Response(JSON.stringify(readyOverview())))
    await expect(Promise.all([first, second])).resolves.toEqual([readyOverview(), readyOverview()])
    await api.chainOverviewCards('C1', undefined, overviewIdentity, readyOverview().artifact_revision)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('pins the request to the caller snapshot context before global context effects run', async () => {
    setActiveSnapshotContext(null)
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(readyOverview())))
    vi.stubGlobal('fetch', fetchMock)

    await api.chainOverviewCards(
      'C1',
      undefined,
      overviewIdentity,
      readyOverview().artifact_revision,
      { snapshot_id: 'S1', snapshot_version: '001', topology_version: 'topology-v1' },
    )

    const [, requestInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = new Headers(requestInit.headers)
    expect(headers.get('X-NocPro-Snapshot-Id')).toBe('S1')
    expect(headers.get('X-NocPro-Snapshot-Version')).toBe('001')
    expect(headers.get('X-NocPro-Topology-Version')).toBe('topology-v1')
  })

  it('lets one consumer abort without cancelling other subscribers', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    let resolveFetch!: (response: Response) => void
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => new Promise<Response>((resolve) => {
      resolveFetch = resolve
      expect(init?.signal).toBeDefined()
    }))
    vi.stubGlobal('fetch', fetchMock)
    const firstController = new AbortController()
    const secondController = new AbortController()
    const first = api.chainOverviewCards('C1', firstController.signal)
    const second = api.chainOverviewCards('C1', secondController.signal)
    const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })
    await Promise.resolve()

    firstController.abort()

    await rejected
    const [, requestInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(requestInit.signal?.aborted).toBe(false)
    resolveFetch(new Response(JSON.stringify(readyOverview())))
    await expect(second).resolves.toEqual(readyOverview())
  })

  it('aborts in-flight work and rejects stale subscribers when snapshot context changes', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    let resolveOldFetch!: (response: Response) => void
    const newOverview = readyOverview({
      snapshot_id: 'S2',
      topology_version: 'topology-v2',
      analysis_identity: { ...overviewIdentity, snapshot_id: 'S2', topology_version: 'topology-v2' },
    })
    const fetchMock = vi.fn()
      .mockImplementationOnce((_path: string, init?: RequestInit) => new Promise<Response>((resolve) => {
        resolveOldFetch = resolve
        expect(init?.signal).toBeDefined()
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(newOverview)))
    vi.stubGlobal('fetch', fetchMock)
    const oldRequest = api.chainOverviewCards('C1')
    const rejected = expect(oldRequest).rejects.toMatchObject({ name: 'AbortError' })
    await Promise.resolve()
    const [, oldInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]

    setActiveSnapshotContext('S2', '001', 'topology-v2')
    await rejected
    expect(oldInit.signal?.aborted).toBe(true)
    await expect(api.chainOverviewCards('C1')).resolves.toEqual(newOverview)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    resolveOldFetch(new Response(JSON.stringify(readyOverview())))
  })

  it('retries PENDING and UNAVAILABLE responses rather than caching them', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...readyOverview(), status: 'PENDING' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...readyOverview(), status: 'UNAVAILABLE' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(readyOverview())))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.chainOverviewCards('C1')).status).toBe('PENDING')
    expect((await api.chainOverviewCards('C1')).status).toBe('UNAVAILABLE')
    const ready = await api.chainOverviewCards('C1')
    expect(ready.status).toBe('READY')
    expect((await api.chainOverviewCards(
      'C1',
      undefined,
      overviewIdentity,
      ready.artifact_revision,
    )).status).toBe('READY')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('requires the complete A4 identity to reuse a cached READY projection', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    const updatedIdentity = {
      ...overviewIdentity,
      analysis_config_version: 'analysis-config-v2',
      input_fingerprint: 'overview-fingerprint-v2',
    }
    const updatedRevision = {
      resource_kind: 'chain_overview',
      fingerprint: 'overview-fingerprint-v2',
    }
    const updated = readyOverview({
      analysis_identity: updatedIdentity,
      artifact_revision: updatedRevision,
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(readyOverview())))
      .mockResolvedValueOnce(new Response(JSON.stringify(updated)))
    vi.stubGlobal('fetch', fetchMock)

    await api.chainOverviewCards('C1')
    await expect(api.chainOverviewCards(
      'C1',
      undefined,
      overviewIdentity,
      readyOverview().artifact_revision,
    )).resolves.toEqual(readyOverview())
    await expect(api.chainOverviewCards(
      'C1',
      undefined,
      updatedIdentity,
      updatedRevision,
    )).resolves.toEqual(updated)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('caches only the exact singleton NOT_APPLICABLE terminal state', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    const singleton = {
      snapshot_id: 'S1',
      snapshot_version: '001',
      chain_id: 'C1',
      status: 'NOT_APPLICABLE',
      projection_version: null,
      reason: 'SINGLETON_CHAIN',
      topology_version: null,
      representative_member: null,
      topology: null,
      quality_assessment: null,
      recommendations: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(singleton)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.chainOverviewCards('C1')).resolves.toEqual(singleton)
    await expect(api.chainOverviewCards('C1')).resolves.toEqual(singleton)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('rejects artifact mismatches for caching and never shares unknown topology context', async () => {
    setActiveSnapshotContext('S1', '001', 'topology-v1')
    const mismatched = readyOverview({
      artifact_revision: { resource_kind: 'chain_overview', fingerprint: 'different' },
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(mismatched)))
      .mockResolvedValueOnce(new Response(JSON.stringify(readyOverview())))
      .mockResolvedValueOnce(new Response(JSON.stringify(readyOverview())))
      .mockResolvedValueOnce(new Response(JSON.stringify(readyOverview())))
    vi.stubGlobal('fetch', fetchMock)

    await api.chainOverviewCards('C1')
    await api.chainOverviewCards('C1')
    expect(fetchMock).toHaveBeenCalledTimes(2)

    setActiveSnapshotContext('S1', '001')
    await api.chainOverviewCards('C1')
    await api.chainOverviewCards('C1')
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })
})
