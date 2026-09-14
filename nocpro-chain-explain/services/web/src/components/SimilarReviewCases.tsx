import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SimilarCaseRetrievalResult, SimilarReviewCase } from '../types'

interface SimilarReviewCasesProps {
  jobId: string
  candidateId: string | null
}

function CaseCard({ c }: { c: SimilarReviewCase }) {
  const pct = Math.round(c.similarity_score * 100)
  const decisionColor =
    c.decision === 'APPROVE' || c.decision === 'APPROVED'
      ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50'
      : c.decision === 'REJECT' || c.decision === 'REJECTED'
      ? 'bg-rose-900/60 text-rose-300 border-rose-700/50'
      : 'bg-amber-900/60 text-amber-300 border-amber-700/50'

  return (
    <div className="bg-slate-800/70 border border-slate-700/50 rounded-lg p-3 hover:border-slate-600 transition-colors">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold border ${decisionColor}`}>
            {c.decision}
          </span>
          <span className="text-xs text-slate-400 font-mono">
            {c.case_id.slice(0, 16)}
          </span>
          {c.lineage_component_id && (
            <span className="text-[10px] font-mono bg-indigo-950/80 text-indigo-300 border border-indigo-800/60 px-1.5 py-0.5 rounded">
              {c.lineage_component_id.slice(0, 12)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-cyan-400">
            {pct}% Match
          </span>
          <span className="text-[11px] text-slate-400 bg-slate-900/80 px-1.5 py-0.5 rounded">
            {c.common_block_count}/5 blocks
          </span>
        </div>
      </div>

      {/* Block Breakdown */}
      {c.block_scores && Object.keys(c.block_scores).length > 0 && (
        <div className="mt-2 grid grid-cols-5 gap-1.5 text-[11px]">
          {Object.entries(c.block_scores).map(([block, rawScore]) => {
            const numScore =
              typeof rawScore === 'object' && rawScore !== null
                ? rawScore.status === 'AVAILABLE'
                  ? rawScore.score
                  : null
                : typeof rawScore === 'number'
                ? rawScore
                : null
            const isScoreAvailable = numScore !== null && typeof numScore === 'number'
            const blockPct = isScoreAvailable ? Math.round(numScore * 100) : null
            const label = block.replace('_shape', '').replace('_context', '').replace('_pattern', '')
            return (
              <div
                key={block}
                className="bg-slate-900/80 rounded px-1.5 py-1 text-center border border-slate-800"
                title={isScoreAvailable ? `${block}: ${(numScore * 100).toFixed(1)}%` : `${block}: Unobserved (Excluded)`}
              >
                <div className="text-[9px] uppercase tracking-wider text-slate-400 truncate">
                  {label}
                </div>
                <div
                  className={`font-mono font-medium ${
                    !isScoreAvailable
                      ? 'text-slate-500'
                      : blockPct! > 70
                      ? 'text-emerald-400'
                      : blockPct! > 30
                      ? 'text-amber-400'
                      : 'text-slate-400'
                  }`}
                >
                  {isScoreAvailable ? `${blockPct}%` : '—'}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function SimilarReviewCases({ jobId, candidateId }: SimilarReviewCasesProps) {
  const [state, setState] = useState<{
    key: string
    result: SimilarCaseRetrievalResult | null
    loading: boolean
    error: string | null
  }>({
    key: '',
    result: null,
    loading: false,
    error: null,
  })

  const currentKey = `${jobId ?? ''}:${candidateId ?? ''}`
  const isStale = state.key !== currentKey
  const retrievalResult = isStale ? null : state.result
  const loading = isStale ? Boolean(jobId && candidateId) : state.loading
  const error = isStale ? null : state.error

  useEffect(() => {
    if (!jobId || !candidateId) return

    const controller = new AbortController()
    api.similarCases(jobId, candidateId, 5, controller.signal)
      .then((data) => {
        setState({
          key: currentKey,
          result: data,
          loading: false,
          error: null,
        })
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState({
          key: currentKey,
          result: null,
          loading: false,
          error: err instanceof Error ? err.message : 'Failed to retrieve similar cases',
        })
      })

    return () => controller.abort()
  }, [jobId, candidateId, currentKey])

  if (!candidateId) return null

  const isUnavailable = retrievalResult?.retrieval_status === 'UNAVAILABLE'
  const crossCases = retrievalResult?.cross_incident_cases ?? []
  const lineageCases = retrievalResult?.same_lineage_history ?? []
  const totalMatches = crossCases.length + lineageCases.length
  const minSimPct = Math.round((retrievalResult?.min_similarity ?? 0.5) * 100)

  return (
    <div className="similar-cases-panel bg-slate-900 border border-slate-700/60 rounded-xl p-4 mt-4 text-slate-200">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div>
          <h4 className="text-sm font-semibold tracking-wide text-slate-100 flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                isUnavailable ? 'bg-amber-400' : 'bg-cyan-400 animate-pulse'
              }`}
            ></span>
            Historical Similar Cases (Multi-Block)
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            Deterministic peer matching (threshold &ge; {minSimPct}%, min 3 common blocks)
          </p>
        </div>
        <span
          className={`text-xs font-mono px-2 py-1 rounded ${
            isUnavailable
              ? 'bg-amber-950 text-amber-300 border border-amber-800/60'
              : 'bg-slate-800 text-cyan-300'
          }`}
        >
          {isUnavailable ? 'ABSTAINED' : `${totalMatches} Match${totalMatches === 1 ? '' : 'es'}`}
        </span>
      </div>

      {/* Non-probability disclaimer */}
      <div className="mt-3 p-2.5 rounded-lg bg-amber-950/40 border border-amber-800/50 text-amber-300 text-xs flex items-start gap-2">
        <span className="text-sm leading-none font-bold">ℹ</span>
        <span>
          <strong>Disclaimer:</strong> {retrievalResult?.disclaimer || 'Historical reference only — not probability or automated recommendation. Intended solely as peer context for human decision-making.'}
        </span>
      </div>

      {loading && (
        <div className="py-6 text-center text-xs text-slate-400">
          Searching review case store with temporal cutoff...
        </div>
      )}

      {error && (
        <div className="py-3 text-xs text-rose-400">
          {error}
        </div>
      )}

      {/* Structured Abstention View */}
      {!loading && !error && isUnavailable && (
        <div className="mt-3 p-4 rounded-lg bg-slate-800/60 border border-slate-700/60 text-center space-y-1.5">
          <div className="text-xs font-semibold text-amber-300 flex items-center justify-center gap-1.5">
            <span className="material-symbols-outlined text-[16px]">do_not_disturb_on</span>
            Similarity Context Unavailable: Insufficient Common Blocks
          </div>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            Observed {retrievalResult.common_block_count ?? 0} common blocks with historical store (minimum required: {retrievalResult.required_common_block_count ?? 3}). Peer comparison safely abstains to avoid false analogies.
          </p>
        </div>
      )}

      {/* Available but Zero Matches */}
      {!loading && !error && !isUnavailable && totalMatches === 0 && (
        <div className="py-4 text-center text-xs text-slate-400">
          No historical cases found with &ge; 3 common blocks and &ge; {minSimPct}% similarity.
        </div>
      )}

      {/* Matches List */}
      {!loading && !error && !isUnavailable && totalMatches > 0 && (
        <div className="mt-3 space-y-4">
          {/* 1. Independent Cross-Incident Cases */}
          {crossCases.length > 0 && (
            <div className="space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                <span>Cross-Incident Precedents</span>
                <span className="text-slate-500 font-normal">{crossCases.length}</span>
              </div>
              <div className="space-y-2">
                {crossCases.map((c) => (
                  <CaseCard key={c.case_id} c={c} />
                ))}
              </div>
            </div>
          )}

          {/* 2. Same-Lineage History (Separated from independent precedents) */}
          {lineageCases.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-slate-800">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-indigo-400 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
                  Same Lineage / Incident History
                </span>
                <span className="text-indigo-400/80 font-normal">{lineageCases.length}</span>
              </div>
              <div className="space-y-2">
                {lineageCases.map((c) => (
                  <CaseCard key={c.case_id} c={c} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
