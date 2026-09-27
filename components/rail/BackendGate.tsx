'use client'

import { useRail } from '@/lib/rail/store'

/** Renders children only when the GNN bridge is streaming; otherwise says exactly what is going on. */
export function BackendGate({ children }: { children: React.ReactNode }) {
  const backend = useRail(s => s.backend)
  const error = useRail(s => s.backendError)
  const metrics = useRail(s => s.metrics)

  if (backend === 'live' && metrics) return <>{children}</>

  return (
    <section className="max-w-3xl border bg-card p-5 text-[13.5px] leading-relaxed">
      {backend === 'warming' || backend === 'connecting' ? (
        <>
          <h2 className="text-[15px] font-semibold">Warming up the GNN bridge</h2>
          <p className="mt-2 text-muted-foreground">
            The bridge is loading <code className="font-mono text-[12.5px]">nolambur_transactions.csv</code> (30,353 rows), building the transaction graph, and
            scoring every edge with the GIN checkpoint. This takes about 30 seconds on a CPU. The page connects on its own when it is ready.
          </p>
        </>
      ) : (
        <>
          <h2 className="text-[15px] font-semibold">{backend === 'error' ? 'The GNN bridge failed to start' : 'The GNN bridge is not running'}</h2>
          <p className="mt-2 text-muted-foreground">
            Every alert, score and transaction on this console comes from the Python backend. Nothing is generated in the browser. Start it from the
            repository root:
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
