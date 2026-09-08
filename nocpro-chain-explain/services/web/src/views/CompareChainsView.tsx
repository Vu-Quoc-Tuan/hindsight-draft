import type { ReactNode } from 'react'

import type { ChainSummary } from '../types'

interface CompareChainsViewProps {
  chainAId: string
  chainBId: string
  chains?: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onChangeSelection: () => void
}

function compactTime(value: string | null) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function duration(chain: ChainSummary) {
  if (chain.duration_seconds == null) return 'Unavailable'
  if (chain.duration_seconds < 60) return `${Math.round(chain.duration_seconds)}s`
  if (chain.duration_seconds < 3600) return `${Math.round(chain.duration_seconds / 60)}m`
  return `${(chain.duration_seconds / 3600).toFixed(1)}h`
}

function FactRow({ label, value }: { label: string; value: ReactNode }) {
  return <div className="grid grid-cols-[120px_1fr] gap-space-sm border-b border-surface-container-highest/50 py-space-sm last:border-b-0"><dt className="font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant">{label}</dt><dd className="min-w-0 break-words font-code-sm text-on-surface">{value}</dd></div>
}

function ChainFacts({ chain, label, onSelect }: { chain: ChainSummary; label: string; onSelect: () => void }) {
  return <article className="overflow-hidden rounded-xl border border-surface-container-highest bg-surface-container shadow-sm">
    <header className="border-b border-surface-container-highest bg-surface-container-lowest p-space-lg">
      <div className="flex items-start justify-between gap-space-sm">
        <div className="min-w-0"><p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">{label}</p><strong className="mt-1 block truncate font-headline-md text-on-surface">{chain.chain_id}</strong><p className="mt-space-xs line-clamp-2 text-body-sm text-on-surface-variant">{chain.title || 'Observed title unavailable'}</p></div>
        <span className="shrink-0 rounded-full border border-surface-container-highest bg-surface-container-high px-space-sm py-space-2xs font-code-sm text-on-surface-variant">{chain.is_singleton ? 'Singleton' : 'Multi-alarm'}</span>
      </div>
    </header>
    <dl className="px-space-lg py-space-sm">
      <FactRow label="Members" value={<strong className="text-lg">{chain.member_count}</strong>} />
      <FactRow label="First alarm" value={compactTime(chain.start_time)} />
      <FactRow label="Last alarm" value={compactTime(chain.end_time)} />
      <FactRow label="Duration" value={duration(chain)} />
      <FactRow label="Audit" value={<span className="inline-flex items-center gap-1 text-on-surface-variant"><span aria-hidden="true" className="material-symbols-outlined text-[15px]">query_stats</span>Open chain to inspect persisted results</span>} />
    </dl>
    <footer className="border-t border-surface-container-highest bg-surface-container-low px-space-lg py-space-sm"><button className="inline-flex items-center gap-space-xs text-secondary hover:text-on-surface" onClick={onSelect}>Inspect chain <span aria-hidden="true">→</span></button></footer>
  </article>
}

export function CompareChainsView({ chainAId, chainBId, chains = [], onSelectChain, onChangeSelection }: CompareChainsViewProps) {
  const chainA = chains.find(chain => chain.chain_id === chainAId)
  const chainB = chains.find(chain => chain.chain_id === chainBId)
  const memberDelta = chainA && chainB ? chainA.member_count - chainB.member_count : null

  return <div className="flex w-full flex-col gap-space-md pb-12">
    <section className="flex flex-col gap-space-md rounded-xl border border-surface-container-high bg-surface-container-lowest p-space-lg shadow-md lg:flex-row lg:items-end lg:justify-between">
      <div><p className="font-label-caps text-label-caps uppercase tracking-[0.16em] text-secondary">Side-by-side inspection</p><h1 className="mt-1 font-headline-lg text-headline-lg font-bold text-on-surface">Compare observed chain facts</h1><p className="mt-space-xs max-w-2xl text-body-sm text-on-surface-variant">This view compares fields from the current snapshot only. It does not infer cross-chain direction or operational dependency.</p></div>
      <button className="inline-flex items-center justify-center gap-space-xs rounded bg-surface-container-high px-space-md py-space-xs text-on-surface hover:bg-surface-container-highest" onClick={onChangeSelection}><span aria-hidden="true" className="material-symbols-outlined text-[17px]">swap_horiz</span>Change selection</button>
    </section>

    {!chainA || !chainB ? <section role="status" className="rounded-xl border border-surface-container-highest bg-surface-container p-space-xl text-center text-on-surface-variant">Select two chains available in the current snapshot.</section> : <>
      <div className="grid grid-cols-1 gap-space-md lg:grid-cols-2">
        <ChainFacts chain={chainA} label="Chain A" onSelect={() => onSelectChain(chainA.chain_id)} />
        <ChainFacts chain={chainB} label="Chain B" onSelect={() => onSelectChain(chainB.chain_id)} />
      </div>
      <section className="grid grid-cols-1 overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-low sm:grid-cols-3">
        <div className="border-b border-surface-container-high p-space-md sm:border-b-0 sm:border-r"><small className="uppercase tracking-wider text-on-surface-variant">Member difference A − B</small><strong className="mt-1 block font-code-lg text-xl text-on-surface">{memberDelta! > 0 ? '+' : ''}{memberDelta}</strong></div>
        <div className="border-b border-surface-container-high p-space-md sm:border-b-0 sm:border-r"><small className="uppercase tracking-wider text-on-surface-variant">Chain A duration</small><strong className="mt-1 block font-code-lg text-xl text-on-surface">{duration(chainA)}</strong></div>
        <div className="p-space-md"><small className="uppercase tracking-wider text-on-surface-variant">Chain B duration</small><strong className="mt-1 block font-code-lg text-xl text-on-surface">{duration(chainB)}</strong></div>
      </section>
    </>}
  </div>
}
