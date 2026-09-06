import { EvidenceAttribution } from '../EvidenceAttribution'
import { AuditGraphVisualization } from '../components/AuditGraphVisualization'
import type { AuditVisualizationArtifact, ChainAnalysis, DeepDive, Job } from '../types'

interface AuditStructureViewProps {
  analysis: ChainAnalysis
  job?: Job | null
  auditVisualization?: AuditVisualizationArtifact | null
  onRunDeepDive?: () => void
}

function displayNumber(value: number | null, digits = 3) {
  return value === null ? 'N/A' : value.toFixed(digits)
}

function AuditResult({ result }: { result: DeepDive }) {
  const audit = result.structural_audit
  return (
    <div className="flex flex-col gap-space-md">
      <section className="rounded-lg border border-surface-container-highest bg-surface-container p-space-md shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-space-sm">
          <div>
            <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Exact structural audit</p>
            <h2 className="mt-space-2xs font-headline-md text-headline-md font-bold">{audit.verdict}</h2>
          </div>
          <span className="rounded bg-surface-container-high px-space-sm py-space-xs font-code-sm text-code-sm">
            {result.audit_graph_mode}
          </span>
        </div>
        <dl className="mt-space-md grid grid-cols-1 gap-space-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-on-surface-variant">Reason</dt><dd className="font-semibold">{audit.reason || 'N/A'}</dd></div>
          <div><dt className="text-on-surface-variant">Best cut</dt><dd className="font-semibold">{audit.best_cut_label ?? 'N/A'}</dd></div>
          <div><dt className="text-on-surface-variant">Conductance Phi</dt><dd className="font-semibold">{displayNumber(audit.best_cut_phi)}</dd></div>
          <div><dt className="text-on-surface-variant">Balance epsilon</dt><dd className="font-semibold">{displayNumber(audit.epsilon)}</dd></div>
        </dl>
        <p className="mt-space-md text-on-surface-variant">{result.over_merge_narrative}</p>
      </section>

      <AuditGraphVisualization value={result.audit_visualization} />

      <EvidenceAttribution
        result={result.evidence_attribution}
        evaluation={result.evidence_attribution_evaluation}
      />
    </div>
  )
}

export function AuditStructureView({ analysis, job = null, auditVisualization = null, onRunDeepDive }: AuditStructureViewProps) {
  const matchingJob = job?.chain_id === analysis.chain_id ? job : null
  const result = matchingJob?.status === 'SUCCEEDED' ? matchingJob.result : null

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <header className="flex flex-wrap items-center justify-between gap-space-md rounded-lg bg-surface-container-lowest p-space-md shadow-sm">
        <div>
          <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">Tier 2 · on demand</p>
          <h1 className="font-headline-lg text-headline-lg font-bold">Structural Audit · {analysis.chain_id}</h1>
        </div>
        <button
          type="button"
          onClick={onRunDeepDive}
          aria-disabled={!onRunDeepDive}
          disabled={matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'}
          className="rounded bg-secondary-container px-space-md py-space-xs font-semibold text-on-secondary-container disabled:opacity-50"
        >
          {matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'
            ? `Running ${matchingJob.progress_percent}%`
            : 'Run Deep Dive'}
        </button>
      </header>

      {matchingJob?.status === 'FAILED' && (
        <section role="alert" className="rounded-lg border border-error bg-error-container p-space-md text-error">
          Deep Dive failed · {matchingJob.error ?? 'UNKNOWN_ERROR'}
        </section>
      )}
      {!result && matchingJob?.status !== 'FAILED' && (
        <section role="status" className="rounded-lg border border-surface-container-highest bg-surface-container p-space-xl text-center">
          <h2 className="font-headline-md text-headline-md font-bold">Structural Audit unavailable</h2>
          <p className="mt-space-xs text-on-surface-variant">
            {matchingJob ? 'The explicit Deep Dive job has not completed.' : 'No compatible Deep Dive result is loaded for this chain.'}
          </p>
        </section>
      )}
      {!result && auditVisualization?.chain_id === analysis.chain_id && (
        <AuditGraphVisualization value={auditVisualization.visualization} />
      )}
      {result && <AuditResult result={result} />}
    </div>
  )
}
