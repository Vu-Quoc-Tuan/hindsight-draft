import React from 'react'
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
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>{title}</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-reason">{result.reason}</p>
    <p className="topology-muted">Tín hiệu này duy trì trạng thái chưa khả dụng (fail-closed) cho đến khi có đủ chứng cứ quan hệ có hướng và cấu hình hợp lệ.</p>
  </article>
}

function DominatorCard({ result }: { result: DominatorResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Unavoidable dependency annotation" result={result} />
  return <article className="topology-card topology-card--dominator">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Unavoidable dependency annotation</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <dl className="topology-metrics">
      <Metric label="Nút chứng thực (witness)" value={result.witness_resource_id ?? 'UNAVAILABLE'} />
      <Metric label="Tài nguyên bao phủ (covered resources)" value={result.covered_resource_ids.length} />
    </dl>
    {result.covered_resource_ids.length > 0 && (
      <div className="topology-list-block">
        <h4 className="flex items-center justify-between">
          <span>Tài nguyên bao phủ · Covered resources ({result.covered_resource_ids.length})</span>
          <span className="text-[10px] text-on-surface-variant font-normal">Máy chủ Nova compute</span>
        </h4>
        <ul className="topology-resource-tags">
          {result.covered_resource_ids.map((res) => (
            <li key={res}><code>{res}</code></li>
          ))}
        </ul>
      </div>
    )}
    <Provenance result={result} />
  </article>
}

function PropagationCard({ result }: { result: PropagationResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Propagation hypothesis score" result={result} />
  const diag = (result as Record<string, any>).diagnostics || {}
  const candidateNodeCount = result.candidate_node_count ?? diag.candidate_node_count ?? 0
  const candidateEdgeCount = result.candidate_edge_count ?? diag.candidate_edge_count ?? 0
  const iterations = result.iterations ?? diag.iterations ?? 0
  const finalL1Distance = result.final_l1_distance ?? diag.final_l1_distance
  const convergenceTolerance = result.convergence_tolerance ?? diag.convergence_tolerance
  const configVersion = result.config_version ?? diag.config_version ?? 'UNAVAILABLE'
  const seedPolicy = result.seed_policy ?? diag.seed_policy ?? 'seed unavailable'
  const danglingPolicy = result.dangling_policy ?? diag.dangling_policy ?? 'dangling policy unavailable'

  return <article className="topology-card topology-card--propagation">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Propagation hypothesis score</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <dl className="topology-metrics topology-metrics--dense">
      <Metric label="Nút ứng viên (candidate nodes)" value={candidateNodeCount} />
      <Metric label="Cạnh ứng viên (candidate edges)" value={candidateEdgeCount} />
      <Metric label="Số vòng lặp (iterations)" value={iterations} />
      <Metric label="Khoảng cách L1 distance" value={decimal(finalL1Distance, 7)} />
      <Metric label="Ngưỡng sai số (tolerance)" value={decimal(convergenceTolerance, 7)} />
      <Metric label="Cấu hình (config)" value={configVersion} />
    </dl>
    <div className="topology-list-block">
      <div className="flex items-center justify-between">
        <h4>Khối lượng dừng nút · Node stationary mass ({result.node_scores.length})</h4>
        {candidateEdgeCount === 0 && (
          <span className="text-[10px] text-accent-sky font-mono px-1.5 py-0.5 rounded bg-sky-500/10">
            Uniform (đồng đều {ratio(result.node_scores[0]?.score ?? 0)})
          </span>
        )}
      </div>
      {result.node_scores.length > 0 ? (
        <ul className="topology-score-list">
          {result.node_scores.map((node) => (
            <li key={node.alarm_id}>
              <span>{node.alarm_id}</span>
              <strong>{decimal(node.score)}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="topology-muted">Không có điểm số nút nào vượt qua ngưỡng kết quả cấu hình.</p>
      )}
    </div>
    <div className="topology-list-block">
      <h4>Luồng lan truyền cạnh · Edge propagation flow ({result.hypotheses.length})</h4>
      {result.hypotheses.length > 0 ? (
        <ul className="topology-score-list">
          {result.hypotheses.map((edge) => (
            <li key={`${edge.source_alarm_id}-${edge.target_alarm_id}`}>
              <span>{edge.source_alarm_id} → {edge.target_alarm_id}</span>
              <strong>{decimal(edge.score)}</strong>
              <small>chuyển tiếp {decimal(edge.transition_probability)} · +{decimal(edge.temporal_delta_seconds, 1)}s</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="topology-muted">
          {candidateEdgeCount === 0
            ? 'Không có cạnh lan truyền chéo giữa các cảnh báo độc lập trong chuỗi.'
            : 'Không có luồng lan truyền cạnh nào vượt qua ngưỡng kết quả cấu hình.'}
        </p>
      )}
    </div>
    <p className="topology-provenance">{seedPolicy} · {danglingPolicy}</p>
    {Object.keys(result.parameter_provenance || {}).length > 0 && (
      <p className="topology-provenance">
        parameter provenance · {Object.entries(result.parameter_provenance).map(([name, source]) => `${name}: ${source}`).join(' · ')}
      </p>
    )}
    <Provenance result={result} />
  </article>
}

function ScopeMetrics({ result }: { result: DependencyScopeResult }) {
  return <dl className="topology-metrics topology-metrics--scope">
    <Metric label="Tài nguyên quan sát (observed)" value={result.observed_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="Tài nguyên phạm vi (scope)" value={result.scope_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="Giao tập hợp (intersection)" value={result.intersection_count ?? 'UNAVAILABLE'} />
    <Metric label="Hợp tập hợp (union)" value={result.union_count ?? 'UNAVAILABLE'} />
    <Metric label="Độ phủ (coverage)" value={ratio(result.observed_coverage)} />
    <Metric label="Độ chính xác (precision)" value={ratio(result.scope_precision)} />
    <Metric label="Chỉ số Jaccard" value={ratio(result.jaccard)} />
    <Metric label="Số tài nguyên thiếu (missing)" value={result.missing_resource_count ?? 'UNAVAILABLE'} />
    <Metric label="Số tài nguyên thừa (extra)" value={result.extra_resource_count ?? 'UNAVAILABLE'} />
  </dl>
}

function ScopeDetails({ result }: { result: DependencyScopeResult }) {
  const details = result.resource_details
  if (details.status === 'UNAVAILABLE') return <p className="topology-detail-unavailable">{details.reason}</p>
  return <div className="topology-resource-lists">
    <div className="topology-resource-list">
      <h4>Tài nguyên thiếu · Missing resources ({details.missing_resources?.length ?? 0})</h4>
      <ul>
        {details.missing_resources && details.missing_resources.length > 0 ? (
          details.missing_resources.map((resource) => <li key={resource}><code>{resource}</code></li>)
        ) : (
          <li className="topology-empty">0 tài nguyên thiếu</li>
        )}
      </ul>
    </div>
    <div className="topology-resource-list">
      <h4>Tài nguyên thừa · Extra resources ({details.extra_resources?.length ?? 0})</h4>
      <ul>
        {details.extra_resources && details.extra_resources.length > 0 ? (
          details.extra_resources.map((resource) => <li key={resource}><code>{resource}</code></li>)
        ) : (
          <li className="topology-empty">0 tài nguyên thừa</li>
        )}
      </ul>
    </div>
  </div>
}

function ScopeCard({ result }: { result: DependencyScopeResult }) {
  if (result.status === 'UNAVAILABLE') return <UnavailableCard title="Dependency scope overlap signal" result={result} />
  return <article className="topology-card topology-card--scope">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Dependency scope overlap signal</h3></div><StatusPill status={result.status} /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <ScopeMetrics result={result} />
    <ScopeDetails result={result} />
    <p className="topology-provenance">Nút chứng thực: {result.witness_resource_id ?? 'UNAVAILABLE'} · Phạm vi neo theo nút chứng thực được chọn (scope anchored)</p>
    <Provenance result={result} />
  </article>
}

export function TopologyHypotheses({
  topology_hypotheses,
  action,
}: {
  topology_hypotheses?: TopologyHypothesesResult | null
  action?: React.ReactNode
}) {
  if (!topology_hypotheses || !topology_hypotheses.dominator) return null
  return <section className="topology-hypotheses" role="region" aria-labelledby="topology-hypotheses-heading">
    <header className="section-heading topology-section-heading">
      <div>
        <p className="kicker">Tier 2 · Tín hiệu độc lập (independent signals)</p>
        <h2 id="topology-hypotheses-heading">Giả thuyết Topology (Topology hypotheses)</h2>
      </div>
      <div className="flex items-center gap-space-sm">
        {action}
        <span className="text-xs text-on-surface-variant font-mono">Chế độ kiểm chứng an toàn (Fail-closed capability view)</span>
      </div>
    </header>
    <div className="topology-card-grid">
      <DominatorCard result={topology_hypotheses.dominator} />
      <PropagationCard result={topology_hypotheses.propagation} />
      <ScopeCard result={topology_hypotheses.dependency_scope} />
    </div>
  </section>
}
