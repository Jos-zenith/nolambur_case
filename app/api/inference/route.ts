import { NextResponse } from 'next/server'

export const runtime = 'nodejs'

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8001'

function getBackendUrl() {
  return (process.env.GNN_FASTAPI_URL || DEFAULT_BACKEND_URL).replace(/\/$/, '')
}

async function readJsonResponse(response: Response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    return response.json()
  }

  return {
    status: response.ok ? 'ok' : 'error',
    message: await response.text(),
  }
}

async function proxyHealth() {
  const response = await fetch(`${getBackendUrl()}/health`, {
    cache: 'no-store',
  })

  return NextResponse.json(await readJsonResponse(response), { status: response.status })
}

async function proxyPrediction(request: Request) {
  let payload: unknown

  try {
    payload = await request.json()
  } catch {
    return NextResponse.json(
      {
        status: 'error',
        message: 'Request body must be valid JSON',
      },
      { status: 400 },
    )
  }

  const response = await fetch(`${getBackendUrl()}/predict`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  })

  return NextResponse.json(await readJsonResponse(response), { status: response.status })
}

export async function GET() {
  try {
    return await proxyHealth()
  } catch (error) {
    return NextResponse.json(
      {
        status: 'unavailable',
        message: error instanceof Error ? error.message : 'FastAPI inference bridge is not reachable',
      },
      { status: 503 },
    )
  }
}

export async function POST(request: Request) {
  try {
    return await proxyPrediction(request)
  } catch (error) {
    return NextResponse.json(
      {
        status: 'error',
        message: error instanceof Error ? error.message : 'Failed to proxy the inference request',
      },
      { status: 502 },
    )
  }
}