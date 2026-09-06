import { useState } from 'react'
import type { ChainAnalysis } from '../types'

interface AuditStructureViewProps {
  analysis: ChainAnalysis
  onSelectCutCandidate?: (candidateId: string) => void
  onOpenValidationModal?: () => void
}

type AuditTab = 'GRAPH' | 'CUTS' | 'ATTRIBUTION'

export function AuditStructureView({
  analysis,
  onOpenValidationModal,
}: AuditStructureViewProps) {
  const [activeTab, setActiveTab] = useState<AuditTab>('GRAPH')
  const [zoomLevel, setZoomLevel] = useState(100)
  const [showLabels, setShowLabels] = useState(true)
  const [showWeakOnly, setShowWeakOnly] = useState(false)
  const [selectedCutIndex, setSelectedCutIndex] = useState(0)

  const candidateCuts = [
    {
      id: 'CUT-01',
      plane: 'DEHL01-CR01 ↔ DEHT01-AR02',
      conductance: 0.038,
      subchainA: 'DEHL01 Core Cluster (42 alms)',
      subchainB: 'DEHT01 Access Tail (16 alms)',
      modularityGain: '+0.142',
      status: 'RECOMMENDED (MIN-CUT)',
    },
    {
      id: 'CUT-02',
      plane: 'DEHL01-SR02 ↔ HNI-PE03',
      conductance: 0.115,
      subchainA: 'DEHL01 Backbone (50 alms)',
      subchainB: 'HNI Edge Transit (8 alms)',
      modularityGain: '+0.088',
      status: 'SECONDARY ALTERNATIVE',
    },
    {
      id: 'CUT-03',
      plane: 'VLAN 4001 Gateway Fission',
      conductance: 0.245,
      subchainA: 'L3 Core Routing (54 alms)',
      subchainB: 'L2 Access Leaf (4 alms)',
      modularityGain: '+0.031',
      status: 'MARGINAL (LOW BENEFIT)',
    },
  ]

  const activeCut = candidateCuts[selectedCutIndex]

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Subheader & Context Controls */}
      <div className="w-full bg-surface-container-lowest px-space-lg py-space-sm rounded-lg shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-md">
          {/* Breadcrumb */}
          <div className="flex items-center gap-space-xs font-code-sm text-code-sm">
            <span className="text-on-surface-variant">Snapshot S102</span>
            <span className="text-surface-variant font-bold">/</span>
            <span className="px-space-xs py-space-2xs bg-surface-container rounded text-secondary font-semibold">
              Chain {analysis.chain_id}
            </span>
            <span className="text-surface-variant font-bold">/</span>
            <span className="text-on-surface-variant">Audit</span>
            <span className="text-surface-variant font-bold">/</span>
            <div className="flex items-center gap-space-xs text-on-surface bg-surface-container-high px-space-sm py-space-2xs rounded">
              <span className="material-symbols-outlined text-secondary text-[14px]">hub</span>
              <span className="font-bold text-on-surface">
                {activeTab === 'GRAPH' && '11 - G*_audit Full Graph Inspection'}
                {activeTab === 'CUTS' && '12 - Candidate Cut Selected'}
                {activeTab === 'ATTRIBUTION' && '13 - Attribution Deletion Curves'}
              </span>
            </div>
          </div>

          {/* Mode Selector Tab Switcher */}
          <div className="flex items-center bg-surface-container-low p-space-2xs rounded">
            <button
              onClick={() => setActiveTab('GRAPH')}
              className={`px-space-md py-space-xs rounded font-headline-md text-body-sm font-semibold flex items-center gap-space-xs transition-all ${
                activeTab === 'GRAPH'
                  ? 'bg-secondary-container text-on-secondary-container shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">schema</span>
              G*_audit Graph
            </button>
            <button
              onClick={() => setActiveTab('CUTS')}
              className={`px-space-md py-space-xs rounded font-headline-md text-body-sm font-semibold flex items-center gap-space-xs transition-all ${
                activeTab === 'CUTS'
                  ? 'bg-secondary-container text-on-secondary-container shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">content_cut</span>
              Candidate Cuts (3)
            </button>
            <button
              onClick={() => setActiveTab('ATTRIBUTION')}
              className={`px-space-md py-space-xs rounded font-headline-md text-body-sm font-semibold flex items-center gap-space-xs transition-all ${
                activeTab === 'ATTRIBUTION'
                  ? 'bg-secondary-container text-on-secondary-container shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">account_tree</span>
              Attribution Curves
            </button>
          </div>
        </div>

        {/* Secondary Telemetry Strip */}
        <div className="flex flex-wrap items-center justify-between gap-space-md pt-space-sm mt-space-xs border-t border-surface-container-highest">
          <div className="flex items-center gap-space-md">
            <div className="flex items-center gap-space-xs font-code-sm text-code-sm text-on-surface-variant">
              <span>SPECTRAL_SOLVER:</span>
              <span className="text-secondary font-semibold">Cheeger-Normalized Laplacian</span>
            </div>
            <div className="flex items-center gap-space-xs font-code-sm text-code-sm text-error bg-error-container/40 px-space-sm py-space-2xs rounded">
              <span className="material-symbols-outlined text-[14px]">warning</span>
              <span className="font-bold">BOTTLENECK DETECTED (Φ = 0.038)</span>
            </div>
          </div>
          {onOpenValidationModal && (
            <button
              onClick={onOpenValidationModal}
              className="px-space-md py-space-2xs bg-primary-container text-on-primary-container font-code-sm text-code-sm font-bold rounded flex items-center gap-space-xs shadow-sm hover:brightness-110"
            >
              <span className="material-symbols-outlined text-[16px]">verified</span>
              <span>Review Partition Sign-off</span>
            </button>
          )}
        </div>
      </div>

      {/* ========================================================================= */}
      {/* SCREEN 11: G*_audit GRAPH INSPECTION */}
      {/* ========================================================================= */}
      {activeTab === 'GRAPH' && (
        <div className="flex flex-col gap-space-md">
          {/* Viewport Toolbar */}
          <div className="w-full bg-surface-container-low px-space-lg py-space-xs rounded-lg flex flex-wrap items-center justify-between gap-space-sm">
            <div className="flex items-center gap-space-xs">
              <div className="flex items-center bg-surface-container rounded p-space-2xs">
                <button
                  onClick={() => setZoomLevel(prev => Math.max(50, prev - 15))}
                  className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded transition-colors"
                  title="Zoom Out"
                >
                  <span className="material-symbols-outlined text-[16px]">remove</span>
                </button>
                <span className="font-code-sm text-code-sm text-on-surface px-space-xs font-semibold w-12 text-center">
                  {zoomLevel}%
                </span>
                <button
                  onClick={() => setZoomLevel(prev => Math.min(180, prev + 15))}
                  className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded transition-colors"
                  title="Zoom In"
                >
                  <span className="material-symbols-outlined text-[16px]">add</span>
                </button>
                <button
                  onClick={() => setZoomLevel(100)}
                  className="w-7 h-7 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded transition-colors ml-space-2xs"
                  title="Reset Zoom"
                >
                  <span className="material-symbols-outlined text-[16px]">restart_alt</span>
                </button>
              </div>
              <div className="h-4 w-px bg-surface-variant mx-space-2xs"></div>
              <label className="flex items-center gap-space-xs px-space-sm py-space-2xs bg-surface-container rounded cursor-pointer hover:bg-surface-container-high transition-colors">
                <input
                  type="checkbox"
                  checked={showLabels}
                  onChange={e => setShowLabels(e.target.checked)}
                  className="accent-secondary-container w-3.5 h-3.5"
                />
                <span className="font-code-sm text-code-sm text-on-surface">Node Labels</span>
              </label>
              <label className="flex items-center gap-space-xs px-space-sm py-space-2xs bg-surface-container rounded cursor-pointer hover:bg-surface-container-high transition-colors">
                <input
                  type="checkbox"
                  checked={showWeakOnly}
                  onChange={e => setShowWeakOnly(e.target.checked)}
                  className="accent-secondary-container w-3.5 h-3.5"
                />
                <span className="font-code-sm text-code-sm text-on-surface">Highlight Weak Cut Edges</span>
              </label>
            </div>
            <span className="font-code-sm text-code-sm text-on-surface-variant">
              Cheeger Gap \lambda_2 = 0.082 • Spectral Partition Line Active
            </span>
          </div>

          {/* SVG Graph Viewport */}
          <div className="w-full bg-surface-container rounded-lg p-space-lg flex flex-col items-center justify-center overflow-hidden shadow-xl min-h-[540px] relative">
            <svg
              className="w-full h-[480px] text-surface-bright transition-transform duration-150"
              style={{ transform: `scale(${zoomLevel / 100})` }}
              viewBox="0 0 800 360"
            >
              {/* Internal Cluster Links DEHL01 */}
              <path d="M140 180 L240 120" stroke="#7bd0ff" strokeWidth="2" strokeOpacity="0.6" />
              <path d="M140 180 L240 240" stroke="#ff5451" strokeWidth="3" />
              <path d="M240 120 L380 180" stroke="#ff5451" strokeWidth="2.5" />
              <path d="M240 240 L380 180" stroke="#7bd0ff" strokeWidth="1.5" strokeOpacity="0.5" />

              {/* Weak Cut Inter-Cluster Boundary Links */}
              <path d="M380 180 L520 130" stroke="#ca8100" strokeWidth="2.5" strokeDasharray="6 3" />
              <path d="M380 180 L520 230" stroke="#ca8100" strokeWidth="2.5" strokeDasharray="6 3" />

              {/* Internal Cluster Links DEHT01 */}
              <path d="M520 130 L660 150" stroke="#7bd0ff" strokeWidth="1.5" strokeOpacity="0.6" />
              <path d="M520 230 L660 210" stroke="#7bd0ff" strokeWidth="1.5" strokeOpacity="0.6" />
              <path d="M660 150 L660 210" stroke="#7bd0ff" strokeWidth="1" strokeOpacity="0.4" />

              {/* Spectral Partition Cut Line */}
              <line x1="450" y1="40" x2="450" y2="320" stroke="#ff5451" strokeWidth="2" strokeDasharray="8 4" />
              <text x="458" y="65" fill="#ff5451" fontFamily="JetBrains Mono" fontSize="12" fontWeight="700">
                SPECTRAL CUT PLANE Φ = 0.038
              </text>

              {/* Node DEHL01-CR01 (Incident Root) */}
              <g transform="translate(140, 180)" className="cursor-pointer">
                <circle r="22" fill="rgba(255, 84, 81, 0.2)" stroke="#ff5451" strokeWidth="2" />
                <circle r="8" fill="#ff5451" className="animate-pulse" />
                {showLabels && (
                  <>
                    <text x="-40" y="38" fill="#ffb4ab" fontFamily="JetBrains Mono" fontSize="11" fontWeight="700">
                      DEHL01-CR01
                    </text>
                    <text x="-32" y="52" fill="#ab8986" fontFamily="JetBrains Mono" fontSize="9">
                      ROOT [CORE]
                    </text>
                  </>
                )}
              </g>

              {/* Cluster Nodes DEHL01 */}
              <g transform="translate(240, 120)">
                <circle r="12" fill="#202532" stroke="#7bd0ff" strokeWidth="1.5" />
                {showLabels && <text x="-25" y="-16" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="10">DEHL01-AGG1</text>}
              </g>
              <g transform="translate(240, 240)">
                <circle r="12" fill="#202532" stroke="#7bd0ff" strokeWidth="1.5" />
                {showLabels && <text x="-25" y="28" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="10">DEHL01-AGG2</text>}
              </g>

              {/* Cut Gateway Bridge Node */}
              <g transform="translate(380, 180)">
                <circle r="15" fill="#2e3545" stroke="#7bd0ff" strokeWidth="2" />
                {showLabels && (
                  <>
                    <text x="-30" y="-22" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="11" fontWeight="600">
                      DEHL01-GW01
                    </text>
                    <text x="-20" y="30" fill="#7bd0ff" fontFamily="JetBrains Mono" fontSize="9">
                      [BRIDGE]
                    </text>
                  </>
                )}
              </g>

              {/* Subcluster DEHT01 Access Nodes */}
              <g transform="translate(520, 130)">
                <circle r="12" fill="#2a2f3d" stroke="#ffb95f" strokeWidth="1.5" />
                {showLabels && <text x="-25" y="-16" fill="#ffb95f" fontFamily="JetBrains Mono" fontSize="10">DEHT01-SW01</text>}
              </g>
              <g transform="translate(520, 230)">
                <circle r="12" fill="#2a2f3d" stroke="#ffb95f" strokeWidth="1.5" />
                {showLabels && <text x="-25" y="28" fill="#ffb95f" fontFamily="JetBrains Mono" fontSize="10">DEHT01-SW02</text>}
              </g>
              <g transform="translate(660, 150)">
                <circle r="10" fill="#202532" stroke="#e4beba" strokeWidth="1" />
                {showLabels && <text x="14" y="4" fill="#e4beba" fontFamily="JetBrains Mono" fontSize="9">DEHT01-OLT01</text>}
              </g>
              <g transform="translate(660, 210)">
                <circle r="10" fill="#202532" stroke="#e4beba" strokeWidth="1" />
                {showLabels && <text x="14" y="4" fill="#e4beba" fontFamily="JetBrains Mono" fontSize="9">DEHT01-OLT02</text>}
              </g>
            </svg>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SCREEN 12: CANDIDATE CUTS */}
      {/* ========================================================================= */}
      {activeTab === 'CUTS' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
          {/* Left Col: Cut Candidate List */}
          <div className="lg:col-span-5 flex flex-col gap-space-sm">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
              Synthesized Cut Planes ({candidateCuts.length})
            </span>
            {candidateCuts.map((cut, idx) => (
              <div
                key={cut.id}
                onClick={() => setSelectedCutIndex(idx)}
                className={`p-space-md rounded-lg flex flex-col gap-space-xs cursor-pointer transition-all border ${
                  selectedCutIndex === idx
                    ? 'bg-surface-container border-secondary shadow-md'
                    : 'bg-surface-container-low border-transparent hover:bg-surface-container'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-code-md text-code-md font-bold text-on-surface">{cut.id}</span>
                  <span
                    className={`font-label-caps text-label-caps uppercase px-space-xs py-0.5 rounded font-bold ${
                      idx === 0 ? 'bg-primary-container/20 text-primary' : 'bg-surface-container text-on-surface-variant'
                    }`}
                  >
                    {cut.status}
                  </span>
                </div>
                <span className="font-code-sm text-code-sm text-secondary font-mono">{cut.plane}</span>
                <div className="flex items-center justify-between pt-space-2xs text-code-sm font-code-sm border-t border-surface-container-highest">
                  <span className="text-on-surface-variant">Conductance:</span>
                  <span className="text-primary font-bold">{cut.conductance.toFixed(3)}</span>
                  <span className="text-on-surface-variant">Gain:</span>
                  <span className="text-secondary font-bold">{cut.modularityGain}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Right Col: Selected Cut Deep-Dive */}
          <div className="lg:col-span-7 bg-surface-container rounded-lg p-space-md flex flex-col gap-space-md shadow-md">
            <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[20px]">content_cut</span>
                <span className="font-headline-md text-headline-md font-bold text-on-surface">
                  Cut Specification: {activeCut.id}
                </span>
              </div>
              <span className="font-code-sm text-code-sm text-primary font-bold">
                Conductance Φ = {activeCut.conductance.toFixed(3)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-space-sm font-code-sm text-code-sm">
              <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-secondary font-bold">Subchain A (Left)</span>
                <span className="text-on-surface font-semibold">{activeCut.subchainA}</span>
                <span className="text-on-surface-variant text-body-sm">Retains upstream root failure context.</span>
              </div>
              <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
                <span className="font-label-caps text-label-caps uppercase text-tertiary font-bold">Subchain B (Right)</span>
                <span className="text-on-surface font-semibold">{activeCut.subchainB}</span>
                <span className="text-on-surface-variant text-body-sm">Isolates downstream access cascade.</span>
              </div>
            </div>

            <div className="bg-surface-container-low p-space-sm rounded flex flex-col gap-space-xs">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant font-bold">
                Disconnected Bridge Edges
              </span>
              <div className="font-mono text-code-sm text-on-surface space-y-1">
                <div className="flex justify-between p-1 bg-surface-container rounded">
                  <span>ALM-47933130 ↔ ALM-99210014</span>
                  <span className="text-error font-bold">Weight: 0.11</span>
                </div>
                <div className="flex justify-between p-1 bg-surface-container rounded">
                  <span>DEHL01-GW01::Gi0/1 ↔ DEHT01-SW01::Gi0/2</span>
                  <span className="text-error font-bold">Weight: 0.08</span>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-space-sm pt-space-xs">
              {onOpenValidationModal && (
                <button
                  onClick={onOpenValidationModal}
                  className="px-space-lg py-space-xs bg-primary text-on-primary font-body-md text-body-md font-bold rounded shadow-md hover:brightness-110 flex items-center gap-space-xs transition-all"
                >
                  <span className="material-symbols-outlined text-[18px]">verified</span>
                  Sign-off Cut Dispatch
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SCREEN 13: ATTRIBUTION DELETION CURVES */}
      {/* ========================================================================= */}
      {activeTab === 'ATTRIBUTION' && (
        <div className="bg-surface-container rounded-lg p-space-lg flex flex-col gap-space-md shadow-md">
          <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
            <div>
              <span className="font-headline-md text-headline-md font-bold text-on-surface">
                Attribution Exact Deletion Curves
              </span>
              <p className="font-body-sm text-body-sm text-on-surface-variant mt-0.5">
                Primary vs Reverse vs Random Feature Ablation. Lower primary AUC proves superior evidence ranking.
              </p>
            </div>
            <div className="flex items-center gap-space-sm font-code-sm text-code-sm">
              <span className="text-on-surface-variant">Randomization:</span>
              <span className="text-secondary font-semibold">100 runs · seed 42</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md">
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Primary AUC</span>
              <span className="font-headline-xl text-headline-xl text-secondary font-bold my-1">0.184</span>
              <span className="font-code-sm text-code-sm text-secondary font-semibold">Superior ranking (Steep descent)</span>
            </div>
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Random Baseline AUC</span>
              <span className="font-headline-xl text-headline-xl text-on-surface font-bold my-1">0.512 ± 0.03</span>
              <span className="font-code-sm text-code-sm text-on-surface-variant">Null hypothesis baseline</span>
            </div>
            <div className="p-space-md bg-surface-container-low rounded flex flex-col justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Reverse Ablation AUC</span>
              <span className="font-headline-xl text-headline-xl text-tertiary font-bold my-1">0.824</span>
              <span className="font-code-sm text-code-sm text-tertiary font-semibold">Worst-order deletion check</span>
            </div>
          </div>

          {/* SVG Ablation Curve */}
          <div className="w-full h-56 bg-surface-container-lowest rounded p-space-md flex flex-col justify-end">
            <svg className="w-full h-44 overflow-visible" preserveAspectRatio="none" viewBox="0 0 700 160">
              {/* Grid */}
              <line x1="0" y1="30" x2="700" y2="30" stroke="#2e3545" strokeDasharray="3 3" />
              <line x1="0" y1="80" x2="700" y2="80" stroke="#2e3545" strokeDasharray="3 3" />
              <line x1="0" y1="130" x2="700" y2="130" stroke="#2e3545" strokeDasharray="3 3" />

              {/* Random line */}
              <line x1="60" y1="20" x2="640" y2="140" stroke="#4e5566" strokeWidth="2" strokeDasharray="4 4" />

              {/* Reverse line */}
              <polyline points="60,20 200,25 350,35 500,60 640,140" fill="none" stroke="#ffb95f" strokeWidth="2.5" />

              {/* Primary line */}
              <polyline points="60,20 150,110 300,135 480,140 640,140" fill="none" stroke="#7bd0ff" strokeWidth="3" />
            </svg>
            <div className="flex justify-between text-code-sm font-code-sm text-on-surface-variant pt-space-xs">
              <span className="text-secondary font-bold">— Primary AUC (0.184)</span>
              <span className="text-tertiary font-semibold">— Reverse AUC (0.824)</span>
              <span className="text-on-surface-variant">--- Random Mean (0.512)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
