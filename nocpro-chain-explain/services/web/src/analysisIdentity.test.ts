import { describe, expect, it } from 'vitest'

import {
  analysisIdentityMatches,
  isAnalysisIdentity,
  serializeAnalysisIdentity,
} from './analysisIdentity'
import type { AnalysisIdentity } from './types'

const identity: AnalysisIdentity = {
  identity_version: 'analysis-identity-v1',
  snapshot_id: 'snapshot-1',
  snapshot_version: '001',
  chain_id: 'chain-1',
  topology_version: null,
  analysis_config_version: 'analysis-config-3',
  review_config_version: 'review-config-2',
  pipeline_version: 'pipeline-4',
  input_fingerprint: 'fingerprint-9',
}

describe('AnalysisIdentity', () => {
  it('accepts explicit null topology and preserves string snapshot versions', () => {
    const decoded = JSON.parse(serializeAnalysisIdentity(identity)!) as unknown
    expect(isAnalysisIdentity(decoded)).toBe(true)
    expect((decoded as AnalysisIdentity).snapshot_version).toBe('001')
    expect((decoded as AnalysisIdentity).topology_version).toBeNull()
    expect(analysisIdentityMatches(decoded, identity)).toBe(true)
  })

  it('rejects an omitted field rather than treating it as unknown or null', () => {
    const legacy = { ...identity } as Partial<AnalysisIdentity>
    delete legacy.topology_version
    expect(isAnalysisIdentity(legacy)).toBe(false)
    expect(analysisIdentityMatches(legacy, identity)).toBe(false)
  })

  it('compares every field in the envelope', () => {
    const changed = { ...identity, review_config_version: 'review-config-3' }
    expect(analysisIdentityMatches(changed, identity)).toBe(false)
    expect(analysisIdentityMatches(identity, { ...identity, topology_version: 'topology-1' })).toBe(false)
  })

  it('does not coerce numeric snapshot versions', () => {
    expect(isAnalysisIdentity({ ...identity, snapshot_version: 1 })).toBe(false)
  })
})
