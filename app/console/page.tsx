'use client'

import { ListChecks, MousePointerClick } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AlertDetail } from '@/components/rail/AlertDetail'
import { AlertQueue } from '@/components/rail/AlertQueue'
import { BackendGate } from '@/components/rail/BackendGate'
import { MetricStrip } from '@/components/rail/MetricStrip'
import { ReplayBar } from '@/components/rail/ReplayBar'
import { TxnTape } from '@/components/rail/TxnTape'
import { PageHeader, Term } from '@/components/rail/kit'
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
      <PageHeader
        icon={ListChecks}
        eyebrow="Live monitoring"
        title="Alert queue"
        guideKey="console"
        right={
          <label className="flex h-8 items-center gap-2 rounded-md border bg-card px-2.5 text-[12.5px] text-muted-foreground shadow-card" title="Labels come from nolambur_labels.csv. Detectors never read them.">
            <input type="checkbox" checked={showLabels} onChange={e => setShowLabels(e.target.checked)} className="accent-[var(--brand-2)]" />
            Show dataset labels
          </label>
        }
        guide={[
          { title: 'Watch it arrive', body: <>Payments stream in at the bottom. Detectors check each one as the <Term k="replay">replay</Term> reaches it.</> },
          { title: 'Pick the top alert', body: 'The queue is sorted by severity, then score (rule points plus 10 × the GNN score). Red means several signals at once.' },
          { title: 'Read why, follow the money', body: <>Each alert says in plain words why it fired. The money trail and &ldquo;Follow the money&rdquo; show where it went next.</> },
          { title: 'Decide, with a reason', body: <>Clear, escalate or <Term k="freeze">freeze</Term>. Every action needs a note and lands in the <Term k="audit trail">audit trail</Term>.</> },
        ]}
      >
        Every alert here was raised by <code className="font-mono text-[12.5px]">Multi-GNN/rail_engine.py</code> on a real row of the dataset, scored by the trained{' '}
        <Term k="gnn">GNN</Term>.
      </PageHeader>
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
            <div className="grid min-h-[300px] place-items-center rounded-lg border bg-card p-6 text-center text-[13px] text-muted-foreground shadow-card">
              <div>
                <MousePointerClick className="mx-auto size-8 text-brand-2/60" />
                <p className="mt-2 font-medium text-foreground">No open alerts yet</p>
                <p className="mt-1">The fraud in this dataset happens between 10:30 and 10:35 on the first morning. Alerts appear the moment a detector fires.</p>
              </div>
            </div>
          )}
        </div>
        <TxnTape showLabels={showLabels} />
      </BackendGate>
    </div>
  )
}
