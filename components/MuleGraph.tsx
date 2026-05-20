'use client'

import { useEffect, useMemo, useState } from 'react'
import dynamic from 'next/dynamic'

import { DataFreshness } from '@/components/data-freshness'
import { Skeleton } from '@/components/ui/skeleton'
import { useMuleStore } from '@/lib/mule-store'
import type { MuleGraphPayload, MuleGraphNode } from '@/lib/mule-data'

const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false }) as unknown as typeof import('react-force-graph-2d').default

type PredictionHop = {
  id: string
  label: string
  prob: number
  amount?: number
  geoMismatch?: boolean
}

function scoreToColor(score: number) {
  if (score >= 0.95) return '#ef4444'
  if (score >= 0.85) return '#f97316'
  if (score >= 0.65) return '#facc15'
  return '#60a5fa'
}

function scoreToRadius(score: number) {
  return 4 + Math.max(0, Math.min(12, score * 12))
}

function typeLabel(type: MuleGraphNode['type']) {
  switch (type) {
    case 'victim':
      return 'Victim'
    case 'layer1':
      return 'Layer 1'
    case 'layer2':
      return 'Layer 2'
    case 'beneficiary':
      return 'Beneficiary'
  }
}

export function MuleGraph() {
  const graphData = useMuleStore(state => state.graphData)
  const selectedNodeId = useMuleStore(state => state.selectedNodeId)
  const setGraphData = useMuleStore(state => state.setGraphData)
  const setSelectedNodeId = useMuleStore(state => state.setSelectedNodeId)
  const setPredictionsByNodeId = useMuleStore(state => state.setPredictionsByNodeId)
  const setGraphStatus = useMuleStore(state => state.setGraphStatus)
  const setGraphError = useMuleStore(state => state.setGraphError)

  const [isFetching, setIsFetching] = useState(true)

  useEffect(() => {
    let cancelled = false

    const loadGraph = async () => {
      setGraphStatus('loading')
      try {
        const response = await fetch('/api/graph/live', { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Graph request failed (${response.status})`)
        }

        const payload = (await response.json()) as MuleGraphPayload
        if (cancelled) return

        setGraphData(payload)
        setGraphError(null)
        setIsFetching(false)

        if (payload.nodes.length > 0 && !selectedNodeId) {
          const nextSelected = [...payload.nodes].sort((left, right) => right.mule_score - left.mule_score)[0]
          setSelectedNodeId(nextSelected.id)
        }

        const inferencePayload = {
          model: 'gin',
          node_features: payload.nodes.map(() => [1]),
          edges: payload.links.map(link => ({
            source: payload.nodes.findIndex(node => node.id === link.source),
            target: payload.nodes.findIndex(node => node.id === link.target),
            features: [link.amount / 1_000_000, link.velocity],
          })),
        }

        const inferenceResponse = await fetch('/api/inference', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(inferencePayload),
        })

        const inferenceJson = await inferenceResponse.json().catch(() => null)

        if (!inferenceResponse.ok || !inferenceJson?.predictions) {
          throw new Error('Inference bridge returned no predictions')
        }

        const predictionMap: Record<string, PredictionHop[]> = {}

        for (const prediction of inferenceJson.predictions as Array<{ source: number; target: number; fraud_probability: number }>) {
          const sourceNode = payload.nodes[prediction.source]
          const targetNode = payload.nodes[prediction.target]

          if (!sourceNode || !targetNode) continue

          predictionMap[sourceNode.id] ??= []
          predictionMap[sourceNode.id].push({
            id: targetNode.id,
            label: targetNode.label,
            prob: prediction.fraud_probability,
            amount: targetNode.amount,
            geoMismatch: targetNode.geo_mismatch,
          })
        }

        Object.values(predictionMap).forEach(entries => entries.sort((left, right) => right.prob - left.prob))
        setPredictionsByNodeId(predictionMap)
      } catch (error) {
        if (cancelled) return

        setGraphStatus('error')
        setGraphError(error instanceof Error ? error.message : 'Unable to load graph data')
        setIsFetching(false)
      }
    }

    void loadGraph()

    return () => {
      cancelled = true
    }
  }, [selectedNodeId, setGraphData, setGraphError, setGraphStatus, setPredictionsByNodeId, setSelectedNodeId])

  const nodes = graphData?.nodes ?? []
  const links = graphData?.links ?? []

  const selectedNode = useMemo(() => nodes.find(node => node.id === selectedNodeId) ?? null, [nodes, selectedNodeId])

  return (
    <div className="relative h-[34rem] overflow-hidden rounded-3xl border border-border/60 bg-[radial-gradient(circle_at_top,_rgba(239,68,68,0.14),_transparent_35%),linear-gradient(180deg,rgba(13,13,13,0.94),rgba(5,5,5,0.98))] p-4">
      <div className="pointer-events-none absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] [background-size:56px_56px]" />
      <div className="relative z-10 mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Mule Cluster Graph View</p>
          <h3 className="mt-1 text-xl font-semibold text-foreground">Live Neo4j topology</h3>
          <DataFreshness className="mt-2 text-xs text-muted-foreground" />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-full bg-emerald-500/20 px-2 py-1 text-emerald-200">{graphData?.source ?? 'loading'}</span>
          <span>{nodes.length} nodes</span>
          <span>{links.length} edges</span>
        </div>
      </div>

      {graphData ? (
        <ForceGraph2D
          graphData={graphData}
          nodeLabel={(node: MuleGraphNode) => `${node.label} · ${typeLabel(node.type)} · ${(node.mule_score * 100).toFixed(0)}%`}
          nodeColor={(node: MuleGraphNode) => scoreToColor(node.mule_score)}
          nodeRelSize={8}
          nodeVal={(node: MuleGraphNode) => scoreToRadius(node.mule_score)}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkColor={() => 'rgba(248,113,113,0.6)'}
          linkWidth={(link: { amount: number }) => Math.max(1, Math.min(6, Math.sqrt(link.amount / 100000)))}
          onNodeClick={(node: MuleGraphNode) => setSelectedNodeId(node.id)}
          onBackgroundClick={() => setSelectedNodeId(null)}
          width={undefined}
          height={undefined}
          enableNodeDrag
          cooldownTicks={120}
          d3AlphaDecay={0.02}
          backgroundColor="rgba(0,0,0,0)"
        />
      ) : (
        <div className="relative z-10 flex h-[26rem] items-center justify-center rounded-2xl border border-border/60 bg-black/20 text-sm text-muted-foreground">
          {isFetching ? (
            <div className="w-full space-y-4 px-6">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-48 w-full" />
              <Skeleton className="h-4 w-64" />
            </div>
          ) : (
            'Graph unavailable'
          )}
        </div>
      )}

      {selectedNode ? (
        <div className="absolute bottom-4 left-4 z-10 max-w-sm rounded-2xl border border-border/60 bg-black/70 p-4 backdrop-blur">
          <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Selected Node</p>
          <p className="mt-1 text-lg font-semibold text-foreground">{selectedNode.label}</p>
          <p className="mt-1 text-sm text-muted-foreground">{typeLabel(selectedNode.type)} · score {(selectedNode.mule_score * 100).toFixed(1)}%</p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            <div className="rounded-xl border border-border/60 bg-secondary/15 p-2">Location: {selectedNode.location ?? 'n/a'}</div>
            <div className="rounded-xl border border-border/60 bg-secondary/15 p-2">Geo mismatch: {selectedNode.geo_mismatch ? 'yes' : 'no'}</div>
          </div>
        </div>
      ) : null}
    </div>
  )
}