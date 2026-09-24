import type { AnalysisIdentity, ArtifactRevision } from './types'

const IDENTITY_KEYS = [
  'identity_version',
  'snapshot_id',
  'snapshot_version',
  'chain_id',
  'topology_version',
  'analysis_config_version',
  'review_config_version',
  'pipeline_version',
  'input_fingerprint',
] as const

const hasOwn = (value: object, key: PropertyKey) =>
  Object.prototype.hasOwnProperty.call(value, key)

const nonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0

export function isAnalysisIdentity(value: unknown): value is AnalysisIdentity {
  if (typeof value !== 'object' || value === null) return false
  const identity = value as Record<string, unknown>
  if (!IDENTITY_KEYS.every((key) => hasOwn(identity, key))) return false
  return identity.identity_version === 'analysis-identity-v1'
    && nonEmptyString(identity.snapshot_id)
    && nonEmptyString(identity.snapshot_version)
    && nonEmptyString(identity.chain_id)
    && (identity.topology_version === null || nonEmptyString(identity.topology_version))
    && nonEmptyString(identity.analysis_config_version)
    && (identity.review_config_version === null || nonEmptyString(identity.review_config_version))
    && nonEmptyString(identity.pipeline_version)
    && nonEmptyString(identity.input_fingerprint)
}

export function serializeAnalysisIdentity(value: unknown): string | null {
  if (!isAnalysisIdentity(value)) return null
  return JSON.stringify(Object.fromEntries(IDENTITY_KEYS.map((key) => [key, value[key]])))
}

export function analysisIdentityMatches(
  actual: unknown,
  expected: unknown,
): actual is AnalysisIdentity {
  const actualSerialized = serializeAnalysisIdentity(actual)
  return actualSerialized !== null && actualSerialized === serializeAnalysisIdentity(expected)
}

export function isArtifactRevision(value: unknown): value is ArtifactRevision {
  if (typeof value !== 'object' || value === null) return false
  const revision = value as Record<string, unknown>
  return nonEmptyString(revision.resource_kind) && nonEmptyString(revision.fingerprint)
}

export function artifactRevisionMatches(actual: unknown, expected: unknown): actual is ArtifactRevision {
  return isArtifactRevision(actual)
    && isArtifactRevision(expected)
    && actual.resource_kind === expected.resource_kind
    && actual.fingerprint === expected.fingerprint
}
