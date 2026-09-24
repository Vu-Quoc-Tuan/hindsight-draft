import {
  analysisIdentityMatches,
  artifactRevisionMatches,
  isAnalysisIdentity,
  isArtifactRevision,
  serializeAnalysisIdentity,
} from './analysisIdentity'
import type { AnalysisIdentity, ArtifactRevision, CounterfactualJob } from './types'

const REVIEW_CACHE_PREFIX = 'nocpro_review_v3_'
const LEGACY_REVIEW_CACHE_PREFIX = 'nocpro_review_'
const REVIEW_CACHE_SCHEMA = 3
const MAX_MEMORY_ENTRIES = 100
const MAX_SESSION_TERMINAL_ENTRIES = 20
const REVIEW_CACHE_TTL_MS = 5 * 60 * 1000

type ReviewCacheEntry = {
  job: CounterfactualJob
  storedAt: number
}

type StoredReviewCacheEntry = ReviewCacheEntry & {
  schema: typeof REVIEW_CACHE_SCHEMA
}

const reviewJobCache = new Map<string, ReviewCacheEntry>()
let legacyKeysCleaned = false

function sessionStorageOrNull(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function cacheKey(identity: unknown, revision: unknown): string | null {
  const serializedIdentity = serializeAnalysisIdentity(identity)
  if (!serializedIdentity || !isArtifactRevision(revision)) return null
  return `${REVIEW_CACHE_PREFIX}${encodeURIComponent(serializedIdentity)}:${encodeURIComponent(revision.resource_kind)}:${encodeURIComponent(revision.fingerprint)}`
}

function isTerminal(job: CounterfactualJob): boolean {
  return job.status === 'SUCCEEDED' || job.status === 'FAILED'
}

function isFresh(storedAt: number, now = Date.now()): boolean {
  return Number.isFinite(storedAt)
    && storedAt <= now
    && now - storedAt <= REVIEW_CACHE_TTL_MS
}

function remember(key: string, entry: ReviewCacheEntry) {
  reviewJobCache.delete(key)
  reviewJobCache.set(key, entry)
  while (reviewJobCache.size > MAX_MEMORY_ENTRIES) {
    const oldestKey = reviewJobCache.keys().next().value
    if (oldestKey === undefined) break
    reviewJobCache.delete(oldestKey)
  }
}

function removeStored(storage: Storage | null, key: string) {
  if (!storage) return
  try {
    storage.removeItem(key)
  } catch {
    // Storage is only a best-effort cache.
  }
}

function removeEntry(key: string, storage = sessionStorageOrNull()) {
  reviewJobCache.delete(key)
  removeStored(storage, key)
}

function decodeStoredEntry(raw: string | null, expectedKey: string): ReviewCacheEntry | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<StoredReviewCacheEntry>
    const job = value.job
    if (
      value.schema !== REVIEW_CACHE_SCHEMA
      || typeof value.storedAt !== 'number'
      || !isFresh(value.storedAt)
      || !job
      || !isAnalysisIdentity(job.analysis_identity)
      || !isArtifactRevision(job.artifact_revision)
      || !isTerminal(job)
      || cacheKey(job.analysis_identity, job.artifact_revision) !== expectedKey
      || !reviewJobMatchesExpected(job, job.analysis_identity, job.artifact_revision)
    ) {
      return null
    }
    return { job, storedAt: value.storedAt }
  } catch {
    return null
  }
}

function cleanLegacyKeys() {
  if (legacyKeysCleaned) return
  const storage = sessionStorageOrNull()
  if (!storage) return
  try {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index)
      if (
        key?.startsWith(LEGACY_REVIEW_CACHE_PREFIX)
        && !key.startsWith(REVIEW_CACHE_PREFIX)
      ) {
        storage.removeItem(key)
      }
    }
    legacyKeysCleaned = true
  } catch {
    // Cache cleanup is best-effort; storage is never authoritative.
  }
}

function pruneSessionStorage(storage: Storage, protectedKey?: string) {
  try {
    const entries: Array<{ key: string; storedAt: number }> = []
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index)
      if (!key?.startsWith(REVIEW_CACHE_PREFIX)) continue
      const entry = decodeStoredEntry(storage.getItem(key), key)
      if (!entry) {
        storage.removeItem(key)
      } else {
        entries.push({ key, storedAt: entry.storedAt })
      }
    }
    entries.sort((left, right) => left.storedAt - right.storedAt || left.key.localeCompare(right.key))
    while (entries.length > MAX_SESSION_TERMINAL_ENTRIES) {
      const oldestIndex = entries.findIndex(entry => entry.key !== protectedKey)
      if (oldestIndex < 0) break
      const [oldest] = entries.splice(oldestIndex, 1)
      storage.removeItem(oldest.key)
    }
  } catch {
    // Storage quota/security failures never affect the API-backed UI.
  }
}

