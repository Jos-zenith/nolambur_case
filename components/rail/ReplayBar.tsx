'use client'

import { useState } from 'react'

import { clock } from '@/lib/rail/format'
import { railPost, useRail, useRoles } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

const SPEEDS = [4, 60, 240, 600, 1800]

export function ReplayBar() {
  const m = useRail(s => s.metrics)
  const dataset = useRail(s => s.dataset)
  const paused = useRail(s => s.paused)
  const setPaused = useRail(s => s.setPaused)
  const [busy, setBusy] = useState(false)
  const { can } = useRoles()
  if (!m || !dataset) return null

  const control = async (body: object) => {
    setBusy(true)
    const { data } = await railPost<{ paused: boolean }>('control', body)
    if (typeof data.paused === 'boolean') setPaused(data.paused)
    setBusy(false)
  }

  if (m.rowsTotal === null) return <StreamBar paused={paused} busy={busy} control={control} canRestart={can('restart')} />

  const progress = m.rowsReplayed / m.rowsTotal
  const start = Date.parse(`${dataset.start}Z`) / 1000
  const end = Date.parse(`${dataset.end}Z`) / 1000
  const at = (iso: string | null) => (iso ? (Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`) / 1000 - start) / (end - start) : 0)
  const timePos = Math.min(1, Math.max(0, (m.simT - start) / (end - start)))
  // v2: the train / validation / test days; v1: the one window its fraud falls in
  const bands = dataset.splits
    ? [
        { key: 'val', from: at(dataset.splits.val[0]), to: at(dataset.splits.val[1]), cls: 'bg-sev-medium/35', label: 'validation' },
        { key: 'test', from: at(dataset.splits.test[0]), to: Math.min(1, at(dataset.splits.test[1])), cls: 'bg-ok/35', label: 'test' },
      ]
    : [{ key: 'fraud', from: at(dataset.fraudWindow[0]), to: at(dataset.fraudWindow[1]), cls: 'bg-sev-critical/40', label: 'fraud' }]

  return (
    <section className="grid gap-2 border bg-card px-3 py-2.5 md:grid-cols-[auto_1fr_auto] md:items-center md:gap-4">
      <div className="text-[12.5px]">
        <span className="text-muted-foreground">Replaying </span>
        <span className="font-mono">{dataset.file}</span>
        <span className="text-muted-foreground"> · {dataset.start.slice(0, 10)} </span>
        <span className="font-mono">{clock(m.simT)}</span>
        {m.ingested > 0 && <span className="text-muted-foreground"> · +{m.ingested.toLocaleString('en-IN')} ingested via webhook</span>}
      </div>
      <div className="grid gap-1">
        <div className="relative h-2 rounded-full bg-muted" title={dataset.splits ? 'Days 0–5 train the model, 6–7 pick its threshold (amber), 8–9 are the test days every reported number comes from (green).' : 'Dataset timeline. The red band is when the fraud happens.'}>
          {bands.map(b => (
            <div key={b.key} className={cn('absolute inset-y-0', b.cls)} style={{ left: `${b.from * 100}%`, width: `${Math.max(0.4, (b.to - b.from) * 100)}%` }} />
          ))}
          <div className="absolute inset-y-0 left-0 rounded-full bg-primary/70" style={{ width: `${timePos * 100}%` }} />
        </div>
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span>
            {m.rowsReplayed.toLocaleString('en-IN')} of {m.rowsTotal.toLocaleString('en-IN')} rows ({(progress * 100).toFixed(1)}%)
          </span>
          <span>
            {dataset.splits
              ? `train days 0–5 · validation 6–7 · test 8–9 · ${m.ruleVersion ? `rules ${m.ruleVersion} · ` : ''}model threshold ${m.modelThreshold?.toFixed(2) ?? '—'}`
              : `fraud window ${dataset.fraudWindow[0]?.slice(11) ?? '—'} to ${dataset.fraudWindow[1]?.slice(11) ?? '—'}`}
          </span>
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
        <button
          disabled={busy || !can('restart')}
          onClick={() => control({ restart: true })}
          className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
          title={can('restart') ? 'Reset alerts, freezes and cases, and replay from the first row' : 'Restart needs the admin role'}
        >
          Restart
        </button>
      </div>
    </section>
  )
}

/** Stream mode (RAIL_SOURCE=webhook|kafka|kinesis): no replay, the clock is event time. */
function StreamBar({ paused, busy, control, canRestart }: { paused: boolean; busy: boolean; control: (body: object) => Promise<void>; canRestart: boolean }) {
  const m = useRail(s => s.metrics)!
  const counts = useRail(s => s.tickCounts)
  const perSec = counts.length ? counts.slice(-10).reduce((a, b) => a + b, 0) / (Math.min(10, counts.length) * 0.5) : 0
  return (
    <section className="flex flex-wrap items-center gap-x-4 gap-y-2 border bg-card px-3 py-2.5 text-[12.5px]">
      <span className="flex items-center gap-1.5">
        <span className={cn('size-1.5 rounded-full', paused ? 'bg-sev-medium' : 'bg-ok')} />
        Live stream from <span className="font-mono">{m.source}</span>
      </span>
      <span className="text-muted-foreground">
        Event time <span className="font-mono text-foreground">{clock(m.simT)}</span>
      </span>
      <span className="text-muted-foreground">
        <span className="font-mono text-foreground">{m.ingested.toLocaleString('en-IN')}</span> payments this run · {perSec.toFixed(0)}/s ·{' '}
        {m.duplicatesDropped} duplicates dropped
      </span>
      {m.ingested === 0 && (
        <span className="basis-full text-muted-foreground">
          Waiting for payments. Send them to <code className="font-mono">POST /rail/ingest/payments</code>, publish to the configured topic or stream, or run{' '}
          <code className="font-mono">python -m infra.producer webhook</code> in <code className="font-mono">Multi-GNN/</code>. For the recorded demo, start the bridge with{' '}
          <code className="font-mono">RAIL_SOURCE=replay</code>.
        </span>
      )}
      <div className="ml-auto flex gap-1">
        <button disabled={busy} onClick={() => control({ paused: !paused })} className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent" title="Paused payments wait in the inbox; nothing is dropped">
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          disabled={busy || !canRestart}
          onClick={() => control({ restart: true })}
          className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
          title={canRestart ? 'Clear alerts, freezes and cases. The audit trail in the store is kept.' : 'Reset needs the admin role'}
        >
          Reset state
        </button>
      </div>
    </section>
  )
}
