import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EvolutionChangesContent } from './EvolutionChanges'
import type { EvolutionChanges, EvolutionEndpoint } from '../types'

const child: EvolutionEndpoint = { snapshot_id: 'S2', snapshot_version: 'v2', chain_id: 'C2' }
const parent: EvolutionEndpoint = { snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1' }

function changes(overrides: Partial<EvolutionChanges> = {}): EvolutionChanges {
  return {
    status: 'PARTIAL', reason_codes: ['QUALITY_RECEIPT_UNAVAILABLE'],
    parent, child, event_type: 'CONTINUE',
    parent_source_kind: 'SYNTHETIC', child_source_kind: 'REAL_EXPORT_REPLAY',
    predecessor_choices: [], predecessor_choices_truncated: false,
    parent_receipt_choices: [], child_receipt_choices: [],
    parent_receipt_choices_truncated: false, child_receipt_choices_truncated: false,
    membership: {
      added_count: 1, removed_count: 1, retained_count: 2,
      added_alarm_ids: ['A-2'], removed_alarm_ids: ['A-1'], truncated: false,
    },
    context_changes: [],
    quality: {
      comparable: false, reason_codes: ['QUALITY_RECEIPT_UNAVAILABLE'],
      before_score: null, after_score: null, before_stars: null, after_stars: null,
      delta: null, before_receipt_id: null, after_receipt_id: null,
    },
    explanations: [{ code: 'MEMBERS_LEFT_CHAIN', text: 'unused server narrative', evidence_ids: ['A-1'] }],
    ...overrides,
  }
}

describe('EvolutionChangesContent', () => {
  it('explains a single-snapshot case without exposing raw unavailable codes', () => {
    const html = renderToStaticMarkup(<EvolutionChangesContent
      child={child}
      discovered={{ key: 'child', value: changes({
        status: 'UNAVAILABLE', reason_codes: ['SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE'],
        parent: null, event_type: null, membership: null, explanations: [],
      }), error: null }}
      current={null}
      parent={null}
      receiptOptions={null}
      parentReceiptId={null}
      childReceiptId={null}
      onSelectParent={() => undefined}
      onSelectParentReceipt={() => undefined}
      onSelectChildReceipt={() => undefined}
    />)

    expect(html).toContain('Chưa đủ dữ liệu')
    expect(html).toContain('Chưa có snapshot trước để đối chiếu.')
    expect(html).not.toContain('UNAVAILABLE')
    expect(html).not.toContain('SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE')
  })

  it('renders the selected lineage edge and says leaving a chain is not a cleared alarm', () => {
    const value = changes()
    const html = renderToStaticMarkup(<EvolutionChangesContent
      child={child}
      discovered={{ key: 'child', value: changes({ predecessor_choices: [{
        parent, event_type: 'CONTINUE', parent_source_kind: 'SYNTHETIC', child_source_kind: 'REAL_EXPORT_REPLAY',
      }] }), error: null }}
      current={{ key: 'selection', value, error: null }}
      parent={parent}
      receiptOptions={null}
      parentReceiptId={null}
      childReceiptId={null}
      onSelectParent={() => undefined}
      onSelectParentReceipt={() => undefined}
      onSelectChildReceipt={() => undefined}
    />)

    expect(html).toContain('C1 · S1@v1')
    expect(html).toContain('C2 · S2@v2')
    expect(html).toContain('1 alarm rời chain; điều này không đồng nghĩa alarm đã clear.')
    expect(html).toContain('Chưa đủ dữ liệu so sánh chênh lệch điểm · Thiếu biên nhận đánh giá lịch sử.')
  })
})
