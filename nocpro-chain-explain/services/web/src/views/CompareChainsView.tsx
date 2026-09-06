import type { ChainSummary } from '../types'

interface CompareChainsViewProps {
  chainAId: string
  chainBId: string
  chains?: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onChangeSelection: () => void
}

function temporalRange(chain: ChainSummary) {
  if (!chain.start_time || !chain.end_time) return 'Unavailable'
  return `${chain.start_time} → ${chain.end_time}`
}

function duration(chain: ChainSummary) {
  if (chain.duration_seconds == null) return 'Unavailable'
  return chain.duration_seconds < 60 ? `${Math.round(chain.duration_seconds)}s` : `${Math.round(chain.duration_seconds / 60)}m`
}

function ChainFacts({ chain, onSelect }: { chain: ChainSummary; onSelect: () => void }) {
  return <article className="rounded-lg border border-surface-container-highest bg-surface-container p-space-lg shadow-sm">
    <header className="flex items-start justify-between gap-space-sm border-b border-surface-container-highest pb-space-sm">
      <div><strong className="font-headline-md text-on-surface">{chain.chain_id}</strong><p className="mt-space-2xs text-body-sm text-on-surface-variant">{chain.title || 'Title unavailable'}</p></div>
      <span className="rounded bg-surface-container-high px-space-xs py-space-2xs font-code-sm text-on-surface-variant">{chain.is_singleton ? 'Singleton' : 'Multi-alarm'}</span>
    </header>
    <dl className="mt-space-md grid grid-cols-1 gap-space-sm font-code-sm sm:grid-cols-2">
      <div><dt className="text-on-surface-variant">Members</dt><dd className="font-bold text-on-surface">{chain.member_count}</dd></div>
      <div><dt className="text-on-surface-variant">Duration</dt><dd className="font-bold text-on-surface">{duration(chain)}</dd></div>
      <div className="sm:col-span-2"><dt className="text-on-surface-variant">Observed temporal range</dt><dd className="break-all text-on-surface">{temporalRange(chain)}</dd></div>
      <div className="sm:col-span-2"><dt className="text-on-surface-variant">Structural Audit</dt><dd className="text-on-surface">Open the chain to run or inspect its persisted Audit artifact.</dd></div>
    </dl>
    <button className="mt-space-md rounded border border-secondary/30 px-space-md py-space-xs text-secondary" onClick={onSelect}>Inspect chain →</button>
  </article>
}

export function CompareChainsView({ chainAId, chainBId, chains = [], onSelectChain, onChangeSelection }: CompareChainsViewProps) {
  const chainA = chains.find(chain => chain.chain_id === chainAId)
  const chainB = chains.find(chain => chain.chain_id === chainBId)
  return <div className="flex w-full flex-col gap-space-md pb-12">
    <div className="flex flex-col gap-space-sm rounded-lg bg-surface-container-lowest px-space-lg py-space-sm sm:flex-row sm:items-center sm:justify-between">
      <div><h1 className="font-headline-md font-bold text-on-surface">Compare observed chain facts</h1><p className="text-body-sm text-on-surface-variant">No cross-chain causal direction is inferred.</p></div>
      <button className="rounded bg-surface-container-high px-space-md py-space-xs text-on-surface" onClick={onChangeSelection}>Change selection</button>
    </div>
    {!chainA || !chainB ? <section role="status" className="rounded-lg border border-surface-container-highest bg-surface-container p-space-xl text-center text-on-surface-variant">Select two chains available in the current snapshot.</section> : <div className="grid grid-cols-1 gap-space-md lg:grid-cols-2">
      <ChainFacts chain={chainA} onSelect={() => onSelectChain(chainA.chain_id)} />
      <ChainFacts chain={chainB} onSelect={() => onSelectChain(chainB.chain_id)} />
    </div>}
  </div>
}
