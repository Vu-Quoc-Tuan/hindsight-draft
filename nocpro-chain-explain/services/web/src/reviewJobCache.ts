import type { CounterfactualJob } from './types'

const reviewJobCache = new Map<string, CounterfactualJob>()

function cacheKey(
  chainId: string,
  snapshotId?: string | null,
  snapshotVersion?: string | null,
  topologyVersion?: string | null,
): string | null {
  if (!snapshotId || !snapshotVersion) return null
  const topologyKey = topologyVersion === undefined ? 'UNKNOWN_TOPOLOGY' : topologyVersion ?? 'NO_TOPOLOGY'
  return [snapshotId, snapshotVersion, topologyKey, chainId].map(encodeURIComponent).join(':')
}

function matchesContext(
  job: CounterfactualJob,
  chainId: string,
  snapshotId: string,
  snapshotVersion: string,
  topologyVersion?: string | null,
): boolean {
  return job.chain_id === chainId
    && job.identity?.chain_id === chainId
    && job.identity?.snapshot_id === snapshotId
    && job.identity?.snapshot_version === snapshotVersion
    && (topologyVersion === undefined || job.identity?.topology_version === topologyVersion)
}

export function getCachedReviewJob(
  chainId: string,
  snapshotId?: string | null,
  snapshotVersion?: string | null,
  topologyVersion?: string | null,
): CounterfactualJob | null {
  const key = cacheKey(chainId, snapshotId, snapshotVersion, topologyVersion)
  if (!key || !snapshotId || !snapshotVersion) return null
  const cached = reviewJobCache.get(key)
  if (cached) return matchesContext(cached, chainId, snapshotId, snapshotVersion, topologyVersion) ? cached : null
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      const raw = window.sessionStorage.getItem(`nocpro_review_${key}`)
      if (raw) {
        const parsed = JSON.parse(raw) as CounterfactualJob
        if (matchesContext(parsed, chainId, snapshotId, snapshotVersion, topologyVersion)) {
          reviewJobCache.set(key, parsed)
          return parsed
        }
      }
    } catch {
      // Ignore unavailable session storage.
    }
  }
  return null
}

export function setCachedReviewJob(
  chainId: string,
  snapshotId: string | null | undefined,
  snapshotVersion: string | null | undefined,
  topologyVersion: string | null | undefined,
  job: CounterfactualJob,
) {
  const key = cacheKey(chainId, snapshotId, snapshotVersion, topologyVersion)
  if (!key || !snapshotId || !snapshotVersion || !matchesContext(job, chainId, snapshotId, snapshotVersion, topologyVersion)) return
  reviewJobCache.set(key, job)
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      window.sessionStorage.setItem(`nocpro_review_${key}`, JSON.stringify(job))
    } catch {
      // Ignore unavailable session storage.
    }
  }
}
