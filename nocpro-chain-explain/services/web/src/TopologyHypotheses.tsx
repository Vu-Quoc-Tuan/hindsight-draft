import React from 'react'
import type {
  DependencyScopeResult,
  DominatorResult,
  PropagationResult,
  TopologyHypothesesResult,
} from './types'

function StatusPill() {
  return <span className="pill pill--positive" role="status">Đã đánh giá</span>
}

function ratio(value: number | null) {
  if (value == null) return 'Chưa đủ dữ liệu'
  return `${(value * 100).toFixed(2).replace(/\.?0+$/, '')}%`
}

function decimal(value: number | null, digits = 4) {
  return value == null ? 'Chưa đủ dữ liệu' : value.toFixed(digits)
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
    <p>Nguồn topology · {result.source_id ?? 'Chưa ghi nhận'} @ {result.source_version ?? 'Chưa ghi nhận'} · {result.relation_type ?? 'Chưa có loại quan hệ'}</p>
    {(result.scenario_id || result.generator_version) && <p>Dữ liệu mô phỏng · {result.scenario_id ?? 'Chưa ghi nhận'} · {result.generator_version ?? 'Chưa ghi nhận'}</p>}
  </div>
}

const reasonDescriptions: Record<string, string> = {
  DIRECTED_TOPOLOGY_UNAVAILABLE: 'Chưa có topology quan hệ có hướng bao phủ đầy đủ các tài nguyên trong chuỗi.',
  RESOURCE_MAPPING_UNAVAILABLE: 'Chưa ánh xạ đầy đủ các cảnh báo tới tài nguyên topology.',
  TEMPORAL_ORDERING_UNAVAILABLE: 'Thiếu thời điểm bắt đầu hợp lệ của một hoặc nhiều cảnh báo.',
  PROPAGATION_CONFIG_INCOMPLETE: 'Chưa có đủ cấu hình để tính tín hiệu lan truyền.',
  INVALID_DAG: 'Quan hệ topology hiện có chưa tạo thành đồ thị có hướng hợp lệ.',
  CANDIDATE_LIMIT_EXCEEDED: 'Số luồng ứng viên vượt giới hạn phân tích an toàn.',
  RWR_NOT_CONVERGED: 'Phép tính lan truyền chưa hội tụ trong giới hạn cho phép.',
  COMMON_DOMINATOR_UNAVAILABLE: 'Chưa tìm thấy tài nguyên topology chung mà các nhánh của chuỗi cùng đi qua.',
  AMBIGUOUS_DOMINATOR_WITNESS: 'Có nhiều tài nguyên có thể làm điểm chung nên chưa đủ căn cứ chọn một điểm.',
  DEPENDENCY_SCOPE_UNAVAILABLE: 'Chưa xác định được phạm vi phụ thuộc từ topology hiện có.',
  SCOPE_LIMIT_EXCEEDED: 'Phạm vi phụ thuộc vượt giới hạn phân tích an toàn.',
  MATERIALIZATION_LIMIT_EXCEEDED: 'Danh sách tài nguyên vượt giới hạn có thể xử lý để hiển thị chi tiết.',
  TOPOLOGY_SOURCE_VERSION_MISSING: 'Topology chưa có phiên bản nguồn để kiểm chứng và đối chiếu.',
}

function describeReason(reason: string | null | undefined) {
  return reason
    ? reasonDescriptions[reason] ?? 'Dữ liệu hiện có chưa đáp ứng điều kiện để đánh giá tín hiệu này.'
    : 'Dữ liệu hiện có chưa đáp ứng điều kiện để đánh giá tín hiệu này.'
}

type MissingSignal = { title: string; reason: string }

function InsufficientDataNotice({
  signals,
  compact = false,
}: {
  signals: MissingSignal[]
  compact?: boolean
}) {
  return <div className={`topology-insufficient${compact ? ' topology-insufficient--compact' : ''}`} role="status" aria-live="polite">
    {!compact && <span aria-hidden="true" className="topology-insufficient-icon">i</span>}
    <div className="topology-insufficient-content">
      <h3>{compact ? 'Một số tín hiệu chưa đủ dữ liệu' : 'Chưa đủ dữ liệu để đánh giá'}</h3>
      {!compact && <p>Deep Dive chưa thể đánh giá các tín hiệu topology dưới đây. Kết quả được để trống thay vì suy đoán khi dữ liệu hoặc điều kiện kiểm chứng còn thiếu.</p>}
      <ul className="topology-missing-signals">
        {signals.map((signal) => <li key={signal.title}>
          <strong>{signal.title}</strong>
          <span>{describeReason(signal.reason)}</span>
        </li>)}
      </ul>
    </div>
  </div>
}

