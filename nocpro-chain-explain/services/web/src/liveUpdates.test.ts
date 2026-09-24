import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  LiveRefreshScheduler,
  LiveUpdateClient,
  chainListResponseMatchesRefresh,
  invalidationMatchesChain,
  invalidationMatchesSnapshot,
  type ChangeInvalidation,
  type EventSourceLike,
  type LiveConnectionState,
  type LiveNotice,
} from './liveUpdates'

const EPOCH = 'ad2c5f7a-70aa-4ff6-91d8-8e5037247e76'
const chainInvalidation: ChangeInvalidation = {
  kind: 'invalidate',
  event_type: 'quality.changed',
  snapshot_id: 'snapshot-a',
  snapshot_version: 'v1',
  chain_id: 'chain-a',
  topology_version: 'topology-1',
  identity_digest: null,
  invalidates: ['chain-detail'],
}

class FakeEventSource extends EventTarget implements EventSourceLike {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  closed = false

  open() {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }

  error() {
    this.onerror?.(new Event('error'))
  }

  invalidate(revision: number, overrides: Record<string, unknown> = {}) {
    const payload = {
      schema_version: 'change-event-v1',
      event_type: 'quality.changed',
      snapshot_id: 'snapshot-a',
      snapshot_version: 'v1',
      chain_id: 'chain-a',
      topology_version: 'topology-1',
      identity_digest: null,
      invalidates: ['quality-summary', 'chain-detail'],
      ...overrides,
    }
    this.dispatchEvent(new MessageEvent('invalidate', {
      data: JSON.stringify(payload),
      lastEventId: `${EPOCH}:${revision}`,
    }))
  }

  heartbeat() {
    this.dispatchEvent(new MessageEvent('heartbeat', {
      data: JSON.stringify({
        schema_version: 'change-event-v1',
        server_time: '2026-09-25T10:00:00Z',
      }),
    }))
  }

  reset(revision: number, reason = 'CURSOR_EXPIRED') {
    this.dispatchEvent(new MessageEvent('reset', {
      data: JSON.stringify({ reason, epoch: EPOCH, revision }),
      lastEventId: `${EPOCH}:${revision}`,
    }))
  }

  close() {
    this.closed = true
    this.readyState = 2
  }
}

function eventTargets() {
  const documentTarget = new EventTarget() as EventTarget & { hidden: boolean }
  documentTarget.hidden = false
  return { documentTarget, windowTarget: new EventTarget() }
}

