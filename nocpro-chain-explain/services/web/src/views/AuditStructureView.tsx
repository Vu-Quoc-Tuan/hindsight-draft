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

function verdictTone(verdict: string) {
  if (verdict === 'PASS' || verdict === 'COHESIVE') return 'border-secondary/30 bg-secondary-container/20 text-secondary'
  if (verdict.includes('OVER') || verdict.includes('SPLIT')) return 'border-tertiary/35 bg-tertiary-container/20 text-tertiary'
  return 'border-surface-container-highest bg-surface-container-high text-on-surface'
}

function AuditResult({
  result,
  analysis,
  onRunDeepDive,
}: {
  result: DeepDive
  analysis?: ChainAnalysis
  onRunDeepDive?: () => void
}) {
  const audit = result.structural_audit
  return (
    <div className="flex flex-col gap-space-md">
      <section className="overflow-hidden rounded-xl border border-surface-container-highest bg-surface-container shadow-sm">
        <div className="h-1 bg-gradient-to-r from-secondary via-primary to-tertiary" />
        <div className="p-space-lg">
        <div className="flex flex-wrap items-start justify-between gap-space-sm">
          <div>
            <p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">Exact structural audit</p>
            <h2 className="mt-space-2xs font-headline-md text-headline-md font-bold">{audit.verdict}</h2>
          </div>
          <span className={`rounded-full border px-space-sm py-space-xs font-code-sm text-code-sm font-bold ${verdictTone(audit.verdict)}`}>
            {result.audit_graph_mode}
          </span>
        </div>
        <dl className="mt-space-lg grid grid-cols-1 overflow-hidden rounded-lg border border-surface-container-highest sm:grid-cols-2 lg:grid-cols-4">
          <div className="border-b border-surface-container-highest p-space-md sm:border-r lg:border-b-0"><dt className="font-label-caps text-label-caps uppercase text-on-surface-variant">Reason</dt><dd className="mt-1 break-words font-code-sm font-semibold">{audit.reason || 'N/A'}</dd></div>
          <div className="border-b border-surface-container-highest p-space-md lg:border-b-0 lg:border-r"><dt className="font-label-caps text-label-caps uppercase text-on-surface-variant">Best cut</dt><dd className="mt-1 break-words font-code-sm font-semibold">{audit.best_cut_label ?? 'N/A'}</dd></div>
          <div className="border-b border-surface-container-highest p-space-md sm:border-b-0 sm:border-r"><dt className="font-label-caps text-label-caps uppercase text-on-surface-variant">Conductance Phi</dt><dd className="mt-1 font-code-lg text-xl font-bold text-secondary">{displayNumber(audit.best_cut_phi)}</dd></div>
          <div className="p-space-md"><dt className="font-label-caps text-label-caps uppercase text-on-surface-variant">Balance epsilon</dt><dd className="mt-1 font-code-lg text-xl font-bold">{displayNumber(audit.epsilon)}</dd></div>
        </dl>
        <p className="mt-space-md border-l-2 border-secondary/60 pl-space-md text-on-surface-variant">{result.over_merge_narrative}</p>
        </div>
      </section>

      <AuditGraphVisualization
        value={result.audit_visualization}
        analysis={analysis}
        onRunDeepDive={onRunDeepDive}
      />

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
      <header className="overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-md">
        <div className="flex flex-wrap items-center justify-between gap-space-md p-space-lg">
        <div>
          <p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">Tier 2 · explicit operator action</p>
          <h1 className="mt-1 font-headline-lg text-headline-lg font-bold">Structural Audit · {analysis.chain_id}</h1>
          <p className="mt-space-xs max-w-2xl text-body-sm text-on-surface-variant">Exact structural findings are loaded from the matching persisted Deep Dive. The bounded graph below is visualization-only.</p>
        </div>
        <button
          type="button"
          onClick={onRunDeepDive}
          aria-disabled={!onRunDeepDive}
          disabled={matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'}
          className="inline-flex items-center gap-space-xs rounded bg-secondary-container px-space-md py-space-xs font-semibold text-on-secondary-container shadow-sm transition-colors hover:bg-secondary-container/80 disabled:opacity-50"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[17px]">query_stats</span>
          {matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'
            ? `Running ${matchingJob.progress_percent}%`
            : 'Run Deep Dive'}
        </button>
        </div>
        <div className="grid grid-cols-1 border-t border-surface-container-high sm:grid-cols-3">
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r"><small className="block uppercase tracking-wider text-on-surface-variant">Members</small><strong className="font-code-lg text-lg">{analysis.member_count}</strong></div>
          <div className="border-b border-surface-container-high px-space-md py-space-sm sm:border-b-0 sm:border-r"><small className="block uppercase tracking-wider text-on-surface-variant">Audit graph mode</small><strong className="font-code-sm text-secondary">{analysis.audit_graph_mode}</strong></div>
          <div className="px-space-md py-space-sm"><small className="block uppercase tracking-wider text-on-surface-variant">Analysis config</small><strong className="font-code-sm text-on-surface">{analysis.config_version}</strong></div>
        </div>
      </header>

      {matchingJob?.status === 'FAILED' && (
        <section role="alert" className="rounded-lg border border-error bg-error-container p-space-md text-error">
          Deep Dive failed · {matchingJob.error ?? 'UNKNOWN_ERROR'}
        </section>
      )}
      {!result && matchingJob?.status !== 'FAILED' && (
        <section
          role="status"
          className="rounded-xl border border-[#1e2b44] bg-[#0c1424] p-space-md shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-space-md"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-secondary/15 border border-secondary/30 flex items-center justify-center text-secondary shrink-0">
              <span aria-hidden="true" className="material-symbols-outlined text-[20px]">
                account_tree
              </span>
            </div>
            <div>
              <h2 className="font-headline-md text-sm font-bold text-on-surface">
                Structural Audit unavailable
              </h2>
              <p className="mt-0.5 text-xs text-on-surface-variant">
                {matchingJob
                  ? 'The explicit Deep Dive job has not completed.'
                  : 'No compatible Deep Dive result is loaded for this chain. Run Deep Dive to compute exact Cheeger conductance.'}
              </p>
            </div>
          </div>
          {onRunDeepDive && (
            <button
              type="button"
              onClick={onRunDeepDive}
              disabled={matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'}
              className="inline-flex items-center gap-1.5 rounded-lg bg-secondary px-3.5 py-1.5 font-code-sm text-xs font-bold text-[#070e1d] shadow-sm transition-all hover:bg-secondary/80 disabled:opacity-50 shrink-0 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">query_stats</span>
              <span>
                {matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'
                  ? `Running ${matchingJob.progress_percent}%`
                  : 'Run Deep Dive'}
              </span>
            </button>
          )}
        </section>
      )}
      {!result && auditVisualization?.chain_id === analysis.chain_id && (
        <AuditGraphVisualization
          value={auditVisualization.visualization}
          analysis={analysis}
          onRunDeepDive={onRunDeepDive}
        />
      )}
      {result && (
        <AuditResult
          result={result}
          analysis={analysis}
          onRunDeepDive={onRunDeepDive}
        />
      )}
    </div>
  )
}
