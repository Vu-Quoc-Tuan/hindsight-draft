type CacheEntry = {
  value: unknown
  expiresAt: number
}

type Subscriber<T> = {
  resolve: (value: T) => void
  reject: (reason: unknown) => void
  signal?: AbortSignal
  onAbort?: () => void
}

type InFlightRequest = {
  controller: AbortController
  subscribers: Set<Subscriber<unknown>>
  settled: boolean
  cancelled: boolean
  started: boolean
}

const MAX_CHAIN_READ_ENTRIES = 100
const CHAIN_READ_TTL_MS = 5 * 60 * 1000
const values = new Map<string, CacheEntry>()
const inFlight = new Map<string, InFlightRequest>()

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError')
}

function touch(key: string, entry: CacheEntry) {
  values.delete(key)
  values.set(key, entry)
}

function cachedValue<T>(key: string, canUseCached: (value: T) => boolean): T | undefined {
  const entry = values.get(key)
  if (!entry) return undefined
  if (entry.expiresAt <= Date.now()) {
    values.delete(key)
    return undefined
  }
  try {
    if (!canUseCached(entry.value as T)) return undefined
  } catch {
    return undefined
  }
  touch(key, entry)
  return entry.value as T
}

function remember(key: string, value: unknown) {
  values.delete(key)
  values.set(key, { value, expiresAt: Date.now() + CHAIN_READ_TTL_MS })
  while (values.size > MAX_CHAIN_READ_ENTRIES) {
    const oldestKey = values.keys().next().value
    if (oldestKey === undefined) break
    values.delete(oldestKey)
  }
}

function detachSubscriber<T>(pending: InFlightRequest, subscriber: Subscriber<T>) {
  if (subscriber.signal && subscriber.onAbort) {
    subscriber.signal.removeEventListener('abort', subscriber.onAbort)
  }
  pending.subscribers.delete(subscriber as Subscriber<unknown>)
}

function settleRequest<T>(
  key: string,
  pending: InFlightRequest,
  result: { value: T } | { error: unknown },
  shouldCache: (value: T) => boolean,
) {
  if (pending.settled) return
  pending.settled = true
  if (inFlight.get(key) === pending) inFlight.delete(key)

  if (!pending.cancelled && 'value' in result) {
    try {
      if (shouldCache(result.value)) remember(key, result.value)
    } catch {
      // Cache policy is a performance hint; it must not fail the request.
    }
  }

  const subscribers = [...pending.subscribers]
  pending.subscribers.clear()
  for (const subscriber of subscribers) {
    if (subscriber.signal && subscriber.onAbort) {
      subscriber.signal.removeEventListener('abort', subscriber.onAbort)
    }
    if ('value' in result) subscriber.resolve(result.value)
    else subscriber.reject(result.error)
  }
}

/**
 * Share one request across callers with the same exact key. Each caller owns
 * its own cancellation; the shared request is aborted only when its last
 * subscriber leaves. Only validated terminal values are retained in memory.
 */
export function getOrLoadChainRead<T>(
  key: string,
  signal: AbortSignal | undefined,
  load: (signal: AbortSignal) => Promise<T>,
  shouldCache: (value: T) => boolean,
  canUseCached: (value: T) => boolean = () => true,
): Promise<T> {
  if (signal?.aborted) return Promise.reject(abortError())

  const cached = cachedValue<T>(key, canUseCached)
  if (cached !== undefined) return Promise.resolve(cached)

  let pending = inFlight.get(key)
  if (!pending) {
    pending = {
      controller: new AbortController(),
      subscribers: new Set(),
      settled: false,
      cancelled: false,
      started: false,
    }
    inFlight.set(key, pending)
  }

  return new Promise<T>((resolve, reject) => {
    const subscriber: Subscriber<T> = { resolve, reject, signal }
    subscriber.onAbort = () => {
      if (pending!.settled || !pending!.subscribers.has(subscriber as Subscriber<unknown>)) return
      detachSubscriber(pending!, subscriber)
      reject(abortError())
      if (pending!.subscribers.size === 0) {
        pending!.cancelled = true
        if (inFlight.get(key) === pending) inFlight.delete(key)
        pending!.controller.abort()
      }
    }
    pending!.subscribers.add(subscriber as Subscriber<unknown>)
    signal?.addEventListener('abort', subscriber.onAbort, { once: true })

    if (!pending!.started) {
      pending!.started = true
      const current = pending!
      try {
        void load(current.controller.signal).then(
          value => settleRequest(key, current, { value }, shouldCache),
          error => settleRequest(key, current, { error }, shouldCache),
        )
      } catch (error) {
        settleRequest(key, current, { error }, shouldCache)
      }
    }
  })
}

/** Invalidate cached values and reject/abort subscribers during context changes. */
export function clearChainReadCache() {
  values.clear()
  const pendingRequests = [...inFlight.values()]
  inFlight.clear()
  for (const pending of pendingRequests) {
    if (pending.settled) continue
    pending.cancelled = true
    pending.settled = true
    pending.controller.abort()
    const subscribers = [...pending.subscribers]
    pending.subscribers.clear()
    for (const subscriber of subscribers) {
      if (subscriber.signal && subscriber.onAbort) {
        subscriber.signal.removeEventListener('abort', subscriber.onAbort)
      }
      subscriber.reject(abortError())
    }
  }
}
