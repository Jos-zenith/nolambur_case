'use client'

import { DataFreshness } from '@/components/data-freshness'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { useMulePulse } from '@/hooks/useMulePulse'

function scoreBadgeClass(score: number) {
  if (score >= 0.95) return 'bg-destructive/20 text-destructive-foreground'
  if (score >= 0.85) return 'bg-orange-500/20 text-orange-200'
  if (score >= 0.65) return 'bg-yellow-500/20 text-yellow-100'
  return 'bg-blue-500/20 text-blue-100'
}

export function MulePulseFeed() {
  const { alerts, connected } = useMulePulse()

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="space-y-2 border-b border-border/60 pb-4">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-xl">Mule Pulse Live Feed</CardTitle>
          <Badge variant={connected ? 'secondary' : 'destructive'} className={connected ? 'bg-emerald-500/20 text-emerald-200' : ''}>
            {connected ? 'streaming' : 'fallback feed'}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">Flagged accounts with risk, velocity, and geographic mismatch signals.</p>
        <DataFreshness className="text-xs text-muted-foreground" />
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[18rem]">
          <div className="space-y-3 p-4">
            {alerts.length === 0 ? (
              Array.from({ length: 4 }).map((_, index) => (
                <div key={`skeleton-${index}`} className="space-y-2 rounded-2xl border border-border/60 bg-secondary/15 p-3">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-56" />
                  <Skeleton className="h-6 w-full" />
                </div>
              ))
            ) : (
              alerts.map(alert => (
                <article key={alert.id} className="rounded-2xl border border-border/60 bg-secondary/15 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-foreground">{alert.accountId}</p>
                      <p className="text-xs text-muted-foreground">{alert.label}</p>
                    </div>
                    <Badge className={scoreBadgeClass(alert.muleScore)}>{(alert.muleScore * 100).toFixed(1)}%</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full border border-border/60 px-2 py-1">In {alert.inVelocity.toFixed(2)}</span>
                    <span className="rounded-full border border-border/60 px-2 py-1">Out {alert.outVelocity.toFixed(2)}</span>
                    <span className="rounded-full border border-border/60 px-2 py-1">{alert.statePair}</span>
                    <span className={['rounded-full border px-2 py-1', alert.geoMismatch ? 'border-destructive/40 text-destructive-foreground' : 'border-border/60'].join(' ')}>
                      {alert.geoMismatch ? 'geo mismatch' : 'geo aligned'}
                    </span>
                  </div>
                </article>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}