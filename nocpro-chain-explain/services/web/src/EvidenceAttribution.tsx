import type { AttributionDeletionEvaluationResult, EvidenceCoverageAttributionResult } from './types'

function percent(value: number | null) {
  if (value === null) return '⊥'
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
}

function decimal(value: number | null) {
  return value === null ? '⊥' : value.toFixed(3)
}

function DeletionEvaluation({ evaluation }: { evaluation?: AttributionDeletionEvaluationResult | null }) {
  if (!evaluation) return null
  return (
    <section className="deletion-evaluation" aria-label="Attribution deletion evaluation">
      <header>
        <div><p className="kicker">Ranking check · lower primary AUC is better</p><h4>Exact deletion curves</h4></div>
        <div className="attribution-status"><span>Evaluation {evaluation.status}</span><strong>Evaluation {evaluation.mode}</strong></div>
      </header>
      {evaluation.status === 'AVAILABLE' ? (
        <>
          <dl className="attribution-summary">
            <div><dt>primary AUC</dt><dd>{decimal(evaluation.primary.auc)}</dd></div>
            <div><dt>random AUC</dt><dd>{decimal(evaluation.random.mean_auc)} ± {decimal(evaluation.random.std_auc)}</dd></div>
            <div><dt>reverse AUC</dt><dd>{decimal(evaluation.reverse.auc)}</dd></div>
          </dl>
          <dl className="deletion-deltas">
            <div><dt>Δ vs random</dt><dd>{decimal(evaluation.delta_vs_random_auc)}</dd></div>
            <div><dt>Δ vs reverse</dt><dd>{decimal(evaluation.delta_vs_reverse_auc)}</dd></div>
            <div><dt>randomization</dt><dd>{evaluation.random.algorithm} · seed {evaluation.random.seed} · {evaluation.random.repetitions_executed} runs</dd></div>
          </dl>
        </>
      ) : (
        <div className="attribution-reason">
          <strong>{evaluation.reason ?? evaluation.status}</strong>
          <p>{evaluation.group_count} eligible groups; no deletion AUC is reported.</p>
        </div>
      )}
    </section>
  )
}

export function EvidenceAttribution({
  result,
  evaluation,
}: {
  result?: EvidenceCoverageAttributionResult | null
  evaluation?: AttributionDeletionEvaluationResult | null
}) {
  if (!result) return null
  const available = result.status === 'AVAILABLE'
  return (
    <section className={`attribution ${available ? '' : 'attribution--unavailable'}`} aria-label="Evidence Coverage Attribution">
      <header>
        <div><p className="kicker">Tier 2 · exact group allocation</p><h3>Evidence Coverage Attribution</h3></div>
        <div className="attribution-status"><span>{result.status}</span><strong>{result.mode}</strong></div>
      </header>
      {!available ? (
        <div className="attribution-reason">
          <strong>{result.reason ?? 'UNAVAILABLE'}</strong>
          {result.detail && <small>{result.detail}</small>}
          <p>Chain size {result.chain_size}; exact ceiling {result.exact_max_members}.</p>
        </div>
      ) : (
        <>
          <dl className="attribution-summary">
            <div><dt>covered pairs</dt><dd>{result.covered_pair_count} / {result.total_pair_count}</dd></div>
            <div><dt>total evidence coverage</dt><dd>{percent(result.total_coverage)}</dd></div>
            <div><dt>execution</dt><dd>exact indexed</dd></div>
          </dl>
          <div className="attribution-list">
            {result.contributions.map((item) => (
              <article key={item.group_id}>
                <div className="attribution-label">
                  <strong>{item.derivation_tag}</strong>
                  {item.behavioral && <span>BEHAVIORAL</span>}
                  <small>{item.provenance_class} · {item.supported_pair_count} supported pairs</small>
                </div>
                <div className="attribution-value"><strong>{percent(item.attribution)}</strong><small>evidence coverage</small></div>
                <i style={{ width: percent(item.attribution) }} />
              </article>
            ))}
          </div>
        </>
      )}
      <DeletionEvaluation evaluation={evaluation} />
    </section>
  )
}
