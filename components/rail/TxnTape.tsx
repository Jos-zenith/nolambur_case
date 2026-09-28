'use client'

import { useMemo, useState } from 'react'

import { clock, inr, rowLabel } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import type { Row } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { Score } from './bits'

export function TxnTape({ showLabels }: { showLabels: boolean }) {
  const rows = useRail(s => s.rows)
  const alerts = useRail(s => s.alerts)
  const [held, setHeld] = useState<Row[] | null>(null)

  const flagged = useMemo(() => {
    const set = new Set<string>()
    for (const a of Object.values(alerts)) if (a.status !== 'cleared' && a.status !== 'superseded') set.add(a.accountId)
    return set
  }, [alerts])

  const view = (held ?? rows).slice(0, 25)

  return (
    <section className="border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-[13px] font-semibold">
          Transactions as they arrive <span className="font-normal text-muted-foreground">· rows of nolambur_transactions.csv, with the checkpoint&apos;s score</span>
        </h2>
        <button onClick={() => setHeld(held ? null : rows)} className="h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent">
          {held ? 'Follow live' : 'Hold view'}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="border-b text-left text-[12px] text-muted-foreground">
              <th className="px-3 py-1.5 font-normal">Time</th>
              <th className="px-3 py-1.5 font-normal" title="CSV row number, or the ingest source for a live payment">Row</th>
              <th className="px-3 py-1.5 font-normal">From</th>
              <th className="px-3 py-1.5 font-normal">To</th>
              <th className="px-3 py-1.5 font-normal">States</th>
              <th className="px-3 py-1.5 text-right font-normal">Amount</th>
              <th className="px-3 py-1.5 font-normal">GNN</th>
              {showLabels && <th className="px-3 py-1.5 font-normal">Label</th>}
            </tr>
          </thead>
          <tbody>
            {view.map(r => {
              const hot = flagged.has(r.toId) || flagged.has(r.fromId)
              return (
                <tr key={`${r.row}-${r.t}`} className={cn('border-b last:border-0', r.blocked ? 'bg-sev-critical-bg/60 text-muted-foreground line-through decoration-sev-critical/50' : hot && 'bg-sev-high-bg/50')}>
                  <td className="px-3 py-1 font-mono text-muted-foreground">{clock(r.t)}</td>
                  <td className="px-3 py-1 font-mono text-muted-foreground">{r.source === 'replay' ? `#${r.row}` : <span className="rounded-sm bg-accent px-1 text-foreground">{r.source}</span>}</td>
                  <td className="max-w-[170px] truncate px-3 py-1 font-mono">{r.fromVpa}</td>
                  <td className="max-w-[170px] truncate px-3 py-1 font-mono">
                    {r.toVpa}
                    {r.blocked && <span className="ml-1.5 font-sans text-[11px] text-sev-critical no-underline">blocked</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1 text-muted-foreground">{r.fromState === r.toState ? r.fromState : `${r.fromState} → ${r.toState}`}</td>
                  <td className="px-3 py-1 text-right font-mono">{inr(r.amount)}</td>
                  <td className="px-3 py-1">
                    <Score value={r.gnn} />
                  </td>
                  {showLabels && <td className="px-3 py-1 font-mono text-[11.5px] text-muted-foreground">{rowLabel(r)}</td>}
                </tr>
              )
            })}
          </tbody>
        </table>
        {view.length === 0 && <p className="p-4 text-[13px] text-muted-foreground">Waiting for the first row…</p>}
      </div>
    </section>
  )
}
