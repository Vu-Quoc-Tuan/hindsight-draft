import type {
  DependencyScopeResult,
  DominatorResult,
  PropagationResult,
  TopologyHypothesesResult,
} from './types'

type Status = 'AVAILABLE' | 'UNAVAILABLE'

function statusTone(status: Status) {
  return status === 'AVAILABLE' ? 'positive' : 'muted'
}

function StatusPill({ status }: { status: Status }) {
  return <span className={`pill pill--${statusTone(status)}`} role="status">{status}</span>
}

function ratio(value: number | null) {
  if (value == null) return 'UNAVAILABLE'
  return `${(value * 100).toFixed(2).replace(/\.?0+$/, '')}%`
}

function decimal(value: number | null, digits = 4) {
  return value == null ? 'UNAVAILABLE' : value.toFixed(digits)
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="topology-metric"><dt>{label}</dt><dd>{value}</dd></div>
}

function Provenance({ result }: { result: {
  source_ref: string | null
  source_id: string | null
  source_version: string | null
  scenario_id: string | null
  generator_version: string | null
  relation_type: string | null
} }) {
  return <div className="topology-provenance">
    <p>topology source · {result.source_id ?? 'UNAVAILABLE'} @ {result.source_version ?? 'UNAVAILABLE'} · {result.relation_type ?? 'relation unavailable'}</p>
    {(result.scenario_id || result.generator_version) && <p>synthetic generation · {result.scenario_id ?? 'UNAVAILABLE'} · {result.generator_version ?? 'UNAVAILABLE'}</p>}
  </div>
}

function UnavailableCard({ title, result }: { title: string; result: { status: 'UNAVAILABLE'; reason: string } }) {
  return <article className="topology-card topology-card--unavailable">
    <header className="topology-card-heading"><div><p className="kicker">P2 capability</p><h3>{title}</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-reason">{result.reason}</p>
    <p className="topology-muted">This signal stays unavailable until its required evidence and configuration are present.</p>
  </article>
}

function DominatorCard({ result }: { result: DominatorResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Unavoidable dependency annotation" result={result} />
  return <article className="topology-card topology-card--dominator">
    <header className="topology-card-heading"><div><p className="kicker">P2 capability</p><h3>Unavoidable dependency annotation</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <dl className="topology-metrics">
      <Metric label="witness" value={result.witness_resource_id ?? 'UNAVAILABLE'} />
      <Metric label="covered resources" value={result.covered_resource_ids.length} />
    </dl>
    <Provenance result={result} />
  </article>
}

function PropagationCard({ result }: { result: PropagationResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Propagation hypothesis score" result={result} />
  return <article className="topology-card topology-card--propagation">
    <header className="topology-card-heading"><div><p className="kicker">P2 capability</p><h3>Propagation hypothesis score</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <dl className="topology-metrics topology-metrics--dense">
      <Metric label="candidate nodes" value={result.candidate_node_count} />
      <Metric label="candidate edges" value={result.candidate_edge_count} />
      <Metric label="iterations" value={result.iterations} />
      <Metric label="L1 distance" value={decimal(result.final_l1_distance, 7)} />
      <Metric label="tolerance" value={decimal(result.convergence_tolerance, 7)} />
      <Metric label="config" value={result.config_version ?? 'UNAVAILABLE'} />
    </dl>
    <div className="topology-list-block">
      <h4>Node stationary mass</h4>
      {result.node_scores.length > 0 ? <ul className="topology-score-list">
        {result.node_scores.map((node) => <li key={node.alarm_id}><span>{node.alarm_id}</span><strong>{decimal(node.score)}</strong></li>)}
      </ul> : <p className="topology-muted">No node scores passed the configured result boundary.</p>}
    </div>
    <div className="topology-list-block">
      <h4>Edge propagation flow</h4>
      {result.hypotheses.length > 0 ? <ul className="topology-score-list">
        {result.hypotheses.map((edge) => <li key={`${edge.source_alarm_id}-${edge.target_alarm_id}`}>
          <span>{edge.source_alarm_id} → {edge.target_alarm_id}</span><strong>{decimal(edge.score)}</strong>
          <small>transition {decimal(edge.transition_probability)} · +{decimal(edge.temporal_delta_seconds, 1)}s</small>
        </li>)}
      </ul> : <p className="topology-muted">No edge flows passed the configured result boundary.</p>}
    </div>
    <p className="topology-provenance">{result.seed_policy ?? 'seed unavailable'} · {result.dangling_policy ?? 'dangling policy unavailable'}</p>
    {Object.keys(result.parameter_provenance).length > 0 && <p className="topology-provenance">parameter provenance · {Object.entries(result.parameter_provenance).map(([name, source]) => `${name}: ${source}`).join(' · ')}</p>}
    <Provenance result={result} />
  </article>
}

function ScopeMetrics({ result }: { result: DependencyScopeResult }) {
  return <dl className="topology-metrics topology-metrics--scope">
    <Metric label="observed resources" value={result.observed_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="scope resources" value={result.scope_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="intersection" value={result.intersection_count ?? 'UNAVAILABLE'} />
    <Metric label="union" value={result.union_count ?? 'UNAVAILABLE'} />
    <Metric label="coverage" value={ratio(result.observed_coverage)} />
    <Metric label="precision" value={ratio(result.scope_precision)} />
    <Metric label="Jaccard" value={ratio(result.jaccard)} />
    <Metric label="missing count" value={result.missing_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="extra count" value={result.extra_resource_count ?? 'UNAVAILABLE'} />
  </dl>
}

function ScopeDetails({ result }: { result: DependencyScopeResult }) {
  const details = result.resource_details
  if (details.status === 'UNAVAILABLE') return <p className="topology-detail-unavailable">{details.reason}</p>
  return <div className="topology-resource-lists">
    <div className="topology-resource-list"><h4>Missing resources</h4><ul>{details.missing_resources.map((resource) => <li key={resource}>{resource}</li>)}</ul></div>
    <div className="topology-resource-list"><h4>Extra resources</h4><ul>{details.extra_resources.map((resource) => <li key={resource}>{resource}</li>)}</ul></div>
  </div>
}

function ScopeCard({ result }: { result: DependencyScopeResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Dependency scope overlap signal" result={result} />
  return <article className="topology-card topology-card--scope">
    <header className="topology-card-heading"><div><p className="kicker">P2 capability</p><h3>Dependency scope overlap signal</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <ScopeMetrics result={result} />
    <ScopeDetails result={result} />
    <p className="topology-provenance">witness {result.witness_resource_id ?? 'UNAVAILABLE'} · scope anchored to selected witness</p>
    <Provenance result={result} />
  </article>
}

export function TopologyHypotheses({ topology_hypotheses }: { topology_hypotheses: TopologyHypothesesResult }) {
  return <section className="topology-hypotheses" role="region" aria-labelledby="topology-hypotheses-heading">
    <header className="section-heading topology-section-heading">
      <div><p className="kicker">Tier 2 · independent signals</p><h2 id="topology-hypotheses-heading">Topology hypotheses</h2></div>
      <span>Fail-closed capability view</span>
    </header>
    <div className="topology-card-grid">
      <DominatorCard result={topology_hypotheses.dominator} />
      <PropagationCard result={topology_hypotheses.propagation} />
      <ScopeCard result={topology_hypotheses.dependency_scope} />
    </div>
  </section>
}
