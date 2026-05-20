'use client'

import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useMuleStore } from '@/lib/mule-store'

export function PredictedHops() {
  const [queuedTargets, setQueuedTargets] = useState<Record<string, boolean>>({})
  const graphData = useMuleStore(state => state.graphData)
  const selectedNodeId = useMuleStore(state => state.selectedNodeId)
  const predictionsByNodeId = useMuleStore(state => state.predictionsByNodeId)

  const selectedNode = useMemo(
    () => graphData?.nodes.find(node => node.id === selectedNodeId) ?? null,
    [graphData, selectedNodeId],
  )

  const hops = selectedNodeId ? predictionsByNodeId[selectedNodeId] ?? [] : []

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="space-y-2 border-b border-border/60 pb-4">
        <CardTitle className="text-xl">Predicted Next-Hop Accounts</CardTitle>
        <p className="text-sm text-muted-foreground">
          {selectedNode ? `T-GNN top targets for ${selectedNode.label}` : 'Click a cluster node to inspect pre-freeze targets.'}
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[18rem]">
          <div className="space-y-3 p-4">
            {hops.length > 0 ? (
              hops.slice(0, 5).map(hop => {
                const queued = queuedTargets[hop.id] === true

                return (
                  <div key={hop.id} className="rounded-2xl border border-border/60 bg-secondary/15 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-foreground">{hop.label}</p>
                        <p className="text-xs text-muted-foreground">{hop.id}</p>
                      </div>
                      <Badge className="bg-emerald-500/20 text-emerald-200">{(hop.prob * 100).toFixed(1)}%</Badge>
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        {hop.amount ? <span className="rounded-full border border-border/60 px-2 py-1">₹{(hop.amount / 100000).toFixed(1)}L</span> : null}
                        {hop.geoMismatch ? <span className="rounded-full border border-destructive/40 px-2 py-1 text-destructive-foreground">geo mismatch</span> : null}
                      </div>
                      <Button
                        size="sm"
                        variant={queued ? 'secondary' : 'default'}
                        onClick={() => setQueuedTargets(current => ({ ...current, [hop.id]: true }))}
                      >
                        {queued ? 'Queued' : 'Pre-freeze ↗'}
                      </Button>
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="rounded-2xl border border-dashed border-border/60 p-6 text-sm text-muted-foreground">
                No predictions yet. Select a mule cluster to compute next-hop accounts.
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}