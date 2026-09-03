import { useEffect, useMemo, useRef, useState } from 'react'

import { api, ApiError } from './api'
import { compactTime, duration, humanize, percent } from './format'
import { TopologyHypotheses } from './TopologyHypotheses'
import { EvidenceAttribution } from './EvidenceAttribution'
import { CounterfactualReview } from './CounterfactualReview'
import { EvolutionPanel } from './EvolutionPanel'
import type { ChainAnalysis, ChainList, Job, Member, PairEvidence, PairWhy } from './types'
import './App.css'

type Tab = 'why' | 'members' | 'structure' | 'review' | 'evolution'
type EvidenceLayer = 'ALL' | PairEvidence['provenance_class']

const tabs: Array<{ id: Tab; label: string; eyebrow: string }> = [
  { id: 'why', label: 'Why grouped', eyebrow: 'Tier 1B' },
  { id: 'members', label: 'Members', eyebrow: 'Role map' },
  { id: 'structure', label: 'Structure', eyebrow: 'Tier 2' },
  { id: 'review', label: 'Review', eyebrow: 'What-if' },
  { id: 'evolution', label: 'Evolution', eyebrow: 'Snapshots' },
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

function Timeline({ members, selected, onSelect }: { members: Member[]; selected: string[]; onSelect: (member: Member) => void }) {
  const shown = members.slice(0, 18)
  return (
    <section className="timeline-card" aria-label="Bounded member timeline">
      <header className="section-heading">
        <div><p className="kicker">Bounded visualization</p><h2>Alarm sequence</h2></div>
        <span>{shown.length} / {members.length} members</span>
      </header>
      <div className="timeline-track">
        {shown.map((member, index) => (
          <button key={member.alarm_id} className={`timeline-node timeline-node--${member.role.toLowerCase()} ${selected.includes(member.alarm_id) ? 'is-selected' : ''}`} onClick={() => onSelect(member)} aria-pressed={selected.includes(member.alarm_id)} title={`${member.alarm_name ?? member.alarm_id} · ${member.role}`}>
            <span className="node-index">{String(index + 1).padStart(2, '0')}</span>
            <span className="node-name">{member.alarm_name ?? member.alarm_id}</span>
            <span className="node-time">{compactTime(member.canonical_start_time)}</span>
          </button>
        ))}
      </div>
      {members.length > shown.length && <p className="bounded-note">Pair materialization remains bounded. Use the member table for all {members.length} alarms.</p>}
    </section>
  )
}

function PairEvidenceRail({ analysis, selected, pair, loading, layer }: {
  analysis: ChainAnalysis
  selected: string[]
  pair: PairWhy | null
  loading: boolean
  layer: EvidenceLayer
}) {
  const visible = pair?.evidence.filter((item) => layer === 'ALL' || item.provenance_class === layer) ?? []
  if (selected.length < 2) {
    return (
      <aside className="evidence-rail">
        <p className="kicker">Pair WHY · on demand</p>
        <h2>Select two alarms</h2>
        <p className="rail-intro">Choose two nodes or table rows. No dense pair graph is built in Tier‑1B.</p>
        <div className="evidence-placeholder"><span>01</span><i /><span>02</span></div>
        <div className="system-card"><span>Analysis mode</span><strong>{analysis.graybox.mode}</strong><small>{analysis.graybox.pair_facts} supplied pair facts</small></div>
      </aside>
    )
  }
  return (
    <aside className="evidence-rail">
      <p className="kicker">Pair WHY · {selected[0]} ↔ {selected[1]}</p>
      <h2>{loading ? 'Evaluating evidence…' : `${visible.length} evidence channels`}</h2>
      {pair && <div className="system-card"><span>System fact</span><strong>{pair.system_fact.status}</strong><small>{pair.system_fact.semantic ?? 'No pair semantic supplied'}</small></div>}
      <div className="evidence-list">
        {visible.map((item, index) => (
          <article className="evidence-item" key={`${item.provider_id ?? item.channel_family}-${index}`}>
            <div className="evidence-spine"><span>{String(index + 1).padStart(2, '0')}</span></div>
            <div>
              <div className="evidence-title"><strong>{item.channel_family}</strong><Pill tone={statusTone(item.state)}>{item.state}</Pill></div>
              {item.dependency_semantic && <p>{humanize(item.dependency_semantic)}</p>}
              <dl className="mini-grid"><div><dt>score</dt><dd>{percent(item.score)}</dd></div><div><dt>{item.threshold == null ? 'support gate' : 'threshold'}</dt><dd>{item.threshold == null ? 'strictly positive' : percent(item.threshold)}</dd></div></dl>
              <small>{item.derivation_tag}</small>
              {item.channel_family === 'H' && item.evidence_metadata && <small>history model · {String(item.evidence_metadata.history_model_id ?? 'UNAVAILABLE')} · cutoff {String(item.evidence_metadata.training_cutoff ?? 'UNAVAILABLE')} · level {String(item.evidence_metadata.resolved_level ?? 'UNAVAILABLE')}</small>}
              {item.channel_family === 'T_delay' && item.evidence_metadata && <small>historical temporal pattern · {String(item.evidence_metadata.direction ?? 'UNAVAILABLE')} · observed {String(item.evidence_metadata.delay_seconds ?? 'UNAVAILABLE')}s · {String(item.evidence_metadata.estimator ?? 'UNAVAILABLE')} · episodes {String(item.evidence_metadata.episode_sample_count ?? 'UNAVAILABLE')}</small>}
              {(item.source_id || item.source_version) && <small>topology source · {item.source_id ?? 'UNAVAILABLE'} @ {item.source_version ?? 'UNAVAILABLE'}</small>}
              {(item.scenario_id || item.generator_version) && <small>synthetic generation · {item.scenario_id ?? 'UNAVAILABLE'} · {item.generator_version ?? 'UNAVAILABLE'}</small>}
              {item.detail && <p className="evidence-detail">{item.detail}</p>}
            </div>
          </article>
        ))}
        {!loading && pair && visible.length === 0 && <p className="rail-intro">No channel belongs to this evidence layer.</p>}
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

function MemberTable({ members, selected, onSelect }: { members: Member[]; selected: string[]; onSelect: (member: Member) => void }) {
  return (
    <section className="table-card">
      <header className="section-heading"><div><p className="kicker">All alarms</p><h2>Member diagnostics</h2></div><span>Select two for pair WHY</span></header>
      <div className="member-table" role="table">
        <div className="table-row table-head" role="row"><span>ID / alarm</span><span>device</span><span>role</span><span>support</span><span>coverage</span><span>groups</span></div>
        {members.map((member) => (
          <button className={`table-row ${selected.includes(member.alarm_id) ? 'is-selected' : ''}`} role="row" key={member.alarm_id} onClick={() => onSelect(member)}>
            <span><strong>{member.alarm_id}</strong><small>{member.alarm_name ?? 'unnamed alarm'}</small></span>
            <span>{member.device_code ?? '⊥'}<small>{member.node_reference ?? 'unmapped'}</small></span>
            <span><Pill tone={statusTone(member.role)}>{member.role}</Pill></span><span>{percent(member.membership_support)}</span><span>{percent(member.availability_coverage)}</span><span>{member.computable_groups}</span>
          </button>
        ))}
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
          <EvidenceAttribution
            result={result.evidence_attribution}
            evaluation={result.evidence_attribution_evaluation}
          />
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
  const [tab, setTab] = useState<Tab>('why')
  const [layer, setLayer] = useState<EvidenceLayer>('ALL')
  const [selectedMembers, setSelectedMembers] = useState<string[]>([])
  const [pairWhy, setPairWhy] = useState<PairWhy | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [submitting, setSubmitting] = useState(false)

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
      setPairWhy(null)
      setJob(null)
      setApiStatus('online')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Snapshot load failed')
    } finally {
      setLoadingSnapshot(false)
    }
  }

  function selectMember(member: Member) {
    setSelectedMembers((current) => {
      if (current.includes(member.alarm_id)) return current.filter((id) => id !== member.alarm_id)
      if (current.length >= 2) return [current[1], member.alarm_id]
      return [...current, member.alarm_id]
    })
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

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NocPro Chain Explain home"><span><Icon name="pulse" /></span><strong>NocPro</strong><i>Chain Explain</i></a>
        <div className="snapshot-chip"><span className="connection-dot connection-dot--online" />snapshot <strong>{chainList.snapshot_id}</strong></div>
        <label className="chain-search"><Icon name="search" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter chains" aria-label="Filter chains" /></label>
        <select value={chainId} onChange={(event) => {
          setSelectedMembers([])
          setPairWhy(null)
          setJob(null)
          setError(null)
          setChainId(event.target.value)
        }} aria-label="Select alarm chain">{filteredChains.map((chain) => <option value={chain.chain_id} key={chain.chain_id}>{chain.chain_id} · {chain.member_count} alarms</option>)}</select>
        <label className="upload-compact"><input type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadSnapshot(file); event.target.value = '' }} /><Icon name="upload" /><span>Replace</span></label>
      </header>

      <nav className="tabbar" aria-label="Analysis views">
        {tabs.map((item) => <button key={item.id} className={tab === item.id ? 'is-active' : ''} onClick={() => setTab(item.id)}><small>{item.eyebrow}</small>{item.label}</button>)}
        <div className="layer-switcher"><label htmlFor="layer">Evidence layer</label><select id="layer" value={layer} onChange={(event) => setLayer(event.target.value as EvidenceLayer)}>{evidenceLayers.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></div>
      </nav>

      {error && <div className="error-banner workspace-error" role="alert">{error}<button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      {!analysis || analysis.chain_id !== chainId ? <main className="loading-state"><span /><p>Computing exact indexed statistics…</p></main> : (
        <main className="workspace" id="top">
          <section className="chain-hero">
            <div><p className="kicker">Chain {analysis.chain_id}</p><h1>{analysis.title}</h1><p>{analysis.member_count} alarms · {analysis.singleton ? 'singleton path' : 'multi-member chain'} · {analysis.graybox.mode}</p></div>
            <div className="hero-metrics"><div><span>statistics</span><strong>{humanize(analysis.statistics_mode)}</strong></div><div><span>pair detail</span><strong>{humanize(analysis.pair_materialization)}</strong></div><div><span>Tier‑1B</span><strong>{duration(Object.values(analysis.phase_durations).reduce((sum, value) => sum + value, 0))}</strong></div></div>
          </section>

          <div className="workspace-grid">
            <div className="primary-column">
              <Timeline members={analysis.members} selected={selectedMembers} onSelect={selectMember} />
              {tab === 'why' && <WhyPanel analysis={analysis} />}
              {tab === 'members' && <MemberTable members={analysis.members} selected={selectedMembers} onSelect={selectMember} />}
              {tab === 'structure' && <>
                <StructurePanel job={visibleJob} onRun={() => void runDeepDive()} submitting={submitting} />
                {visibleJob?.result && <TopologyHypotheses topology_hypotheses={visibleJob.result.topology_hypotheses} />}
              </>}
              {tab === 'review' && <CounterfactualReview key={chainId} chainId={chainId} />}
              {tab === 'evolution' && <EvolutionPanel chainId={chainId} />}
            </div>
            <PairEvidenceRail analysis={analysis} selected={selectedMembers} pair={visiblePair} loading={selectedMembers.length === 2 && !pairMatchesSelection} layer={layer} />
          </div>
        </main>
      )}
    </div>
  )
}

export default App
