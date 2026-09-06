import type { ChainList, ChainSummary } from '../types'

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
  if (!value) return 'N/A'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="min-w-0 rounded-lg border border-surface-container-high bg-surface-container p-space-md shadow-sm">
      <p className="font-label-caps text-label-caps uppercase text-on-surface-variant">{label}</p>
      <p className="mt-space-xs break-words font-headline-xl text-headline-xl font-bold text-on-surface">{value}</p>
      <p className="mt-space-2xs break-words font-code-sm text-code-sm text-on-surface-variant">{detail}</p>
    </article>
  )
}

function bucketCount(chains: ChainSummary[], lower: number, upper?: number): number {
  return chains.filter(chain => chain.member_count >= lower && (upper === undefined || chain.member_count <= upper)).length
}

export function SnapshotOverviewView({ chainList, onSelectChain, onNavigate }: SnapshotOverviewViewProps) {
  if (!chainList) {
    return (
      <section className="mx-auto max-w-3xl rounded-lg border border-surface-container-highest bg-surface-container p-space-xl text-center" role="status">
        <span className="material-symbols-outlined text-3xl text-on-surface-variant">database_off</span>
        <h1 className="mt-space-sm font-headline-md text-headline-md font-bold">Snapshot unavailable</h1>
        <p className="mt-space-xs text-on-surface-variant">Load a snapshot to view observed chain statistics.</p>
      </section>
    )
  }

  const chains = chainList.chains
  const sizes = chains.map(chain => chain.member_count)
  const totalAlarms = sizes.reduce((sum, value) => sum + value, 0)
  const singletons = chains.filter(chain => chain.is_singleton).length
  const largest = [...chains].sort((a, b) => b.member_count - a.member_count || a.chain_id.localeCompare(b.chain_id))[0] ?? null
  const observedStarts = chains.map(chain => chain.start_time).filter((value): value is string => Boolean(value)).sort()
  const observedEnds = chains.map(chain => chain.end_time).filter((value): value is string => Boolean(value)).sort()
  const topChains = [...chains]
    .sort((a, b) => b.member_count - a.member_count || a.chain_id.localeCompare(b.chain_id))
    .slice(0, 5)
  const buckets = [
    { label: 'Singleton (1)', count: bucketCount(chains, 1, 1) },
    { label: '2–5 alarms', count: bucketCount(chains, 2, 5) },
    { label: '6–20 alarms', count: bucketCount(chains, 6, 20) },
    { label: '>20 alarms', count: bucketCount(chains, 21) },
  ]

  return (
    <div className="flex w-full min-w-0 flex-col gap-space-lg animate-fadeIn">
      <section className="grid grid-cols-1 gap-space-md sm:grid-cols-2 xl:grid-cols-5" aria-label="Observed snapshot metrics">
        <MetricCard label="Observed alarms" value={totalAlarms.toLocaleString()} detail="Sum of returned chain member counts" />
        <MetricCard label="Observed chains" value={chains.length.toLocaleString()} detail={`${chains.length - singletons} multi-alarm chains`} />
        <MetricCard
          label="Singletons"
          value={singletons.toLocaleString()}
          detail={chains.length > 0 ? `${((singletons / chains.length) * 100).toFixed(1)}% of returned chains` : 'No chains returned'}
        />
        <MetricCard
          label="Largest chain"
          value={largest ? largest.member_count.toLocaleString() : 'N/A'}
          detail={largest ? largest.chain_id : 'No chains returned'}
        />
        <MetricCard
          label="Chain size"
          value={median(sizes)?.toLocaleString() ?? 'N/A'}
          detail={`Median · P95 ${percentile(sizes, 0.95)?.toLocaleString() ?? 'N/A'}`}
        />
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-space-md lg:grid-cols-2">
        <article className="min-w-0 rounded-lg border border-surface-container-high bg-surface-container p-space-md shadow-sm">
          <h2 className="font-headline-md text-headline-md font-bold">Observed chain-size distribution</h2>
          <div className="mt-space-md space-y-space-sm">
            {buckets.map(bucket => {
              const share = chains.length > 0 ? (bucket.count / chains.length) * 100 : 0
              return (
                <div key={bucket.label}>
                  <div className="flex items-center justify-between gap-space-sm text-code-sm">
                    <span>{bucket.label}</span>
                    <span>{bucket.count.toLocaleString()} ({share.toFixed(1)}%)</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded bg-surface-container-lowest">
                    <div className="h-full bg-secondary" style={{ width: `${share}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
          <p className="mt-space-md text-code-sm text-on-surface-variant">
            These counts are derived from the current ChainList response. Structural findings require an explicit per-chain Audit.
          </p>
        </article>

        <article className="min-w-0 rounded-lg border border-surface-container-high bg-surface-container p-space-md shadow-sm">
          <h2 className="font-headline-md text-headline-md font-bold">Observed temporal coverage</h2>
          <dl className="mt-space-md grid grid-cols-[auto_minmax(0,1fr)] gap-x-space-md gap-y-space-sm text-code-sm">
            <dt className="text-on-surface-variant">First observed start</dt>
            <dd className="break-words text-right">{formatTimestamp(observedStarts[0] ?? null)}</dd>
            <dt className="text-on-surface-variant">Last observed end</dt>
            <dd className="break-words text-right">{formatTimestamp(observedEnds.at(-1) ?? null)}</dd>
            <dt className="text-on-surface-variant">Snapshot identity</dt>
            <dd className="break-all text-right">{chainList.snapshot_id}@{chainList.snapshot_version}</dd>
          </dl>
          <button className="mt-space-md rounded border border-surface-container-highest px-space-sm py-space-xs text-secondary" onClick={() => onNavigate('multi-chain-timeline')}>
            Open factual timeline
          </button>
        </article>
      </section>

      <section className="min-w-0 overflow-hidden rounded-lg border border-surface-container-high bg-surface-container shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-sm border-b border-surface-container-high px-space-md py-space-sm">
          <div>
            <h2 className="font-headline-md text-headline-md font-bold">Largest observed chains</h2>
            <p className="text-code-sm text-on-surface-variant">Ordered only by returned member count; this is not an Audit ranking.</p>
          </div>
          <button className="rounded border border-surface-container-highest px-space-sm py-space-xs text-secondary" onClick={() => onNavigate('chains-explorer')}>
            View all chains
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-code-sm">
            <thead className="bg-surface-container-low text-on-surface-variant">
              <tr><th className="px-space-md py-space-xs">Chain</th><th className="px-space-md py-space-xs">Title</th><th className="px-space-md py-space-xs text-right">Members</th><th className="px-space-md py-space-xs">Analysis</th></tr>
            </thead>
            <tbody className="divide-y divide-surface-container-high">
              {topChains.map(chain => (
                <tr key={chain.chain_id} className="hover:bg-surface-container-high">
                  <td className="px-space-md py-space-sm font-bold text-primary">
                    <button type="button" className="rounded text-left hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary" onClick={() => onSelectChain(chain.chain_id)}>
                      {chain.chain_id}
                    </button>
                  </td>
                  <td className="px-space-md py-space-sm">{chain.title}</td>
                  <td className="px-space-md py-space-sm text-right">{chain.member_count}</td>
                  <td className="px-space-md py-space-sm text-on-surface-variant">Audit on demand</td>
                </tr>
              ))}
              {topChains.length === 0 && <tr><td colSpan={4} className="px-space-md py-space-lg text-center text-on-surface-variant">No chains returned.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
