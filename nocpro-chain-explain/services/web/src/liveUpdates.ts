export const INVALIDATION_SCOPES = [
  'catalog',
  'quality-summary',
  'chain-list',
  'chain-detail',
  'topology',
  'evolution',
] as const

export type InvalidationScope = typeof INVALIDATION_SCOPES[number]
export type LiveConnectionState = 'CONNECTING' | 'LIVE' | 'DEGRADED' | 'DISABLED'

export type ChangeInvalidation = {
  kind: 'invalidate'
  event_type: 'quality.changed' | 'snapshot.changed' | 'topology.changed'
  snapshot_id: string | null
  snapshot_version: string | null
  chain_id: string | null
  topology_version: string | null
  identity_digest: string | null
  invalidates: readonly InvalidationScope[]
}

export type FullResyncNotice = {
  kind: 'resync'
  reason: string
}

export type LiveNotice = ChangeInvalidation | FullResyncNotice
export type RefreshTask = (signal: AbortSignal) => Promise<void>

export function invalidationMatchesSnapshot(
  invalidation: ChangeInvalidation,
  snapshotId: string | null,
  snapshotVersion: string | null,
): boolean {
  if (invalidation.snapshot_id === null) return true
  return snapshotId !== null
    && invalidation.snapshot_id === snapshotId
    && (invalidation.snapshot_version === null || invalidation.snapshot_version === snapshotVersion)
}

export function invalidationMatchesChain(
  invalidation: ChangeInvalidation,
  identity: {
    snapshotId: string | null
    snapshotVersion: string | null
    topologyVersion: string | null | undefined
    chainId: string | null
  },
): boolean {
  if (!identity.chainId || !invalidationMatchesSnapshot(invalidation, identity.snapshotId, identity.snapshotVersion)) {
    return false
  }
  if (
    invalidation.topology_version !== null
    && identity.topologyVersion !== undefined
    && invalidation.topology_version !== identity.topologyVersion
  ) return false
  return invalidation.chain_id === null || invalidation.chain_id === identity.chainId
}

export function chainListResponseMatchesRefresh(
  response: {
    snapshot_id: string
    snapshot_version: string
    topology_version?: string | null
  },
  expected: {
    snapshotId: string
    snapshotVersion: string
    topologyVersion?: string | null
  },
): boolean {
  if (
    response.snapshot_id !== expected.snapshotId
    || response.snapshot_version !== expected.snapshotVersion
  ) return false
  return expected.topologyVersion === undefined
    || response.topology_version === expected.topologyVersion
}

const UUID_PATTERN = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
const EVENT_CURSOR_PATTERN = new RegExp(`^(${UUID_PATTERN}):(0|[1-9][0-9]{0,18})$`)
const IDENTITY_DIGEST_PATTERN = /^[0-9a-f]{64}$/
const ALLOWED_EVENT_TYPES = new Set<ChangeInvalidation['event_type']>([
  'quality.changed',
  'snapshot.changed',
  'topology.changed',
])
const ALLOWED_RESET_REASONS = new Set([
  'INITIAL_SYNC',
  'CURSOR_EXPIRED',
  'EPOCH_CHANGED',
  'CURSOR_AHEAD',
  'BUFFER_OVERFLOW',
])

const EVENT_BATCH_MS = 250
const MAX_BATCH_NOTICES = 256
const FALLBACK_REFRESH_MS = 6000
const RECONCILE_REFRESH_MS = 60_000
const MAX_SILENCE_MS = 30_000

type Cursor = { epoch: string; revision: bigint }

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  readonly readyState?: number
  addEventListener(type: string, listener: EventListener): void
  removeEventListener(type: string, listener: EventListener): void
  close(): void
}

type EventTargetLike = Pick<EventTarget, 'addEventListener' | 'removeEventListener'>
type DocumentLike = EventTargetLike & { hidden: boolean }

