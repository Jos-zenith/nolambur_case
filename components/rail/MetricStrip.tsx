'use client'

import { duration, inrShort, pct } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'

export function MetricStrip() {
  const m = useRail(s => s.metrics)
  const ticks = useRail(s => s.tickCounts)
  if (!m) return null

  const cells: { label: string; value: string; note: string; extra?: React.ReactNode }[] = [
    { label: 'Transactions, last replay minute', value: String(m.txnsLastMinute), note: `${inrShort(m.volumeReplayed)} replayed so far`, extra: <Spark data={ticks} /> },
    {
      label: 'Open alerts',
      value: String(m.openAlerts),
      note: `${m.openBySeverity.critical} critical · ${m.openBySeverity.high} high · ${m.openBySeverity.medium} medium`,
    },
    { label: 'Median lead time', value: duration(m.medianLeadSec), note: 'alert raised → mule forwards the money' },
    { label: 'Precision vs labels', value: pct(m.precision), note: 'rule alerts on accounts labelled mule' },
    { label: 'Mule recall so far', value: pct(m.muleRecall), note: `${m.mulesAlerted} of ${m.mulesSeen} mules seen in the replay` },
    { label: 'Fraud money blocked', value: inrShort(m.blockedFraudAmount), note: `${m.frozenAccounts} frozen · ${inrShort(m.blockedGenuineAmount)} genuine blocked` },
  ]

  return (
    <section className="grid grid-cols-2 border bg-card md:grid-cols-3 xl:grid-cols-6">
      {cells.map(c => (
        <div key={c.label} className="min-h-[84px] border-b border-r p-3 xl:border-b-0 xl:last:border-r-0">
          <p className="text-[12px] text-muted-foreground">{c.label}</p>
          <div className="mt-1 flex items-end justify-between gap-2">
            <p className="text-[22px] font-medium leading-none tabular-nums">{c.value}</p>
            {c.extra}
          </div>
          <p className="mt-1.5 truncate text-[11.5px] text-muted-foreground" title={c.note}>
            {c.note}
          </p>
        </div>
      ))}
    </section>
  )
}

function Spark({ data }: { data: number[] }) {
  if (data.length < 2) return null
  const max = Math.max(...data, 1)
  const w = 72
  const h = 22
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h}`).join(' ')
  return (
    <svg width={w} height={h} className="text-chart-2" aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.25" />
    </svg>
  )
}
