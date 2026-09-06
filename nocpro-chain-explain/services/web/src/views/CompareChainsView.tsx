import { useState } from 'react'
import type { ChainSummary } from '../types'

interface CompareChainsViewProps {
  chainAId: string
  chainBId: string
  chains?: ChainSummary[]
  onSelectChain: (chainId: string) => void
  onChangeSelection: () => void
}

export function CompareChainsView({
  chainAId,
  chainBId,
  chains = [],
  onSelectChain,
  onChangeSelection,
}: CompareChainsViewProps) {
  const [differentialMode, setDifferentialMode] = useState<'WEIGHTS' | 'MEMBERSHIP' | 'CHANNELS'>('CHANNELS')

  const chainA = chains.find(c => c.chain_id === chainAId)
  const chainB = chains.find(c => c.chain_id === chainBId)

  const aAlarms = chainA ? chainA.member_count : 58
  const bAlarms = chainB ? chainB.member_count : 34
  const aConductance = 0.12
  const bConductance = 0.44

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Active Context Bar / Filter Strip */}
      <div className="flex items-center justify-between bg-surface-container px-space-md py-space-sm rounded-lg shadow-sm">
          <div className="flex items-center gap-space-xs font-code-md text-code-md text-on-surface bg-surface-container-low px-space-sm py-space-2xs rounded border border-surface-container-highest">
            <span className="material-symbols-outlined text-secondary text-[18px]">compare_arrows</span>
            <span className="font-semibold text-primary">{chainAId}</span>
            <span className="text-on-surface-variant font-label-caps uppercase text-xs">VS</span>
            <span className="font-semibold text-secondary">{chainBId}</span>
          </div>
        </div>
        <div className="flex items-center gap-space-sm">
          <button
            onClick={onChangeSelection}
            className="flex items-center gap-space-xs px-space-sm py-space-2xs bg-surface-container-high hover:bg-surface-container-highest text-on-surface rounded transition-colors text-body-sm font-body-sm font-semibold shadow-sm"
          >
            <span className="material-symbols-outlined text-[14px] text-secondary">swap_horizontal_circle</span>
            <span>Change Selection</span>
          </button>
          <div className="flex items-center bg-surface-container-lowest rounded p-space-2xs">
            <button
              onClick={() => setDifferentialMode('CHANNELS')}
              className={`px-space-xs py-space-2xs rounded font-code-sm text-code-sm ${
                differentialMode === 'CHANNELS'
                  ? 'bg-secondary-container text-on-secondary-container font-semibold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Evidence Channels
            </button>
            <button
              onClick={() => setDifferentialMode('MEMBERSHIP')}
              className={`px-space-xs py-space-2xs rounded font-code-sm text-code-sm ${
                differentialMode === 'MEMBERSHIP'
                  ? 'bg-secondary-container text-on-secondary-container font-semibold'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Membership
            </button>
          </div>
        </div>
      </div>

      {/* Side-by-Side Dual Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-space-md items-stretch">
        {/* LEFT COLUMN: Chain A */}
        <div className="flex flex-col bg-surface-container rounded-lg p-space-md space-y-space-md shadow-md border border-primary/20">
          <div className="flex items-start justify-between">
            <div className="space-y-space-2xs">
              <div className="flex items-center gap-space-sm">
                <span className="font-headline-md text-headline-md font-bold text-on-surface">
                  Chain {chainAId}
                </span>
                <span className="px-space-sm py-space-2xs bg-error-container text-error rounded font-label-caps text-label-caps uppercase tracking-wide flex items-center gap-space-2xs font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-error animate-pulse"></span>
                  Needs Attention
                </span>
              </div>
              <p className="font-body-md text-body-md text-primary font-medium">
                Interface Down / BGP Transit Peering Tear
              </p>
              <p className="font-code-sm text-code-sm text-on-surface-variant">
                Identified Root: <span className="text-on-surface font-semibold">ALM-47933128</span> (GigE0/1/0/4.100 - IP_TRANSIT_CORE)
              </p>
            </div>
            <div className="text-right">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">CONFIDENCE</span>
              <span className="font-code-lg text-code-lg text-primary font-bold">78.4%</span>
            </div>
          </div>

          {/* Quick Metrics Strip */}
          <div className="grid grid-cols-3 gap-space-xs bg-surface-container-lowest p-space-sm rounded">
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Alarms</span>
              <span className="font-code-md text-code-md text-on-surface font-bold">{aAlarms} alarms</span>
            </div>
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Duration</span>
              <span className="font-code-md text-code-md text-on-surface font-bold">22s burst</span>
            </div>
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Dominant Node</span>
              <span className="font-code-md text-code-md text-secondary font-bold">DEHL01 (92%)</span>
            </div>
          </div>

          {/* Conductance & Support Gauge */}
          <div className="bg-surface-container-low p-space-sm rounded space-y-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-error text-[16px]">warning</span>
                <span className="font-label-caps text-label-caps uppercase text-on-surface font-semibold">
                  Conductance Score (φ)
                </span>
              </div>
              <div className="flex items-center gap-space-xs">
                <span className="font-code-md text-code-md font-bold text-error">{aConductance.toFixed(2)}</span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">(Weak split risk)</span>
              </div>
            </div>
            <div className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden">
              <div className="bg-error h-full rounded" style={{ width: `${Math.round(aConductance * 100)}%` }}></div>
            </div>
            <div className="flex items-center justify-between pt-space-xs">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Min Association Support:</span>
              <span className="font-code-sm text-code-sm text-on-surface font-semibold">0.31 (Threshold: 0.50)</span>
            </div>
          </div>

          {/* Membership Breakdown */}
          <div className="space-y-space-xs">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Topology Role Allocation</span>
            <div className="grid grid-cols-4 gap-space-xs">
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-primary block font-bold">CORE</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">42</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-tertiary block font-bold">WEAK</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">2</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-secondary block font-bold">PERIPHERAL</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">12</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block font-bold">NO DATA</span>
                <span className="font-code-lg text-code-lg font-bold text-error">2</span>
              </div>
            </div>
          </div>

          {/* Multi-Evidence Channel Alignment */}
          <div className="space-y-space-xs">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Evidence Attribution Channel Weights</span>
            <div className="space-y-space-2xs font-code-sm text-code-sm">
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Graph Support (Co-occurrence)</span>
                <span className="text-secondary font-bold">0.82 (Dominant)</span>
              </div>
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Temporal Proximity (Δt ≤ 15m)</span>
                <span className="text-secondary font-bold">0.94 (Strict Burst)</span>
              </div>
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Taxonomy Multi-Evidence</span>
                <span className="text-tertiary font-bold">0.61 (Medium)</span>
              </div>
            </div>
          </div>

          <div className="pt-space-xs">
            <button
              onClick={() => onSelectChain(chainAId)}
              className="w-full py-space-xs bg-surface-container-high hover:bg-surface-bright text-secondary font-code-sm text-code-sm font-semibold rounded flex items-center justify-center gap-space-xs transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">visibility</span>
              Inspect Chain {chainAId} Details
            </button>
          </div>
        </div>

        {/* RIGHT COLUMN: Chain B */}
        <div className="flex flex-col bg-surface-container rounded-lg p-space-md space-y-space-md shadow-md border border-secondary/20">
          <div className="flex items-start justify-between">
            <div className="space-y-space-2xs">
              <div className="flex items-center gap-space-sm">
                <span className="font-headline-md text-headline-md font-bold text-on-surface">
                  Chain {chainBId}
                </span>
                <span className="px-space-sm py-space-2xs bg-secondary-container/30 text-secondary rounded font-label-caps text-label-caps uppercase tracking-wide flex items-center gap-space-2xs font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-secondary"></span>
                  Cascading Optical
                </span>
              </div>
              <p className="font-body-md text-body-md text-secondary font-medium">
                Optical DWDM Transponder Loss of Frame
              </p>
              <p className="font-code-sm text-code-sm text-on-surface-variant">
                Identified Root: <span className="text-on-surface font-semibold">ALM-47933190</span> (100G-DWDM-CH24 - SITE_DEHT01)
              </p>
            </div>
            <div className="text-right">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">CONFIDENCE</span>
              <span className="font-code-lg text-code-lg text-secondary font-bold">91.2%</span>
            </div>
          </div>

          {/* Quick Metrics Strip */}
          <div className="grid grid-cols-3 gap-space-xs bg-surface-container-lowest p-space-sm rounded">
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Alarms</span>
              <span className="font-code-md text-code-md text-on-surface font-bold">{bAlarms} alarms</span>
            </div>
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Duration</span>
              <span className="font-code-md text-code-md text-on-surface font-bold">48s burst</span>
            </div>
            <div>
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block">Dominant Node</span>
              <span className="font-code-md text-code-md text-secondary font-bold">DEHT01 (88%)</span>
            </div>
          </div>

          {/* Conductance & Support Gauge */}
          <div className="bg-surface-container-low p-space-sm rounded space-y-space-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[16px]">check_circle</span>
                <span className="font-label-caps text-label-caps uppercase text-on-surface font-semibold">
                  Conductance Score (φ)
                </span>
              </div>
              <div className="flex items-center gap-space-xs">
                <span className="font-code-md text-code-md font-bold text-secondary">{bConductance.toFixed(2)}</span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">(Stable cluster)</span>
              </div>
            </div>
            <div className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden">
              <div className="bg-secondary h-full rounded" style={{ width: `${Math.round(bConductance * 100)}%` }}></div>
            </div>
            <div className="flex items-center justify-between pt-space-xs">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Min Association Support:</span>
              <span className="font-code-sm text-code-sm text-on-surface font-semibold">0.74 (Threshold: 0.50)</span>
            </div>
          </div>

          {/* Membership Breakdown */}
          <div className="space-y-space-xs">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Topology Role Allocation</span>
            <div className="grid grid-cols-4 gap-space-xs">
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-primary block font-bold">CORE</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">28</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-tertiary block font-bold">WEAK</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">0</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-secondary block font-bold">PERIPHERAL</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface">6</span>
              </div>
              <div className="bg-surface-container-high p-space-xs rounded text-center">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant block font-bold">NO DATA</span>
                <span className="font-code-lg text-code-lg font-bold text-on-surface-variant">0</span>
              </div>
            </div>
          </div>

          {/* Multi-Evidence Channel Alignment */}
          <div className="space-y-space-xs">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Evidence Attribution Channel Weights</span>
            <div className="space-y-space-2xs font-code-sm text-code-sm">
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Graph Support (Co-occurrence)</span>
                <span className="text-secondary font-bold">0.91 (Strong)</span>
              </div>
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Temporal Proximity (Δt ≤ 15m)</span>
                <span className="text-secondary font-bold">0.89 (High)</span>
              </div>
              <div className="flex items-center justify-between p-space-xs bg-surface-container-low rounded">
                <span>Taxonomy Multi-Evidence</span>
                <span className="text-secondary font-bold">0.86 (Verified)</span>
              </div>
            </div>
          </div>

          <div className="pt-space-xs">
            <button
              onClick={() => onSelectChain(chainBId)}
              className="w-full py-space-xs bg-surface-container-high hover:bg-surface-bright text-secondary font-code-sm text-code-sm font-semibold rounded flex items-center justify-center gap-space-xs transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">visibility</span>
              Inspect Chain {chainBId} Details
            </button>
          </div>
        </div>
      </div>

      {/* Differential Synthesis & Operator Action Banner */}
      <div className="bg-surface-container rounded-lg p-space-md shadow-md border border-tertiary/20 flex flex-col md:flex-row items-start md:items-center justify-between gap-space-md">
        <div className="flex items-start gap-space-md">
          <div className="w-10 h-10 rounded-lg bg-tertiary-container/30 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-tertiary text-[24px]">insights</span>
          </div>
          <div className="flex flex-col gap-space-2xs">
            <span className="font-headline-md text-headline-md font-bold text-on-surface">
              Differential Coupling Hypothesis
            </span>
            <p className="font-body-sm text-body-sm text-on-surface-variant max-w-3xl">
              Cross-cluster analysis shows <strong className="text-on-surface font-semibold">{chainAId}</strong> and <strong className="text-on-surface font-semibold">{chainBId}</strong> share transit link interface <code className="text-secondary font-code-sm bg-surface-container-lowest px-space-xs py-0.5 rounded">DEH-GW01::HundredGigE0/0/0/2</code>. The temporal delay is <span className="text-tertiary font-bold font-code-sm">+1.82s</span>, indicating {chainAId} is the upstream root cause of {chainBId}.
            </p>
          </div>
        </div>
        <button
          onClick={() => onSelectChain(chainAId)}
          className="px-space-lg py-space-sm bg-primary text-on-primary font-headline-md text-body-sm font-semibold rounded hover:brightness-110 flex items-center gap-space-xs transition-all shadow-md shrink-0"
        >
          <span className="material-symbols-outlined text-[18px]">account_tree</span>
          Correlate Combined Hierarchy
        </button>
      </div>
    </div>
  )
}