export interface LiveUpdateClientOptions {
  onInvalidate: (notices: readonly LiveNotice[]) => void
  onState: (state: LiveConnectionState) => void
  createEventSource?: (url: string) => EventSourceLike
  document?: DocumentLike | null
  window?: EventTargetLike | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableIdentifier(value: unknown): value is string | null {
  return value === null || (
    typeof value === 'string'
    && value.trim().length > 0
    && value.length <= 255
  )
}

function parseCursor(value: unknown): Cursor | null {
  if (typeof value !== 'string' || value.length > 56) return null
  const match = EVENT_CURSOR_PATTERN.exec(value)
  if (!match) return null
  try {
    return { epoch: match[1].toLowerCase(), revision: BigInt(match[2]) }
  } catch {
    return null
  }
}

function parseInvalidation(value: unknown): ChangeInvalidation | null {
  if (!isRecord(value) || value.schema_version !== 'change-event-v1') return null
  if (typeof value.event_type !== 'string' || !ALLOWED_EVENT_TYPES.has(value.event_type as ChangeInvalidation['event_type'])) {
    return null
  }
  if (
    !nullableIdentifier(value.snapshot_id)
    || !nullableIdentifier(value.snapshot_version)
    || !nullableIdentifier(value.chain_id)
    || !nullableIdentifier(value.topology_version)
  ) return null
  if (
    value.identity_digest !== null
    && (typeof value.identity_digest !== 'string' || !IDENTITY_DIGEST_PATTERN.test(value.identity_digest))
  ) return null
  if (
    !Array.isArray(value.invalidates)
    || value.invalidates.length === 0
    || value.invalidates.some(scope => !INVALIDATION_SCOPES.includes(scope as InvalidationScope))
  ) return null

  return {
    kind: 'invalidate',
    event_type: value.event_type as ChangeInvalidation['event_type'],
    snapshot_id: value.snapshot_id,
    snapshot_version: value.snapshot_version,
    chain_id: value.chain_id,
    topology_version: value.topology_version,
    identity_digest: value.identity_digest as string | null,
    invalidates: [...new Set(value.invalidates as InvalidationScope[])],
  }
}

function isDocumentLike(value: Document | undefined): value is Document & DocumentLike {
  return value !== undefined
    && typeof value.hidden === 'boolean'
    && typeof value.addEventListener === 'function'
    && typeof value.removeEventListener === 'function'
}

function isWindowTarget(value: Window | undefined): value is Window & EventTargetLike {
  return value !== undefined
    && typeof value.addEventListener === 'function'
    && typeof value.removeEventListener === 'function'
}

/** Owns exactly one native SSE connection and all of its timers/listeners. */
export class LiveUpdateClient {
  private readonly options: LiveUpdateClientOptions
  private readonly createEventSource: ((url: string) => EventSourceLike) | undefined
  private readonly documentTarget: DocumentLike | null
  private readonly windowTarget: EventTargetLike | null
  private readonly notices: LiveNotice[] = []
  private source: EventSourceLike | null = null
  private started = false
  private cursor: Cursor | null = null
  private batchTimer: ReturnType<typeof setTimeout> | null = null
  private fallbackTimer: ReturnType<typeof setInterval> | null = null
  private reconcileTimer: ReturnType<typeof setInterval> | null = null
  private silenceTimer: ReturnType<typeof setTimeout> | null = null
  private wasHidden = false

  private readonly handleInvalidateEvent: EventListener = event => {
    this.touchConnection()
    let decoded: unknown
    try {
      decoded = JSON.parse((event as MessageEvent<string>).data)
    } catch {
      this.failClosed('INVALID_EVENT_JSON')
      return
    }
    const invalidation = parseInvalidation(decoded)
    if (!invalidation) {
      this.failClosed('UNKNOWN_EVENT_SCHEMA')
      return
    }

    const eventCursor = parseCursor((event as MessageEvent<string>).lastEventId)
    if (!eventCursor) {
      this.failClosed('INVALID_EVENT_CURSOR')
      return
    }
    const cursorDecision = this.acceptCursor(eventCursor)
    if (cursorDecision === 'DUPLICATE') return
    if (cursorDecision !== 'ACCEPT') {
      this.queueNotice({ kind: 'resync', reason: cursorDecision })
      return
    }
    this.queueNotice(invalidation)
  }

  private readonly handleResetEvent: EventListener = event => {
    this.touchConnection()
    let decoded: unknown
    try {
      decoded = JSON.parse((event as MessageEvent<string>).data)
    } catch {
      this.failClosed('INVALID_RESET_JSON')
      return
    }
    if (
      !isRecord(decoded)
      || typeof decoded.reason !== 'string'
      || !ALLOWED_RESET_REASONS.has(decoded.reason)
      || typeof decoded.epoch !== 'string'
      || !new RegExp(`^${UUID_PATTERN}$`).test(decoded.epoch)
      || typeof decoded.revision !== 'number'
      || !Number.isFinite(decoded.revision)
      || !Number.isInteger(decoded.revision)
      || decoded.revision < 0
    ) {
      this.failClosed('UNKNOWN_RESET_SCHEMA')
      return
    }
    const eventCursor = parseCursor((event as MessageEvent<string>).lastEventId)
    if (!eventCursor || eventCursor.epoch !== decoded.epoch.toLowerCase()) {
      this.failClosed('INVALID_RESET_CURSOR')
      return
    }
    this.cursor = eventCursor
    this.queueNotice({ kind: 'resync', reason: decoded.reason })
  }

