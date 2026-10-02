'use client'

import { ArrowRight, CircleDashed, History, PlugZap } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

import { capturedLabel } from '@/lib/rail/snapshot'
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
  const captured = snapshot ? capturedLabel(snapshot.capturedAt) : null
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
    <section className="grid gap-3">
    <div className="grid gap-5 rounded-xl border bg-card p-5 text-[13.5px] leading-relaxed shadow-card lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div>
      {waking ? (
        <>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            <CircleDashed className="size-4 animate-spin text-sev-medium" />
            {backend === 'warming' ? 'Warming up the GNN bridge' : 'Waking the GNN bridge'}
          </h2>
          <p className="mt-2 text-muted-foreground">{waitText(backend, seconds)}</p>
          <p className="mt-2 text-muted-foreground">
            Once awake it replays the 10-day synthetic dataset (83,067 payments) and scores each one with the GIN checkpoint. The page connects on its own when
            it is ready.
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
      </div>
      <div className="rounded-lg bg-muted/40 p-4">
        <p className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Works without the bridge</p>
        <ul className="mt-2 grid gap-1.5">
          {OFFLINE_PAGES.map(p => (
            <li key={p.href}>
              <Link href={p.href} className="group flex items-baseline justify-between gap-3 text-[13px] hover:text-brand-2">
                <span>
                  <span className="font-medium">{p.label}</span> <span className="text-muted-foreground">· {p.note}</span>
                </span>
                <ArrowRight className="size-3.5 shrink-0 text-muted-foreground group-hover:text-brand-2" />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
    <PageSkeleton />
    </section>
  )
}

const OFFLINE_PAGES = [
  { href: '/', label: 'Overview', note: 'last captured snapshot' },
  { href: '/merchants', label: 'Merchants', note: 'merchant-side replay snapshot' },
  { href: '/model', label: 'Model', note: 'training and held-out results' },
]

/** Where the page's content will land, so the wait reads as loading rather than an empty page. */
function PageSkeleton() {
  const bar = 'rounded-md bg-muted/70'
  return (
    <div aria-hidden className="grid animate-pulse gap-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="grid gap-2 rounded-xl border bg-card p-4">
            <div className={`${bar} h-3 w-1/2`} />
            <div className={`${bar} h-6 w-2/3`} />
          </div>
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="grid content-start gap-2 rounded-xl border bg-card p-4">
          {[0, 1, 2, 3, 4, 5].map(i => (
            <div key={i} className={`${bar} h-10`} />
          ))}
        </div>
        <div className="grid content-start gap-2 rounded-xl border bg-card p-4">
          <div className={`${bar} h-4 w-1/3`} />
          <div className={`${bar} h-40`} />
          <div className={`${bar} h-4 w-2/3`} />
          <div className={`${bar} h-4 w-1/2`} />
        </div>
      </div>
    </div>
  )
}
