'use client'

import { useEffect } from 'react'
import { create } from 'zustand'

import { BUNDLED_SNAPSHOT } from './snapshot'
import type { Alert, AuditEntry, Case, DatasetFacts, Metrics, RailSnapshotFile, Roles, RoleName, Row, Snapshot, StreamEvent } from './types'

export type BackendState = 'connecting' | 'live' | 'warming' | 'offline' | 'error'

interface RailState {
  backend: BackendState
  backendError: string | null
  /** when the page started waiting for the bridge (ms), null once it is live */
  waitingSince: number | null
  /** last-known numbers from public/rail-snapshot.json, shown only while the bridge is not live */
  snapshot: RailSnapshotFile | null
  paused: boolean
  metrics: Metrics | null
  dataset: DatasetFacts | null
  alerts: Record<string, Alert>
  rows: Row[]
  audit: AuditEntry[]
  cases: Case[]
  frozen: Record<string, string | null>
  tickCounts: number[]
  fresh: Record<string, true>
  /** who the console acts as; sent as X-Rail-Actor and checked by the bridge */
  actor: string | null
  roles: Roles | null
  setActor: (actor: string) => void
  setRoles: (roles: Roles) => void
  setBackend: (b: BackendState, error?: string | null) => void
  setPaused: (p: boolean) => void
  load: (s: Snapshot) => void
  apply: (e: StreamEvent) => void
}

export const useRail = create<RailState>(set => ({
  backend: 'connecting',
  backendError: null,
  waitingSince: null,
  snapshot: BUNDLED_SNAPSHOT,
  paused: false,
  metrics: null,
  dataset: null,
  alerts: {},
  rows: [],
  audit: [],
  cases: [],
  frozen: {},
  tickCounts: [],
  fresh: {},
  actor: null,
  roles: null,
  setActor: actor => {
    try {
      localStorage.setItem('rail.actor', actor)
    } catch {}
    set({ actor })
  },
  setRoles: roles =>
    set(state => {
      let saved: string | null = null
      try {
        saved = localStorage.getItem('rail.actor')
      } catch {}
      const known = (a: string | null) => !!a && roles.users.some(u => u.actor === a)
      return { roles, actor: known(state.actor) ? state.actor : known(saved) ? saved : roles.users[0]?.actor ?? null }
    }),
  setBackend: (backend, backendError = null) =>
    set(s => ({ backend, backendError, waitingSince: backend === 'live' ? null : (s.waitingSince ?? Date.now()) })),
  setPaused: paused => set({ paused }),
  load: s =>
    set({
      backend: 'live',
      waitingSince: null,
      paused: s.paused,
      metrics: s.metrics,
      dataset: s.dataset,
      alerts: Object.fromEntries(s.alerts.map(a => [a.id, a])),
      rows: s.rows,
      audit: s.audit,
      cases: s.cases,
      frozen: Object.fromEntries(s.frozen.map(f => [f.accountId, f.reference])),
      tickCounts: s.tickCounts,
      fresh: {},
    }),
  apply: e =>
    set(state => {
      switch (e.type) {
        case 'tick':
          return {
            metrics: e.metrics,
            // a reconnect can deliver a row in both the snapshot and the next tick; keep one copy
            rows: e.rows.length
              ? [...[...e.rows].reverse(), ...state.rows].filter((r, i, all) => all.findIndex(x => x.row === r.row && x.t === r.t) === i).slice(0, 120)
              : state.rows,
            tickCounts: [...state.tickCounts, e.rows.length].slice(-60),
          }
        case 'alert':
          return {
            alerts: { ...state.alerts, [e.alert.id]: e.alert },
            fresh: state.alerts[e.alert.id] ? state.fresh : { ...state.fresh, [e.alert.id]: true },
          }
        case 'audit':
          return { audit: [e.entry, ...state.audit].slice(0, 200) }
        case 'frozen':
          return { frozen: { ...state.frozen, [e.accountId]: e.reference } }
        case 'held':
        case 'released':
          return {}
        case 'reset':
          return {
            metrics: e.snapshot.metrics,
            alerts: {},
            rows: [],
            audit: [],
            cases: [],
            frozen: {},
            tickCounts: [],
            fresh: {},
          }
      }
    }),
}))

const SEV = { critical: 3, high: 2, medium: 1, low: 0 }

export function sortAlerts(alerts: Alert[]) {
  return [...alerts].sort((a, b) => SEV[b.severity] - SEV[a.severity] || b.score - a.score || b.updatedT - a.updatedT)
}

/** One app-wide stream from the GNN bridge's replay engine. */
export function useRailStream() {
  useEffect(() => {
    const { setBackend, load, apply } = useRail.getState()
    useRail.setState(s => ({ waitingSince: s.waitingSince ?? Date.now() }))
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    const diagnose = async () => {
      try {
        const res = await fetch('/api/rail/status', { cache: 'no-store' })
        const body = await res.json()
        const status = body.status ?? body.detail?.status
        if (status === 'warming' || status === 'starting') setBackend('warming')
        else if (status === 'error') setBackend('error', body.error ?? body.detail?.error)
        else if (res.status === 502) setBackend('offline', body.detail?.error)
        else if (status === 'ready') return true
        else setBackend('offline')
      } catch {
        setBackend('offline')
      }
      return false
    }

    const connect = async () => {
      if (closed) return
      const ready = await diagnose()
      if (!ready) {
        retry = setTimeout(connect, 3000)
        return
      }
      source = new EventSource('/api/rail/stream')
      source.addEventListener('snapshot', e => load(JSON.parse((e as MessageEvent).data)))
      for (const name of ['tick', 'alert', 'audit', 'frozen', 'reset']) {
        source.addEventListener(name, e => apply(JSON.parse((e as MessageEvent).data)))
      }
      source.onerror = () => {
        source?.close()
        if (closed) return
        setBackend('connecting')
        retry = setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      source?.close()
    }
  }, [])
}

export async function railPost<T = unknown>(path: string, body?: unknown): Promise<{ ok: boolean; data: T & { error?: string } }> {
  const res = await fetch(`/api/rail/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Rail-Actor': useRail.getState().actor ?? '' },
    body: JSON.stringify(body ?? {}),
  })
  const data = await res.json()
  // FastAPI puts refusals (401 / 403 / 409) in `detail`; surface them as `error`
  if (!res.ok && !data.error && typeof data.detail === 'string') data.error = data.detail
  return { ok: res.ok, data }
}

/** Live metrics when the bridge streams; otherwise the captured snapshot, flagged as such. */
export function useDisplayMetrics() {
  const live = useRail(s => (s.backend === 'live' ? s.metrics : null))
  const snapshot = useRail(s => s.snapshot)
  if (live) return { metrics: live, stale: false as const, capturedAt: null }
  if (snapshot) return { metrics: snapshot.metrics, stale: true as const, capturedAt: snapshot.capturedAt }
  return { metrics: null, stale: false as const, capturedAt: null }
}

export function useRoles() {
  const roles = useRail(s => s.roles)
  const actor = useRail(s => s.actor)
  const backend = useRail(s => s.backend)
  useEffect(() => {
    if (roles || backend !== 'live') return
    fetch('/api/rail/roles', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(r => r && useRail.getState().setRoles(r))
      .catch(() => {})
  }, [roles, backend])
  const role = (roles?.users.find(u => u.actor === actor)?.role ?? null) as RoleName | null
  const can = (permission: string) => !!role && !!roles?.permissions[role]?.includes(permission)
  return { roles, actor, role, can }
}