  private readonly handleHeartbeatEvent: EventListener = event => {
    let decoded: unknown
    try {
      decoded = JSON.parse((event as MessageEvent<string>).data)
    } catch {
      this.failClosed('INVALID_HEARTBEAT_JSON')
      return
    }
    if (
      !isRecord(decoded)
      || decoded.schema_version !== 'change-event-v1'
      || typeof decoded.server_time !== 'string'
      || !Number.isFinite(Date.parse(decoded.server_time))
    ) {
      this.failClosed('UNKNOWN_HEARTBEAT_SCHEMA')
      return
    }
    // Heartbeats prove liveness only. They have no event id and never refresh data.
    this.touchConnection()
  }

  private readonly handleOpen = () => {
    this.touchConnection()
  }

  private readonly handleError = () => {
    this.setState(this.source?.readyState === 2 ? 'DISABLED' : 'DEGRADED')
    this.stopReconcile()
    this.startFallback()
  }

  private readonly handleVisibilityChange = () => {
    const hidden = this.documentTarget?.hidden ?? false
    if (this.wasHidden && !hidden) this.queueNotice({ kind: 'resync', reason: 'TAB_VISIBLE' })
    this.wasHidden = hidden
  }

  private readonly handleFocus = () => {
    if (!(this.documentTarget?.hidden ?? false)) {
      this.queueNotice({ kind: 'resync', reason: 'WINDOW_FOCUS' })
    }
  }

  constructor(options: LiveUpdateClientOptions) {
    this.options = options
    this.createEventSource = options.createEventSource
    const currentDocument = typeof document === 'undefined' ? undefined : document
    const currentWindow = typeof window === 'undefined' ? undefined : window
    this.documentTarget = options.document === null
      ? null
      : options.document ?? (isDocumentLike(currentDocument) ? currentDocument : null)
    this.windowTarget = options.window === null
      ? null
      : options.window ?? (isWindowTarget(currentWindow) ? currentWindow : null)
  }

  start() {
    if (this.started) return
    this.started = true
    this.options.onState('CONNECTING')
    this.wasHidden = this.documentTarget?.hidden ?? false
    this.documentTarget?.addEventListener('visibilitychange', this.handleVisibilityChange)
    this.windowTarget?.addEventListener('focus', this.handleFocus)
    this.armSilenceTimer()

    const factory = this.createEventSource ?? (
      typeof EventSource === 'undefined' ? undefined : (url: string) => new EventSource(url)
    )
    if (!factory) {
      this.setState('DISABLED')
      this.startFallback()
      return
    }

    try {
      const source = factory('/api/v1/events')
      this.source = source
      source.onopen = this.handleOpen
      source.onerror = this.handleError
      source.addEventListener('invalidate', this.handleInvalidateEvent)
      source.addEventListener('reset', this.handleResetEvent)
      source.addEventListener('heartbeat', this.handleHeartbeatEvent)
    } catch {
      this.setState('DISABLED')
      this.startFallback()
    }
  }

  stop() {
    if (!this.started) return
    this.started = false
    this.documentTarget?.removeEventListener('visibilitychange', this.handleVisibilityChange)
    this.windowTarget?.removeEventListener('focus', this.handleFocus)
    if (this.source) {
      this.source.onopen = null
      this.source.onerror = null
      this.source.removeEventListener('invalidate', this.handleInvalidateEvent)
      this.source.removeEventListener('reset', this.handleResetEvent)
      this.source.removeEventListener('heartbeat', this.handleHeartbeatEvent)
      this.source.close()
      this.source = null
    }
    if (this.batchTimer !== null) clearTimeout(this.batchTimer)
    if (this.silenceTimer !== null) clearTimeout(this.silenceTimer)
    this.stopReconcile()
    this.stopFallback()
    this.batchTimer = null
    this.silenceTimer = null
    this.reconcileTimer = null
    this.notices.length = 0
  }

  private setState(state: LiveConnectionState) {
    this.options.onState(state)
  }

  private touchConnection() {
    if (!this.started) return
    this.setState('LIVE')
    this.stopFallback()
    this.startReconcile()
    this.armSilenceTimer()
  }

  private armSilenceTimer() {
    if (this.silenceTimer !== null) clearTimeout(this.silenceTimer)
    this.silenceTimer = setTimeout(() => {
      this.setState('DEGRADED')
      this.stopReconcile()
      this.startFallback()
    }, MAX_SILENCE_MS)
  }

