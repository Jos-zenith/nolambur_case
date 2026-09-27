'use client'

import { useEffect } from 'react'
import { create } from 'zustand'

import type { Alert, AuditEntry, Case, DatasetFacts, Metrics, Row, Snapshot, StreamEvent } from './types'

export type BackendState = 'connecting' | 'live' | 'warming' | 'offline' | 'error'

interface RailState {
  backend: BackendState
  backendError: string | null
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
  setBackend: (b: BackendState, error?: string | null) => void
  setPaused: (p: boolean) => void
  load: (s: Snapshot) => void
  apply: (e: StreamEvent) => void
}

export const useRail = create<RailState>(set => ({
  backend: 'connecting',
  backendError: null,
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
  setBackend: (backend, backendError = null) => set({ backend, backendError }),
  setPaused: paused => set({ paused }),
  load: s =>
    set({
      backend: 'live',
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
            rows: e.rows.length ? [...[...e.rows].reverse(), ...state.rows].slice(0, 120) : state.rows,
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return { ok: res.ok, data: await res.json() }
}
