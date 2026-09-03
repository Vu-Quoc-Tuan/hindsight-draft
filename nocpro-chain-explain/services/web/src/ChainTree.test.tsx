import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ChainTree } from './ChainTree'
import type { Member } from './types'

const mockMembers: Member[] = [
  {
    alarm_id: 'alm-001',
    alarm_name: 'BGP Neighbor Down',
    device_code: 'RTR-CORE-01',
    node_reference: 'SITE-HN',
    canonical_start_time: '2026-09-03T08:00:00Z',
    role: 'CORE',
    membership_support: 0.95,
    availability_coverage: 1.0,
    computable_groups: 3,
    representativeness: 0.9,
    group_fits: [],
    margins: [],
    redundancy_role: null,
    failure_domains: ['FD-01'],
  },
  {
    alarm_id: 'alm-002',
    alarm_name: 'OSPF Adjacency Loss',
    device_code: 'RTR-CORE-01',
    node_reference: 'SITE-HN',
    canonical_start_time: '2026-09-03T08:00:04Z',
    role: 'CONNECTOR',
    membership_support: 0.85,
    availability_coverage: 1.0,
    computable_groups: 2,
    representativeness: 0.8,
    group_fits: [],
    margins: [],
    redundancy_role: null,
    failure_domains: ['FD-01'],
  },
  {
    alarm_id: 'alm-003',
    alarm_name: 'Interface Link Down',
    device_code: 'SW-ACC-05',
    node_reference: 'SITE-DN',
    canonical_start_time: '2026-09-03T08:00:20Z',
    role: 'LEAF',
    membership_support: 0.7,
    availability_coverage: 0.9,
    computable_groups: 1,
    representativeness: 0.5,
    group_fits: [],
    margins: [],
    redundancy_role: null,
    failure_domains: [],
  },
]

describe('ChainTree component', () => {
  it('renders 3-level Resource Hierarchy (Site -> Device -> Alarm) by default', () => {
    const html = renderToStaticMarkup(
      <ChainTree
        members={mockMembers}
        selectedMembers={[]}
        onSelectMember={() => {}}
        onInspectMember={() => {}}
      />
    )

    // Level 1: Sites
    expect(html).toContain('SITE-HN')
    expect(html).toContain('SITE-DN')

    // Level 2: Devices
    expect(html).toContain('RTR-CORE-01')
    expect(html).toContain('SW-ACC-05')

    // Device role pills
    expect(html).toContain('1 CORE')
    expect(html).toContain('1 CONNECTOR')
    expect(html).toContain('1 LEAF')

    // Level 3: Alarms with sanitized membership roles (no root cause claim)
    expect(html).toContain('BGP Neighbor Down')
    expect(html).toContain('OSPF Adjacency Loss')
    expect(html).toContain('Interface Link Down')
    expect(html).toContain('CORE member')
    expect(html).not.toContain('Root Cause')
  })

  it('marks selected members for pair comparison', () => {
    const html = renderToStaticMarkup(
      <ChainTree
        members={mockMembers}
        selectedMembers={['alm-001']}
        activeInspectId="alm-002"
        onSelectMember={() => {}}
        onInspectMember={() => {}}
      />
    )

    expect(html).toContain('is-selected-pair')
    expect(html).toContain('is-inspecting')
    expect(html).toContain('✓ Compared')
  })

  it('renders tree structure controls with sanitized mode names', () => {
    const html = renderToStaticMarkup(
      <ChainTree
        members={mockMembers}
        selectedMembers={[]}
        onSelectMember={() => {}}
        onInspectMember={() => {}}
      />
    )

    expect(html).toContain('Resource Hierarchy')
    expect(html).toContain('By Role &amp; Membership')
    expect(html).toContain('Cascade Stages')
    expect(html).toContain('Expand all')
    expect(html).toContain('Collapse all')
  })
})
