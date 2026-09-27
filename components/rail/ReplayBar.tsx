'use client'

import { useState } from 'react'

import { clock } from '@/lib/rail/format'
import { railPost, useRail } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

const SPEEDS = [1, 4, 20, 120, 600]

export function ReplayBar() {
  const m = useRail(s => s.metrics)
  const dataset = useRail(s => s.dataset)
  const paused = useRail(s => s.paused)
  const setPaused = useRail(s => s.setPaused)
  const [busy, setBusy] = useState(false)
  if (!m || !dataset) return null

  const control = async (body: object) => {
    setBusy(true)
    const { data } = await railPost<{ paused: boolean }>('control', body)
    if (typeof data.paused === 'boolean') setPaused(data.paused)
    setBusy(false)
  }

  const progress = m.rowsReplayed / m.rowsTotal
  const start = Date.parse(`${dataset.start}Z`) / 1000
  const end = Date.parse(`${dataset.end}Z`) / 1000
  const fraudStart = (Date.parse(`${dataset.fraudWindow[0]}Z`) / 1000 - start) / (end - start)
  const fraudEnd = (Date.parse(`${dataset.fraudWindow[1]}Z`) / 1000 - start) / (end - start)
  const timePos = Math.min(1, Math.max(0, (m.simT - start) / (end - start)))

  return (
    <section className="grid gap-2 border bg-card px-3 py-2.5 md:grid-cols-[auto_1fr_auto] md:items-center md:gap-4">
      <div className="text-[12.5px]">
        <span className="text-muted-foreground">Replaying </span>
        <span className="font-mono">{dataset.file}</span>
        <span className="text-muted-foreground"> · {dataset.start.slice(0, 10)} </span>
        <span className="font-mono">{clock(m.simT)}</span>
      </div>
      <div className="grid gap-1">
        <div className="relative h-2 rounded-full bg-muted" title="Dataset timeline. The red band is the hour the fraud happens in.">
          <div className="absolute inset-y-0 bg-sev-critical/40" style={{ left: `${fraudStart * 100}%`, width: `${Math.max(0.4, (fraudEnd - fraudStart) * 100)}%` }} />
          <div className="absolute inset-y-0 left-0 rounded-full bg-primary/70" style={{ width: `${timePos * 100}%` }} />
        </div>
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span>
            {m.rowsReplayed.toLocaleString('en-IN')} of {m.rowsTotal.toLocaleString('en-IN')} rows ({(progress * 100).toFixed(1)}%)
          </span>
          <span>fraud window {dataset.fraudWindow[0].slice(11)} to {dataset.fraudWindow[1].slice(11)}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {SPEEDS.map(s => (
          <button
            key={s}
            disabled={busy}
            onClick={() => control({ speed: s })}
            className={cn('h-7 rounded-sm border px-2 font-mono text-[12px] hover:bg-accent', m.speed === s && 'border-primary bg-accent')}
          >
            {s}×
          </button>
        ))}
        <button disabled={busy} onClick={() => control({ paused: !paused })} className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent">
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button disabled={busy} onClick={() => control({ restart: true })} className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent" title="Reset alerts, freezes and cases, and replay from the first row">
          Restart
        </button>
      </div>
    </section>
  )
}
