import { useCallback, useEffect, useRef, useState } from 'react'

import {
  LiveRefreshScheduler,
  LiveUpdateClient,
  type LiveConnectionState,
  type LiveNotice,
} from './liveUpdates'

export type LiveInvalidationHandler = (
  notices: readonly LiveNotice[],
  scheduler: LiveRefreshScheduler,
) => void

export function useLiveUpdates(onInvalidate: LiveInvalidationHandler) {
  const handlerRef = useRef(onInvalidate)
  const schedulerRef = useRef<LiveRefreshScheduler | null>(null)
  const [connectionState, setConnectionState] = useState<LiveConnectionState>('CONNECTING')
  const [lastSuccessfulSync, setLastSuccessfulSync] = useState<Date | null>(null)

  useEffect(() => {
    handlerRef.current = onInvalidate
  }, [onInvalidate])

  useEffect(() => {
    const scheduler = new LiveRefreshScheduler()
    const client = new LiveUpdateClient({
      onInvalidate: notices => handlerRef.current(notices, scheduler),
      onState: setConnectionState,
    })
    schedulerRef.current = scheduler
    client.start()

    return () => {
      client.stop()
      scheduler.stop()
      if (schedulerRef.current === scheduler) schedulerRef.current = null
    }
  }, [])

  const scheduleRefresh = useCallback((key: string, task: (signal: AbortSignal) => Promise<void>) => (
    schedulerRef.current?.schedule(key, task) ?? false
  ), [])
  const cancelRefresh = useCallback((key: string) => {
    schedulerRef.current?.cancel(key)
  }, [])
  const markSuccessfulSync = useCallback(() => {
    setLastSuccessfulSync(new Date())
  }, [])

  return {
    connectionState,
    lastSuccessfulSync,
    scheduleRefresh,
    cancelRefresh,
    markSuccessfulSync,
  }
}
