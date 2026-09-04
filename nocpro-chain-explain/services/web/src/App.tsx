import { Component, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from 'react'

import { api, ApiError } from './api'
import { duration, humanize, percent } from './format'
import { TopologyHypotheses } from './TopologyHypotheses'
import { EvidenceAttribution } from './EvidenceAttribution'
import { CounterfactualReview } from './CounterfactualReview'
import { EvolutionPanel } from './EvolutionPanel'
import { ChainTree } from './ChainTree'
import { TopologyTree, type TopologyTreePayload } from './TopologyTree'
import { AIAdvisorPanel } from './AIAdvisorPanel'
import type { ChainAnalysis, ChainList, Job, Member, PairEvidence, PairWhy } from './types'
import './App.css'

type Tab = 'tree' | 'members' | 'why' | 'topology' | 'structure' | 'review' | 'evolution' | 'ai'
type EvidenceLayer = 'ALL' | PairEvidence['provenance_class']

const tabs: Array<{ id: Tab; label: string; eyebrow: string }> = [
  { id: 'tree', label: 'Chain Tree', eyebrow: 'Hierarchy' },
  { id: 'members', label: 'All Alarms', eyebrow: 'Table' },
  { id: 'why', label: 'Why Grouped', eyebrow: 'Tier 1B' },
  { id: 'structure', label: 'Structure', eyebrow: 'Tier 2' },
  { id: 'topology', label: 'Topology', eyebrow: 'Source view' },
  { id: 'review', label: 'Review', eyebrow: 'What-if' },
  { id: 'evolution', label: 'Evolution', eyebrow: 'Snapshots' },
  { id: 'ai', label: 'AI Advisor', eyebrow: 'Mistral-Large' },
]

const evidenceLayers: Array<{ id: EvidenceLayer; label: string }> = [
  { id: 'ALL', label: 'All evidence' },
  { id: 'SYSTEM_FACT', label: 'System fact' },
  { id: 'BEHAVIORAL', label: 'Behavioral' },
  { id: 'EXTERNAL_OPERATIONAL', label: 'Operational' },
  { id: 'POST_HOC', label: 'Post-hoc' },
]

function Icon({ name }: { name: 'pulse' | 'search' | 'upload' | 'arrow' }) {
  const paths = {
    pulse: <path d="M2 12h4l2.2-7 4 14L15 9l2 3h5" />,
    search: <><circle cx="11" cy="11" r="7" /><path d="m16 16 5 5" /></>,
    upload: <><path d="M12 16V3m0 0L7 8m5-5 5 5" /><path d="M4 14v6h16v-6" /></>,
    arrow: <><path d="M5 12h14" /><path d="m14 7 5 5-5 5" /></>,
  }
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}

function statusTone(value: string) {
  if (['SUPPORT', 'CORE', 'SUCCEEDED', 'EXACT_INDEXED'].includes(value)) return 'positive'
  if (['UNAVAILABLE', 'INSUFFICIENT_DATA', 'SKIPPED_SMALL_CHAIN'].includes(value)) return 'muted'
  if (['FAILED', 'WEAK', 'STRONG'].includes(value)) return 'negative'
  return 'neutral'
}

function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill pill--${tone}`}>{children}</span>
}

class ErrorBoundary extends Component<{ children: ReactNode; fallbackTitle?: string }, { hasError: boolean; error: Error | null }> {
  constructor(props: { children: ReactNode; fallbackTitle?: string }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('UI Render Error caught by boundary:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <section className="error-banner" style={{ margin: '1rem 0' }}>
          <strong>{this.props.fallbackTitle ?? 'An error occurred while rendering this section.'}</strong>
          <p style={{ margin: '0.5rem 0 0', fontSize: '0.75rem', fontFamily: 'var(--mono)' }}>
            {this.state.error?.message ?? 'Unknown rendering error'}
          </p>
          <button
            className="primary-action"
            style={{ marginTop: '0.75rem', padding: '0.4rem 0.8rem', minHeight: 'auto' }}
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Retry
          </button>
        </section>
      )
    }
    return this.props.children
  }
}

function EmptyWorkspace({ apiStatus, loading, error, onUpload }: {
  apiStatus: string
  loading: boolean
  error: string | null
  onUpload: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <main className="empty-workspace">
      <div className="empty-grid" aria-hidden="true" />
      <section className="empty-card">
        <div className="signal-mark"><Icon name="pulse" /></div>
        <p className="kicker">NocPro explanation workspace</p>
        <h1>Trace the reason,<br /><em>not just the alarm.</em></h1>
        <p className="lede">Load one canonical Input Contract package. Statistical truth stays indexed; pair evidence is evaluated only when you ask WHY.</p>
        <input ref={input} className="visually-hidden" type="file" accept="application/json,.json" onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(file)
          event.target.value = ''
        }} />
        <button className="primary-action" onClick={() => input.current?.click()} disabled={loading}>
          <Icon name="upload" /> {loading ? 'Indexing snapshot…' : 'Load snapshot package'}
        </button>
        {error && <p className="error-banner" role="alert">{error}</p>}
        <div className="connection-line">
          <span className={`connection-dot connection-dot--${apiStatus}`} /> API {apiStatus}
          <span>•</span> Incremental production mode disabled
        </div>
      </section>
    </main>
  )
}

function MemberInspectorCard({
  member,
  onClose,
  onToggleCompare,
  isCompared,
}: {
  member: Member
  onClose: () => void
  onToggleCompare: () => void
  isCompared: boolean
}) {
  return (
    <aside className="evidence-rail member-inspector-rail" aria-label="Alarm Details">
      <div className="rail-top-bar">
        <div>
          <p className="kicker">Selected Alarm</p>
          <h2 style={{ fontSize: '1.1rem' }}>{member.alarm_name || member.alarm_id}</h2>
        </div>
        <button type="button" className="close-rail-btn" onClick={onClose} aria-label="Close inspector">
          ×
        </button>
      </div>

      <div className="inspector-meta-row">
        <Pill tone={statusTone(member.role)}>{member.role}</Pill>
        {member.device_code && <Pill>{member.device_code}</Pill>}
        {member.node_reference && <Pill>{member.node_reference}</Pill>}
      </div>

      <div className="system-card" style={{ marginTop: '0.8rem' }}>
        <span>Alarm Identifier</span>
        <strong style={{ fontFamily: 'var(--mono)', fontSize: '0.9rem' }}>{member.alarm_id}</strong>
        {member.canonical_start_time && (
          <small>Event Start: {member.canonical_start_time}</small>
        )}
      </div>

      <dl className="mini-grid" style={{ margin: '0.8rem 0' }}>
        <div>
          <dt>membership support</dt>
          <dd>{percent(member.membership_support)}</dd>
        </div>
        <div>
          <dt>availability coverage</dt>
          <dd>{percent(member.availability_coverage)}</dd>
        </div>
        <div>
          <dt>computable groups</dt>
          <dd>{member.computable_groups}</dd>
        </div>
        <div>
          <dt>representativeness</dt>
          <dd>{member.representativeness != null ? percent(member.representativeness) : '—'}</dd>
        </div>
      </dl>

      {member.failure_domains && member.failure_domains.length > 0 && (
        <div className="inspector-block">
          <span className="kicker" style={{ fontSize: '0.65rem' }}>Failure Domains</span>
          <div className="tag-list">
            {member.failure_domains.map((fd) => (
              <span key={fd} className="pill pill--neutral" style={{ fontSize: '0.72rem' }}>{fd}</span>
            ))}
          </div>
        </div>
      )}

      {member.group_fits && member.group_fits.length > 0 && (
        <div className="inspector-block" style={{ marginTop: '0.75rem' }}>
          <span className="kicker" style={{ fontSize: '0.65rem' }}>Group Fit</span>
          <div className="group-fit-table">
            {member.group_fits.map((gf, idx) => (
              <div key={idx} className="group-fit-row">
                <span>{gf.derivation_tag}</span>
                <strong>{gf.fit != null ? percent(gf.fit) : '⊥'}</strong>
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        className={`primary-action ${isCompared ? 'inspector-btn-active' : ''}`}
        onClick={onToggleCompare}
        style={{ marginTop: '1rem', width: '100%' }}
      >
        {isCompared ? '✓ Selected for Pair WHY' : '+ Compare with Another Alarm'}
      </button>
    </aside>
  )
}

function PairEvidenceRail({ selected, pair, loading, layer, onClose, onClear }: {
  selected: string[]
  pair: PairWhy | null
  loading: boolean
  layer: EvidenceLayer
  onClose: () => void
  onClear: () => void
}) {
  const visible = pair?.evidence.filter((item) => layer === 'ALL' || item.provenance_class === layer) ?? []

  return (
    <aside className="evidence-rail" aria-label="Pair Evidence Rail">
      <div className="rail-top-bar">
        <div>
          <p className="kicker">Pair WHY Comparison</p>
          <h2 style={{ fontSize: '1rem' }}>{selected[0]} ↔ {selected[1]}</h2>
        </div>
        <div className="rail-top-actions">
          <button type="button" className="text-action-btn" onClick={onClear}>Clear</button>
          <button type="button" className="close-rail-btn" onClick={onClose} aria-label="Close pair comparison">×</button>
        </div>
      </div>

      <div className="system-card" style={{ margin: '0.75rem 0' }}>
        <span>System Fact Assessment</span>
        <strong>{pair?.system_fact.status ?? 'EVALUATING'}</strong>
        <small>{pair?.system_fact.semantic ?? 'Evaluating pair relationship…'}</small>
      </div>

      <div className="rail-evidence-subheading">
        <span className="kicker" style={{ margin: 0 }}>
          {loading ? 'Evaluating evidence…' : `${visible.length} evidence channels`}
        </span>
      </div>

      <div className="evidence-list">
        {visible.map((item, index) => (
          <article className="evidence-item" key={`${item.provider_id ?? item.channel_family}-${index}`}>
            <div className="evidence-spine"><span>{String(index + 1).padStart(2, '0')}</span></div>
            <div>
              <div className="evidence-title">
                <strong>{item.channel_family}</strong>
                <Pill tone={statusTone(item.state)}>{item.state}</Pill>
              </div>
              {item.dependency_semantic && <p>{humanize(item.dependency_semantic)}</p>}
              <dl className="mini-grid">
                <div><dt>score</dt><dd>{percent(item.score)}</dd></div>
                <div><dt>{item.threshold == null ? 'support gate' : 'threshold'}</dt><dd>{item.threshold == null ? 'strictly positive' : percent(item.threshold)}</dd></div>
              </dl>
              <small>{item.derivation_tag}</small>
              {item.channel_family === 'H' && item.evidence_metadata && (
                <small>history model · {String(item.evidence_metadata.history_model_id ?? 'UNAVAILABLE')}</small>
              )}
              {item.channel_family === 'T_delay' && item.evidence_metadata && (
                <small>observed delay {String(item.evidence_metadata.delay_seconds ?? 'UNAVAILABLE')}s</small>
              )}
              {item.detail && <p className="evidence-detail">{item.detail}</p>}
            </div>
          </article>
        ))}
        {!loading && pair && visible.length === 0 && (
          <p className="rail-intro">No channel belongs to this evidence layer.</p>
        )}
      </div>
    </aside>
  )
}

function WhyPanel({ analysis }: { analysis: ChainAnalysis }) {
  return (
    <div className="why-grid">
      <section className="descriptor-panel">
        <header className="section-heading"><div><p className="kicker">Explanation predicates</p><h2>What defines this chain</h2></div><span>{analysis.descriptors.length} selected</span></header>
        <div className="descriptor-list">
          {analysis.descriptors.map((descriptor) => (
            <article key={`${descriptor.kind}-${descriptor.label}`}>
              <div><Pill>{descriptor.kind}</Pill><strong>{descriptor.label}</strong></div>
              <dl className="metric-row"><div><dt>coverage</dt><dd>{percent(descriptor.coverage)}</dd></div><div><dt>precision</dt><dd>{percent(descriptor.precision_global)}</dd></div><div><dt>local</dt><dd>{percent(descriptor.precision_local)}</dd></div><div><dt>lift</dt><dd>{descriptor.lift?.toFixed(2) ?? '⊥'}</dd></div></dl>
            </article>
          ))}
        </div>
      </section>
      <section className="role-panel">
        <header className="section-heading"><div><p className="kicker">Membership verdict</p><h2>Role distribution</h2></div></header>
        <div className="role-bars">
          {Object.entries(analysis.role_counts).map(([role, count]) => (
            <div key={role}><span>{humanize(role)}</span><div><i style={{ width: `${Math.max(4, (count / analysis.member_count) * 100)}%` }} /></div><strong>{count}</strong></div>
          ))}
        </div>
        <div className="config-note"><span>Exact statistics</span><strong>{analysis.statistics_mode}</strong><span>Audit graph</span><strong>{analysis.audit_graph_mode}</strong><span>Config</span><strong>{analysis.config_version}</strong></div>
      </section>
    </div>
  )
}

function MemberTable({ members, selected, onSelect, onInspect }: {
  members: Member[]
  selected: string[]
  onSelect: (member: Member) => void
  onInspect: (member: Member) => void
}) {
  return (
    <section className="table-card">
      <header className="section-heading">
        <div><p className="kicker">Tabular list</p><h2>Member diagnostics</h2></div>
        <span>Click row to inspect · Check to compare</span>
      </header>
      <div className="member-table" role="table">
        <div className="table-row table-head" role="row">
          <span>Compare</span>
          <span>ID / alarm</span>
          <span>device</span>
          <span>role</span>
          <span>support</span>
          <span>coverage</span>
          <span>groups</span>
        </div>
        {members.map((member) => {
          const isSelected = selected.includes(member.alarm_id)
          return (
            <div
              className={`table-row ${isSelected ? 'is-selected' : ''}`}
              role="row"
              key={member.alarm_id}
              onClick={() => onInspect(member)}
              style={{ cursor: 'pointer' }}
            >
              <span>
                <button
                  type="button"
                  className={`node-compare-btn ${isSelected ? 'is-active' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onSelect(member)
                  }}
                  style={{ minWidth: '60px' }}
                >
                  {isSelected ? '✓' : '+'}
                </button>
              </span>
              <span><strong>{member.alarm_id}</strong><small>{member.alarm_name ?? 'unnamed alarm'}</small></span>
              <span>{member.device_code ?? '⊥'}<small>{member.node_reference ?? 'unmapped'}</small></span>
              <span><Pill tone={statusTone(member.role)}>{member.role}</Pill></span>
              <span>{percent(member.membership_support)}</span>
              <span>{percent(member.availability_coverage)}</span>
              <span>{member.computable_groups}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function StructurePanel({ job, onRun, submitting }: { job: Job | null; onRun: () => void; submitting: boolean }) {
  const result = job?.result
  return (
    <section className="structure-card">
      <div className="structure-copy"><p className="kicker">Tier 2 · structural audit</p><h2>Materialize only when the question needs it.</h2><p>Conductance, over-merge evidence and similar-chain search run behind a versioned asynchronous job boundary.</p><button className="primary-action" onClick={onRun} disabled={submitting || job?.status === 'RUNNING'}>{submitting ? 'Submitting…' : job?.status === 'RUNNING' ? `Running · ${job.progress_percent}%` : 'Run deep dive'} <Icon name="arrow" /></button></div>
      <div className="audit-result">
        {!job && <div className="audit-empty"><span>G*</span><p>Audit graph not computed</p></div>}
        {job && !result && <div className="audit-empty"><span>{job.progress_percent}%</span><p>{job.status}</p>{job.error && <small>{job.error}</small>}</div>}
        {result && <>
          <div className="audit-verdict"><Pill tone={statusTone(result.structural_audit.verdict)}>{result.structural_audit.verdict}</Pill><strong>{result.audit_graph_mode}</strong></div>
          <p>{result.structural_audit.reason}</p>
          <dl className="metric-row"><div><dt>best cut</dt><dd>{result.structural_audit.best_cut_label ?? 'none'}</dd></div><div><dt>conductance</dt><dd>{result.structural_audit.best_cut_phi?.toFixed(3) ?? '⊥'}</dd></div><div><dt>over-merge</dt><dd>{humanize(result.over_merge_strength)}</dd></div></dl>
          <p className="audit-narrative">{result.over_merge_narrative}</p>
          {result.evidence_attribution && (
            <EvidenceAttribution
              result={result.evidence_attribution}
              evaluation={result.evidence_attribution_evaluation}
            />
          )}
          <section className="similar-results" aria-label="Similar chains">
            <header><div><p className="kicker">Different incidents</p><h3>Similar chains</h3></div><Pill tone={statusTone(result.similarity_status)}>{result.similarity_status}</Pill></header>
            {result.similarity_status === 'UNAVAILABLE' ? (
              <p className="similar-empty">{humanize(result.similarity_unavailable_reason ?? 'LINEAGE_NOT_READY')}</p>
            ) : <>
              <dl className="similar-model">
                <div><dt>model</dt><dd>{result.similarity_model_version ?? '⊥'}</dd></div>
                <div><dt>history cutoff</dt><dd>{result.similarity_trained_until_exclusive ?? '⊥'}</dd></div>
                <div><dt>corpus</dt><dd>{result.similarity_corpus_policy ?? '⊥'}</dd></div>
                <div><dt>updates</dt><dd>{result.similarity_model_update_policy ?? '⊥'}</dd></div>
              </dl>
              <div className="taxonomy-capability">
                <span>Alarm taxonomy</span><Pill tone={statusTone(result.taxonomy_status ?? 'UNAVAILABLE')}>{result.taxonomy_status ?? 'UNAVAILABLE'}</Pill>
                {result.taxonomy_reason && <small>{humanize(result.taxonomy_reason)}</small>}
                <small>Active basis: {result.active_fingerprint_blocks.map(humanize).join(', ') || 'none'}</small>
              </div>
              <div className="similar-list">
                {result.similar_chains.map((item, index) => <article key={`${item.chain_id}-${index}`}>
                  <div><strong>{item.chain_id}</strong><span>{percent(item.similarity)}</span></div>
                  <small>Basis {item.compared_blocks.length}/5: {item.compared_blocks.map(humanize).join(', ') || 'none'}</small>
                </article>)}
                {result.similar_chains.length === 0 && <p className="similar-empty">No eligible different incident exists before this snapshot.</p>}
              </div>
            </>}
          </section>
        </>}
      </div>
    </section>
  )
}

