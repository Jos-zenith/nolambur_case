'use client'

import { useEffect, useState } from 'react'

import { AlertDetail } from '@/components/rail/AlertDetail'
import { AlertQueue } from '@/components/rail/AlertQueue'
import { BackendGate } from '@/components/rail/BackendGate'
import { MetricStrip } from '@/components/rail/MetricStrip'
import { ReplayBar } from '@/components/rail/ReplayBar'
import { TxnTape } from '@/components/rail/TxnTape'
import { sortAlerts, useRail } from '@/lib/rail/store'

export default function ConsolePage() {
  const alerts = useRail(s => s.alerts)
  const [selected, setSelected] = useState<string | null>(null)
  const [showLabels, setShowLabels] = useState(true)

  useEffect(() => {
    if (selected && alerts[selected]) return
    const first = sortAlerts(Object.values(alerts).filter(a => a.status === 'open'))[0]
    setSelected(first?.id ?? null)
  }, [alerts, selected])

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-[18px] font-semibold">Alert queue</h1>
          <p className="mt-0.5 text-[12.5px] text-muted-foreground">
            Detectors run in <code className="font-mono">Multi-GNN/rail_engine.py</code>{' '}on each row as the replay reaches it. The GIN checkpoint&apos;s score adds to the ranking.
          </p>
        </div>
        <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground" title="Labels come from nolambur_labels.csv. Detectors never read them.">
          <input type="checkbox" checked={showLabels} onChange={e => setShowLabels(e.target.checked)} className="accent-[var(--primary)]" />
          Show dataset labels (evaluation only)
        </label>
      </div>
      <BackendGate>
        <ReplayBar />
        <MetricStrip />
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
          <div className="lg:sticky lg:top-16 lg:h-[calc(100vh-5rem)]">
            <AlertQueue selectedId={selected} onSelect={setSelected} showLabels={showLabels} />
          </div>
          {selected ? (
            <AlertDetail alertId={selected} onSelect={setSelected} showLabels={showLabels} />
          ) : (
            <div className="grid min-h-[300px] place-items-center border bg-card p-6 text-center text-[13px] text-muted-foreground">
              No open alerts yet. The fraud in this dataset happens between 10:30 and 10:35 on the first morning.
            </div>
          )}
        </div>
        <TxnTape showLabels={showLabels} />
      </BackendGate>
    </div>
  )
}