function DominatorCard({ result }: { result: Extract<DominatorResult, { status: 'AVAILABLE' }> }) {
  return <article className="topology-card topology-card--dominator">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Unavoidable dependency annotation</h3></div><StatusPill /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <dl className="topology-metrics">
      <Metric label="Nút chứng thực (witness)" value={result.witness_resource_id ?? 'Chưa xác định'} />
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

function PropagationCard({ result }: { result: Extract<PropagationResult, { status: 'AVAILABLE' }> }) {
  const diag = (result as Record<string, any>).diagnostics || {}
  const candidateNodeCount = result.candidate_node_count ?? diag.candidate_node_count ?? 0
  const candidateEdgeCount = result.candidate_edge_count ?? diag.candidate_edge_count ?? 0
  const iterations = result.iterations ?? diag.iterations ?? 0
  const finalL1Distance = result.final_l1_distance ?? diag.final_l1_distance
  const convergenceTolerance = result.convergence_tolerance ?? diag.convergence_tolerance
  const configVersion = result.config_version ?? diag.config_version ?? 'Chưa ghi nhận'
  const seedPolicy = result.seed_policy ?? diag.seed_policy ?? 'seed unavailable'
  const danglingPolicy = result.dangling_policy ?? diag.dangling_policy ?? 'dangling policy unavailable'

  return <article className="topology-card topology-card--propagation">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Propagation hypothesis score</h3></div><StatusPill /></header>
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

function ScopeMetrics({ result }: { result: Extract<DependencyScopeResult, { status: 'AVAILABLE' }> }) {
  return <dl className="topology-metrics topology-metrics--scope">
    <Metric label="Tài nguyên quan sát (observed)" value={result.observed_resource_count ?? 'Chưa đủ dữ liệu'} />
    <Metric label="Tài nguyên phạm vi (scope)" value={result.scope_resource_count ?? 'Chưa đủ dữ liệu'} />
    <Metric label="Giao tập hợp (intersection)" value={result.intersection_count ?? 'Chưa đủ dữ liệu'} />
    <Metric label="Hợp tập hợp (union)" value={result.union_count ?? 'Chưa đủ dữ liệu'} />
    <Metric label="Độ phủ (coverage)" value={ratio(result.observed_coverage)} />
    <Metric label="Độ chính xác (precision)" value={ratio(result.scope_precision)} />
    <Metric label="Chỉ số Jaccard" value={ratio(result.jaccard)} />
    <Metric label="Số tài nguyên thiếu (missing)" value={result.missing_resource_count ?? 'Chưa đủ dữ liệu'} />
    <Metric label="Số tài nguyên thừa (extra)" value={result.extra_resource_count ?? 'Chưa đủ dữ liệu'} />
  </dl>
}

function ScopeDetails({ result }: { result: Extract<DependencyScopeResult, { status: 'AVAILABLE' }> }) {
  const details = result.resource_details
  if (details.status === 'UNAVAILABLE') return <p className="topology-detail-unavailable">{describeReason(details.reason)}</p>
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

function ScopeCard({ result }: { result: Extract<DependencyScopeResult, { status: 'AVAILABLE' }> }) {
  return <article className="topology-card topology-card--scope">
    <header className="topology-card-heading"><div><p className="kicker">Năng lực P2 (P2 capability)</p><h3>Dependency scope overlap signal</h3></div><StatusPill /></header>
    <p className="topology-semantic">{result.semantic}</p>
    <ScopeMetrics result={result} />
    <ScopeDetails result={result} />
    <p className="topology-provenance">Nút chứng thực: {result.witness_resource_id ?? 'Chưa xác định'} · Phạm vi neo theo nút chứng thực được chọn (scope anchored)</p>
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
  const missingSignals: MissingSignal[] = [
    ...(topology_hypotheses.dominator.status === 'UNAVAILABLE' ? [{
      title: 'Nút phụ thuộc chung',
      reason: topology_hypotheses.dominator.reason,
    }] : []),
    ...(topology_hypotheses.propagation.status === 'UNAVAILABLE' ? [{
      title: 'Luồng lan truyền',
      reason: topology_hypotheses.propagation.reason,
    }] : []),
    ...(topology_hypotheses.dependency_scope.status === 'UNAVAILABLE' ? [{
      title: 'Phạm vi phụ thuộc',
      reason: topology_hypotheses.dependency_scope.reason,
    }] : []),
  ]
  const availableCount = 3 - missingSignals.length
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
    {availableCount === 0 ? (
      <InsufficientDataNotice signals={missingSignals} />
    ) : (
      <>
        <div className="topology-card-grid">
          {topology_hypotheses.dominator.status === 'AVAILABLE' && <DominatorCard result={topology_hypotheses.dominator} />}
          {topology_hypotheses.propagation.status === 'AVAILABLE' && <PropagationCard result={topology_hypotheses.propagation} />}
          {topology_hypotheses.dependency_scope.status === 'AVAILABLE' && <ScopeCard result={topology_hypotheses.dependency_scope} />}
        </div>
        {missingSignals.length > 0 && <InsufficientDataNotice signals={missingSignals} compact />}
      </>
    )}
  </section>
}
