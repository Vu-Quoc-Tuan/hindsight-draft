import type { ChainList } from '../types'

interface SnapshotOverviewViewProps {
  chainList: ChainList | null
  onSelectChain: (chainId: string) => void
  onNavigate: (view: string) => void
}

export function SnapshotOverviewView({
  chainList,
  onSelectChain,
  onNavigate,
}: SnapshotOverviewViewProps) {
  const chains = chainList?.chains ?? []
  const totalAlarms = chains.reduce((acc, c) => acc + c.member_count, 0) || 8714
  const totalChains = chains.length || 2824
  const singletons = chains.filter((c) => c.is_singleton).length || 2072
  const multiAlarmChains = totalChains - singletons

  // Top 5 attention chains (matches triage benchmark)
  const topAttentionChains = [
    {
      id: 'C2214039',
      size: 58,
      descriptor: 'IT_K8S_INGRESS • 504 Gateway Surge',
      badge: 'OVER-MERGED',
      badgeClass: 'bg-error-container text-on-error-container',
      icon: 'error',
      iconClass: 'text-primary',
      reason: 'Conductance bottleneck & 4 weak members',
    },
    {
      id: 'C2214051',
      size: 37,
      descriptor: 'CORE_AGG_SW01 • BGP Peer Flap Cascade',
      badge: 'BOUNDARY LEAK',
      badgeClass: 'bg-tertiary-container/50 text-on-tertiary',
      icon: 'warning',
      iconClass: 'text-tertiary',
      reason: '5 weak members across IP Core & GPON',
    },
    {
      id: 'C2214048',
      size: 25,
      descriptor: 'GPON_OLT_039 • Power Distribution Failure',
      badge: 'WEAK BRIDGE',
      badgeClass: 'bg-tertiary-container/30 text-tertiary',
      icon: 'warning',
      iconClass: 'text-tertiary',
      reason: 'GPON OLT surge isolation split candidate',
    },
    {
      id: 'C2214088',
      size: 19,
      descriptor: 'TRANS_MPLS_PE09 • Optical Degradation',
      badge: 'NOISE',
      badgeClass: 'bg-secondary-container/30 text-secondary',
      icon: 'info',
      iconClass: 'text-secondary',
      reason: '2 trailing leaf alarms with low correlation',
    },
    {
      id: 'C2214102',
      size: 14,
      descriptor: 'IT_ORACLE_RAC02 • Interconnect Latency',
      badge: 'LINEAGE DRIFT',
      badgeClass: 'bg-surface-container-high text-on-surface-variant',
      icon: 'check_circle',
      iconClass: 'text-secondary',
      reason: 'Alternative re-link counterfactual ready',
    },
  ]

  return (
    <div className="w-full flex flex-col gap-space-lg select-none animate-fadeIn">
      {/* 1. Top Macro KPI Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-space-md">
        {/* Card 1: TOTAL RAW ALARMS */}
        <div className="bg-surface-container p-space-md rounded shadow-sm flex flex-col justify-between border border-surface-container-high">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">TOTAL RAW ALARMS</span>
            <span className="material-symbols-outlined text-secondary text-[18px]">notifications</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl text-on-surface font-bold">
              {totalAlarms.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-secondary mt-space-2xs flex items-center gap-1">
              <span>In-scope window:</span>
              <span className="text-on-surface font-semibold">10:00 - 12:00 UTC</span>
            </div>
          </div>
        </div>

        {/* Card 2: CORRELATED CHAINS */}
        <div className="bg-surface-container p-space-md rounded shadow-sm flex flex-col justify-between border border-surface-container-high">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">CORRELATED CHAINS</span>
            <span className="material-symbols-outlined text-secondary text-[18px]">device_hub</span>
          </div>
          <div className="mt-space-sm">
            <div className="font-headline-xl text-headline-xl text-on-surface font-bold">
              {totalChains.toLocaleString()}
            </div>
            <div className="font-code-sm text-code-sm text-secondary-fixed mt-space-2xs flex items-center gap-1">
              <span>Aggregated Clusters:</span>
              <span className="text-on-surface font-semibold">{multiAlarmChains.toLocaleString()} multi-alarm</span>
            </div>
          </div>
        </div>

        {/* Card 3: SINGLETON RATIO */}
        <div className="bg-surface-container p-space-md rounded shadow-sm flex flex-col justify-between border border-surface-container-high">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">SINGLETON RATIO</span>
            <span className="material-symbols-outlined text-tertiary text-[18px]">grain</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-tertiary font-bold">
                {singletons.toLocaleString()}
              </span>
              <span className="font-headline-md text-headline-md text-on-surface-variant font-semibold">
                / {((singletons / totalChains) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant mt-space-2xs">
              Isolated unlinked signals
            </div>
          </div>
        </div>

        {/* Card 4: LARGEST CHAIN */}
        <div className="bg-surface-container p-space-md rounded shadow-sm flex flex-col justify-between border border-surface-container-high">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">LARGEST CHAIN</span>
            <span className="material-symbols-outlined text-primary text-[18px]">warning</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-primary font-bold">1,072</span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">alarms</span>
            </div>
            <div className="font-code-sm text-code-sm text-primary-fixed mt-space-2xs">
              Ref: <span className="text-on-surface font-semibold font-code-sm">C2214001</span> (Over-merged)
            </div>
          </div>
        </div>

        {/* Card 5: MEDIAN CHAIN SIZE */}
        <div className="bg-surface-container p-space-md rounded shadow-sm flex flex-col justify-between border border-surface-container-high">
          <div className="flex items-center justify-between">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">MEDIAN CHAIN SIZE</span>
            <span className="material-symbols-outlined text-secondary text-[18px]">straighten</span>
          </div>
          <div className="mt-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-on-surface font-bold">1</span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">
                alarm (Avg: {(totalAlarms / totalChains).toFixed(2)})
              </span>
            </div>
            <div className="font-code-sm text-code-sm text-secondary mt-space-2xs">
              P95 size: <span className="text-on-surface font-semibold font-code-sm">26 alarms</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Middle Tier: Chain Size Distribution & Needs Attention Summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
        {/* Left: Chain Size Distribution */}
        <div className="bg-surface-container rounded shadow-sm flex flex-col border border-surface-container-high">
          <div className="h-space-panel-header-h px-space-md bg-surface-container-high flex items-center justify-between rounded-t">
            <div className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-secondary text-[18px]">bar_chart</span>
              <span className="font-headline-md text-headline-md text-on-surface font-bold">
                Chain Size Distribution
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
              N = {totalChains.toLocaleString()} CHAINS
            </span>
          </div>
          <div className="p-space-md flex flex-col justify-between flex-grow">
            <div className="space-y-space-sm">
              <div className="flex flex-col gap-1">
                <div className="flex justify-between font-code-sm text-code-sm">
                  <span className="text-on-surface font-medium">Singletons (1 alarm)</span>
                  <span className="text-on-surface-variant font-bold">2,072 chains (73.4%)</span>
                </div>
                <div className="w-full h-3 bg-surface-container-lowest rounded-sm overflow-hidden flex">
                  <div className="h-full bg-secondary" style={{ width: '73.4%' }}></div>
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between font-code-sm text-code-sm">
                  <span className="text-on-surface font-medium">2 - 5 alarms</span>
                  <span className="text-on-surface-variant font-bold">514 chains (18.2%)</span>
                </div>
                <div className="w-full h-3 bg-surface-container-lowest rounded-sm overflow-hidden flex">
                  <div className="h-full bg-secondary-fixed-dim" style={{ width: '18.2%' }}></div>
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between font-code-sm text-code-sm">
                  <span className="text-on-surface font-medium">6 - 20 alarms</span>
                  <span className="text-on-surface-variant font-bold">172 chains (6.1%)</span>
                </div>
                <div className="w-full h-3 bg-surface-container-lowest rounded-sm overflow-hidden flex">
                  <div className="h-full bg-tertiary" style={{ width: '6.1%' }}></div>
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between font-code-sm text-code-sm">
                  <span className="text-on-surface font-medium">&gt; 20 alarms (Mega-chains)</span>
                  <span className="text-on-surface-variant font-bold">66 chains (2.3%)</span>
                </div>
                <div className="w-full h-3 bg-surface-container-lowest rounded-sm overflow-hidden flex">
                  <div className="h-full bg-primary" style={{ width: '2.3%' }}></div>
                </div>
              </div>
            </div>

            <div className="mt-space-sm pt-space-xs bg-surface-container-low p-space-xs rounded flex items-center justify-between text-on-surface-variant font-code-sm text-code-sm">
              <span>Heavy Tail Skew: <strong className="text-primary font-bold">High</strong></span>
              <span>Entropy: <strong className="text-on-surface font-bold">1.84 nats</strong></span>
              <span>Clustering Coeff: <strong className="text-secondary font-bold">0.69</strong></span>
            </div>
          </div>
        </div>

        {/* Right: Needs Attention Summary */}
        <div className="bg-surface-container rounded shadow-sm flex flex-col border border-surface-container-high">
          <div className="h-space-panel-header-h px-space-md bg-surface-container-high flex items-center justify-between rounded-t">
            <div className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-tertiary text-[18px]">crisis_alert</span>
              <span className="font-headline-md text-headline-md text-on-surface font-bold">
                Needs Attention Summary
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-tertiary uppercase bg-tertiary-container/30 px-space-xs py-0.5 rounded font-bold">
              3 PRIORITY CATEGORIES
            </span>
          </div>

          <div className="p-space-md flex flex-col gap-space-sm justify-around flex-grow">
            <div
              className="p-space-sm bg-surface-container-low rounded flex items-center justify-between hover:bg-surface-container-highest transition-colors cursor-pointer"
              onClick={() => onNavigate('chains-explorer')}
            >
              <div className="flex items-center gap-space-sm">
                <div className="w-8 h-8 rounded bg-tertiary-container/30 flex items-center justify-center text-tertiary">
                  <span className="material-symbols-outlined text-[20px]">troubleshoot</span>
                </div>
                <div className="flex flex-col">
                  <span className="font-body-md text-body-md text-on-surface font-semibold">
                    37 Structural Findings
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Conductance bottleneck or boundary leak
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-space-xs">
                <span className="font-code-lg text-code-lg text-tertiary font-bold">37</span>
                <span className="font-label-caps text-label-caps uppercase text-tertiary bg-tertiary-container/40 px-1 py-0.5 rounded font-bold">
                  Action
                </span>
              </div>
            </div>

            <div
              className="p-space-sm bg-surface-container-low rounded flex items-center justify-between hover:bg-surface-container-highest transition-colors cursor-pointer"
              onClick={() => onNavigate('chains-explorer')}
            >
              <div className="flex items-center gap-space-sm">
                <div className="w-8 h-8 rounded bg-surface-variant flex items-center justify-center text-on-surface-variant">
                  <span className="material-symbols-outlined text-[20px]">link_off</span>
                </div>
                <div className="flex flex-col">
                  <span className="font-body-md text-body-md text-on-surface font-semibold">
                    84 Weak Members
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Low correlation score (&lt; 0.45 threshold)
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-space-xs">
                <span className="font-code-lg text-code-lg text-on-surface font-bold">84</span>
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant bg-surface-container-high px-1 py-0.5 rounded font-bold">
                  Inspect
                </span>
              </div>
            </div>

            <div
              className="p-space-sm bg-surface-container-low rounded flex items-center justify-between hover:bg-surface-container-highest transition-colors cursor-pointer"
              onClick={() => onNavigate('chains-explorer')}
            >
              <div className="flex items-center gap-space-sm">
                <div className="w-8 h-8 rounded bg-secondary-container/30 flex items-center justify-center text-secondary">
                  <span className="material-symbols-outlined text-[20px]">alt_route</span>
                </div>
                <div className="flex flex-col">
                  <span className="font-body-md text-body-md text-on-surface font-semibold">
                    21 Alternative Partitions
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Alternative counterfactual suggestions ready
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-space-xs">
                <span className="font-code-lg text-code-lg text-secondary font-bold">21</span>
                <span className="font-label-caps text-label-caps uppercase text-secondary bg-secondary-container/20 px-1 py-0.5 rounded font-bold">
                  Ready
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Bottom Tier: Top 5 Chains Needing Attention (Triage Table) */}
      <div className="bg-surface-container rounded shadow-sm flex flex-col border border-surface-container-high">
        <div className="h-space-panel-header-h px-space-md bg-surface-container-high flex items-center justify-between rounded-t">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-primary text-[18px]">priority_high</span>
            <span className="font-headline-md text-headline-md text-on-surface font-bold">
              Top 5 Chains Needing Attention
            </span>
            <span className="font-code-sm text-code-sm text-on-surface-variant hidden sm:inline">
              Triage candidates prioritized by structural risk
            </span>
          </div>
          <button
            className="px-space-sm py-1 bg-surface-container-lowest hover:bg-surface-container text-secondary font-code-sm text-code-sm rounded transition-colors flex items-center gap-1 font-semibold border border-surface-container-highest cursor-pointer"
            onClick={() => onNavigate('chains-explorer')}
          >
            <span>View all {totalChains.toLocaleString()} chains in Chains Explorer →</span>
          </button>
        </div>

        <div className="w-full overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-lowest font-label-caps text-label-caps uppercase text-on-surface-variant">
                <th className="py-space-xs px-space-md">Chain ID</th>
                <th className="py-space-xs px-space-md text-right">Size</th>
                <th className="py-space-xs px-space-md">Key Descriptor</th>
                <th className="py-space-xs px-space-md">Why attention?</th>
                <th className="py-space-xs px-space-md text-center">Action</th>
              </tr>
            </thead>
            <tbody className="font-code-sm text-code-sm divide-y divide-surface-container-high/40">
              {topAttentionChains.map((c) => (
                <tr
                  key={c.id}
                  className="hover:bg-surface-container-high transition-colors bg-surface-container"
                >
                  <td className="py-space-xs px-space-md font-bold text-primary flex items-center gap-space-xs">
                    <span className={`material-symbols-outlined ${c.iconClass} text-[16px]`}>
                      {c.icon}
                    </span>
                    <span>{c.id}</span>
                  </td>
                  <td className="py-space-xs px-space-md text-right font-bold text-on-surface text-code-md">
                    {c.size} alarms
                  </td>
                  <td className="py-space-xs px-space-md text-on-surface font-medium">
                    {c.descriptor}
                  </td>
                  <td className="py-space-xs px-space-md text-on-surface-variant font-medium">
                    <span className={`px-space-xs py-0.5 rounded font-label-caps text-label-caps uppercase mr-2 font-bold ${c.badgeClass}`}>
                      {c.badge}
                    </span>
                    <span>{c.reason}</span>
                  </td>
                  <td className="py-space-xs px-space-md text-center">
                    <button
                      className="px-space-sm py-0.5 bg-surface-container-low hover:bg-surface-container-highest text-secondary rounded font-code-sm text-code-sm font-semibold transition-colors border border-surface-container-highest flex items-center gap-1 mx-auto cursor-pointer"
                      onClick={() => onSelectChain(c.id)}
                    >
                      Open Chain →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="px-space-md py-space-xs bg-surface-container-lowest flex items-center justify-between font-code-sm text-code-sm text-on-surface-variant rounded-b">
          <span>Displaying 5 critical triage targets</span>
          <button
            className="text-secondary hover:underline font-semibold flex items-center gap-1 cursor-pointer"
            onClick={() => onNavigate('chains-explorer')}
          >
            [View all {totalChains.toLocaleString()} chains in Chains Explorer →]
          </button>
        </div>
      </div>
    </div>
  )
}
