import { NextResponse } from 'next/server'

import { getPulseAlerts } from '@/lib/mule-data'

export const runtime = 'nodejs'

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8001'

function getBackendUrl() {
  return (process.env.GNN_FASTAPI_URL || DEFAULT_BACKEND_URL).replace(/\/$/, '')
}

function createLocalStream() {
  const encoder = new TextEncoder()
  const alerts = getPulseAlerts()
  let index = 0

  return new ReadableStream<Uint8Array>({
    start(controller) {
      const emit = () => {
        const alert = alerts[index % alerts.length]
        index += 1
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(alert)}\n\n`))
      }

      emit()
      const timer = setInterval(emit, 1800)

      const close = () => {
        clearInterval(timer)
        controller.close()
      }

      setTimeout(close, 12000)
    },
  })
}

export async function GET() {
  try {
    const backendResponse = await fetch(`${getBackendUrl()}/stream`, {
      headers: {
        Accept: 'text/event-stream',
      },
      cache: 'no-store',
    })

    if (backendResponse.ok && backendResponse.body) {
      return new Response(backendResponse.body, {
        status: backendResponse.status,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache, no-transform',
          Connection: 'keep-alive',
        },
      })
    }
  } catch {
    // Local fallback below.
  }

  return new NextResponse(createLocalStream(), {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  })
}