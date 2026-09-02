import { useEffect, useState } from 'react'

import { api, ApiError } from './api'
import { percent } from './format'
import type {
  CounterfactualCandidate,
  CounterfactualJob,
  CounterfactualMetricVector,
  CounterfactualOperation,
} from './types'

const metricLabels: Array<[keyof CounterfactualMetricVector, string]> = [
  ['weak_member_count', 'Weak members'],
  ['minimum_membership_support', 'Minimum support'],
  ['evidence_union_coverage', 'Evidence coverage'],
  ['component_count', 'Components'],
  ['audit_conductance', 'Conductance'],
  ['audit_verdict_severity', 'Audit severity'],
  ['eligible_external_contradiction_count', 'Contradictions'],
]

function metricValue(name: keyof CounterfactualMetricVector, vector: CounterfactualMetricVector | null) {
  const metric = vector?.[name]
  if (!metric || metric.availability !== 'AVAILABLE' || metric.value == null) return '⊥'
  if (['minimum_membership_support', 'evidence_union_coverage'].includes(name)) return percent(metric.value)
  return Number.isInteger(metric.value) ? String(metric.value) : metric.value.toFixed(3)
}

function CandidateCard({ candidate, recommended }: { candidate: CounterfactualCandidate; recommended: boolean }) {
  return (
    <article className={`review-candidate ${recommended ? 'review-candidate--recommended' : ''}`}>
      <header>
        <div>
          <span className="review-operation">{candidate.operation}</span>
          <strong>{candidate.member_ids.join(' · ') || 'Partition proposal'}</strong>
        </div>
        <span className={`review-state review-state--${candidate.status.toLowerCase()}`}>{candidate.status}</span>
      </header>
      <div className="review-partition" aria-label="Before and after partition">
        <div><small>Current</small>{candidate.partition_delta.before.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
        <i aria-hidden="true">→</i>
        <div><small>Proposed</small>{candidate.partition_delta.after.map(([id, members]) => <p key={id}><strong>{id}</strong><span>{members.length} members</span></p>)}</div>
      </div>
      <div className="review-ledger" role="table" aria-label="Exact before and after metrics">
        <div className="review-ledger-head" role="row"><span>Metric</span><span>Before</span><span>After</span></div>
        {metricLabels.map(([name, label]) => (
          <div role="row" key={name}>
            <span>{label}</span>
            <span>{metricValue(name, candidate.before)}</span>
            <strong>{metricValue(name, candidate.after)}</strong>
          </div>
        ))}
      </div>
      <footer>
        <span>Exact bounded evaluation · {candidate.source_ref}</span>
        <span>{candidate.materially_improved_metrics.length} material improvements</span>
      </footer>
    </article>
  )
}

function OperationSection({ operation, recommendationIds }: { operation: CounterfactualOperation; recommendationIds: Set<string> }) {
  return (
    <section className="review-operation-section">
      <header>
        <div><p className="kicker">Bounded operation</p><h3>{operation.operation}</h3></div>
        <span className={`review-state review-state--${operation.status.toLowerCase()}`}>{operation.status}</span>
      </header>
      <dl className="review-search-diagnostics">
        <div><dt>discovered</dt><dd>{operation.discovered_candidate_count}</dd></div>
        <div><dt>evaluated</dt><dd>{operation.evaluated_candidate_count}</dd></div>
        <div><dt>rejected</dt><dd>{operation.rejected_candidate_count}</dd></div>
        <div><dt>limit</dt><dd>{operation.candidate_limit ?? '⊥'}</dd></div>
      </dl>
      {operation.reason && <p className="review-reason">{operation.reason}</p>}
      <div className="review-candidate-list">
        {operation.candidates.map((candidate) => (
          <CandidateCard key={candidate.candidate_id} candidate={candidate} recommended={recommendationIds.has(candidate.candidate_id)} />
        ))}
        {operation.status === 'AVAILABLE' && operation.candidates.length === 0 ? <p className="review-empty">No bounded candidate met the trigger policy.</p> : null}
      </div>
    </section>
  )
}

export function CounterfactualReview({ chainId, initialJob = null }: { chainId: string; initialJob?: CounterfactualJob | null }) {
  const [job, setJob] = useState<CounterfactualJob | null>(initialJob)
  const [loading, setLoading] = useState(initialJob == null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialJob?.chain_id === chainId) return
    const controller = new AbortController()
    async function load() {
      try {
        let current: CounterfactualJob
        try {
          current = await api.latestReview(chainId, controller.signal)
        } catch (cause) {
          if (!(cause instanceof ApiError && cause.status === 404)) throw cause
          const submission = await api.submitReview(chainId)
          current = await api.reviewJob(submission.job_id, controller.signal)
        }
        if (!controller.signal.aborted) setJob(current)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Review unavailable')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [chainId, initialJob])

  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.reviewJob(job.job_id, controller.signal).then(setJob).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Review polling failed')
      })
    }, 450)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [job])

  if (loading && !job) return <section className="review-shell review-loading"><span /><p>Evaluating bounded alternatives…</p></section>
  if (error) return <section className="review-shell review-unavailable" role="alert"><span>UNAVAILABLE</span><h2>Counterfactual review could not be loaded.</h2><p>{error}</p></section>
  if (!job) return null
  if (!job.result) return <section className="review-shell review-loading"><span>{job.progress_percent}%</span><p>{job.status}</p>{job.error ? <small>{job.error}</small> : null}</section>

  const result = job.result
  const recommendationIds = new Set(result.recommendations.map((item) => item.candidate_id))
  return (
    <section className="review-shell">
      <header className="review-heading">
        <div><p className="kicker">Review-only · {result.identity.engine_version}</p><h2>Counterfactual chain review</h2><p>Compare exact, bounded partition alternatives. This analysis does not change the NocPro grouping.</p></div>
        <div><span className={`review-state review-state--${result.recommendation_status.toLowerCase()}`}>{result.recommendation_status}</span><small>{result.identity.config_version}</small></div>
      </header>
      <div className="review-safety-notice"><strong>Proposal only</strong><span>NocPro was not changed. No candidate is applied automatically.</span></div>
      {result.reason ? <p className="review-global-reason">{result.reason}</p> : null}
      <div className="review-operation-grid">
        <OperationSection operation={result.remove} recommendationIds={recommendationIds} />
        <OperationSection operation={result.split} recommendationIds={recommendationIds} />
      </div>
      <footer className="review-provenance">
        <span>Snapshot {result.identity.snapshot_id}@{result.identity.snapshot_version}</span>
        <span>{result.frontier_count_before_limit} frontier candidates{result.frontier_truncated ? ' · bounded for display' : ''}</span>
        <span>Artifact {job.cache_fingerprint.slice(0, 12)}</span>
      </footer>
    </section>
  )
}