  private startReconcile() {
    if (this.reconcileTimer !== null || !this.started) return
    this.reconcileTimer = setInterval(() => {
      if (this.optionsStateIsLive() && !(this.documentTarget?.hidden ?? false)) {
        this.queueNotice({ kind: 'resync', reason: 'PERIODIC_RECONCILIATION' })
      }
    }, RECONCILE_REFRESH_MS)
  }

  private stopReconcile() {
    if (this.reconcileTimer !== null) clearInterval(this.reconcileTimer)
    this.reconcileTimer = null
  }

  private optionsStateIsLive() {
    // The timer is installed only while live and removed on every degraded transition.
    return this.started && this.source?.readyState !== 2
  }

  private startFallback() {
    if (this.fallbackTimer !== null || !this.started) return
    this.fallbackTimer = setInterval(() => {
      if (!(this.documentTarget?.hidden ?? false)) {
        this.options.onInvalidate([{ kind: 'resync', reason: 'LIVE_FALLBACK_POLL' }])
      }
    }, FALLBACK_REFRESH_MS)
  }

  private stopFallback() {
    if (this.fallbackTimer !== null) clearInterval(this.fallbackTimer)
    this.fallbackTimer = null
  }

  private failClosed(reason: string) {
    this.setState('DEGRADED')
    this.stopReconcile()
    this.startFallback()
    this.queueNotice({ kind: 'resync', reason })
  }

  private acceptCursor(next: Cursor): 'ACCEPT' | 'DUPLICATE' | 'EPOCH_CHANGED' | 'REVISION_GAP' {
    if (!this.cursor) {
      this.cursor = next
      return 'ACCEPT'
    }
    if (next.epoch !== this.cursor.epoch) {
      this.cursor = next
      return 'EPOCH_CHANGED'
    }
    if (next.revision <= this.cursor.revision) return 'DUPLICATE'
    if (next.revision !== this.cursor.revision + 1n) {
      this.cursor = next
      return 'REVISION_GAP'
    }
    this.cursor = next
    return 'ACCEPT'
  }

  private queueNotice(notice: LiveNotice) {
    if (!this.started || (this.documentTarget?.hidden ?? false)) return
    if (notice.kind === 'resync') {
      if (!this.notices.some(item => item.kind === 'resync')) {
        this.notices.splice(0, this.notices.length, notice)
      }
    } else if (!this.notices.some(item => item.kind === 'resync')) {
      this.notices.push(notice)
      if (this.notices.length > MAX_BATCH_NOTICES) {
        this.notices.splice(0, this.notices.length, {
          kind: 'resync',
          reason: 'INVALIDATION_BATCH_LIMIT',
        })
      }
    }
    if (this.batchTimer === null) {
      this.batchTimer = setTimeout(() => this.flushNotices(), EVENT_BATCH_MS)
    }
  }

  private flushNotices() {
    this.batchTimer = null
    if (!this.started || this.notices.length === 0) return
    const pending = this.notices.splice(0, this.notices.length)
    try {
      this.options.onInvalidate(pending)
    } catch {
      this.failClosed('INVALIDATION_HANDLER_FAILED')
    }
  }
}

type ScheduledRefresh = {
  controller: AbortController
  task: RefreshTask
  dirty: boolean
}

/** Per-resource single-flight scheduler; invalidations during a read coalesce. */
export class LiveRefreshScheduler {
  private readonly pending = new Map<string, ScheduledRefresh>()
  private stopped = false

  get size() {
    return this.pending.size
  }

  schedule(key: string, task: RefreshTask): boolean {
    if (this.stopped || !key) return false
    const existing = this.pending.get(key)
    if (existing) {
      existing.task = task
      existing.dirty = true
      return true
    }
    const entry: ScheduledRefresh = {
      controller: new AbortController(),
      task,
      dirty: false,
    }
    this.pending.set(key, entry)
    void this.run(key, entry)
    return true
  }

  cancel(key: string) {
    const entry = this.pending.get(key)
    if (!entry) return
    this.pending.delete(key)
    entry.dirty = false
    entry.controller.abort()
  }

  cancelWhere(predicate: (key: string) => boolean) {
    for (const key of this.pending.keys()) {
      if (predicate(key)) this.cancel(key)
    }
  }

  stop() {
    if (this.stopped) return
    this.stopped = true
    this.cancelWhere(() => true)
  }

  private async run(key: string, entry: ScheduledRefresh) {
    try {
      do {
        entry.dirty = false
        const task = entry.task
        try {
          await task(entry.controller.signal)
        } catch {
          // The resource owner records/display errors; one failed GET must not stop other scopes.
        }
      } while (entry.dirty && !entry.controller.signal.aborted && !this.stopped)
    } finally {
      if (this.pending.get(key) === entry) this.pending.delete(key)
    }
  }
}
