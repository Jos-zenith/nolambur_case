'use client'

import { CircleDashed, History, PlugZap } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useRail } from '@/lib/rail/store'

/** Seconds since the page started waiting for the bridge; ticks once a second while waiting. */
export function useWaitSeconds() {
  const since = useRail(s => s.waitingSince)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since === null) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [since])
  return since === null ? 0 : Math.max(0, Math.round((now - since) / 1000))
}

function waitText(backend: string, seconds: number) {
  if (backend === 'warming') return `The bridge is up and scoring the dataset (${seconds}s). Usually under a minute.`
  if (backend === 'error') return 'The bridge started but failed. Its logs say why.'
  return seconds < 90
    ? `Waking the GNN bridge (${seconds}s). The free server sleeps after 15 idle minutes and takes about a minute to start.`
    : `Still waiting for the GNN bridge (${seconds}s). It may be down; the page keeps retrying every 3 seconds.`
}

/** Shown above snapshot content: what the numbers are, and that live data is on its way. */
export function WakeBanner() {
  const backend = useRail(s => s.backend)
  const snapshot = useRail(s => s.snapshot)
  const seconds = useWaitSeconds()
  if (backend === 'live') return null
  const captured = snapshot ? new Date(snapshot.capturedAt).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : null
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-sev-medium/30 bg-sev-medium-bg/60 px-3 py-2 text-[12.5px]">
      <span className="flex items-center gap-1.5 font-medium">
        <CircleDashed className="size-3.5 animate-spin text-sev-medium" />
        {backend === 'warming' ? 'Bridge warming up' : 'Bridge waking up'}
      </span>
      <span className="text-muted-foreground">{waitText(backend, seconds)}</span>
      {captured && (
        <span className="flex items-center gap-1 text-muted-foreground">
          <History className="size-3.5" /> Numbers below are a snapshot the bridge reported on {captured}; they switch to live on their own.
        </span>
      )}
    </div>
  )
}

/**
 * Renders children only when the GNN bridge is streaming. With `allowSnapshot`, it renders them
 * from the captured snapshot while the bridge wakes, under a banner that says so.
 */
export function BackendGate({ children, allowSnapshot = false }: { children: React.ReactNode; allowSnapshot?: boolean }) {
  const backend = useRail(s => s.backend)
  const error = useRail(s => s.backendError)
  const metrics = useRail(s => s.metrics)
  const snapshot = useRail(s => s.snapshot)
  const seconds = useWaitSeconds()

  if (backend === 'live' && metrics) return <>{children}</>
  if (allowSnapshot && snapshot) {
    return (
      <div className="grid gap-3">
        <WakeBanner />
        {children}
      </div>
    )
  }

  const waking = backend === 'warming' || backend === 'connecting' || (backend === 'offline' && seconds < 90)
  return (
    <section className="max-w-3xl border bg-card p-5 text-[13.5px] leading-relaxed">
      {waking ? (
        <>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            <CircleDashed className="size-4 animate-spin text-sev-medium" />
            {backend === 'warming' ? 'Warming up the GNN bridge' : 'Waking the GNN bridge'}
          </h2>
          <p className="mt-2 text-muted-foreground">{waitText(backend, seconds)}</p>
          <p className="mt-2 text-muted-foreground">
            Once awake it loads <code className="font-mono text-[12.5px]">nolambur_transactions.csv</code> (30,353 rows) and scores every edge with the GIN
            checkpoint. The page connects on its own when it is ready.
          </p>
        </>
      ) : (
        <>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            <PlugZap className="size-4 text-sev-critical" />
            {backend === 'error' ? 'The GNN bridge failed to start' : 'The GNN bridge is not reachable'}
          </h2>
          <p className="mt-2 text-muted-foreground">
            Every alert, score and transaction on this console comes from the Python backend. Nothing is generated in the browser. To run it locally:
          </p>
          <pre className="mt-3 overflow-x-auto rounded-sm border bg-background p-3 font-mono text-[12.5px]">
            {'cd Multi-GNN\npython bridge_api.py   # FastAPI on :8001, set GNN_FASTAPI_URL to change'}
          </pre>
          {error && <p className="mt-3 font-mono text-[12px] text-sev-critical">{error}</p>}
        </>
      )}
    </section>
  )
}
