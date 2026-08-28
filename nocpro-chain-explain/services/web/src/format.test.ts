import { describe, expect, it } from 'vitest'

import { compactTime, humanize, percent } from './format'

describe('operator formatting', () => {
  it('keeps missing statistics visibly unavailable', () => {
    expect(percent(null)).toBe('UNAVAILABLE')
    expect(percent(0)).toBe('0%')
  })

  it('formats known values without inventing precision', () => {
    expect(percent(0.734)).toBe('73%')
    expect(compactTime(null)).toBe('time unavailable')
    expect(humanize('SHARED_ACTIVE_PATH')).toBe('shared active path')
  })
})
