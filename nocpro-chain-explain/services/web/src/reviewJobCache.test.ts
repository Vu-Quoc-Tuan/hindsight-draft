import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  clearReviewJobCache,
  getCachedReviewJob,
  setCachedReviewJob,
} from './reviewJobCache'
import type { AnalysisIdentity, ArtifactRevision, CounterfactualJob } from './types'

const identity: AnalysisIdentity = {
  identity_version: 'analysis-identity-v1',
  snapshot_id: 'snapshot-1',
  snapshot_version: '001',
  chain_id: 'chain-1',
  topology_version: null,
  analysis_config_version: 'analysis-config-1',
  review_config_version: 'review-config-1',
  pipeline_version: 'review-engine-1',
  input_fingerprint: 'tier1b-fingerprint',
}

const revision: ArtifactRevision = {
  resource_kind: 'counterfactual_review',
  fingerprint: 'review-cache-fingerprint',
}

const job: CounterfactualJob = {
  job_id: 'review-1',
  chain_id: 'chain-1',
  status: 'SUCCEEDED',
  progress_percent: 100,
  cache_hit: false,
  cache_fingerprint: revision.fingerprint,
  identity: {
    snapshot_id: identity.snapshot_id,
    snapshot_version: identity.snapshot_version,
    topology_version: identity.topology_version,
    chain_id: identity.chain_id,
    alarm_universe_fingerprint: 'alarms',
    analysis_version: identity.analysis_config_version,
    engine_version: identity.pipeline_version,
    config_version: identity.review_config_version!,
    tier1b_artifact_fingerprint: identity.input_fingerprint,
    structural_audit_artifact_fingerprint: null,
    external_validation_artifact_fingerprint: null,
  },
  analysis_identity: identity,
  artifact_revision: revision,
  result: null,
  error: null,
}

