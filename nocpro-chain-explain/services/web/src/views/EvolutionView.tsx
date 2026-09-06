import { useState } from 'react'
import type { ChainAnalysis } from '../types'
import { EvolutionPanel } from '../EvolutionPanel'
import type { MutationSpec } from '../components/OperatorValidationModal'

interface EvolutionViewProps {
  analysis: ChainAnalysis
  onExecutePartition?: (spec: MutationSpec) => void
}

export function EvolutionView({
  analysis,
  onExecutePartition,
}: EvolutionViewProps) {
  const [viewMode, setViewMode] = useState<'TIMELINE' | 'LINEAGE_DAG'>('TIMELINE')

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Sub-navigation Tabs Bar */}
      <div className="w-full bg-surface-container-lowest px-space-md py-space-xs rounded-lg shadow-sm flex items-center justify-between gap-space-md">
        <div className="flex items-center bg-surface-container-low p-1 rounded-lg gap-1">
          <button
            onClick={() => setViewMode('TIMELINE')}
            className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              viewMode === 'TIMELINE'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">timeline</span>
            <span>Incident Timeline</span>
          </button>
          <button
            onClick={() => setViewMode('LINEAGE_DAG')}
            className={`px-3 py-1.5 rounded-md font-code-sm text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              viewMode === 'LINEAGE_DAG'
                ? 'bg-secondary-container text-on-secondary-container shadow-xs'
                : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">account_tree</span>
            <span>Lineage DAG &amp; Transition WHY</span>
          </button>
        </div>
      </div>

      {viewMode === 'LINEAGE_DAG' ? (
        <div className="bg-surface-container rounded-lg p-space-lg shadow-md">
          <EvolutionPanel chainId={analysis.chain_id} initialResult={(analysis as any).evolution} />
        </div>
      ) : (
        <>
          {/* Top 4 Epoch KPI Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-space-md">
            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-secondary"></div>
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold tracking-wider">
                  Genesis Epoch
                </span>
                <span className="material-symbols-outlined text-secondary text-[18px]">flag</span>
              </div>
              <div className="mt-space-xs">
                <div className="font-code-lg text-code-lg text-on-surface font-bold">Snapshot S100</div>
                <div className="font-code-sm text-code-sm text-on-surface-variant mt-space-2xs">
                  10:00:00 UTC • 42 Alarms Base
                </div>
              </div>
              <div className="mt-space-sm flex items-center justify-between font-code-sm text-code-sm">
                <span className="text-on-surface-variant">Established by:</span>
                <span className="text-secondary font-semibold">DEHL01-CR01 Fiber Outage</span>
              </div>
            </div>

            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-tertiary"></div>
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold tracking-wider">
                  Expansion Velocity
                </span>
                <span className="material-symbols-outlined text-tertiary text-[18px]">trending_up</span>
              </div>
              <div className="mt-space-xs">
                <div className="font-code-lg text-code-lg text-tertiary font-bold">+16 Alarms (+38.1%)</div>
                <div className="font-code-sm text-code-sm text-on-surface-variant mt-space-2xs">
                  From S100 (42) → S102 (58)
                </div>
              </div>
              <div className="mt-space-sm flex items-center justify-between font-code-sm text-code-sm">
                <span className="text-on-surface-variant">Cascade Rate:</span>
                <span className="text-tertiary font-semibold">+8 alarms / 15m epoch</span>
              </div>
            </div>

            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-primary-container"></div>
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold tracking-wider">
                  Active Epoch (S102)
                </span>
                <span className="material-symbols-outlined text-primary text-[18px]">call_split</span>
              </div>
              <div className="mt-space-xs">
                <div className="font-code-lg text-code-lg text-primary font-bold">Split Candidate</div>
                <div className="font-code-sm text-code-sm text-on-surface-variant mt-space-2xs">
                  Weak Link Detected (Conductance: 0.11)
                </div>
              </div>
              <div className="mt-space-sm flex items-center gap-space-xs">
                <span className="w-2 h-2 rounded-full bg-primary-container animate-ping"></span>
                <span className="font-code-sm text-code-sm text-primary font-semibold">58 ALARMS (MAX SIZE)</span>
              </div>
            </div>

            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between shadow-sm relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-secondary-fixed"></div>
              <div className="flex items-center justify-between">
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold tracking-wider">
                  Projected Evolution (S103)
                </span>
                <span className="material-symbols-outlined text-secondary-fixed text-[18px]">schema</span>
              </div>
              <div className="mt-space-xs">
                <div className="font-code-lg text-code-lg text-on-surface font-bold">Partition → 2 Subchains</div>
                <div className="font-code-sm text-code-sm text-secondary-fixed mt-space-2xs">
                  Subchain A (Core) + Subchain B (Access)
                </div>
              </div>
              <div className="mt-space-sm flex items-center justify-between font-code-sm text-code-sm">
                <span className="text-on-surface-variant">Stability Confidence:</span>
                <span className="text-secondary font-bold">96.4% Projected</span>
              </div>
            </div>
          </div>

          {/* Chronological Stepper Timeline (Epoch S100 -> S103) */}
          <div className="bg-surface-container rounded p-space-md shadow-sm flex flex-col gap-space-sm">
            <div className="flex items-center justify-between flex-wrap gap-space-md">
              <div>
                <div className="flex items-center gap-space-xs">
                  <span className="material-symbols-outlined text-secondary text-[20px]">timeline</span>
                  <h2 className="font-headline-md text-headline-md font-bold text-on-surface leading-tight">
                    Chronological Chain Lineage Across Epochs
                  </h2>
                </div>
                <p className="font-body-sm text-body-sm text-on-surface-variant mt-0.5">
                  Historical progression and chain accretion across Epochs (S100 Genesis → S101 Expansion → S102 Active → S103 Projected)
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-space-md mt-space-sm">
              {/* Epoch S100 */}
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-space-md flex flex-col justify-between">
                <div className="flex items-center justify-between pb-space-xs border-b border-surface-container-highest">
                  <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary font-label-caps text-label-caps uppercase rounded font-bold">
                    EPOCH S100
                  </span>
                  <span className="font-code-sm text-code-sm text-secondary font-bold">42 Alarms</span>
                </div>
                <div className="py-space-sm flex flex-col gap-space-xs font-body-sm text-body-sm text-on-surface-variant">
                  <span className="text-on-surface font-semibold">Genesis / New Chain</span>
                  <p>Root optical failure triggers core transport alarms on DEHL01-CR01. Clean cluster formed.</p>
                  <div className="bg-surface-container p-space-xs rounded font-code-sm text-code-sm flex justify-between">
                    <span>Conductance:</span>
                    <span className="text-secondary font-bold">0.84 (Strong)</span>
                  </div>
                </div>
              </div>

              {/* Epoch S101 */}
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-space-md flex flex-col justify-between">
                <div className="flex items-center justify-between pb-space-xs border-b border-surface-container-highest">
                  <span className="px-space-xs py-space-2xs bg-tertiary-container/30 text-tertiary font-label-caps text-label-caps uppercase rounded font-bold">
                    EPOCH S101
                  </span>
                  <span className="font-code-sm text-code-sm text-tertiary font-bold">51 Alarms (+9)</span>
                </div>
                <div className="py-space-sm flex flex-col gap-space-xs font-body-sm text-body-sm text-on-surface-variant">
                  <span className="text-on-surface font-semibold">Growth & Expansion</span>
                  <p>Protocol teardown propagates across BGP and OSPF neighbors to Site DEHT01.</p>
                  <div className="bg-surface-container p-space-xs rounded font-code-sm text-code-sm flex justify-between">
                    <span>Conductance:</span>
                    <span className="text-tertiary font-bold">0.48 (Degrading)</span>
                  </div>
                </div>
              </div>

              {/* Epoch S102 (Active) */}
              <div className="bg-surface-container-high border-2 border-primary-container rounded p-space-md flex flex-col justify-between relative shadow-md">
                <div className="flex items-center justify-between pb-space-xs border-b border-surface-container-highest">
                  <span className="px-space-xs py-space-2xs bg-primary-container/20 text-primary font-label-caps text-label-caps uppercase rounded font-bold">
                    EPOCH S102 (ACTIVE)
                  </span>
                  <span className="font-code-sm text-code-sm text-primary font-bold">58 Alarms (+7)</span>
                </div>
                <div className="py-space-sm flex flex-col gap-space-xs font-body-sm text-body-sm text-on-surface">
                  <span className="text-primary font-bold">Split Candidate / Weak Link</span>
                  <p>Weak bridging conductance between Core and Access tail. Exceeds single-chain size.</p>
                  <div className="bg-surface-container-lowest p-space-xs rounded font-code-sm text-code-sm flex justify-between">
                    <span>Cut Conductance:</span>
                    <span className="text-primary font-bold">0.11 (SPLIT CRITICAL)</span>
                  </div>
                </div>
              </div>

              {/* Epoch S103 (Projected) */}
              <div className="bg-surface-container-low border border-dashed border-surface-variant rounded p-space-md flex flex-col justify-between opacity-90 hover:opacity-100 transition-opacity">
                <div className="flex items-center justify-between pb-space-xs border-b border-surface-container-highest">
                  <span className="px-space-xs py-space-2xs bg-surface-container-highest text-on-surface-variant font-label-caps text-label-caps uppercase rounded font-bold">
                    EPOCH S103 (PROJECTED)
                  </span>
                  <span className="font-code-sm text-code-sm text-secondary-fixed font-bold">34 + 24 Alarms</span>
                </div>
                <div className="py-space-sm flex flex-col gap-space-xs font-body-sm text-body-sm text-on-surface-variant">
                  <span className="text-secondary-fixed font-semibold">Partition into 2 Subchains</span>
                  <p>Fission execution separates Core DWDM cluster from Access edge.</p>
                  <div className="bg-surface-container p-space-xs rounded font-code-sm text-code-sm flex justify-between">
                    <span>Post-Split Φ:</span>
                    <span className="text-secondary font-bold">0.91 & 0.88</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Lineage State Transition & Member Drift Table */}
          <div className="bg-surface-container rounded p-space-md shadow-sm">
            <div className="flex items-center justify-between mb-space-sm">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-secondary text-[18px]">table_chart</span>
                <h3 className="font-body-md text-body-md font-bold text-on-surface">
                  Lineage State Transition & Member Drift Matrix
                </h3>
              </div>
              <span className="font-code-sm text-code-sm text-on-surface-variant">Epoch Step: 15 Minutes</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left font-code-sm text-code-sm">
                <thead className="bg-surface-container-low text-on-surface-variant uppercase font-label-caps text-label-caps border-b border-surface-container-highest">
                  <tr>
                    <th className="py-space-xs px-space-sm">Epoch Transition</th>
                    <th className="py-space-xs px-space-sm">Timestamp</th>
                    <th className="py-space-xs px-space-sm">Alarm Delta</th>
                    <th className="py-space-xs px-space-sm">Conductance Drift</th>
                    <th className="py-space-xs px-space-sm">Triggering Root Cause / Evidence</th>
                    <th className="py-space-xs px-space-sm">Lineage Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-highest">
                  <tr className="hover:bg-surface-container-high transition-colors">
                    <td className="py-space-sm px-space-sm font-bold text-secondary">S099 → S100</td>
                    <td className="py-space-sm px-space-sm text-on-surface-variant">10:00:00 UTC</td>
                    <td className="py-space-sm px-space-sm font-semibold text-on-surface">0 → 42 (+42)</td>
                    <td className="py-space-sm px-space-sm text-secondary">0.00 → 0.84</td>
                    <td className="py-space-sm px-space-sm text-on-surface">Genesis event ALM-47933128 [Port Down DEHL01-CR01]</td>
                    <td className="py-space-sm px-space-sm">
                      <span className="px-space-xs py-space-2xs bg-secondary-container/20 text-secondary rounded font-label-caps uppercase font-bold">
                        GENESIS CREATION
                      </span>
                    </td>
                  </tr>
                  <tr className="hover:bg-surface-container-high transition-colors">
                    <td className="py-space-sm px-space-sm font-bold text-tertiary">S100 → S101</td>
                    <td className="py-space-sm px-space-sm text-on-surface-variant">10:15:00 UTC</td>
                    <td className="py-space-sm px-space-sm font-semibold text-tertiary">42 → 51 (+9)</td>
                    <td className="py-space-sm px-space-sm text-tertiary">0.84 → 0.48</td>
                    <td className="py-space-sm px-space-sm text-on-surface">BGP & OSPF tear cascading to transit links (Site DEHT01)</td>
                    <td className="py-space-sm px-space-sm">
                      <span className="px-space-xs py-space-2xs bg-tertiary-container/30 text-tertiary rounded font-label-caps uppercase font-bold">
                        EXPANSION (GROWTH)
                      </span>
                    </td>
                  </tr>
                  <tr className="hover:bg-surface-container-high transition-colors bg-primary-container/10">
                    <td className="py-space-sm px-space-sm font-bold text-primary">S101 → S102 (Active)</td>
                    <td className="py-space-sm px-space-sm text-on-surface font-semibold">10:30:00 UTC</td>
                    <td className="py-space-sm px-space-sm font-bold text-primary">51 → 58 (+7)</td>
                    <td className="py-space-sm px-space-sm text-primary font-bold">0.48 → 0.11</td>
                    <td className="py-space-sm px-space-sm text-on-surface">Weak bridging conductance across access telemetry; exceeds 50</td>
                    <td className="py-space-sm px-space-sm">
                      <span className="px-space-xs py-space-2xs bg-primary-container text-on-primary-container rounded font-label-caps uppercase font-bold">
                        SPLIT CANDIDATE
                      </span>
                    </td>
                  </tr>
                  <tr className="hover:bg-surface-container-high transition-colors opacity-80">
                    <td className="py-space-sm px-space-sm font-bold text-secondary-fixed">S102 → S103 (Proj.)</td>
                    <td className="py-space-sm px-space-sm text-on-surface-variant">10:45:00 UTC</td>
                    <td className="py-space-sm px-space-sm font-semibold text-on-surface">58 → 34 + 24</td>
                    <td className="py-space-sm px-space-sm text-secondary-fixed">0.11 → 0.91 / 0.88</td>
                    <td className="py-space-sm px-space-sm text-on-surface-variant">Bipartition: Subchain A (Core) and Subchain B (Edge)</td>
                    <td className="py-space-sm px-space-sm">
                      <span className="px-space-xs py-space-2xs bg-surface-container-highest text-secondary-fixed rounded font-label-caps uppercase font-bold">
                        PARTITIONED
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Lower Panel: Growth Curve & Partition Action */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
            <div className="lg:col-span-7 bg-surface-container rounded p-space-md shadow-sm flex flex-col justify-between">
              <div className="flex items-center justify-between pb-space-sm">
                <span className="font-body-md text-body-md font-bold text-on-surface">
                  Chain Growth & Conductance Evolution Curve
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">Cumulative Alarm Size vs Φ</span>
              </div>
              <div className="w-full h-52 bg-surface-container-lowest rounded p-space-sm flex flex-col justify-end">
                <svg className="w-full h-40 overflow-visible" preserveAspectRatio="none" viewBox="0 0 700 160">
                  <line x1="0" y1="30" x2="700" y2="30" stroke="#2e3545" strokeDasharray="3 3" />
                  <line x1="0" y1="70" x2="700" y2="70" stroke="#2e3545" strokeDasharray="3 3" />
                  <line x1="0" y1="110" x2="700" y2="110" stroke="#2e3545" strokeDasharray="3 3" />
                  <polyline points="60,60 250,42 450,22 640,78" fill="none" stroke="#7bd0ff" strokeWidth="2.5" />
                  <polyline points="60,30 250,75 450,135 640,25" fill="none" stroke="#ff5451" strokeWidth="2" strokeDasharray="4 4" />
                  <circle cx="450" cy="22" r="5" fill="#ffb3ad" stroke="#68000a" strokeWidth="2" />
                  <text x="415" y="14" fill="#ffb3ad" fontFamily="JetBrains Mono" fontSize="11" fontWeight="700">
                    S102: Peak (58)
                  </text>
                </svg>
                <div className="flex justify-between items-center text-on-surface-variant font-code-sm text-code-sm pt-space-xs">
                  <span className="text-secondary font-semibold">Epoch S100</span>
                  <span className="text-tertiary font-semibold">Epoch S101</span>
                  <span className="text-primary font-bold">Epoch S102 Active</span>
                  <span className="text-secondary-fixed font-semibold">Epoch S103 Proj.</span>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5 bg-surface-container rounded p-space-md shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-space-sm border-b border-surface-container-highest">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-secondary text-[18px]">alt_route</span>
                    <span className="font-body-md text-body-md font-bold text-on-surface">
                      Evolution Governance Action
                    </span>
                  </div>
                  <span className="px-space-xs py-space-2xs bg-primary-container text-on-primary-container font-label-caps text-label-caps uppercase rounded font-bold">
                    ACTION REQUIRED
                  </span>
                </div>
                <div className="flex flex-col gap-space-sm mt-space-sm font-body-sm text-body-sm">
                  <p className="text-on-surface">
                    Chain has sustained &gt;50 alarms across 2 consecutive epochs. Automatic fission policy mandates partition into Subchains A and B.
                  </p>
                  <div className="p-space-sm bg-surface-container-low rounded font-code-sm text-code-sm flex justify-between">
                    <span className="text-on-surface-variant">Recommended Fission:</span>
                    <span className="text-secondary font-bold">C2214039-A + C2214039-B</span>
                  </div>
                </div>
              </div>

              <div className="pt-space-md flex items-center justify-end">
                <button
                  onClick={() =>
                    onExecutePartition?.({
                      opId: 'MUT-S103-FISSION',
                      opType: 'TEMPORAL_EPOCH_FISSION',
                      title: 'Phê duyệt Phân rã Chuỗi Sự cố (S103 Fission Policy)',
                      targetSummary: `Tách chuỗi ${analysis.chain_id} thành C2214039-A và C2214039-B`,
                      detail:
                        'Chính sách tự động S103 kích hoạt do chuỗi duy trì >50 cảnh báo trong 2 chu kỳ liên tiếp (S101-S102). Phân rã chuỗi theo vòng đời sự cố.',
                      badgeLabel: 'EPOCH_S103',
                      defaultNote: `Xác nhận phân rã chuỗi ${analysis.chain_id} theo chính sách vòng đời sự cố S103.`,
                    })
                  }
                  className="w-full py-space-xs bg-primary text-on-primary font-body-md text-body-md font-bold rounded shadow-md hover:brightness-110 flex items-center justify-center gap-space-xs transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">call_split</span>
                  <span>Execute S103 Partition</span>
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
