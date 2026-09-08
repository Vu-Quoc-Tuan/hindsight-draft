import type { ChainList } from '../types'

interface SnapshotOverviewViewProps {
  chainList?: ChainList | null
  onSelectChain: (chainId: string) => void
  onNavigate: (view: string) => void
}

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const ordered = [...values].sort((a, b) => a - b)
  const middle = Math.floor(ordered.length / 2)
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle]
}

function percentile(values: number[], fraction: number): number | null {
  if (values.length === 0) return null
  const ordered = [...values].sort((a, b) => a - b)
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)]
}

function formatTimestamp(value: string | null): string {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export function SnapshotOverviewView({
  chainList,
  onSelectChain,
  onNavigate,
}: SnapshotOverviewViewProps) {
  if (!chainList) {
    return (
      <section
        className="mx-auto max-w-3xl rounded-xl border border-surface-container-highest bg-surface-container p-space-xl text-center shadow-md"
        role="status"
      >
        <span className="material-symbols-outlined text-4xl text-on-surface-variant">database_off</span>
        <h1 className="mt-space-sm font-headline-md text-headline-md font-bold text-on-surface">Snapshot unavailable</h1>
        <p className="mt-space-xs text-on-surface-variant">Load a snapshot from the catalog to view observed chain statistics.</p>
      </section>
    )
  }

  const chains = chainList.chains
  const sizes = chains.map(chain => chain.member_count)
  const totalAlarms = sizes.reduce((sum, value) => sum + value, 0)
  const totalChains = chains.length
  const singletons = chains.filter(chain => chain.is_singleton).length
  const multiAlarmChains = totalChains - singletons
  const largest = [...chains].sort((a, b) => b.member_count - a.member_count || a.chain_id.localeCompare(b.chain_id))[0] ?? null
  const observedStarts = chains.map(chain => chain.start_time).filter((value): value is string => Boolean(value)).sort()
  const observedEnds = chains.map(chain => chain.end_time).filter((value): value is string => Boolean(value)).sort()
  const topChains = [...chains]
    .sort((a, b) => b.member_count - a.member_count || a.chain_id.localeCompare(b.chain_id))
    .slice(0, 5)

  const buckets = [
    { label: 'Singleton (1)', count: chains.filter(c => c.member_count === 1).length, barClass: 'bg-secondary' },
    { label: '2–5 alarms', count: chains.filter(c => c.member_count >= 2 && c.member_count <= 5).length, barClass: 'bg-sky-400' },
    { label: '6–20 alarms', count: chains.filter(c => c.member_count >= 6 && c.member_count <= 20).length, barClass: 'bg-amber-400' },
    { label: '>20 alarms', count: chains.filter(c => c.member_count > 20).length, barClass: 'bg-rose-500' },
  ]

  const singletonShare = totalChains > 0 ? (singletons / totalChains) * 100 : 0
  const isHeavyTail = largest && largest.member_count > 10

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn select-none">
      {/* 1. Top Tier: 5 Macro KPI Cards */}
      <section className="grid grid-cols-1 gap-space-md sm:grid-cols-2 xl:grid-cols-5" aria-label="Observed snapshot metrics">
        {/* Card 1: Observed alarms */}
        <div className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/40 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold">Observed alarms</span>
            <span className="material-symbols-outlined text-secondary text-[20px]">notifications</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight">
              {totalAlarms.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate" title="Sum of returned chain member counts">
              Total alarms
            </div>
          </div>
        </div>

        {/* Card 2: Observed chains */}
        <div
          className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/50 hover:bg-[#101a2e] cursor-pointer flex flex-col justify-between group"
          onClick={() => onNavigate('chains-explorer')}
          title="Open Chains Explorer"
        >
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold group-hover:text-secondary transition-colors">Observed chains</span>
            <span className="material-symbols-outlined text-secondary text-[20px]">device_hub</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight group-hover:text-primary transition-colors">
              {totalChains.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-secondary-fixed mt-1 truncate flex items-center gap-1">
              <span className="font-bold text-secondary">{multiAlarmChains.toLocaleString()}</span>
              <span>multi-alarm chains</span>
            </div>
          </div>
        </div>

        {/* Card 3: Singletons */}
        <div
          className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-tertiary/50 hover:bg-[#101a2e] cursor-pointer flex flex-col justify-between group"
          onClick={() => onNavigate('chains-explorer')}
          title="Open Chains Explorer (Filtered to singletons)"
        >
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold group-hover:text-tertiary transition-colors">Singletons</span>
            <span className="material-symbols-outlined text-tertiary text-[20px]">grain</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-1.5">
              <span className="font-headline-xl text-headline-xl font-extrabold text-tertiary tracking-tight">
                {singletons.toLocaleString()}
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant font-semibold">
                ({singletonShare.toFixed(1)}%)
              </span>
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate">
              {totalChains > 0 ? `${singletonShare.toFixed(1)}% of returned chains` : 'No chains returned'}
            </div>
          </div>
        </div>

        {/* Card 4: Largest chain */}
        <div
          className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-primary/50 hover:bg-[#101a2e] cursor-pointer flex flex-col justify-between group"
          onClick={() => largest && onSelectChain(largest.chain_id)}
          title={largest ? `Inspect largest chain ${largest.chain_id}` : 'No chains'}
        >
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold group-hover:text-primary transition-colors">Largest chain</span>
            <span className="material-symbols-outlined text-primary text-[20px]">warning</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-1.5">
              <span className="font-headline-xl text-headline-xl font-extrabold text-primary tracking-tight">
                {largest ? largest.member_count.toLocaleString() : 'N/A'}
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">alarms</span>
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate">
              Ref: <span className="font-bold text-primary">{largest ? largest.chain_id : 'None'}</span>
            </div>
          </div>
        </div>

        {/* Card 5: Chain size */}
        <div className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/40 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold">Chain size</span>
            <span className="material-symbols-outlined text-secondary text-[20px]">straighten</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-1.5">
              <span className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight">
                {median(sizes)?.toLocaleString() ?? 'N/A'}
              </span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">median</span>
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate">
              Median · P95 {percentile(sizes, 0.95)?.toLocaleString() ?? 'N/A'}
            </div>
          </div>
        </div>
      </section>

      {/* 2. Middle Tier: Chain Size Distribution & Snapshot Triage / Chronology */}
      <section className="grid min-w-0 grid-cols-1 gap-space-md lg:grid-cols-2">
        {/* Left: Chain Size Distribution */}
        <article className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#1a253c] pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[20px]">bar_chart</span>
                <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Observed chain-size distribution</h2>
              </div>
              <span className="font-code-sm text-[11px] text-on-surface-variant bg-[#141d30] px-2 py-0.5 rounded border border-[#22304c]">
                {totalChains} total
              </span>
            </div>

            <div className="mt-space-md space-y-space-sm">
              {buckets.map(bucket => {
                const share = totalChains > 0 ? (bucket.count / totalChains) * 100 : 0
                return (
                  <div key={bucket.label} className="space-y-1">
                    <div className="flex items-center justify-between text-code-sm">
                      <span className="font-medium text-on-surface">{bucket.label}</span>
                      <span className="font-bold text-on-surface-variant">
                        {bucket.count.toLocaleString()}{' '}
                        <span className="font-normal text-[11px] text-[#64748b]">({share.toFixed(1)}%)</span>
                      </span>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-[#080d17] p-0.5 border border-[#192339]">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${bucket.barClass}`}
                        style={{ width: `${Math.max(share > 0 ? 1.5 : 0, share)}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="mt-space-md">
            <div className="rounded-lg bg-[#080d17] p-2.5 border border-[#172136] flex flex-wrap items-center justify-between gap-2 text-code-sm text-[11px] text-on-surface-variant">
              <span>Tail Skew: <strong className={isHeavyTail ? 'text-rose-400 font-bold' : 'text-secondary font-bold'}>{isHeavyTail ? 'Heavy Tail' : 'Normal'}</strong></span>
              <span>Multi-alarm: <strong className="text-secondary font-bold">{totalChains > 0 ? ((multiAlarmChains / totalChains) * 100).toFixed(1) : 0}%</strong></span>
              <span>Avg size: <strong className="text-on-surface font-bold">{totalChains > 0 ? (totalAlarms / totalChains).toFixed(1) : 0} alarms</strong></span>
            </div>
          </div>
        </article>

        {/* Right: Snapshot Triage & Chronology */}
        <article className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#1a253c] pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[20px]">crisis_alert</span>
                <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Observed temporal coverage</h2>
              </div>
              <span className="font-code-sm text-[11px] text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/30">
                Factual Evidence
              </span>
            </div>

            {/* 3 Quick Action Triage Cards */}
            <div className="mt-space-md space-y-2.5">
              {/* Triage 1: Multi-alarm Chains */}
              <div
                className="p-3 rounded-lg bg-[#080d17] border border-[#1a253c] hover:border-secondary/50 hover:bg-[#0e1628] transition-all flex items-center justify-between cursor-pointer group"
                onClick={() => onNavigate('chains-explorer')}
              >
                <div className="flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-secondary/15 border border-secondary/30 flex items-center justify-center text-secondary">
                    <span className="material-symbols-outlined text-[20px]">hub</span>
                  </div>
                  <div>
                    <strong className="block text-sm font-bold text-on-surface group-hover:text-primary transition-colors">
                      {multiAlarmChains.toLocaleString()} Multi-alarm Chains
                    </strong>
                    <span className="text-[11px] text-on-surface-variant font-code-sm">
                      Correlated candidate propagation clusters
                    </span>
                  </div>
                </div>
                <span className="rounded bg-secondary/15 px-2 py-1 font-code-sm text-xs font-semibold text-secondary border border-secondary/30 group-hover:bg-secondary group-hover:text-on-secondary transition-colors">
                  Explore →
                </span>
              </div>

              {/* Triage 2: Singletons */}
              <div
                className="p-3 rounded-lg bg-[#080d17] border border-[#1a253c] hover:border-tertiary/50 hover:bg-[#0e1628] transition-all flex items-center justify-between cursor-pointer group"
                onClick={() => onNavigate('chains-explorer')}
              >
                <div className="flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-tertiary/15 border border-tertiary/30 flex items-center justify-center text-tertiary">
                    <span className="material-symbols-outlined text-[20px]">link_off</span>
                  </div>
                  <div>
                    <strong className="block text-sm font-bold text-on-surface group-hover:text-tertiary transition-colors">
                      {singletons.toLocaleString()} Solitary Alarms
                    </strong>
                    <span className="text-[11px] text-on-surface-variant font-code-sm">
                      Isolated unlinked signals in snapshot
                    </span>
                  </div>
                </div>
                <span className="rounded bg-tertiary/15 px-2 py-1 font-code-sm text-xs font-semibold text-tertiary border border-tertiary/30 group-hover:bg-tertiary group-hover:text-on-tertiary transition-colors">
                  Filter →
                </span>
              </div>

              {/* Triage 3: Timeline */}
              <div
                className="p-3 rounded-lg bg-[#080d17] border border-[#1a253c] hover:border-emerald-500/50 hover:bg-[#0e1628] transition-all flex items-center justify-between cursor-pointer group"
                onClick={() => onNavigate('multi-chain-timeline')}
              >
                <div className="flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                    <span className="material-symbols-outlined text-[20px]">schedule</span>
                  </div>
                  <div>
                    <strong className="block text-sm font-bold text-on-surface group-hover:text-emerald-400 transition-colors">
                      Observed Timeline
                    </strong>
                    <span className="text-[11px] text-on-surface-variant font-code-sm">
                      {formatTimestamp(observedStarts[0] ?? null)} → {formatTimestamp(observedEnds.at(-1) ?? null)}
                    </span>
                  </div>
                </div>
                <button
                  className="rounded bg-emerald-500/15 px-2 py-1 font-code-sm text-xs font-semibold text-emerald-400 border border-emerald-500/30 group-hover:bg-emerald-500 group-hover:text-black transition-colors"
                  onClick={(e) => {
                    e.stopPropagation()
                    onNavigate('multi-chain-timeline')
                  }}
                >
                  Open factual timeline
                </button>
              </div>
            </div>
          </div>

          <span className="sr-only">{chainList.snapshot_id}@{chainList.snapshot_version}</span>
        </article>
      </section>

      {/* 3. Bottom Tier: Largest observed chains (Triage Table) */}
      <section className="min-w-0 overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-sm border-b border-[#1a253c] px-space-md py-3 bg-[#0f1728]">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[20px]">priority_high</span>
            <div>
              <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Largest observed chains</h2>
              <p className="text-code-sm text-xs text-on-surface-variant">Ordered only by returned member count; this is not an Audit ranking.</p>
            </div>
          </div>
          <button
            className="rounded-lg border border-secondary/40 bg-secondary/10 px-3 py-1.5 font-code-sm text-xs font-semibold text-secondary hover:bg-secondary hover:text-on-secondary transition-colors cursor-pointer"
            onClick={() => onNavigate('chains-explorer')}
          >
            View all chains
          </button>
        </div>

        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-code-sm">
            <thead>
              <tr className="bg-[#080d17] font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant border-b border-[#1a253c]">
                <th className="px-space-md py-2.5">Chain</th>
                <th className="px-space-md py-2.5">Title</th>
                <th className="px-space-md py-2.5 text-right">Members</th>
                <th className="px-space-md py-2.5">Analysis</th>
                <th className="px-space-md py-2.5 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f33]">
              {topChains.map(chain => (
                <tr
                  key={chain.chain_id}
                  onClick={() => onSelectChain(chain.chain_id)}
                  className="hover:bg-[#101a2e] transition-colors cursor-pointer group"
                >
                  <td className="px-space-md py-3 font-bold text-primary">
                    <button
                      type="button"
                      className="rounded text-left group-hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary flex items-center gap-1.5"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectChain(chain.chain_id)
                      }}
                    >
                      <span className="material-symbols-outlined text-[16px] text-secondary">device_hub</span>
                      <span>{chain.chain_id}</span>
                    </button>
                  </td>
                  <td className="px-space-md py-3 text-on-surface font-medium max-w-[320px] truncate" title={chain.title}>
                    {chain.title || 'Unavailable'}
                  </td>
                  <td className="px-space-md py-3 text-right">
                    <span className="font-bold text-on-surface text-base">{chain.member_count}</span>{' '}
                    <span className="text-[11px] text-on-surface-variant">alarms</span>
                  </td>
                  <td className="px-space-md py-3">
                    <span className="inline-flex items-center gap-1 rounded bg-[#131d31] px-2 py-0.5 text-xs text-on-surface-variant border border-[#22314d]">
                      <span className="material-symbols-outlined text-[13px] text-secondary">query_stats</span>
                      Audit on demand
                    </span>
                  </td>
                  <td className="px-space-md py-3 text-center">
                    <button
                      className="rounded border border-secondary/40 bg-secondary/10 px-2.5 py-1 font-code-sm text-xs font-semibold text-secondary hover:bg-secondary hover:text-on-secondary transition-colors"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectChain(chain.chain_id)
                      }}
                    >
                      Inspect Chain →
                    </button>
                  </td>
                </tr>
              ))}
              {topChains.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-space-md py-space-lg text-center text-on-surface-variant">
                    No chains returned.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
