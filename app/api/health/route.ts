export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8001'

/**
 * GET /health            frontend liveness: 200 whenever Next.js is serving. `bridge` reports the
 *                        GNN bridge's state but never fails this check, so a sleeping bridge does
 *                        not count as frontend downtime.
 * GET /health?strict=1   200 only when the bridge answers and its rail engine is ready, else 503.
 *                        Waits up to 45 s, long enough for a Render free instance to wake, so a
 *                        monitor on this URL also keeps the bridge awake.
 *
 * On Render the bridge is its own web service; GNN_FASTAPI_URL must be its public URL.
 */
export async function GET(request: Request) {
  const backendUrl = (process.env.GNN_FASTAPI_URL || DEFAULT_BACKEND_URL).replace(/\/$/, '')
  const strict = new URL(request.url).searchParams.has('strict')
  const started = Date.now()

  let bridge: Record<string, unknown> | 'down' = 'down'
  try {
    const res = await fetch(`${backendUrl}/health`, { cache: 'no-store', signal: AbortSignal.timeout(strict ? 45_000 : 3_000) })
    bridge = res.ok ? await res.json() : 'down'
  } catch {
    bridge = 'down'
  }

  const ready = bridge !== 'down' && bridge.rail === 'ready'
  const body = { frontend: 'ok', bridge, bridgeReady: ready, bridgeUrl: backendUrl, checkedInMs: Date.now() - started }
  return Response.json(body, { status: strict && !ready ? 503 : 200, headers: { 'Cache-Control': 'no-store' } })
}
