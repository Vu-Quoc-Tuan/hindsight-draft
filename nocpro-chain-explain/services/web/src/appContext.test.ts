import { describe, expect, it } from 'vitest'

import { analysisContextKey, analysisMatchesContext } from './appContext'
import type { ChainAnalysis } from './types'

const analysis = { chain_id: 'CHAIN-A' } as ChainAnalysis

describe('analysis context identity', () => {
  it('includes snapshot identity, chain and config epoch', () => {
    expect(analysisContextKey('S1:v1', 'CHAIN-A', 3)).toBe('S1:v1\u0000CHAIN-A\u00003')
  })

  it('rejects a previous chain payload under a new chain context', () => {
    expect(analysisMatchesContext(
      { requestKey: analysisContextKey('S1:v1', 'CHAIN-A', 0), payload: analysis },
      analysisContextKey('S1:v1', 'CHAIN-B', 0),
      'CHAIN-B',
    )).toBe(false)
  })

  it('rejects the same chain id from another snapshot version', () => {
    expect(analysisMatchesContext(
      { requestKey: analysisContextKey('S1:v1', 'CHAIN-A', 0), payload: analysis },
      analysisContextKey('S1:v2', 'CHAIN-A', 0),
      'CHAIN-A',
    )).toBe(false)
  })
})
