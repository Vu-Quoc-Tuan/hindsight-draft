import type { ChainAnalysis } from './types'

export type AnalysisState = {
  requestKey: string
  payload: ChainAnalysis
}

export function analysisContextKey(snapshotKey: string, chainId: string, configEpoch: number) {
  return `${snapshotKey}\u0000${chainId}\u0000${configEpoch}`
}

export function analysisMatchesContext(
  state: AnalysisState | null,
  requestKey: string | null,
  chainId: string,
) {
  return Boolean(
    state
    && requestKey
    && state.requestKey === requestKey
    && state.payload.chain_id === chainId,
  )
}