function App() {
  const [apiStatus, setApiStatus] = useState('checking')
  const [chainList, setChainList] = useState<ChainList | null>(null)
  const [chainId, setChainId] = useState('')
  const [analysis, setAnalysis] = useState<ChainAnalysis | null>(null)
  const [loadingSnapshot, setLoadingSnapshot] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<Tab>('tree')
  const [layer, setLayer] = useState<EvidenceLayer>('ALL')
  const [selectedMembers, setSelectedMembers] = useState<string[]>([])
  const [inspectMember, setInspectMember] = useState<Member | null>(null)
  const [pairWhy, setPairWhy] = useState<PairWhy | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [topologyProfile, setTopologyProfile] = useState<'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'>('IT_SERVICES')
  const [topologyPayload, setTopologyPayload] = useState<TopologyTreePayload | null>(null)
  const [topologyRootId, setTopologyRootId] = useState<string | undefined>(undefined)

  useEffect(() => {
    const controller = new AbortController()
    async function connect() {
      try {
        await api.health(controller.signal)
        setApiStatus('online')
        try {
          const existing = await api.chains(controller.signal)
          setChainList(existing)
          setChainId(existing.chains[0]?.chain_id ?? '')
        } catch (cause) {
          if (!(cause instanceof ApiError && cause.status === 409)) throw cause
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setApiStatus('offline')
          setError(cause instanceof Error ? cause.message : 'API unavailable')
        }
      }
    }
    void connect()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!chainId) return
    const controller = new AbortController()
    api.analysis(chainId, controller.signal).then(setAnalysis).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Analysis failed')
    })
    return () => controller.abort()
  }, [chainId])

  useEffect(() => {
    if (selectedMembers.length !== 2 || !chainId) return
    const controller = new AbortController()
    api.pairWhy(chainId, selectedMembers[0], selectedMembers[1], controller.signal).then(setPairWhy).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Pair evaluation failed')
    })
    return () => controller.abort()
  }, [chainId, selectedMembers])

  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.job(job.job_id, controller.signal).then(setJob).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Job polling failed')
      })
    }, 450)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [job])

  useEffect(() => {
    if (tab !== 'topology') return
    const controller = new AbortController()
    setTopologyPayload(null)
    setTopologyPayload(null)
    api.topologyProjection(topologyProfile, controller.signal, topologyRootId).then(setTopologyPayload).catch((cause: unknown) => {
      if (!controller.signal.aborted) setTopologyPayload({
        status: 'UNAVAILABLE', profile: topologyProfile, topology_kind: 'UNAVAILABLE',
        reason: cause instanceof Error ? cause.message : 'TOPOLOGY_PROJECTION_UNAVAILABLE',
      })
    })
    return () => controller.abort()
  }, [tab, topologyProfile, topologyRootId])

  const filteredChains = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return chainList?.chains ?? []
    return chainList?.chains.filter((chain) => `${chain.chain_id} ${chain.title}`.toLowerCase().includes(query)) ?? []
  }, [chainList, search])

  async function uploadSnapshot(file: File) {
    setLoadingSnapshot(true)
    setError(null)
    try {
      const payload = JSON.parse(await file.text()) as unknown
      await api.loadSnapshot(payload)
      const chains = await api.chains()
      setChainList(chains)
      setChainId(chains.chains[0]?.chain_id ?? '')
      setSelectedMembers([])
      setInspectMember(null)
      setPairWhy(null)
      setJob(null)
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    } finally {
      setLoadingSnapshot(false)
    }
  }

  function toggleSelectMember(member: Member) {
    setSelectedMembers((current) => {
      if (current.includes(member.alarm_id)) return current.filter((id) => id !== member.alarm_id)
      if (current.length >= 2) return [current[1], member.alarm_id]
      return [...current, member.alarm_id]
    })
  }

  function handleInspectMember(member: Member) {
    setInspectMember((prev) => (prev?.alarm_id === member.alarm_id ? null : member))
  }

  async function runDeepDive() {
    if (!chainId) return
    setSubmitting(true)
    setError(null)
    try {
      const submission = await api.submitDeepDive(chainId)
      setJob(await api.job(submission.job_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Deep dive failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (!chainList) return <EmptyWorkspace apiStatus={apiStatus} loading={loadingSnapshot} error={error} onUpload={(file) => void uploadSnapshot(file)} />

  const pairMatchesSelection = pairWhy != null
    && pairWhy.chain_id === chainId
    && pairWhy.alarm_id_a === selectedMembers[0]
    && pairWhy.alarm_id_b === selectedMembers[1]
  const visiblePair = pairMatchesSelection ? pairWhy : null
  const visibleJob = job?.chain_id === chainId ? job : null

  // Determine whether inspector side panel is visible
  const isPairActive = selectedMembers.length === 2
  const showSidePanel = isPairActive || inspectMember !== null

  return (
    <div className="app-shell">
      {/* Clean, Modern Top Bar */}
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NocPro Chain Explain home">
          <span><Icon name="pulse" /></span>
          <strong>NocPro</strong>
          <i>Chain Explain</i>
        </a>

        <div className="topbar-center">
          <div className="chain-selector-pill">
            <label className="chain-search" title="Filter chains list">
              <Icon name="search" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter…" aria-label="Filter chains" />
            </label>
            <select
              value={chainId}
              onChange={(event) => {
                setSelectedMembers([])
                setInspectMember(null)
                setPairWhy(null)
                setJob(null)
                setError(null)
                setChainId(event.target.value)
              }}
              aria-label="Select alarm chain"
            >
              {filteredChains.map((chain) => (
                <option value={chain.chain_id} key={chain.chain_id}>
                  {chain.chain_id} · {chain.member_count} alarms ({chain.title})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="topbar-actions">
          <div className="snapshot-chip">
            <span className="connection-dot connection-dot--online" />
            <span>{chainList.snapshot_id}</span>
          </div>
          <label className="upload-compact" title="Load another snapshot JSON file">
            <input
              type="file"
              accept="application/json,.json"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void uploadSnapshot(file)
                event.target.value = ''
              }}
            />
            <Icon name="upload" />
            <span>Load JSON</span>
          </label>
        </div>
      </header>

      {/* Clean Tab Bar */}
      <nav className="tabbar" aria-label="Analysis views">
        <div className="tabbar-items">
          {tabs.map((item) => (
            <button
              key={item.id}
              className={`tab-btn-item ${tab === item.id ? 'is-active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              <small>{item.eyebrow}</small>
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        <div className="layer-switcher">
          <label htmlFor="layer">Evidence</label>
          <select id="layer" value={layer} onChange={(event) => setLayer(event.target.value as EvidenceLayer)}>
            {evidenceLayers.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
          </select>
        </div>
      </nav>

      {/* Comparison floating hint if 1 member selected */}
      {selectedMembers.length === 1 && (
        <aside className="comparison-hint-banner" aria-label="Pair selection status">
          <span>
            Selected <strong>{selectedMembers[0]}</strong>. Click <code>+ Compare</code> on another alarm in the tree to view Pair WHY.
          </span>
          <button type="button" className="text-action-btn" onClick={() => setSelectedMembers([])}>
            Cancel selection
          </button>
        </aside>
      )}

      {error && (
        <div className="error-banner workspace-error" role="alert">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {!analysis || analysis.chain_id !== chainId ? (
        <main className="loading-state">
          <span />
          <p>Computing exact indexed statistics…</p>
        </main>
      ) : (
        <main className="workspace" id="top">
          {/* Streamlined Chain Summary */}
          <section className="chain-hero-compact">
            <div className="chain-hero-info">
              <div className="chain-hero-badges">
                <span className="hero-id-tag">Chain {analysis.chain_id}</span>
                <Pill tone={analysis.singleton ? 'muted' : 'positive'}>
                  {analysis.member_count} {analysis.member_count === 1 ? 'alarm' : 'alarms'}
                </Pill>
                <Pill tone="neutral">{analysis.singleton ? 'Singleton' : 'Correlated Cluster'}</Pill>
                <Pill tone="muted">{analysis.graybox.mode}</Pill>
              </div>
              <h1 className="chain-hero-title">{analysis.title}</h1>
            </div>

            <div className="chain-hero-kpis">
              <div className="kpi-block">
                <span>Total Duration</span>
                <strong>{duration(Object.values(analysis.phase_durations).reduce((sum, value) => sum + value, 0))}</strong>
              </div>
              <div className="kpi-block">
                <span>Statistical Mode</span>
                <strong>{humanize(analysis.statistics_mode)}</strong>
              </div>
              <div className="kpi-block">
                <span>Active Basis</span>
                <strong>{humanize(analysis.pair_materialization)}</strong>
              </div>
            </div>
          </section>

          {/* Main Layout Grid (Expands to full width when side panel is closed!) */}
          <div className={`workspace-layout ${showSidePanel ? 'has-side-panel' : 'is-full-width'}`}>
            <div className="main-content-column">
              <ErrorBoundary fallbackTitle="Could not display tab contents">
                {tab === 'tree' && (
                  <ChainTree
                    members={analysis.members}
                    selectedMembers={selectedMembers}
                    activeInspectId={inspectMember?.alarm_id}
                    onSelectMember={toggleSelectMember}
                    onInspectMember={handleInspectMember}
                  />
                )}
                {tab === 'members' && (
                  <MemberTable
                    members={analysis.members}
                    selected={selectedMembers}
                    onSelect={toggleSelectMember}
                    onInspect={handleInspectMember}
                  />
                )}
                {tab === 'why' && <WhyPanel analysis={analysis} />}
                {tab === 'structure' && (
                  <>
                    <StructurePanel job={visibleJob} onRun={() => void runDeepDive()} submitting={submitting} />
                    {visibleJob?.result?.topology_hypotheses && (
                      <TopologyHypotheses topology_hypotheses={visibleJob.result.topology_hypotheses} />
                    )}
                  </>
                )}
                {tab === 'topology' && (
                  <section className="topology-workspace">
                    <header className="topology-workspace-header">
                      <div>
                        <p className="kicker">Read-only source navigation</p>
                        <h2>Topology records</h2>
                      </div>
                      <label>
                        Dataset profile
                        <select value={topologyProfile} onChange={(event) => {
                          setTopologyProfile(event.target.value as typeof topologyProfile)
                          setTopologyRootId(undefined)
                        }}>
                          <option value="ALARM_ONLY">Alarm-only</option>
                          <option value="IP_NETWORK">IP network</option>
                          <option value="IT_SERVICES">IT services</option>
                        </select>
                      </label>
                    </header>
                    {topologyPayload ? (
                      <TopologyTree
                        key={topologyPayload.status === 'AVAILABLE'
                          ? topologyPayload.profile + ':' + topologyPayload.source_version + ':' + topologyPayload.tree.resource_id
                          : topologyPayload.profile + ':' + topologyPayload.reason}
                        payload={topologyPayload}
                        onSearchSource={(query) => api.topologySearch(topologyProfile, query)}
                        onRootChange={setTopologyRootId}
                      />
                    ) : (
                      <div className="loading-state">
                        <span />
                        <p>Loading bounded topology projection…</p>
                      </div>
                    )}
                  </section>
                )}
                {tab === 'review' && <CounterfactualReview key={chainId} chainId={chainId} />}
                {tab === 'evolution' && <EvolutionPanel chainId={chainId} />}
                {tab === 'ai' && <AIAdvisorPanel key={chainId} chainId={chainId} />}
              </ErrorBoundary>
            </div>

            {/* Sliding Context-Aware Inspector Side Panel */}
            {showSidePanel && (
              <div className="side-inspector-drawer">
                {isPairActive ? (
                  <PairEvidenceRail
                    selected={selectedMembers}
                    pair={visiblePair}
                    loading={selectedMembers.length === 2 && !pairMatchesSelection}
                    layer={layer}
                    onClose={() => setSelectedMembers([])}
                    onClear={() => setSelectedMembers([])}
                  />
                ) : (
                  inspectMember && (
                    <MemberInspectorCard
                      member={inspectMember}
                      onClose={() => setInspectMember(null)}
                      onToggleCompare={() => toggleSelectMember(inspectMember)}
                      isCompared={selectedMembers.includes(inspectMember.alarm_id)}
                    />
                  )
                )}
              </div>
            )}
          </div>
        </main>
      )}
    </div>
  )
}

export default App