describe('review job cache', () => {
  afterEach(() => {
    clearReviewJobCache()
    vi.unstubAllGlobals()
  })

  it('requires the complete expected identity and artifact revision', () => {
    setCachedReviewJob(job)
    expect(getCachedReviewJob()).toBeNull()
    expect(getCachedReviewJob(identity, null)).toBeNull()
    expect(getCachedReviewJob(identity, revision)).toEqual(job)
    expect(getCachedReviewJob(
      { ...identity, review_config_version: 'review-config-2' },
      revision,
    )).toBeNull()
    expect(getCachedReviewJob(identity, { ...revision, fingerprint: 'new-revision' })).toBeNull()
  })

  it('stores under the v3 namespace and removes only this app legacy keys', () => {
    const values = new Map<string, string>([
      ['nocpro_review_v2_old', 'old-schema'],
      ['nocpro_review_old', 'legacy'],
      ['another_app_cache', 'keep'],
    ])
    const storage = {
      get length() { return values.size },
      key(index: number) { return [...values.keys()][index] ?? null },
      getItem(key: string) { return values.get(key) ?? null },
      setItem(key: string, value: string) { values.set(key, value) },
      removeItem(key: string) { values.delete(key) },
    }
    vi.stubGlobal('window', { sessionStorage: storage })

    setCachedReviewJob(job)

    const savedKey = [...values.keys()].find((key) => key.startsWith('nocpro_review_v3_'))
    expect(savedKey).toBeDefined()
    expect(values.has('nocpro_review_v2_old')).toBe(false)
    expect(values.has('nocpro_review_old')).toBe(false)
    expect(values.has('another_app_cache')).toBe(true)
    expect(getCachedReviewJob(identity, revision)).toEqual(job)
  })

  it('refuses jobs whose public envelope and persisted Review identity disagree', () => {
    setCachedReviewJob({
      ...job,
      analysis_identity: { ...identity, topology_version: 'topology-2' },
    })

    expect(getCachedReviewJob(identity, revision)).toBeNull()
  })

  it('keeps only terminal jobs in session storage', () => {
    const values = new Map<string, string>()
    const storage = {
      get length() { return values.size },
      key(index: number) { return [...values.keys()][index] ?? null },
      getItem(key: string) { return values.get(key) ?? null },
      setItem(key: string, value: string) { values.set(key, value) },
      removeItem(key: string) { values.delete(key) },
    }
    vi.stubGlobal('window', { sessionStorage: storage })

    setCachedReviewJob({ ...job, status: 'RUNNING' })

    expect([...values.keys()].filter(key => key.startsWith('nocpro_review_v3_'))).toHaveLength(0)
    expect(getCachedReviewJob(identity, revision)?.status).toBe('RUNNING')
  })

  it('bounds in-memory cache to 100 entries and refreshes LRU recency on read', () => {
    const makeJob = (index: number): CounterfactualJob => {
      const nextIdentity = { ...identity, chain_id: `chain-${index}` }
      const nextRevision = { ...revision, fingerprint: `review-${index}` }
      return {
        ...job,
        job_id: `job-${index}`,
        chain_id: nextIdentity.chain_id,
        cache_fingerprint: nextRevision.fingerprint,
        identity: { ...job.identity, chain_id: nextIdentity.chain_id },
        analysis_identity: nextIdentity,
        artifact_revision: nextRevision,
      }
    }
    const jobs = Array.from({ length: 101 }, (_, index) => makeJob(index))
    jobs.slice(0, 100).forEach(setCachedReviewJob)
    expect(getCachedReviewJob(jobs[0].analysis_identity, jobs[0].artifact_revision)).toEqual(jobs[0])
    setCachedReviewJob(jobs[100])

    expect(getCachedReviewJob(jobs[0].analysis_identity, jobs[0].artifact_revision)).toEqual(jobs[0])
    expect(getCachedReviewJob(jobs[1].analysis_identity, jobs[1].artifact_revision)).toBeNull()
  })

  it('bounds persisted terminal entries to 20 and discards expired or corrupt entries', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-24T00:00:00Z'))
    const values = new Map<string, string>()
    const storage = {
      get length() { return values.size },
      key(index: number) { return [...values.keys()][index] ?? null },
      getItem(key: string) { return values.get(key) ?? null },
      setItem(key: string, value: string) { values.set(key, value) },
      removeItem(key: string) { values.delete(key) },
    }
    vi.stubGlobal('window', { sessionStorage: storage })
    const makeJob = (index: number): CounterfactualJob => {
      const nextIdentity = { ...identity, chain_id: `chain-${index}` }
      const nextRevision = { ...revision, fingerprint: `review-${index}` }
      return {
        ...job,
        job_id: `job-${index}`,
        chain_id: nextIdentity.chain_id,
        cache_fingerprint: nextRevision.fingerprint,
        identity: { ...job.identity, chain_id: nextIdentity.chain_id },
        analysis_identity: nextIdentity,
        artifact_revision: nextRevision,
      }
    }
    const jobs = Array.from({ length: 21 }, (_, index) => makeJob(index))
    jobs.forEach(setCachedReviewJob)
    let keys = [...values.keys()].filter(key => key.startsWith('nocpro_review_v3_'))
    expect(keys).toHaveLength(20)
    expect(keys.some(key => key.includes(encodeURIComponent('chain-0')))).toBe(false)

    const corrupt = jobs[1]
    const expired = jobs[2]
    const corruptKey = keys.find(key => key.includes(encodeURIComponent('chain-1')))
    const expiredKey = keys.find(key => key.includes(encodeURIComponent('chain-2')))
    expect(corruptKey).toBeDefined()
    expect(expiredKey).toBeDefined()
    values.set(corruptKey!, '{not-json')
    const expiredEntry = JSON.parse(values.get(expiredKey!)!) as { storedAt: number }
    values.set(expiredKey!, JSON.stringify({ ...expiredEntry, storedAt: Date.now() - 5 * 60 * 1000 - 1 }))

    await vi.resetModules()
    const reloadedCache = await import('./reviewJobCache')
    expect(reloadedCache.getCachedReviewJob(corrupt.analysis_identity, corrupt.artifact_revision)).toBeNull()
    expect(values.has(corruptKey!)).toBe(false)
    expect(reloadedCache.getCachedReviewJob(expired.analysis_identity, expired.artifact_revision)).toBeNull()
    expect(values.has(expiredKey!)).toBe(false)
  })

  it('keeps the in-memory terminal result when session storage quota writes fail', () => {
    const storage = {
      length: 0,
      key: () => null,
      getItem: () => null,
      setItem: () => { throw new DOMException('quota exceeded', 'QuotaExceededError') },
      removeItem: () => undefined,
    }
    vi.stubGlobal('window', { sessionStorage: storage })

    setCachedReviewJob(job)

    expect(getCachedReviewJob(identity, revision)).toEqual(job)
  })
})
