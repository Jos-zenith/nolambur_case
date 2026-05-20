'use client'

import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { getPulseAlerts, type MulePulseAlert } from '@/lib/mule-data'
import { useMuleStore } from '@/lib/mule-store'

type PulseState = {
  alerts: MulePulseAlert[]
  connected: boolean
  error: string | null
}

export function useMulePulse(): PulseState {
  const alerts = useMuleStore(state => state.alerts)
  const setAlerts = useMuleStore(state => state.setAlerts)
  const setGraphError = useMuleStore(state => state.setGraphError)
  const [connected, setConnected] = useState(false)
  const seenAlertIds = useRef<Set<string>>(new Set())

  useEffect(() => {
    const fallbackAlerts = getPulseAlerts()
    const stream = new EventSource('/api/stream')

    stream.onopen = () => {
      setConnected(true)
      setGraphError(null)
    }

    stream.onmessage = event => {
      try {
        const payload = JSON.parse(event.data) as MulePulseAlert
        const currentAlerts = useMuleStore.getState().alerts
        setAlerts([payload, ...currentAlerts].slice(0, 50))

        if (!seenAlertIds.current.has(payload.id)) {
          seenAlertIds.current.add(payload.id)

          toast.warning(`New mule detected: ${payload.accountId}`, {
            description: `${(payload.muleScore * 100).toFixed(1)}% risk · ${payload.statePair} · ${payload.label}`,
          })

          if (payload.muleScore >= 0.95) {
            toast.success(`Account freeze initiated: ${payload.accountId}`, {
              description: 'Critical risk threshold exceeded (95%+).',
            })
          }
        }
      } catch {
        setAlerts(fallbackAlerts)
      }
    }

    stream.onerror = () => {
      setConnected(false)
      setGraphError('Pulse stream unavailable')
      setAlerts(fallbackAlerts)
      stream.close()
    }

    return () => {
      stream.close()
    }
  }, [setAlerts, setGraphError])

  return {
    alerts,
    connected,
    error: null,
  }
}