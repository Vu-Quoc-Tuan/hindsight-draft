import { useState } from 'react'
import type { ChainAnalysis } from '../types'
import { TopologyTree, type TopologyTreePayload } from '../TopologyTree'

interface TopologyOverlayViewProps {
  analysis: ChainAnalysis
  topologyPayload?: TopologyTreePayload | null
}

export function TopologyOverlayView({
  analysis,
  topologyPayload,
}: TopologyOverlayViewProps) {
  const [showL3, setShowL3] = useState(true)
  const [showIt, setShowIt] = useState(true)
  const [showAlarms, setShowAlarms] = useState(true)
  const [showCutEdges, setShowCutEdges] = useState(true)
  const [filterQuery, setFilterQuery] = useState('')

  // Default demonstration payload for Screen 17 if live backend endpoint not connected
  const effectivePayload: TopologyTreePayload = topologyPayload ?? {
    status: 'AVAILABLE',
    profile: 'IT_SERVICES',
    topology_kind: 'DIRECTED_SOURCE_RELATIONS',
    direction_kind: 'SOURCE_RELATION',
    dependency_semantics: 'UNVERIFIED',
    topology: {
      availability: 'AVAILABLE',
      relation_model: 'DIRECTED_SOURCE_RELATIONS',
      direction_kind: 'SOURCE_RELATION',
      dependency_semantics: 'UNVERIFIED',
      navigation_mapping: 'PARTIAL_EXACT_IDENTITY',
      alarm_resource_mapping: 'PARTIAL_EXACT_ONLY',
    },
    source_version: 'netbox-v3.7-cmdb-live',
    semantic_notice: 'Relation tree projected from Viettel IT Services & IP Backbone CMDB.',
    tree: {
      resource_id: 'SVC-BILLING-01',
      resource_type: 'SERVICE',
      display_name: 'Core BSS / Billing Gateway',
      relation_type: 'ROOT',
      source_table: 'it_service_registry',
      hidden_child_count: 0,
      reference_kind: null,
      linked_parent_count: 0,
      children: [
        {
          resource_id: 'MOD-PAYMENT-CORE',
          resource_type: 'MODULE',
          display_name: 'Payment Settlement Core',
          relation_type: 'HOSTED_ON',
          source_table: 'cmdb_ci',
          hidden_child_count: 0,
          reference_kind: null,
          linked_parent_count: 1,
          children: [
            {
              resource_id: 'DB-ORACLE-DEHL01',
              resource_type: 'DATABASE',
              display_name: 'Billing DB RAC-01 (Site DEHL01)',
              relation_type: 'DEPENDS_ON',
              source_table: 'cmdb_db',
              hidden_child_count: 0,
              reference_kind: null,
              linked_parent_count: 1,
              children: [],
            },
          ],
        },
        {
          resource_id: 'ROUTER-DEHL01-CR01',
          resource_type: 'DEVICE',
          display_name: 'DEHL01-CR01 (Core Backbone)',
          relation_type: 'NETWORK_LINK',
          source_table: 'netbox_device',
          hidden_child_count: 0,
          reference_kind: null,
          linked_parent_count: 1,
          children: [],
        },
      ],
    },
  }

  return (
    <div className="flex flex-col w-full gap-space-md pb-12 select-none animate-fadeIn">
      {/* Header Bar */}
      <div className="w-full bg-surface-container-lowest px-space-lg py-space-sm rounded-lg shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
        <div className="flex flex-col gap-space-2xs">
          <div className="flex items-center gap-space-xs font-code-sm text-code-sm text-on-surface-variant">
            <span>Snapshot S102</span>
            <span className="material-symbols-outlined text-[12px]">chevron_right</span>
            <span className="text-secondary font-semibold">Chain {analysis.chain_id}</span>
            <span className="material-symbols-outlined text-[12px]">chevron_right</span>
            <span className="text-on-surface">Topology (IT Service Relations & IP Physical Overlay)</span>
          </div>
          <div className="flex items-center gap-space-sm">
            <h1 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
              17 - Topology: IT Service Relation Tree & IP Overlay
            </h1>
            <span className="px-space-xs py-space-2xs bg-primary-container/20 text-error font-code-sm text-code-sm rounded font-bold uppercase tracking-wider flex items-center gap-space-2xs">
              <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-ping"></span>
              INCIDENT ROOT T0
            </span>
          </div>
        </div>

        {/* Telemetry Strip */}
        <div className="flex flex-wrap items-center gap-space-xs">
          <div className="flex items-center gap-space-xs px-space-sm py-space-xs bg-surface-container rounded">
            <span className="material-symbols-outlined text-secondary text-[16px]">account_tree</span>
            <div className="flex flex-col">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">IP PHYSICAL</span>
              <span className="font-code-sm text-code-sm text-secondary font-semibold">41 / 58 Mapped (70.6%)</span>
            </div>
          </div>
          <div className="flex items-center gap-space-xs px-space-sm py-space-xs bg-surface-container rounded">
            <span className="material-symbols-outlined text-tertiary text-[16px]">fiber_manual_record</span>
            <div className="flex flex-col">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">OPTICAL DWDM</span>
              <span className="font-code-sm text-code-sm text-tertiary font-semibold">17 Drops Unmapped</span>
            </div>
          </div>
          <div className="flex items-center gap-space-xs px-space-sm py-space-xs bg-surface-container-high rounded">
            <span className="material-symbols-outlined text-secondary text-[16px]">cloud_sync</span>
            <div className="flex flex-col">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">CMDB SYNC</span>
              <span className="font-code-sm text-code-sm text-on-surface font-semibold">NetBox v3.7 LIVE</span>
            </div>
          </div>
        </div>
      </div>

      {/* Layer Toggles & Search Ribbon */}
      <div className="w-full bg-surface-container-low px-space-lg py-space-xs rounded-lg flex flex-wrap items-center justify-between gap-space-md shadow-sm">
        <div className="flex items-center gap-space-sm flex-wrap">
          <span className="font-label-caps text-label-caps uppercase text-on-surface-variant tracking-wider">LAYERS:</span>
          <button
            onClick={() => setShowL3(!showL3)}
            className={`px-space-sm py-space-2xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
              showL3 ? 'bg-secondary-container/30 text-secondary' : 'bg-surface-container text-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showL3 ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>IP Layer-3 Mesh</span>
          </button>
          <button
            onClick={() => setShowIt(!showIt)}
            className={`px-space-sm py-space-2xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
              showIt ? 'bg-secondary-container/30 text-secondary' : 'bg-surface-container text-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showIt ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>IT Service Hierarchy</span>
          </button>
          <button
            onClick={() => setShowAlarms(!showAlarms)}
            className={`px-space-sm py-space-2xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
              showAlarms ? 'bg-primary-container/20 text-error' : 'bg-surface-container text-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showAlarms ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>Active Chain Alarms (58)</span>
          </button>
          <button
            onClick={() => setShowCutEdges(!showCutEdges)}
            className={`px-space-sm py-space-2xs rounded font-code-sm text-code-sm font-semibold flex items-center gap-space-xs transition-colors ${
              showCutEdges ? 'bg-tertiary-container/20 text-tertiary' : 'bg-surface-container text-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {showCutEdges ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span>Filter Cheeger Cut Edges</span>
          </button>
        </div>
        <div className="relative flex items-center">
          <span className="material-symbols-outlined absolute left-2 text-on-surface-variant text-[16px]">search</span>
          <input
            type="text"
            value={filterQuery}
            onChange={e => setFilterQuery(e.target.value)}
            placeholder="Filter node, circuit #, SLA..."
            className="bg-surface-container-lowest text-on-surface font-code-sm text-code-sm pl-7 pr-space-sm py-space-2xs rounded w-64 focus:outline-none focus:bg-surface-container-high transition-colors"
          />
        </div>
      </div>

      {/* Split-Screen: Left 35% IT Tree, Right 65% IP Network Mesh */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md items-start">
        {/* Left: IT Service Relations Tree */}
        <div className="lg:col-span-5 bg-surface-container rounded-lg p-space-md shadow-md flex flex-col gap-space-sm min-h-[500px]">
          <TopologyTree payload={effectivePayload} />
        </div>

        {/* Right: IP Physical Network Mesh Overlay */}
        <div className="lg:col-span-7 bg-surface-container rounded-lg p-space-md shadow-md flex flex-col gap-space-md min-h-[500px]">
          <div className="flex items-center justify-between border-b border-surface-container-highest pb-space-xs">
            <div className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-secondary text-[20px]">hub</span>
              <span className="font-headline-md text-headline-md font-bold text-on-surface">
                IP Physical Network Mesh Overlay
              </span>
            </div>
            <span className="font-code-sm text-code-sm text-secondary">
              Metro-Core Ring 04
            </span>
          </div>

          {/* Network Mesh SVG Canvas */}
          <div className="w-full bg-surface-container-lowest rounded-lg p-space-md flex flex-col items-center justify-center overflow-hidden min-h-[400px]">
            <svg className="w-full h-80" viewBox="0 0 600 280">
              {/* L3 mesh lines */}
              {showL3 && (
                <>
                  <path d="M120 140 L220 80" stroke="#7bd0ff" strokeWidth="2" strokeOpacity="0.7" />
                  <path d="M120 140 L220 200" stroke="#ff5451" strokeWidth="3" />
                  <path d="M220 80 L320 140" stroke="#7bd0ff" strokeWidth="2" strokeOpacity="0.7" />
                  <path d="M220 200 L320 140" stroke="#7bd0ff" strokeWidth="1.5" strokeOpacity="0.7" />
                  <path d="M420 90 L520 110" stroke="#ffb95f" strokeWidth="2" />
                  <path d="M420 190 L520 170" stroke="#ffb95f" strokeWidth="2" />
                  <path d="M520 110 L520 170" stroke="#ffb95f" strokeWidth="1.5" strokeOpacity="0.5" />
                </>
              )}

              {/* Cheeger cut edges */}
              {showCutEdges && (
                <>
                  <path d="M320 140 L420 90" stroke="#ca8100" strokeWidth="2.5" strokeDasharray="6 3" />
                  <path d="M320 140 L420 190" stroke="#ca8100" strokeWidth="2.5" strokeDasharray="6 3" />
                  <line x1="370" y1="30" x2="370" y2="250" stroke="#ca8100" strokeWidth="2" strokeDasharray="8 4" />
                  <text x="375" y="50" fill="#ca8100" fontFamily="JetBrains Mono" fontSize="10" fontWeight="700">
                    CUT Φ = 0.120
                  </text>
                </>
              )}

              {/* Station DEHL01 Nodes */}
              <g transform="translate(120, 140)">
                <circle r="18" fill="rgba(255, 84, 81, 0.2)" stroke="#ff5451" strokeWidth="2" />
                <circle r="6" fill="#ff5451" className="animate-ping" />
                <text x="-32" y="32" fill="#ffb4ab" fontFamily="JetBrains Mono" fontSize="10" fontWeight="700">
                  DEHL01-CR01
                </text>
              </g>
              <g transform="translate(220, 80)">
                <circle r="10" fill="#202532" stroke="#7bd0ff" strokeWidth="1.5" />
                <text x="-25" y="-12" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="9">DEHL01-AGG1</text>
              </g>
              <g transform="translate(220, 200)">
                <circle r="10" fill="#202532" stroke="#7bd0ff" strokeWidth="1.5" />
                <text x="-25" y="24" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="9">DEHL01-AGG2</text>
              </g>
              <g transform="translate(320, 140)">
                <circle r="13" fill="#2e3545" stroke="#7bd0ff" strokeWidth="2" />
                <text x="-24" y="-18" fill="#dce2f7" fontFamily="JetBrains Mono" fontSize="10">DEHL01-GW01</text>
              </g>

              {/* Station DEHT01 Nodes */}
              <g transform="translate(420, 90)">
                <circle r="10" fill="#2a2f3d" stroke="#ffb95f" strokeWidth="1.5" />
                <text x="-20" y="-14" fill="#ffb95f" fontFamily="JetBrains Mono" fontSize="9">DEHT01-SW01</text>
              </g>
              <g transform="translate(420, 190)">
                <circle r="10" fill="#2a2f3d" stroke="#ffb95f" strokeWidth="1.5" />
                <text x="-20" y="24" fill="#ffb95f" fontFamily="JetBrains Mono" fontSize="9">DEHT01-SW02</text>
              </g>
              <g transform="translate(520, 110)">
                <circle r="8" fill="#202532" stroke="#e4beba" strokeWidth="1" />
                <text x="12" y="4" fill="#e4beba" fontFamily="JetBrains Mono" fontSize="9">DEHT01-OLT01</text>
              </g>
              <g transform="translate(520, 170)">
                <circle r="8" fill="#202532" stroke="#e4beba" strokeWidth="1" />
                <text x="12" y="4" fill="#e4beba" fontFamily="JetBrains Mono" fontSize="9">DEHT01-OLT02</text>
              </g>
            </svg>
          </div>
        </div>
      </div>
    </div>
  )
}
