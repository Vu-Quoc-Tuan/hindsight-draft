import type { EvidenceCoverageAttributionResult } from './types'

function percent(value: number | null) {
  if (value === null) return '⊥'
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
}

export function EvidenceAttribution({ result }: { result: EvidenceCoverageAttributionResult }) {
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
    </section>
  )
}
