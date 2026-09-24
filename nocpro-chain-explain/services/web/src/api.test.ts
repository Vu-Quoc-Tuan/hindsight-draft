import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, clearCohesionCache, clearTopologySubgraphCache } from './api'

const available = (version: string) => ({
  status: 'AVAILABLE' as const,
  profile_id: 'IP_NETWORK',
  topology_version: version,
  nodes: [],
  edges: [],
})

describe('topology subgraph cache', () => {
  afterEach(() => {
    clearTopologySubgraphCache()
    clearCohesionCache()
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
