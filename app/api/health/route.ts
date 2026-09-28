export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8001'

export async function GET() {
  const backendUrl = (process.env.GNN_FASTAPI_URL || DEFAULT_BACKEND_URL).replace(/\/$/, '')

  try {
    const bridge = await fetch(`${backendUrl}/health`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    })
    const data = await bridge.json()

    return Response.json({ frontend: 'ok', bridge: data }, { status: bridge.ok ? 200 : 503 })
  } catch {
    return Response.json({ frontend: 'ok', bridge: 'down' }, { status: 503 })
  }
}