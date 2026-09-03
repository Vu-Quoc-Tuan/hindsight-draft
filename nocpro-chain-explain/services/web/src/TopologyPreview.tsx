import { useEffect, useState } from 'react'

import { api } from './api'
import { TopologyTree, type TopologyTreePayload } from './TopologyTree'

type Profile = 'ALARM_ONLY' | 'IP_NETWORK' | 'IT_SERVICES'

export function TopologyPreview() {
  const [profile, setProfile] = useState<Profile>('IT_SERVICES')
  const [payload, setPayload] = useState<TopologyTreePayload | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api.topologyProjection(profile, controller.signal).then(setPayload).catch((cause: unknown) => {
      if (!controller.signal.aborted) setPayload({ status: 'UNAVAILABLE', profile, topology_kind: 'UNAVAILABLE', reason: cause instanceof Error ? cause.message : 'TOPOLOGY_PROJECTION_UNAVAILABLE' })
    })
    return () => controller.abort()
  }, [profile])
  return <main className="topology-preview"><header><p className="kicker">Development preview · topology source navigation</p><h1>NocPro topology tree</h1><label>Dataset profile<select value={profile} onChange={(event) => setProfile(event.target.value as Profile)}><option value="ALARM_ONLY">Alarm-only</option><option value="IP_NETWORK">IP network</option><option value="IT_SERVICES">IT services</option></select></label></header>{payload ? <TopologyTree payload={payload} /> : <div className="loading-state"><span /><p>Loading source projection…</p></div>}</main>
}