export function reviewJobMatchesExpected(
  job: CounterfactualJob,
  expectedIdentity: AnalysisIdentity,
  expectedRevision: ArtifactRevision,
): boolean {
  const reviewIdentity = job.identity
  const adapted = job.analysis_identity
  const revision = job.artifact_revision
  return isAnalysisIdentity(adapted)
    && isArtifactRevision(revision)
    && analysisIdentityMatches(adapted, expectedIdentity)
    && artifactRevisionMatches(revision, expectedRevision)
    && job.chain_id === expectedIdentity.chain_id
    && reviewIdentity.chain_id === expectedIdentity.chain_id
    && reviewIdentity.snapshot_id === expectedIdentity.snapshot_id
    && reviewIdentity.snapshot_version === expectedIdentity.snapshot_version
    && Object.prototype.hasOwnProperty.call(reviewIdentity, 'topology_version')
    && reviewIdentity.topology_version === expectedIdentity.topology_version
    && reviewIdentity.analysis_version === expectedIdentity.analysis_config_version
    && reviewIdentity.config_version === expectedIdentity.review_config_version
    && reviewIdentity.engine_version === expectedIdentity.pipeline_version
    && reviewIdentity.tier1b_artifact_fingerprint === expectedIdentity.input_fingerprint
    && revision.resource_kind === 'counterfactual_review'
    && revision.fingerprint === job.cache_fingerprint
}

export function getCachedReviewJob(
  expectedIdentity?: AnalysisIdentity | null,
  expectedRevision?: ArtifactRevision | null,
): CounterfactualJob | null {
  cleanLegacyKeys()
  if (!isAnalysisIdentity(expectedIdentity) || !isArtifactRevision(expectedRevision)) return null
  const key = cacheKey(expectedIdentity, expectedRevision)
  if (!key) return null

  const cached = reviewJobCache.get(key)
  if (cached) {
    if (
      !isFresh(cached.storedAt)
      || !reviewJobMatchesExpected(cached.job, expectedIdentity, expectedRevision)
    ) {
      removeEntry(key)
      return null
    }
    remember(key, cached)
    return cached.job
  }

  const storage = sessionStorageOrNull()
  if (!storage) return null
  try {
    const raw = storage.getItem(key)
    const entry = decodeStoredEntry(raw, key)
    if (!entry || !reviewJobMatchesExpected(entry.job, expectedIdentity, expectedRevision)) {
      if (raw !== null) removeStored(storage, key)
      return null
    }
    remember(key, entry)
    pruneSessionStorage(storage, key)
    return entry.job
  } catch {
    // Ignore corrupt or unavailable session storage.
    return null
  }
}

export function setCachedReviewJob(job: CounterfactualJob) {
  cleanLegacyKeys()
  if (!isAnalysisIdentity(job.analysis_identity) || !isArtifactRevision(job.artifact_revision)) return
  const key = cacheKey(job.analysis_identity, job.artifact_revision)
  if (!key || !reviewJobMatchesExpected(job, job.analysis_identity, job.artifact_revision)) return

  const entry: ReviewCacheEntry = { job, storedAt: Date.now() }
  remember(key, entry)

  const storage = sessionStorageOrNull()
  if (!storage) return
  if (!isTerminal(job)) {
    removeStored(storage, key)
    return
  }

  const serialized = JSON.stringify({
    schema: REVIEW_CACHE_SCHEMA,
    ...entry,
  } satisfies StoredReviewCacheEntry)
  pruneSessionStorage(storage)
  try {
    storage.setItem(key, serialized)
  } catch {
    // A full store must not prevent keeping the bounded in-memory entry.
    pruneSessionStorage(storage)
    try {
      storage.setItem(key, serialized)
    } catch {
      return
    }
  }
  pruneSessionStorage(storage, key)
}

export function clearReviewJobCache() {
  reviewJobCache.clear()
  const storage = sessionStorageOrNull()
  if (!storage) {
    legacyKeysCleaned = false
    return
  }
  try {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index)
      if (key?.startsWith(LEGACY_REVIEW_CACHE_PREFIX)) {
        storage.removeItem(key)
      }
    }
    legacyKeysCleaned = false
  } catch {
    // Ignore unavailable session storage.
  }
}
