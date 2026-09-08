import { useMemo, useState } from 'react'
import { compactTime } from './format'
import type { Member } from './types'

export type TreeGrouping = 'resource' | 'role' | 'cascade'

export interface ChainTreeProps {
  members: Member[]
  selectedMembers: string[]
  activeInspectId?: string | null
  onSelectMember: (member: Member) => void
  onInspectMember: (member: Member) => void
}

interface DeviceGroup {
  deviceCode: string
  members: Member[]
  coreCount: number
  connectorCount: number
  extenderCount: number
  leafCount: number
}

interface SiteGroup {
  siteRef: string
  devices: DeviceGroup[]
  totalAlarms: number
}

interface FlatGroup {
  id: string
  title: string
  subtitle?: string
  badge?: string
  badgeTone?: 'core' | 'extender' | 'connector' | 'leaf' | 'neutral'
  members: Member[]
}

function getRelativeTime(timeStr: string | null, baseTime: number | null): string {
  if (!timeStr || baseTime === null) return ''
  const t = new Date(timeStr).getTime()
  if (isNaN(t)) return ''
  const diffSec = Math.round((t - baseTime) / 1000)
  if (diffSec <= 0) return 'T₀ (+0s)'
  return `+${diffSec}s`
}

function roleTone(role: string): 'core' | 'extender' | 'connector' | 'leaf' | 'neutral' {
  const upper = role.toUpperCase()
  if (upper.includes('CORE') || upper.includes('ROOT')) return 'core'
  if (upper.includes('EXTEND')) return 'extender'
  if (upper.includes('CONNECT')) return 'connector'
  if (upper.includes('LEAF') || upper.includes('SYMPTOM') || upper.includes('WEAK')) return 'leaf'
  return 'neutral'
}

function formatRoleName(role: string): string {
  const upper = role.toUpperCase()
  if (upper.includes('CORE') || upper.includes('ROOT')) return 'CORE member'
  if (upper.includes('CONNECT')) return 'CONNECTOR'
  if (upper.includes('EXTEND')) return 'EXTENDER'
  if (upper.includes('LEAF') || upper.includes('SYMPTOM') || upper.includes('WEAK')) return 'LEAF'
  return role
}

