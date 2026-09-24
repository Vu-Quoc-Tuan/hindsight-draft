import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearChainReadCache, getOrLoadChainRead } from './chainReadCache'

describe('chain read cache', () => {
  afterEach(() => {
    clearChainReadCache()
    vi.useRealTimers()
  })

  it('deduplicates concurrent readers for the same exact key', async () => {
    let resolveLoad!: (value: { status: string }) => void
    const load = vi.fn(() => new Promise<{ status: string }>((resolve) => {
      resolveLoad = resolve
    }))
    const first = getOrLoadChainRead('snapshot-v1:chain-1', undefined, load, () => true)
    const second = getOrLoadChainRead('snapshot-v1:chain-1', undefined, load, () => true)
    await Promise.resolve()

    expect(load).toHaveBeenCalledTimes(1)
    resolveLoad({ status: 'READY' })
    await expect(Promise.all([first, second])).resolves.toEqual([
      { status: 'READY' },
      { status: 'READY' },
    ])

    await getOrLoadChainRead('snapshot-v1:chain-1', undefined, load, () => true)
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('aborts only the departing subscriber while another reader is waiting', async () => {
    let resolveLoad!: (value: string) => void
    let sharedSignal: AbortSignal | undefined
    const load = vi.fn((signal: AbortSignal) => {
      sharedSignal = signal
      return new Promise<string>((resolve) => { resolveLoad = resolve })
    })
    const firstController = new AbortController()
    const secondController = new AbortController()
    const first = getOrLoadChainRead('read', firstController.signal, load, () => true)
    const second = getOrLoadChainRead('read', secondController.signal, load, () => true)
    await Promise.resolve()
    const firstRejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })

    firstController.abort()

    await firstRejected
    expect(sharedSignal?.aborted).toBe(false)
    resolveLoad('still available')
    await expect(second).resolves.toBe('still available')
  })

  it('aborts the shared request when the last subscriber leaves and permits a new request', async () => {
    const signals: AbortSignal[] = []
    const load = vi.fn((signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<string>(() => undefined)
    })
    const controller = new AbortController()
    const pending = getOrLoadChainRead('read', controller.signal, load, () => true)
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await Promise.resolve()

    controller.abort()
    await rejected
    expect(signals[0].aborted).toBe(true)

    const replacement = getOrLoadChainRead('read', undefined, async () => 'new request', () => true)
    await expect(replacement).resolves.toBe('new request')
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('retains only cache-approved values and expires entries after five minutes', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-24T00:00:00Z'))
    const load = vi.fn(async () => ({ status: 'PENDING' }))

    await getOrLoadChainRead('transient', undefined, load, value => value.status === 'READY')
    await getOrLoadChainRead('transient', undefined, load, value => value.status === 'READY')
    expect(load).toHaveBeenCalledTimes(2)

    const readyLoader = vi.fn(async () => ({ status: 'READY' }))
    await getOrLoadChainRead('terminal', undefined, readyLoader, value => value.status === 'READY')
    await getOrLoadChainRead('terminal', undefined, readyLoader, value => value.status === 'READY')
    expect(readyLoader).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(5 * 60 * 1000 + 1)
    await getOrLoadChainRead('terminal', undefined, readyLoader, value => value.status === 'READY')
    expect(readyLoader).toHaveBeenCalledTimes(2)
  })

  it('bounds the LRU to 100 entries and refreshes recency when read', async () => {
    const load = vi.fn(async (key: string) => key)
    const read = (key: string) => getOrLoadChainRead(key, undefined, () => load(key), () => true)
    for (let index = 0; index < 100; index += 1) await read(`key-${index}`)
    await read('key-0')
    await read('key-100')
    await read('key-0')
    expect(load).toHaveBeenCalledTimes(101)
    await read('key-1')
    expect(load).toHaveBeenCalledTimes(102)
  })

  it('invalidates cached data and aborts pending subscribers', async () => {
    let signal: AbortSignal | undefined
    const load = vi.fn((_signal: AbortSignal) => {
      signal = _signal
      return new Promise<string>(() => undefined)
    })
    const pending = getOrLoadChainRead('pending', undefined, load, () => true)
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await Promise.resolve()
    clearChainReadCache()

    await rejected
    expect(signal?.aborted).toBe(true)
  })
})
