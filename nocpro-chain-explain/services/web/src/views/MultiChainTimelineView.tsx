import { useMemo, useState } from 'react'

import type { ChainSummary } from '../types'

interface MultiChainTimelineViewProps {
  chains?: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onCompareChains: (chainA: string, chainB: string) => void
  selectedChainId?: string | null
}

function parsedTime(value: string | null) {
  if (!value) return null
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? null : timestamp
}

function formatTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().slice(11, 19)
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return 'Unavailable'
  return seconds < 60 ? `${Math.round(seconds)}s` : `${Math.round(seconds / 60)}m`
}

export function MultiChainTimelineView({ chains = [], onSelectChain, onCompareChains }: MultiChainTimelineViewProps) {
  const [selected, setSelected] = useState<string[]>([])
  const timed = useMemo(() => chains.flatMap(chain => {
    const startMs = parsedTime(chain.start_time)
    const endMs = parsedTime(chain.end_time)
    return startMs == null || endMs == null ? [] : [{ startMs, endMs: Math.max(startMs, endMs) }]
  }), [chains])
  const minTime = timed.length ? Math.min(...timed.map(chain => chain.startMs)) : null
  const maxTime = timed.length ? Math.max(...timed.map(chain => chain.endMs)) : null
  const span = minTime != null && maxTime != null ? Math.max(1, maxTime - minTime) : 1
  const toggle = (chainId: string) => setSelected(current => current.includes(chainId)
    ? current.filter(value => value !== chainId)
    : current.length >= 2 ? [current[1], chainId] : [...current, chainId])

  return <div className="w-full flex flex-col gap-space-md pb-12">
    <div className="bg-surface-container-lowest rounded-lg px-space-lg py-space-sm flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm">
      <div><h1 className="font-headline-md font-bold text-on-surface">Multi-chain timeline</h1><p className="text-body-sm text-on-surface-variant">Canonical first and last member timestamps; no inferred causal ordering.</p></div>
      <button disabled={selected.length !== 2} onClick={() => selected.length === 2 && onCompareChains(selected[0], selected[1])} className="rounded bg-secondary-container px-space-md py-space-xs text-on-secondary-container disabled:opacity-40">Isolate Pair</button>
    </div>
    <div className="bg-surface-container-low rounded-lg border border-surface-container-high overflow-x-auto"><div className="min-w-[720px]">
      {chains.length === 0 && <p className="p-space-xl text-center text-on-surface-variant">No chains are available for this snapshot.</p>}
      {chains.map(chain => {
        const startMs = parsedTime(chain.start_time)
        const endMs = parsedTime(chain.end_time)
        const available = startMs != null && endMs != null && minTime != null
        const left = available ? ((startMs - minTime) / span) * 100 : 0
        const width = available ? Math.max(0.75, ((Math.max(startMs, endMs) - startMs) / span) * 100) : 0
        return <div key={chain.chain_id} className="grid grid-cols-[260px_1fr] border-b border-surface-container-highest/40 last:border-b-0">
          <div className="flex items-center gap-space-sm border-r border-surface-container-highest p-space-sm">
            <input aria-label={`Select ${chain.chain_id} for comparison`} type="checkbox" checked={selected.includes(chain.chain_id)} onChange={() => toggle(chain.chain_id)} />
            <button className="text-left" onClick={() => onSelectChain(chain.chain_id)}><strong className="block text-secondary">{chain.chain_id}</strong><small className="text-on-surface-variant">{chain.member_count} alarms · {formatDuration(chain.duration_seconds)}</small></button>
          </div>
          <div className="relative min-h-16 p-space-sm">
            {available ? <>
              <div className="absolute top-6 h-5 min-w-1 rounded bg-secondary/35 border border-secondary" style={{ left: `${left}%`, width: `${width}%` }} />
              <div className="flex justify-between text-code-sm font-code-sm text-on-surface-variant"><span>{formatTime(chain.start_time!)}</span><span>{formatTime(chain.end_time!)}</span></div>
            </> : <span className="inline-flex h-full items-center text-on-surface-variant">Temporal range unavailable</span>}
          </div>
        </div>
      })}
    </div></div>
  </div>
}
