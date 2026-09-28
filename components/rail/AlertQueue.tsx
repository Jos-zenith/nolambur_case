'use client'

import { useMemo, useState } from 'react'

import { ago } from '@/lib/rail/format'
import { sortAlerts, useRail } from '@/lib/rail/store'
import type { AlertStatus } from '@/lib/rail/types'
import { Lock } from 'lucide-react'

import { cn } from '@/lib/utils'
import { SeverityBadge, StatusText, TruthTag } from './bits'

// A coloured left edge on each row, so severity reads down the list at a glance (the badge carries the label).
const SEV_EDGE = {
  critical: 'shadow-[inset_3px_0_0_var(--sev-critical)]',
  high: 'shadow-[inset_3px_0_0_var(--sev-high)]',
  medium: 'shadow-[inset_3px_0_0_var(--sev-medium)]',
  low: 'shadow-[inset_3px_0_0_var(--sev-low)]',
} as const

const FILTERS: { id: string; label: string; match: (s: AlertStatus) => boolean }[] = [
  { id: 'open', label: 'Open', match: s => s === 'open' || s === 'held' },
  { id: 'actioned', label: 'Actioned', match: s => s === 'escalated' || s === 'frozen' },
  { id: 'cleared', label: 'Cleared', match: s => s === 'cleared' },
  { id: 'all', label: 'All', match: () => true },
]

export function AlertQueue({ selectedId, onSelect, showLabels }: { selectedId: string | null; onSelect: (id: string) => void; showLabels: boolean }) {
  const alerts = useRail(s => s.alerts)
  const fresh = useRail(s => s.fresh)
  const now = useRail(s => s.metrics?.simT ?? 0)
  const [filter, setFilter] = useState('open')

  const counts = useMemo(() => {
    const all = Object.values(alerts)
    return Object.fromEntries(FILTERS.map(f => [f.id, all.filter(a => f.match(a.status)).length]))
  }, [alerts])

  const rows = useMemo(() => {
    const f = FILTERS.find(x => x.id === filter)!
    return sortAlerts(Object.values(alerts).filter(a => f.match(a.status))).slice(0, 300)
  }, [alerts, filter])

  return (
    <section className="flex h-full max-h-[60vh] min-h-0 flex-col overflow-hidden rounded-lg border bg-card shadow-card lg:max-h-none">
      <div className="flex items-center justify-between border-b bg-muted/40 px-3 py-2.5">
        <h2 className="text-[13px] font-semibold">Alerts</h2>
        <span className="text-[11.5px] text-muted-foreground">severity, then score (rule + 10 × GNN)</span>
      </div>
      <div className="flex gap-1 border-b p-1.5 text-[12.5px]">
        {FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={cn('flex items-center gap-1.5 rounded-md px-2.5 py-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground', filter === f.id && 'bg-brand-1 text-white hover:bg-brand-1 hover:text-white')}
          >
            {f.label}
            <span className={cn('rounded-full px-1.5 text-[11px] tabular-nums', filter === f.id ? 'bg-white/20' : 'bg-muted')}>{counts[f.id] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && (
          <p className="p-4 text-[13px] text-muted-foreground">
            {filter === 'open' ? 'No open alerts. The fraud window starts at the first row; restart the replay to see it again.' : 'Nothing in this view.'}
          </p>
        )}
        <ul>
          {rows.map(a => (
            <li key={a.id}>
              <button
                onClick={() => onSelect(a.id)}
                className={cn(
                  'grid w-full grid-cols-[64px_1fr_auto] items-start gap-2 border-b px-3 py-2.5 text-left transition-colors hover:bg-accent/70',
                  SEV_EDGE[a.severity],
                  selectedId === a.id && 'bg-brand-soft/70 hover:bg-brand-soft/70',
                  fresh[a.id] && (a.severity === 'critical' ? 'glow-critical' : 'row-in'),
                )}
              >
                <SeverityBadge severity={a.severity} className="mt-0.5 w-fit" />
                <span className="min-w-0">
                  <span className="block truncate font-mono text-[12.5px]">{a.vpa}</span>
                  <span className="block truncate text-[12px] text-muted-foreground">
                    {a.detectorLabel} · {a.id} · {ago(now, a.createdT)}
                  </span>
                  {showLabels && <TruthTag role={a.truth.role} className="mt-1" />}
                </span>
                <span className="text-right">
                  <span className="block font-mono text-[13px] tabular-nums">{a.score}</span>
                  <span className="inline-flex items-center gap-1">
                    {a.status === 'held' && <Lock className="size-3 text-sev-critical" />}
                    <StatusText status={a.status} />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
