import { EvidenceAttribution } from '../EvidenceAttribution'
import { AuditGraphVisualization } from '../components/AuditGraphVisualization'
import type { AuditVisualizationArtifact, ChainAnalysis, DeepDive, Job } from '../types'
import { InfoTip } from '../components/InfoTip'

interface AuditStructureViewProps {
  analysis: ChainAnalysis
  snapshotId: string
  snapshotVersion: string
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
  const isDuplicateNarrative =
    !result.over_merge_narrative ||
    (audit.reason &&
      (result.over_merge_narrative.includes(audit.reason) ||
        audit.reason.includes(result.over_merge_narrative) ||
        result.over_merge_narrative.replace(/^Chain\s+[^:]+:\s*/i, '').trim() === audit.reason.trim()))

  return (
    <div className="flex flex-col gap-space-md">
      <section className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#0c1424] shadow-md">
        <div className="h-1 bg-gradient-to-r from-secondary via-primary to-tertiary" />
        <div className="p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[#1b273e]">
            <div>
              <p className="font-label-caps text-xs uppercase tracking-[0.16em] text-secondary font-bold">Kiểm toán cấu trúc đồ thị</p>
              <h2 className="mt-1 font-headline-md text-lg font-bold text-on-surface">{audit.verdict}</h2>
            </div>
            <span className={`rounded-full border px-3 py-1 font-code-sm text-xs font-bold ${verdictTone(audit.verdict)}`}>
              {result.audit_graph_mode}
            </span>
          </div>

          <dl className="mt-4 grid grid-cols-1 overflow-hidden rounded-lg border border-[#1b273e] sm:grid-cols-2 lg:grid-cols-4 bg-[#080d17]">
            <div className="border-b border-[#1b273e] p-3 sm:border-r lg:border-b-0">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Nguyên nhân</dt>
              <dd className="mt-1 break-words font-code-sm text-xs font-semibold text-slate-200">
                {audit.reason || 'N/A'}
              </dd>
            </div>
            <div className="border-b border-[#1b273e] p-3 lg:border-b-0 lg:border-r">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Vết cắt tối ưu</dt>
              <dd className="mt-1 break-words font-code-sm text-xs font-semibold text-slate-200">
                {audit.best_cut_label ?? 'N/A'}
              </dd>
            </div>
            <div className="border-b border-[#1b273e] p-3 sm:border-b-0 sm:border-r">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Độ dẫn Conductance (Φ)</dt>
              <dd className="mt-1 font-code-lg text-lg font-bold text-secondary">
                {displayNumber(audit.best_cut_phi)}
              </dd>
            </div>
            <div className="p-3">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Hệ số cân bằng (ε)</dt>
              <dd className="mt-1 font-code-lg text-lg font-bold text-slate-100">
                {displayNumber(audit.epsilon)}
              </dd>
            </div>
          </dl>

          {!isDuplicateNarrative && (
            <p className="mt-3 border-l-2 border-secondary/60 pl-3 text-xs text-on-surface-variant font-medium">
              {result.over_merge_narrative}
            </p>
          )}
        </div>
      </section>

      <AuditGraphVisualization
        value={result.audit_visualization}
        analysis={analysis}
        verdict={audit.verdict}
        phi={audit.best_cut_phi}
        epsilon={audit.epsilon}
        onRunDeepDive={onRunDeepDive}
      />

      <EvidenceAttribution
        result={result.evidence_attribution}
        evaluation={result.evidence_attribution_evaluation}
      />
    </div>
  )
}

export function AuditStructureView({
  analysis,
  snapshotId,
  snapshotVersion,
  job = null,
  auditVisualization = null,
  onRunDeepDive,
}: AuditStructureViewProps) {
  const matchingJob = (
    job?.chain_id === analysis.chain_id
    && job.snapshot_id === snapshotId
    && job.snapshot_version === snapshotVersion
  ) ? job : null
  const result = matchingJob?.status === 'SUCCEEDED' ? matchingJob.result : null

  return (
    <div className="flex w-full flex-col gap-space-md pb-12 animate-fadeIn">
      <header className="overflow-hidden rounded-xl border border-[#1b273e] bg-[#0c1424] shadow-md">
        <div className="flex flex-wrap items-center justify-between gap-space-sm p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-secondary/15 border border-secondary/30 shadow-sm">
              <span className="material-symbols-outlined text-secondary text-[22px]">account_tree</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <h1 className="font-headline-md text-base font-bold text-on-surface flex items-center gap-2">
                  <span>Kiểm toán Cấu trúc (Structural Audit)</span>
                  <InfoTip text="Kết quả kiểm toán cấu trúc tải từ Deep Dive. Đồ thị trực quan hoá tính gắn kết và vết cắt conductance." />
                </h1>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onRunDeepDive}
            aria-disabled={!onRunDeepDive}
            disabled={matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'}
            className="inline-flex items-center gap-1.5 rounded-lg bg-secondary-container px-3.5 py-1.5 font-semibold text-xs text-on-secondary-container shadow-sm transition-colors hover:bg-secondary-container/80 disabled:opacity-50 cursor-pointer"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[16px]">query_stats</span>
            {matchingJob?.status === 'QUEUED' || matchingJob?.status === 'RUNNING'
              ? `Đang chạy ${matchingJob.progress_percent}%`
              : 'Chạy Deep Dive'}
          </button>
        </div>
      </header>

      {(matchingJob?.status === 'FAILED' || matchingJob?.status === 'INTERRUPTED') && (
        <section role="alert" className="rounded-lg border border-error bg-error-container p-space-md text-error">
          Deep Dive {matchingJob.status === 'INTERRUPTED' ? 'bị gián đoạn' : 'thất bại'} · {matchingJob.error ?? 'LỖI_KHÔNG_XÁC_ĐỊNH'}
        </section>
      )}
      {!result && matchingJob?.status !== 'FAILED' && matchingJob?.status !== 'INTERRUPTED' && !auditVisualization && (
        <section
          role="status"
          className="rounded-xl border border-[#1e2b44] bg-[#0c1424] p-space-md shadow-sm text-xs text-on-surface-variant"
        >
          <span className="sr-only">Structural Audit unavailable. </span>
          {matchingJob
            ? 'Tác vụ Deep Dive chưa hoàn tất.'
            : 'Chưa có kết quả Deep Dive tương thích. Bấm "Chạy Deep Dive" ở trên để tính toán.'}
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
