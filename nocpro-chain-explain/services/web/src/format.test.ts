import { describe, expect, it } from 'vitest'

import { compactTime, formatDuration, humanize, percent } from './format'

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

  it('formats durations in human-readable units', () => {
    expect(formatDuration(null)).toBe('Unavailable')
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(125)).toBe('2m')
    expect(formatDuration(3665)).toBe('1h 1m')
    expect(formatDuration(7200)).toBe('2h')
  })
})