function createClient() {
  const source = new FakeEventSource()
  const notices: LiveNotice[][] = []
  const states: LiveConnectionState[] = []
  const targets = eventTargets()
  const client = new LiveUpdateClient({
    onInvalidate: batch => notices.push([...batch]),
    onState: state => states.push(state),
    createEventSource: () => source,
    document: targets.documentTarget,
    window: targets.windowTarget,
  })
  return { client, source, notices, states, ...targets }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('LiveUpdateClient', () => {
  it('binds chain-list refresh responses to snapshot and requested topology generations', () => {
    const expected = {
      snapshotId: 'snapshot-a',
      snapshotVersion: 'v1',
      topologyVersion: 'topology-2',
    }
    expect(chainListResponseMatchesRefresh({
      snapshot_id: 'snapshot-a', snapshot_version: 'v1', topology_version: 'topology-2',
    }, expected)).toBe(true)
    expect(chainListResponseMatchesRefresh({
      snapshot_id: 'snapshot-a', snapshot_version: 'v1', topology_version: 'topology-1',
    }, expected)).toBe(false)
    expect(chainListResponseMatchesRefresh({
      snapshot_id: 'snapshot-b', snapshot_version: 'v1', topology_version: 'topology-2',
    }, expected)).toBe(false)
    expect(chainListResponseMatchesRefresh({
      snapshot_id: 'snapshot-a', snapshot_version: 'v1', topology_version: 'topology-1',
    }, { snapshotId: 'snapshot-a', snapshotVersion: 'v1' })).toBe(true)
  })

  it('rejects stale snapshot, chain and topology identities for detail refreshes', () => {
    expect(invalidationMatchesSnapshot(chainInvalidation, 'snapshot-b', 'v1')).toBe(false)
    expect(invalidationMatchesSnapshot(chainInvalidation, 'snapshot-a', 'v2')).toBe(false)
    expect(invalidationMatchesSnapshot(chainInvalidation, 'snapshot-a', 'v1')).toBe(true)
    expect(invalidationMatchesSnapshot({ ...chainInvalidation, snapshot_id: null }, 'snapshot-b', 'v2')).toBe(true)

    expect(invalidationMatchesChain(chainInvalidation, {
      snapshotId: 'snapshot-a', snapshotVersion: 'v1', topologyVersion: 'topology-1', chainId: 'chain-a',
    })).toBe(true)
    expect(invalidationMatchesChain(chainInvalidation, {
      snapshotId: 'snapshot-a', snapshotVersion: 'v1', topologyVersion: 'topology-2', chainId: 'chain-a',
    })).toBe(false)
    expect(invalidationMatchesChain(chainInvalidation, {
      snapshotId: 'snapshot-a', snapshotVersion: 'v1', topologyVersion: undefined, chainId: 'chain-b',
    })).toBe(false)
  })

  it('cleans up its EventSource, listeners and timers across StrictMode-style remounts', () => {
    vi.useFakeTimers()
    const first = createClient()
    first.client.start()
    first.source.open()
    first.client.stop()
    expect(first.source.closed).toBe(true)
    expect(vi.getTimerCount()).toBe(0)

    const second = createClient()
    second.client.start()
    expect(second.states.at(-1)).toBe('CONNECTING')
    second.source.open()
    expect(second.states.at(-1)).toBe('LIVE')
    second.client.stop()
    expect(second.source.closed).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('batches distinct scopes and ignores duplicate or older epoch/revision cursors', () => {
    vi.useFakeTimers()
    const { client, source, notices } = createClient()
    client.start()
    source.open()
    source.invalidate(1)
    source.invalidate(1)
    source.invalidate(2, { invalidates: ['catalog'] })

    vi.advanceTimersByTime(249)
    expect(notices).toHaveLength(0)
    vi.advanceTimersByTime(1)
    expect(notices).toHaveLength(1)
    expect(notices[0]).toHaveLength(2)
    expect(notices[0].every(notice => notice.kind === 'invalidate')).toBe(true)

    source.invalidate(1)
    vi.advanceTimersByTime(250)
    expect(notices).toHaveLength(1)
    client.stop()
  })

  it('turns unknown schemas into a full resync and exposes degraded fallback status', () => {
    vi.useFakeTimers()
    const { client, source, notices, states } = createClient()
    client.start()
    source.open()
    source.invalidate(1, { schema_version: 'change-event-v99' })
    vi.advanceTimersByTime(250)

    expect(states.at(-1)).toBe('DEGRADED')
    expect(notices).toEqual([[{ kind: 'resync', reason: 'UNKNOWN_EVENT_SCHEMA' }]])
    vi.advanceTimersByTime(6000)
    expect(notices.at(-1)).toEqual([{ kind: 'resync', reason: 'LIVE_FALLBACK_POLL' }])
    client.stop()
  })

  it('keeps only the six-second refresh while the stream is degraded', () => {
    vi.useFakeTimers()
    const { client, source, notices } = createClient()
    client.start()
    source.open()
    source.error()
    vi.advanceTimersByTime(60_000)

    expect(notices).toHaveLength(10)
    expect(notices.flat().every(notice => notice.kind === 'resync' && notice.reason === 'LIVE_FALLBACK_POLL')).toBe(true)
    client.stop()
  })

  it('uses reset as a resync baseline without treating it as a data delta', () => {
    vi.useFakeTimers()
    const { client, source, notices } = createClient()
    client.start()
    source.open()
    source.reset(7)
    source.invalidate(8)
    vi.advanceTimersByTime(250)

    expect(notices).toEqual([[{ kind: 'resync', reason: 'CURSOR_EXPIRED' }]])
    client.stop()
  })

  it('uses named heartbeat only for liveness, then degrades after silence', () => {
    vi.useFakeTimers()
    const { client, source, notices, states } = createClient()
    client.start()
    source.open()
    vi.advanceTimersByTime(20_000)
    source.heartbeat()
    vi.advanceTimersByTime(20_000)
    expect(states.at(-1)).toBe('LIVE')
    expect(notices).toHaveLength(0)
    vi.advanceTimersByTime(10_000)
    expect(states.at(-1)).toBe('DEGRADED')
    client.stop()
  })

  it('reconciles once after sixty seconds while named heartbeats keep the stream live', () => {
    vi.useFakeTimers()
    const { client, source, notices, states } = createClient()
    client.start()
    source.open()

    vi.advanceTimersByTime(20_000)
    source.heartbeat()
    vi.advanceTimersByTime(20_000)
    source.heartbeat()
    vi.advanceTimersByTime(20_000)
    vi.advanceTimersByTime(250)

    expect(states.at(-1)).toBe('LIVE')
    expect(notices).toEqual([[{ kind: 'resync', reason: 'PERIODIC_RECONCILIATION' }]])
    client.stop()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('performs one full REST revalidation when a hidden tab becomes visible', () => {
    vi.useFakeTimers()
    const { client, documentTarget, windowTarget, notices } = createClient()
    client.start()
    documentTarget.hidden = true
    documentTarget.dispatchEvent(new Event('visibilitychange'))
    windowTarget.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(250)
    expect(notices).toHaveLength(0)

    documentTarget.hidden = false
    documentTarget.dispatchEvent(new Event('visibilitychange'))
    windowTarget.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(250)
    expect(notices).toEqual([[{ kind: 'resync', reason: 'TAB_VISIBLE' }]])
    client.stop()
  })

  it('starts bounded fallback when EventSource construction is unavailable', () => {
    vi.useFakeTimers()
    const notices: LiveNotice[][] = []
    const states: LiveConnectionState[] = []
    const targets = eventTargets()
    const client = new LiveUpdateClient({
      onInvalidate: batch => notices.push([...batch]),
      onState: state => states.push(state),
      createEventSource: () => { throw new Error('EventSource unavailable') },
      document: targets.documentTarget,
      window: targets.windowTarget,
    })
    client.start()
    expect(states.at(-1)).toBe('DISABLED')
    vi.advanceTimersByTime(6000)
    expect(notices).toEqual([[{ kind: 'resync', reason: 'LIVE_FALLBACK_POLL' }]])
    client.stop()
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('LiveRefreshScheduler', () => {
  it('marks an in-flight resource dirty and performs only one follow-up read', async () => {
    const scheduler = new LiveRefreshScheduler()
    const resolvers: Array<() => void> = []
    const task = vi.fn(() => new Promise<void>(resolve => resolvers.push(resolve)))
    scheduler.schedule('catalog', task)
    scheduler.schedule('catalog', task)
    scheduler.schedule('catalog', task)
    expect(task).toHaveBeenCalledTimes(1)

    resolvers[0]()
    await Promise.resolve()
    await Promise.resolve()
    expect(task).toHaveBeenCalledTimes(2)
    resolvers[1]()
    await Promise.resolve()
    expect(scheduler.size).toBe(0)
    scheduler.stop()
  })

  it('aborts obsolete contexts without cancelling the current resource key', () => {
    const scheduler = new LiveRefreshScheduler()
    const signals = new Map<string, AbortSignal>()
    const blockers: Array<() => void> = []
    const schedule = (key: string) => scheduler.schedule(key, signal => {
      signals.set(key, signal)
      return new Promise<void>(resolve => blockers.push(resolve))
    })

    schedule('chain-list:snapshot-a:v1')
    schedule('chain-list:snapshot-b:v2')
    scheduler.cancelWhere(key => key.startsWith('chain-list:snapshot-a:'))
    expect(signals.get('chain-list:snapshot-a:v1')?.aborted).toBe(true)
    expect(signals.get('chain-list:snapshot-b:v2')?.aborted).toBe(false)
    scheduler.stop()
    expect(signals.get('chain-list:snapshot-b:v2')?.aborted).toBe(true)
    blockers.forEach(resolve => resolve())
  })
})