export function ChainTree({
  members,
  selectedMembers,
  activeInspectId,
  onSelectMember,
  onInspectMember,
}: ChainTreeProps) {
  const [grouping, setGrouping] = useState<TreeGrouping>('resource')
  const [search, setSearch] = useState('')
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set())

  // Find root baseline time
  const baseTime = useMemo(() => {
    const times = members
      .map((m) => (m.canonical_start_time ? new Date(m.canonical_start_time).getTime() : null))
      .filter((t): t is number => t !== null && !isNaN(t))
    return times.length > 0 ? Math.min(...times) : null
  }, [members])

  // Filter members by search
  const filteredMembers = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return members
    return members.filter((m) => {
      const name = m.alarm_name?.toLowerCase() ?? ''
      const id = m.alarm_id.toLowerCase()
      const dev = m.device_code?.toLowerCase() ?? ''
      const ref = m.node_reference?.toLowerCase() ?? ''
      const role = m.role.toLowerCase()
      return (
        name.includes(query) ||
        id.includes(query) ||
        dev.includes(query) ||
        ref.includes(query) ||
        role.includes(query)
      )
    })
  }, [members, search])

  // 1. Build 3-level Resource Hierarchy: Site -> Device -> Alarms
  const siteGroups = useMemo<SiteGroup[]>(() => {
    if (grouping !== 'resource') return []

    // Group by site (node_reference)
    const siteMap = new Map<string, Map<string, Member[]>>()

    for (const m of filteredMembers) {
      const site = m.node_reference ?? 'Unassigned Site'
      const device = m.device_code ?? 'Unassigned Device'

      if (!siteMap.has(site)) {
        siteMap.set(site, new Map())
      }
      const devMap = siteMap.get(site)!
      if (!devMap.has(device)) {
        devMap.set(device, [])
      }
      devMap.get(device)!.push(m)
    }

    return Array.from(siteMap.entries()).map(([siteRef, devMap]) => {
      const devices: DeviceGroup[] = Array.from(devMap.entries()).map(([devCode, devAlarms]) => {
        let coreCount = 0
        let connectorCount = 0
        let extenderCount = 0
        let leafCount = 0

        for (const a of devAlarms) {
          const tone = roleTone(a.role)
          if (tone === 'core') coreCount++
          else if (tone === 'connector') connectorCount++
          else if (tone === 'extender') extenderCount++
          else leafCount++
        }

        return {
          deviceCode: devCode,
          members: devAlarms,
          coreCount,
          connectorCount,
          extenderCount,
          leafCount,
        }
      })

      const totalAlarms = devices.reduce((sum, d) => sum + d.members.length, 0)
      return {
        siteRef,
        devices,
        totalAlarms,
      }
    })
  }, [filteredMembers, grouping])

  // 2. Build flat groups for Role and Cascade modes
  const flatGroups = useMemo<FlatGroup[]>(() => {
    if (grouping === 'role') {
      const core: Member[] = []
      const connector: Member[] = []
      const extender: Member[] = []
      const leaf: Member[] = []

      for (const m of filteredMembers) {
        const tone = roleTone(m.role)
        if (tone === 'core') core.push(m)
        else if (tone === 'connector') connector.push(m)
        else if (tone === 'extender') extender.push(m)
        else leaf.push(m)
      }

      const res: FlatGroup[] = []
      if (core.length > 0) {
        res.push({
          id: 'group-core',
          title: 'CORE Members',
          subtitle: 'Core cluster membership alarms',
          badge: `${core.length}`,
          badgeTone: 'core',
          members: core,
        })
      }
      if (connector.length > 0) {
        res.push({
          id: 'group-connector',
          title: 'CONNECTORS',
          subtitle: 'Bridge edges linking domains',
          badge: `${connector.length}`,
          badgeTone: 'connector',
          members: connector,
        })
      }
      if (extender.length > 0) {
        res.push({
          id: 'group-extender',
          title: 'EXTENDERS',
          subtitle: 'Correlated cascade propagations',
          badge: `${extender.length}`,
          badgeTone: 'extender',
          members: extender,
        })
      }
      if (leaf.length > 0) {
        res.push({
          id: 'group-leaf',
          title: 'LEAF / Peripheral Members',
          subtitle: 'Downstream symptom alarms',
          badge: `${leaf.length}`,
          badgeTone: 'leaf',
          members: leaf,
        })
      }
      return res
    }

    if (grouping === 'cascade') {
      const wave0: Member[] = []
      const wave1: Member[] = []
      const wave2: Member[] = []

      for (const m of filteredMembers) {
        if (!m.canonical_start_time || baseTime === null) {
          wave0.push(m)
          continue
        }
        const t = new Date(m.canonical_start_time).getTime()
        const diffSec = (t - baseTime) / 1000
        if (diffSec <= 2) wave0.push(m)
        else if (diffSec <= 15) wave1.push(m)
        else wave2.push(m)
      }

      const res: FlatGroup[] = []
      if (wave0.length > 0) {
        res.push({
          id: 'cascade-0',
          title: 'Wave 0 · Initial Onset (0s – 2s)',
          subtitle: 'Earliest detected anomalies',
          badge: `${wave0.length}`,
          badgeTone: 'core',
          members: wave0,
        })
      }
      if (wave1.length > 0) {
        res.push({
          id: 'cascade-1',
          title: 'Wave 1 · Local Propagation (2s – 15s)',
          subtitle: 'Neighboring device impact',
          badge: `${wave1.length}`,
          badgeTone: 'extender',
          members: wave1,
        })
      }
      if (wave2.length > 0) {
        res.push({
          id: 'cascade-2',
          title: 'Wave 2 · Downstream Ripple (> 15s)',
          subtitle: 'Secondary service effects',
          badge: `${wave2.length}`,
          badgeTone: 'leaf',
          members: wave2,
        })
      }
      return res
    }

    return []
  }, [filteredMembers, grouping, baseTime])

  function toggleCollapse(key: string) {
    setCollapsedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function expandAll() {
    setCollapsedKeys(new Set())
  }

  function collapseAll() {
    const keys = new Set<string>()
    if (grouping === 'resource') {
      for (const s of siteGroups) {
        keys.add(`site-${s.siteRef}`)
        for (const d of s.devices) {
          keys.add(`dev-${s.siteRef}-${d.deviceCode}`)
        }
      }
    } else {
      for (const g of flatGroups) {
        keys.add(g.id)
      }
    }
    setCollapsedKeys(keys)
  }

  // Render individual alarm card
  function renderAlarmCard(member: Member) {
    const isSelectedPair = selectedMembers.includes(member.alarm_id)
    const isInspecting = activeInspectId === member.alarm_id
    const relTime = getRelativeTime(member.canonical_start_time, baseTime)
    const tone = roleTone(member.role)
    const roleLabel = formatRoleName(member.role)

    return (
      <div
        key={member.alarm_id}
        className={`tree-node-wrapper ${isSelectedPair ? 'is-selected-pair' : ''} ${
          isInspecting ? 'is-inspecting' : ''
        }`}
      >
        <div className="tree-connector-elbow" aria-hidden="true" />
        <div
          className={`tree-node-card tone--${tone}`}
          onClick={() => onInspectMember(member)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onInspectMember(member)
            }
          }}
          title="Click to view alarm details"
        >
          <div className="node-card-left">
            <span className={`node-role-pill pill--${tone}`}>
              {roleLabel}
            </span>
            <div className="node-id-block">
              <strong className="node-alarm-name">
                {member.alarm_name || member.alarm_id}
              </strong>
              <div className="node-sub-info">
                <span className="node-id-code">{member.alarm_id}</span>
              </div>
            </div>
          </div>

          <div className="node-card-right">
            {member.canonical_start_time && (
              <div className="node-time-block">
                <span className="node-clock">
                  {compactTime(member.canonical_start_time)}
                </span>
                {relTime && <span className="node-rel-time">{relTime}</span>}
              </div>
            )}

            <button
              type="button"
              className={`node-compare-btn ${isSelectedPair ? 'is-active' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onSelectMember(member)
              }}
              title={
                isSelectedPair
                  ? 'Remove from Pair WHY comparison'
                  : 'Select for Pair WHY comparison (pick 2)'
              }
              aria-pressed={isSelectedPair}
            >
              {isSelectedPair ? '✓ Compared' : '+ Compare'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const isEmpty = grouping === 'resource' ? siteGroups.length === 0 : flatGroups.length === 0

  return (
    <div className="chain-tree-container" aria-label="Hierarchical alarm chain tree">
      {/* Tree Toolbar */}
      <div className="tree-toolbar">
        <div className="tree-group-switchers" role="radiogroup" aria-label="Tree Grouping Mode">
          <button
            type="button"
            className={`tree-mode-btn ${grouping === 'resource' ? 'is-active' : ''}`}
            onClick={() => setGrouping('resource')}
            title="3-Level Resource Hierarchy: Site / Node Reference → Device → Alarms"
          >
            🏢 Resource Hierarchy
          </button>
          <button
            type="button"
            className={`tree-mode-btn ${grouping === 'role' ? 'is-active' : ''}`}
            onClick={() => setGrouping('role')}
            title="Group by membership role (CORE, CONNECTOR, EXTENDER, LEAF)"
          >
            🌳 By Role & Membership
          </button>
          <button
            type="button"
            className={`tree-mode-btn ${grouping === 'cascade' ? 'is-active' : ''}`}
            onClick={() => setGrouping('cascade')}
            title="Group chronologically by cascade waves"
          >
            ⏱️ Cascade Stages
          </button>
        </div>

        <div className="tree-toolbar-right">
          <div className="tree-search-wrapper">
            <svg className="search-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="text"
              className="tree-search-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter alarms, sites, devices…"
              aria-label="Filter alarms in tree"
            />
            {search && (
              <button
                type="button"
                className="search-clear-btn"
                onClick={() => setSearch('')}
                aria-label="Clear filter"
              >
                ×
              </button>
            )}
          </div>

          <div className="tree-expand-actions">
            <button type="button" className="tree-action-link" onClick={expandAll}>
              Expand all
            </button>
            <span className="divider">•</span>
            <button type="button" className="tree-action-link" onClick={collapseAll}>
              Collapse all
            </button>
          </div>
        </div>
      </div>

      {/* Tree Content */}
      {isEmpty ? (
        <div className="tree-empty-state">
          <p>No alarms match the search filter <strong>"{search}"</strong></p>
        </div>
      ) : grouping === 'resource' ? (
        /* 3-Level Resource Hierarchy (Site -> Device -> Alarms) */
        <div className="tree-root-stem">
          {siteGroups.map((site) => {
            const siteKey = `site-${site.siteRef}`
            const isSiteCollapsed = collapsedKeys.has(siteKey)

            return (
              <div key={siteKey} className={`tree-group site-level-group ${isSiteCollapsed ? 'is-collapsed' : ''}`}>
                {/* Level 1: Site / Node Reference Header */}
                <div
                  className="tree-group-header tree-site-header"
                  onClick={() => toggleCollapse(siteKey)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggleCollapse(siteKey)
                    }
                  }}
                  aria-expanded={!isSiteCollapsed}
                >
                  <span className={`tree-collapse-chevron ${isSiteCollapsed ? 'collapsed' : ''}`}>▼</span>
                  <div className="tree-group-titles">
                    <span className="tree-group-title">📍 Site: {site.siteRef}</span>
                    <span className="tree-group-subtitle">
                      {site.devices.length} {site.devices.length === 1 ? 'device' : 'devices'}
                    </span>
                  </div>
                  <span className="tree-group-badge badge--neutral">
                    {site.totalAlarms} {site.totalAlarms === 1 ? 'alarm' : 'alarms'}
                  </span>
                </div>

                {/* Level 1 Children (Devices) */}
                {!isSiteCollapsed && (
                  <div className="tree-branch-container site-branch-container">
                    <div className="tree-branch-line" aria-hidden="true" />
                    <div className="tree-devices-list">
                      {site.devices.map((device) => {
                        const devKey = `dev-${site.siteRef}-${device.deviceCode}`
                        const isDevCollapsed = collapsedKeys.has(devKey)

                        return (
                          <div key={devKey} className={`tree-device-block ${isDevCollapsed ? 'is-collapsed' : ''}`}>
                            {/* Level 2: Device Header */}
                            <div
                              className="tree-device-header"
                              onClick={() => toggleCollapse(devKey)}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  toggleCollapse(devKey)
                                }
                              }}
                              aria-expanded={!isDevCollapsed}
                            >
                              <span className={`tree-collapse-chevron ${isDevCollapsed ? 'collapsed' : ''}`}>▼</span>
                              <div className="tree-device-titles">
                                <strong className="tree-device-code">🖥️ {device.deviceCode}</strong>
                                <span className="tree-device-alarm-count">
                                  {device.members.length} {device.members.length === 1 ? 'alarm' : 'alarms'}
                                </span>
                              </div>

                              {/* Role Distribution Pills */}
                              <div className="tree-device-role-pills">
                                {device.coreCount > 0 && (
                                  <span className="pill pill--core pill-mini">
                                    {device.coreCount} CORE
                                  </span>
                                )}
                                {device.connectorCount > 0 && (
                                  <span className="pill pill--connector pill-mini">
                                    {device.connectorCount} CONNECTOR
                                  </span>
                                )}
                                {device.extenderCount > 0 && (
                                  <span className="pill pill--extender pill-mini">
                                    {device.extenderCount} EXTENDER
                                  </span>
                                )}
                                {device.leafCount > 0 && (
                                  <span className="pill pill--leaf pill-mini">
                                    {device.leafCount} LEAF
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Level 3: Alarm Leaves */}
                            {!isDevCollapsed && (
                              <div className="tree-branch-container device-branch-container">
                                <div className="tree-branch-line device-branch-line" aria-hidden="true" />
                                <div className="tree-nodes-list">
                                  {device.members.map((member) => renderAlarmCard(member))}
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        /* Flat Groups (Role & Cascade Modes) */
        <div className="tree-root-stem">
          {flatGroups.map((group, groupIdx) => {
            const isCollapsed = collapsedKeys.has(group.id)
            const isLastGroup = groupIdx === flatGroups.length - 1

            return (
              <div
                key={group.id}
                className={`tree-group ${isCollapsed ? 'is-collapsed' : ''} ${
                  isLastGroup ? 'is-last-group' : ''
                }`}
              >
                <div
                  className="tree-group-header"
                  onClick={() => toggleCollapse(group.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggleCollapse(group.id)
                    }
                  }}
                  aria-expanded={!isCollapsed}
                >
                  <span className={`tree-collapse-chevron ${isCollapsed ? 'collapsed' : ''}`}>▼</span>
                  <div className="tree-group-titles">
                    <span className="tree-group-title">{group.title}</span>
                    {group.subtitle && (
                      <span className="tree-group-subtitle">{group.subtitle}</span>
                    )}
                  </div>
                  {group.badge && (
                    <span className={`tree-group-badge badge--${group.badgeTone ?? 'neutral'}`}>
                      {group.badge}
                    </span>
                  )}
                </div>

                {!isCollapsed && (
                  <div className="tree-branch-container">
                    <div className="tree-branch-line" aria-hidden="true" />
                    <div className="tree-nodes-list">
                      {group.members.map((member) => renderAlarmCard(member))}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
