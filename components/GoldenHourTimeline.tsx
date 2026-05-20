'use client'

import { CheckCircle, AlertCircle, Clock, Lock } from 'lucide-react'
import { DataFreshness } from '@/components/data-freshness'

export function GoldenHourTimeline() {
  const events = [
    { id: 1, label: 'First Transfer', time: '14:20', icon: 'transfer', status: 'completed' },
    { id: 2, label: 'T-GNN Detection', time: '14:20:34', icon: 'detect', status: 'completed' },
    { id: 3, label: 'Freeze Order', time: '14:20:36', icon: 'freeze', status: 'completed' },
    { id: 4, label: 'Bank Execution', time: '14:20:38', icon: 'bank', status: 'completed' },
    { id: 5, label: 'Recovered', time: '14:21', icon: 'recovered', status: 'completed' },
  ]

  const totalTime = 60 // minutes in golden hour
  const elapsed = 1 // minute

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border/60 bg-card/50 p-6 backdrop-blur-sm">
        <div className="mb-6 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">Golden Hour Timeline (60-90 min window)</h3>
          <div className="text-right">
            <p className="text-sm text-muted-foreground">Elapsed</p>
            <p className="text-2xl font-bold text-emerald-400">{elapsed}m of {totalTime}m</p>
          </div>
        </div>
        <DataFreshness className="mb-4 text-xs text-muted-foreground" />

        {/* Timeline bar */}
        <div className="space-y-4">
          {/* Progress bar */}
          <div className="relative h-2 w-full rounded-full bg-secondary/20">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400"
              style={{ width: `${(elapsed / totalTime) * 100}%` }}
            />
          </div>

          {/* Events */}
          <div className="flex items-center justify-between gap-2">
            {events.map((event, idx) => (
              <div key={event.id} className="flex flex-col items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-emerald-500 bg-emerald-500/10">
                  <CheckCircle className="h-4 w-4 text-emerald-500" />
                </div>
                <div className="text-center">
                  <p className="text-xs font-semibold text-foreground">{event.label}</p>
                  <p className="text-xs text-muted-foreground">{event.time}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Status badges */}
          <div className="mt-6 rounded-lg border border-border/40 bg-emerald-500/10 p-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-emerald-500" />
              <div>
                <p className="text-sm font-semibold text-emerald-400">Recovery Successful</p>
                <p className="text-xs text-muted-foreground">₹25.0L recovered in 53 seconds</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
