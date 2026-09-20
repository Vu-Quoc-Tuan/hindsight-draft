import type { ChainList } from '../types'
import { formatDuration } from '../format'

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
  const observedStarts = chains
    .map(chain => chain.start_time)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())
  const observedEnds = chains
    .map(chain => chain.end_time)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())
  const earliestStart = observedStarts[0] ?? null
  const latestEnd = observedEnds.at(-1) ?? null

  const windowDurationSec = (earliestStart && latestEnd)
    ? Math.max(0, (new Date(latestEnd).getTime() - new Date(earliestStart).getTime()) / 1000)
    : null

  const durations = chains
    .map(c => c.duration_seconds)
    .filter((d): d is number => d != null && !Number.isNaN(d) && d >= 0)

  const medianDuration = median(durations)
  const maxDuration = durations.length > 0 ? Math.max(...durations) : null

  const timedChains = chains.filter(c => c.start_time && c.end_time).length
  const timedPercentage = totalChains > 0 ? (timedChains / totalChains) * 100 : 0

  const buckets = [
    { label: 'Singleton (1)', count: chains.filter(c => c.member_count === 1).length, barClass: 'bg-secondary' },
    { label: '2–5 alarms', count: chains.filter(c => c.member_count >= 2 && c.member_count <= 5).length, barClass: 'bg-sky-400' },
    { label: '6–20 alarms', count: chains.filter(c => c.member_count >= 6 && c.member_count <= 20).length, barClass: 'bg-amber-400' },
    { label: '>20 alarms', count: chains.filter(c => c.member_count > 20).length, barClass: 'bg-rose-500' },
  ]

  const singletonShare = totalChains > 0 ? (singletons / totalChains) * 100 : 0
  const isHeavyTail = largest && largest.member_count > 10

  const topChains = [...chains]
    .sort((a, b) => b.member_count - a.member_count || a.chain_id.localeCompare(b.chain_id))
    .slice(0, 5)

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn select-none">
      {/* 1. Top Tier: 3 Core Macro KPI Cards */}
      <section className="grid grid-cols-1 gap-space-md md:grid-cols-3" aria-label="Observed snapshot metrics">
        {/* Card 1: Observed alarms */}
        <div className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-secondary/40 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold">Observed alarms</span>
            <span className="material-symbols-outlined text-secondary text-[22px]">notifications</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight">
              {totalAlarms.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-1 truncate" title="Sum of returned chain member counts">
              Total alarms across snapshot
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
            <span className="material-symbols-outlined text-secondary text-[22px]">device_hub</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl font-extrabold text-on-surface tracking-tight group-hover:text-primary transition-colors">
              {totalChains.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-secondary-fixed mt-1 truncate flex items-center gap-1.5">
              <span className="font-bold text-secondary">{multiAlarmChains.toLocaleString()} multi-alarm</span>
              <span className="text-on-surface-variant/70">·</span>
              <span className="text-tertiary font-semibold">{singletons.toLocaleString()} singletons ({singletonShare.toFixed(0)}%)</span>
            </div>
          </div>
        </div>

        {/* Card 3: Largest chain */}
        <div
          className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm transition-all hover:border-primary/50 hover:bg-[#101a2e] cursor-pointer flex flex-col justify-between group"
          onClick={() => largest && onSelectChain(largest.chain_id)}
          title={largest ? `Inspect largest chain ${largest.chain_id}` : 'No chains'}
        >
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider font-semibold group-hover:text-primary transition-colors">Largest chain</span>
            <span className="material-symbols-outlined text-primary text-[22px]">warning</span>
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
              {largest?.title && <span className="text-[#64748b] ml-1.5">({largest.title})</span>}
            </div>
          </div>
        </div>
      </section>

      {/* 2. Middle Tier: Chain Size Distribution & Snapshot Temporal Coverage */}
      <section className="grid min-w-0 grid-cols-1 gap-space-md lg:grid-cols-2">
        {/* Left: Chain Size Distribution */}
        <article className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#1a253c] pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[20px]">bar_chart</span>
                <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Observed chain-size distribution</h2>
              </div>
              <span className="rounded bg-[#141d30] px-2 py-0.5 font-code-sm text-[11px] text-on-surface-variant border border-[#22304c]">
                {totalChains.toLocaleString()} chains
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

          <div className="mt-space-md grid grid-cols-3 gap-2 border-t border-[#1a253c] pt-space-sm">
            <div className="rounded-lg bg-[#080d17] p-2.5 border border-[#172136]">
              <span className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps block">Avg Size</span>
              <span className="text-sm font-bold text-on-surface font-code-sm mt-0.5 block truncate">
                {totalChains > 0 ? (totalAlarms / totalChains).toFixed(1) : 0} <span className="text-[11px] font-normal text-on-surface-variant">alarms</span>
              </span>
            </div>
            <div className="rounded-lg bg-[#080d17] p-2.5 border border-[#172136]">
              <span className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps block">Singletons</span>
              <span className="text-sm font-bold text-secondary font-code-sm mt-0.5 block truncate">
                {singletonShare.toFixed(0)}% <span className="text-[11px] font-normal text-on-surface-variant">({singletons})</span>
              </span>
            </div>
            <div className="rounded-lg bg-[#080d17] p-2.5 border border-[#172136]">
              <span className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label-caps block">Tail Skew</span>
              <span className={`text-sm font-bold font-code-sm mt-0.5 block truncate ${isHeavyTail ? 'text-rose-400' : 'text-emerald-400'}`}>
                {isHeavyTail ? 'Heavy Tail' : 'Normal'}
              </span>
            </div>
          </div>
        </article>

        {/* Right: Observed temporal coverage */}
        <article className="min-w-0 rounded-xl border border-[#1e2b44] bg-[#0c1322] p-space-md shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#1a253c] pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[20px]">crisis_alert</span>
                <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Observed temporal coverage</h2>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('multi-chain-timeline')}
                className="inline-flex items-center gap-1 rounded bg-secondary/10 px-2.5 py-1 font-code-sm text-xs font-semibold text-secondary hover:bg-secondary hover:text-on-secondary border border-secondary/30 transition-colors cursor-pointer"
                title="Open Multi-chain Timeline"
              >
                <span className="material-symbols-outlined text-[15px]">timeline</span>
                <span>Timeline View →</span>
              </button>
            </div>

            {/* Temporal Coverage Panels */}
            <div className="mt-space-md space-y-3">
              {/* Row 1: Observation Window */}
              <div className="p-3.5 rounded-lg bg-[#080d17] border border-[#1a253c] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-sky-500/15 border border-sky-500/30 flex items-center justify-center text-sky-400 shrink-0">
                    <span className="material-symbols-outlined text-[22px]">date_range</span>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <strong className="text-sm font-bold text-on-surface">Observation Window</strong>
                      {windowDurationSec != null && (
                        <span className="rounded bg-sky-500/15 px-1.5 py-0.5 font-code-sm text-[10px] font-semibold text-sky-400 border border-sky-500/30">
                          {formatDuration(windowDurationSec)} span
                        </span>
                      )}
                    </div>
                    <span className="text-[11px] text-on-surface-variant font-code-sm block mt-0.5">
                      {formatTimestamp(earliestStart)} → {formatTimestamp(latestEnd)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Row 2: Chain Duration Span */}
              <div className="p-3.5 rounded-lg bg-[#080d17] border border-[#1a253c] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0">
                    <span className="material-symbols-outlined text-[22px]">timelapse</span>
                  </div>
                  <div>
                    <strong className="block text-sm font-bold text-on-surface">
                      Chain Duration Profile
                    </strong>
                    <span className="text-[11px] text-on-surface-variant font-code-sm block mt-0.5">
                      Median: <strong className="text-on-surface">{formatDuration(medianDuration)}</strong> · Max: <strong className="text-on-surface">{formatDuration(maxDuration)}</strong>
                    </span>
                  </div>
                </div>
                <span className="rounded bg-[#141d30] px-2 py-0.5 font-code-sm text-[11px] text-on-surface-variant border border-[#22304c] shrink-0">
                  {timedChains}/{totalChains} timed ({timedPercentage.toFixed(0)}%)
                </span>
              </div>

              {/* Row 3: Visual Timeline Mini-Track */}
              <div className="p-3 rounded-lg bg-[#080d17] border border-[#1a253c] space-y-2">
                <div className="flex items-center justify-between text-code-sm text-[11px]">
                  <span className="text-on-surface-variant flex items-center gap-1.5 font-medium">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Snapshot Activity Span
                  </span>
                  <span className="text-secondary font-bold font-code-sm">
                    {windowDurationSec != null ? formatDuration(windowDurationSec) : '0s'}
                  </span>
                </div>
                <div className="relative h-2 w-full rounded-full bg-[#141d30] overflow-hidden border border-[#22304c]">
                  <div className="absolute inset-y-0 left-0 w-full rounded-full bg-gradient-to-r from-sky-500 via-secondary to-emerald-400 opacity-80" />
                </div>
                <div className="flex items-center justify-between text-[10px] text-[#64748b] font-code-sm">
                  <span className="truncate max-w-[45%]">{formatTimestamp(earliestStart)}</span>
                  <span className="shrink-0 text-on-surface-variant/60">━</span>
                  <span className="truncate max-w-[45%] text-right">{formatTimestamp(latestEnd)}</span>
                </div>
              </div>
            </div>
          </div>

          <span className="sr-only">{chainList.snapshot_id}@{chainList.snapshot_version}</span>
        </article>
      </section>

      {/* 3. Bottom Tier: Largest observed chains (Triage Table) */}
      <section className="min-w-0 overflow-hidden rounded-xl border border-[#1e2b44] bg-[#0c1322] shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-sm border-b border-[#1a253c] px-space-md py-3 bg-[#0f1728]">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <span className="material-symbols-outlined text-[18px]">format_list_numbered</span>
            </div>
            <div>
              <h2 className="font-headline-md text-headline-md font-bold text-on-surface">Largest observed chains</h2>
              <p className="text-code-sm text-xs text-on-surface-variant">Top chains ordered by member alarm count in this snapshot.</p>
            </div>
          </div>

        </div>

        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-code-sm">
            <thead>
              <tr className="bg-[#080d17] font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant border-b border-[#1a253c]">
                <th className="px-space-md py-2.5">Chain</th>
                <th className="px-space-md py-2.5">Title / Component</th>
                <th className="px-space-md py-2.5 text-right">Duration</th>
                <th className="px-space-md py-2.5 text-right">Members</th>
                <th className="px-space-md py-2.5 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f33]">
              {topChains.map((chain, index) => (
                <tr
                  key={chain.chain_id}
                  onClick={() => onSelectChain(chain.chain_id)}
                  className="hover:bg-[#101a2e] transition-colors cursor-pointer group"
                >
                  <td className="px-space-md py-3 font-bold text-primary">
                    <button
                      type="button"
                      className="rounded text-left group-hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary flex items-center gap-2"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectChain(chain.chain_id)
                      }}
                    >
                      <span className="flex h-5 w-5 items-center justify-center rounded bg-[#141d30] text-[10px] font-bold text-on-surface-variant border border-[#22304c]">
                        {index + 1}
                      </span>
                      <span className="material-symbols-outlined text-[16px] text-secondary">device_hub</span>
                      <span>{chain.chain_id}</span>
                    </button>
                  </td>
                  <td className="px-space-md py-3 text-on-surface font-medium max-w-[320px] truncate" title={chain.title}>
                    {chain.title || 'Unavailable'}
                  </td>
                  <td className="px-space-md py-3 text-right font-code-sm text-on-surface-variant">
                    {chain.duration_seconds != null ? formatDuration(chain.duration_seconds) : '—'}
                  </td>
                  <td className="px-space-md py-3 text-right">
                    <span className="font-bold text-on-surface text-base">{chain.member_count}</span>{' '}
                    <span className="text-[11px] text-on-surface-variant">alarms</span>
                  </td>
                  <td className="px-space-md py-3 text-center">
                    <button
                      type="button"
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
