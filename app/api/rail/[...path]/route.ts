export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const BRIDGE = (process.env.GNN_FASTAPI_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')

async function proxy(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  const url = `${BRIDGE}/rail/${path.map(encodeURIComponent).join('/')}${new URL(request.url).search}`
  try {
    const upstream = await fetch(url, {
      method: request.method,
      // X-Rail-Actor is the console's user picker. In production an auth proxy would set it from a verified session.
      headers: { 'Content-Type': 'application/json', Accept: request.headers.get('accept') ?? '*/*', 'X-Rail-Actor': request.headers.get('x-rail-actor') ?? '' },
      body: request.method === 'GET' ? undefined : await request.text(),
      cache: 'no-store',
      signal: request.signal,
    })
    const headers = new Headers({ 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-cache, no-transform' })
    const disposition = upstream.headers.get('content-disposition')
    if (disposition) headers.set('Content-Disposition', disposition)
    return new Response(upstream.body, { status: upstream.status, headers })
  } catch {
    return Response.json({ detail: { status: 'offline', error: `GNN bridge not reachable at ${BRIDGE}` } }, { status: 502 })
  }
}

export const GET = proxy
export const POST = proxy
