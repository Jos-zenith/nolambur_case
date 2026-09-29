'use client'

import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationNodeDatum } from 'd3-force'
import { select } from 'd3-selection'
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from 'd3-zoom'
import { ArrowRight, Maximize2, Network as NetworkIcon, Pause, Play } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'

import { clock, inrShort } from '@/lib/rail/format'
import { capturedLabel } from '@/lib/rail/snapshot'
import { useRail } from '@/lib/rail/store'
import type { Network, NetworkEdge, NetworkNode, Severity } from '@/lib/rail/types'
import { cn } from '@/lib/utils'

// Layout space: wide on desktop, near-square on a phone so the graph is not a thin strip.
const WIDE = { W: 960, H: 560 }
const NARROW = { W: 520, H: 600 }

function useNarrow() {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const q = window.matchMedia('(max-width: 639px)')
    setNarrow(q.matches)
    const on = () => setNarrow(q.matches)
    q.addEventListener('change', on)
    return () => q.removeEventListener('change', on)
  }, [])
  return narrow
}
const POLL_MS = 6000

type Node = NetworkNode & SimulationNodeDatum & { r: number; degree: number }
type Edge = Omit<NetworkEdge, 'source' | 'target'> & { source: Node; target: Node }

const SEV_FILL: Record<Severity, string> = {
  critical: 'var(--sev-critical)',
  high: 'var(--sev-high)',
  medium: 'var(--sev-medium)',
  low: 'var(--sev-low)',
}
const LEVEL_LABEL = ['No restriction', 'Settlement delayed', 'Outbound transfers held', 'Full hold', 'Frozen']
const DETECTOR_LABEL: Record<string, string> = {
  inflow_new_payers: 'Inflow burst from new payers',
  structuring: 'Structuring under the UPI cap',
  pass_through: 'Rapid pass-through',
  hop_from_flagged: 'Funds from a flagged account',
  model_only: 'GNN lead (no rule fired)',
}

const shortVpa = (v: string) => {
  const head = v.split('@')[0]
  return head.length > 16 ? `${head.slice(0, 15)}…` : head
}

/** /rail/graph/network while the bridge is live; the captured copy while it wakes. */
function useNetwork(paused: boolean) {
  const backend = useRail(s => s.backend)
  const saved = useRail(s => s.snapshot?.network ?? null)
  const [live, setLive] = useState<Network | null>(null)
  useEffect(() => {
    if (backend !== 'live' || paused) return
    let stop = false
    const load = () => {
      if (document.hidden) return
      fetch('/api/rail/graph/network?limit=40', { cache: 'no-store' })
        .then(r => (r.ok ? r.json() : null))
        .then(n => !stop && n && setLive(n))
        .catch(() => {})
    }
    load()
    const id = setInterval(load, POLL_MS)
    return () => {
      stop = true
      clearInterval(id)
    }
  }, [backend, paused])
  return { net: live ?? saved, live: !!live }
}

export function NetworkGraph() {
  const [frozenView, setFrozenView] = useState(false)
  const { net, live } = useNetwork(frozenView)
  const threshold = useRail(s => s.metrics?.modelThreshold ?? 0.9)
  const capturedAt = useRail(s => s.snapshot?.capturedAt ?? null)
  const { W, H } = useNarrow() ? NARROW : WIDE

  const svgRef = useRef<SVGSVGElement>(null)
  const simRef = useRef<Simulation<Node, undefined> | null>(null)
  const nodesRef = useRef<Map<string, Node>>(new Map())
  const layoutW = useRef(0) // the width the layout was last run for
  const [graph, setGraph] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] })
  const [, setFrame] = useState(0)
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity)
  const [hover, setHover] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const drag = useRef<{ id: string; moved: boolean } | null>(null)

  // Merge each fetch into the running layout: known accounts keep their place, new ones start next to a neighbour.
  useEffect(() => {
    if (!net) return
    const prev = nodesRef.current
    const next = new Map<string, Node>()
    const degree = new Map<string, number>()
    for (const e of net.edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
    }
    const neighbour = new Map<string, string>()
    for (const e of net.edges) {
      if (!neighbour.has(e.target)) neighbour.set(e.target, e.source)
      if (!neighbour.has(e.source)) neighbour.set(e.source, e.target)
    }
    for (const n of net.nodes) {
      const old = prev.get(n.id)
      const r = n.severity ? (n.severity === 'critical' ? 11 : n.severity === 'high' ? 9 : 7.5) : 4
      next.set(n.id, Object.assign(old ?? {}, n, { r, degree: degree.get(n.id) ?? 0 }) as Node)
    }
    for (const n of next.values()) {
      if (n.x !== undefined) continue
      const near = prev.get(neighbour.get(n.id) ?? '')
      n.x = (near?.x ?? W / 2) + (Math.random() - 0.5) * 40
      n.y = (near?.y ?? H / 2) + (Math.random() - 0.5) * 40
    }
    const edges: Edge[] = net.edges
      .filter(e => next.has(e.source) && next.has(e.target))
      .map(e => ({ ...e, source: next.get(e.source)!, target: next.get(e.target)! }))
    const changed = next.size !== prev.size || [...next.keys()].some(k => !prev.has(k))
    nodesRef.current = next
    const nodes = [...next.values()]
    setGraph({ nodes, edges })

    let sim = simRef.current
    if (!sim) {
      sim = forceSimulation<Node>()
        .force('charge', forceManyBody<Node>().strength(n => (n.severity ? -110 : -30)))
        .force('collide', forceCollide<Node>(n => n.r + 3))
      let raf = 0
      sim.on('tick', () => {
        if (!raf) raf = requestAnimationFrame(() => ((raf = 0), setFrame(f => f + 1)))
      })
      simRef.current = sim
    }
    sim.nodes(nodes)
    sim.force('x', forceX<Node>(W / 2).strength(W < H ? 0.14 : 0.1))
    sim.force('y', forceY<Node>(H / 2).strength(W < H ? 0.1 : 0.16))
    sim.force('link', forceLink<Node, Edge>(edges).id(n => n.id).distance(e => (e.source.severity && e.target.severity ? 46 : 34)).strength(0.5))
    const resized = layoutW.current !== 0 && layoutW.current !== W
    layoutW.current = W
    if (changed || resized) sim.alpha(prev.size && !resized ? 0.35 : 1).restart()
  }, [net, W, H])

  useEffect(() => () => void simRef.current?.stop(), [])

  // Pan and zoom on the background; nodes handle their own pointer events. The svg exists only once there is data.
  const hasSvg = !!net && graph.nodes.length > 0
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const z = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 4])
      .filter(e => !(e.target as Element).closest('[data-node]') && (!e.button || e.type === 'wheel'))
      .on('zoom', e => setTransform(e.transform))
    select(svg).call(z)
    zoomRef.current = z
    return () => void select(svg).on('.zoom', null)
  }, [hasSvg])
  const resetZoom = () => svgRef.current && zoomRef.current && select(svgRef.current).call(zoomRef.current.transform, zoomIdentity)

  const toGraph = (e: React.PointerEvent) => {
    const svg = svgRef.current!
    const rect = svg.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * W
    const y = ((e.clientY - rect.top) / rect.height) * H
    return transform.invert([x, y])
  }
  const onNodeDown = (e: React.PointerEvent, n: Node) => {
    e.stopPropagation()
    ;(e.target as Element).setPointerCapture(e.pointerId)
    drag.current = { id: n.id, moved: false }
    n.fx = n.x
    n.fy = n.y
  }
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const n = nodesRef.current.get(drag.current.id)
    if (!n) return
    const [x, y] = toGraph(e)
    if (!drag.current.moved && Math.hypot(x - (n.fx ?? 0), y - (n.fy ?? 0)) < 3) return
    drag.current.moved = true
    n.fx = x
    n.fy = y
    simRef.current?.alphaTarget(0.2).restart()
  }
  const onUp = () => {
    const d = drag.current
    if (!d) return
    const n = nodesRef.current.get(d.id)
    if (n) {
      n.fx = null
      n.fy = null
    }
    simRef.current?.alphaTarget(0)
    if (!d.moved) setSelected(s => (s === d.id ? null : d.id))
    drag.current = null
  }

  const focus = hover ?? selected
  const linked = useMemo(() => {
    if (!focus) return null
    const s = new Set([focus])
    for (const e of graph.edges) {
      if (e.source.id === focus) s.add(e.target.id)
      if (e.target.id === focus) s.add(e.source.id)
    }
    return s
  }, [focus, graph.edges])
  const maxAmt = Math.max(1, ...graph.edges.map(e => e.amount))
  const focusNode = focus ? nodesRef.current.get(focus) : undefined
  const counts = useMemo(() => {
    const alerted = graph.nodes.filter(n => n.severity)
    return {
      alerted: alerted.length,
      stopped: graph.nodes.filter(n => n.level >= 2).length,
      critical: alerted.filter(n => n.severity === 'critical').length,
      test: alerted.filter(n => n.test).length,
    }
  }, [graph.nodes])

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="relative overflow-hidden rounded-xl border bg-card shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2 text-[12px] text-muted-foreground">
          <span className="flex items-center gap-2">
            <span className={cn('size-2 rounded-full', live && !frozenView ? 'live-dot bg-ok text-ok' : 'bg-sev-medium')} />
            {live ? (frozenView ? 'Paused view' : `Live · refreshes every ${POLL_MS / 1000}s`) : capturedAt ? `Snapshot, ${capturedLabel(capturedAt)}` : 'Waiting for the bridge'}
            {net && <span className="font-mono">· {clock(net.simT)}</span>}
          </span>
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setFrozenView(v => !v)}
              disabled={!live && !frozenView}
              className="inline-flex h-7 items-center gap-1 rounded-md border bg-card px-2 text-[12px] text-foreground hover:bg-accent disabled:opacity-50"
            >
              {frozenView ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
              {frozenView ? 'Resume' : 'Pause'}
            </button>
            <button
              type="button"
              onClick={resetZoom}
              className="inline-flex h-7 items-center gap-1 rounded-md border bg-card px-2 text-[12px] text-foreground hover:bg-accent"
            >
              <Maximize2 className="size-3.5" /> Fit
            </button>
          </span>
        </div>
        {!net ? (
          <div className="grid aspect-[4/3] place-items-center p-6 text-center text-[13px] text-muted-foreground sm:aspect-[16/9]">
            <p>
              <NetworkIcon className="mx-auto mb-2 size-7 text-brand-2/60" />
              The network appears once the GNN bridge answers.
            </p>
          </div>
        ) : graph.nodes.length === 0 ? (
          <div className="grid aspect-[4/3] place-items-center p-6 text-center text-[13px] text-muted-foreground sm:aspect-[16/9]">
            No accounts under alert yet. Accounts appear here the moment a detector fires.
          </div>
        ) : (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="block w-full cursor-grab touch-none select-none active:cursor-grabbing"
            style={{ aspectRatio: `${W} / ${H}` }}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={`Money graph: ${counts.alerted} accounts under alert and the accounts they paid or were paid by.`}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
            onClick={e => e.target === e.currentTarget && setSelected(null)}
          >
            <defs>
              {(['hot', 'cold'] as const).map(k => (
                <marker key={k} id={`arrow-${k}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                  <path d="M0,0 L8,4 L0,8 z" fill={k === 'hot' ? 'var(--sev-high)' : 'var(--muted-foreground)'} />
                </marker>
              ))}
            </defs>
            <g transform={transform.toString()}>
              <g fill="none">
                {graph.edges.map(e => {
                  const hot = e.gnnMax >= threshold
                  const dim = linked && !(linked.has(e.source.id) && linked.has(e.target.id))
                  const dx = (e.target.x ?? 0) - (e.source.x ?? 0)
                  const dy = (e.target.y ?? 0) - (e.source.y ?? 0)
                  const len = Math.hypot(dx, dy) || 1
                  const pad = e.target.r + 3
                  return (
                    <line
                      key={`${e.source.id}>${e.target.id}`}
                      x1={e.source.x}
                      y1={e.source.y}
                      x2={(e.target.x ?? 0) - (dx / len) * pad}
                      y2={(e.target.y ?? 0) - (dy / len) * pad}
                      stroke={hot ? 'var(--sev-high)' : 'var(--muted-foreground)'}
                      strokeOpacity={dim ? 0.08 : hot ? 0.75 : 0.3}
                      strokeWidth={0.8 + 3.2 * Math.sqrt(e.amount / maxAmt)}
                      strokeDasharray={e.blocked ? '3 3' : undefined}
                      className={hot && !e.blocked && !dim ? 'flow' : undefined}
                      markerEnd={`url(#arrow-${hot ? 'hot' : 'cold'})`}
                    />
                  )
                })}
              </g>
              {graph.nodes.map(n => {
                const dim = linked && !linked.has(n.id)
                const isFocus = focus === n.id
                return (
                  <g
                    key={n.id}
                    data-node
                    transform={`translate(${n.x ?? 0},${n.y ?? 0})`}
                    opacity={dim ? 0.2 : 1}
                    className="cursor-pointer"
                    onPointerDown={e => onNodeDown(e, n)}
                    onPointerEnter={() => setHover(n.id)}
                    onPointerLeave={() => setHover(h => (h === n.id ? null : h))}
                  >
                    {n.level >= 2 && <circle r={n.r + 4.5} fill="none" stroke="var(--ok)" strokeWidth={2.5} />}
                    {n.level === 1 && <circle r={n.r + 4} fill="none" stroke="var(--sev-medium)" strokeWidth={1.5} strokeDasharray="2 2" />}
                    <circle
                      r={n.r}
                      fill={n.severity ? SEV_FILL[n.severity] : 'var(--card)'}
                      stroke={n.test ? 'var(--brand-2)' : n.severity ? 'var(--card)' : 'var(--muted-foreground)'}
                      strokeWidth={n.test ? 2 : 1.2}
                      strokeDasharray={n.test ? '2 2' : undefined}
                    />
                    {isFocus && <circle r={n.r + 8} fill="none" stroke="var(--brand-2)" strokeWidth={1.5} />}
                    {(isFocus || (n.severity === 'critical' && transform.k >= 1.4)) && (
                      <text y={-n.r - 6} textAnchor="middle" fontSize={11 / Math.max(1, transform.k * 0.8)} className="fill-foreground" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
                        {shortVpa(n.vpa)}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          </svg>
        )}
        <p className="border-t px-3 py-2 text-[11.5px] text-muted-foreground">Drag to pan, scroll or pinch to zoom, drag a node to move it, click one for details.</p>
      </div>

      <aside className="grid content-start gap-3">
        <div className="rounded-lg border bg-card p-3.5 shadow-card">
          {focusNode ? (
            <NodeDetail node={focusNode} edges={graph.edges} />
          ) : (
            <>
              <p className="text-[13px] font-semibold">What you are looking at</p>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
                The {net?.shown ?? 0} most severe accounts under alert{net && net.alertedAccounts > net.shown ? ` (of ${net.alertedAccounts})` : ''}, and the biggest flows in and out of each. Every
                dot is an account from the engine; every line is real money that moved.
              </p>
              <dl className="mt-3 grid grid-cols-3 gap-2 border-t pt-3 text-center">
                <Figure label="critical" value={counts.critical} tone="text-sev-critical" />
                <Figure label="alerted" value={counts.alerted} />
                <Figure label="held" value={counts.stopped} tone="text-ok" />
              </dl>
            </>
          )}
        </div>
        <div className="rounded-lg border bg-card p-3.5 text-[12px] shadow-card">
          <p className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Legend</p>
          <ul className="grid gap-1.5">
            <Legend swatch={<circle cx={9} cy={9} r={6} fill="var(--sev-critical)" />}>Critical alert (several signals)</Legend>
            <Legend swatch={<circle cx={9} cy={9} r={5} fill="var(--sev-high)" />}>High · medium in amber</Legend>
            <Legend swatch={<circle cx={9} cy={9} r={3.5} fill="var(--card)" stroke="var(--muted-foreground)" />}>Counterparty, no alert</Legend>
            <Legend swatch={<><circle cx={9} cy={9} r={4} fill="var(--sev-high)" /><circle cx={9} cy={9} r={7.5} fill="none" stroke="var(--ok)" strokeWidth={2} /></>}>Held or frozen: money stopped</Legend>
            <Legend swatch={<line x1={1} y1={9} x2={17} y2={9} stroke="var(--sev-high)" strokeWidth={2.5} />}>GNN score ≥ {threshold.toFixed(2)}</Legend>
            <Legend swatch={<line x1={1} y1={9} x2={17} y2={9} stroke="var(--muted-foreground)" strokeWidth={2} strokeDasharray="3 3" />}>Blocked transfer</Legend>
            <Legend swatch={<circle cx={9} cy={9} r={5} fill="var(--sev-high)" stroke="var(--brand-2)" strokeWidth={2} strokeDasharray="2 2" />}>Test scam you sent</Legend>
          </ul>
          <p className="mt-2 text-[11.5px] text-muted-foreground">Line width is the amount moved.</p>
        </div>
      </aside>
    </div>
  )
}

function NodeDetail({ node: n, edges }: { node: Node; edges: Edge[] }) {
  const ins = edges.filter(e => e.target.id === n.id)
  const outs = edges.filter(e => e.source.id === n.id)
  const sum = (xs: Edge[]) => xs.reduce((s, e) => s + e.amount, 0)
  return (
    <div>
      <p className="break-all font-mono text-[12.5px] font-medium">{n.vpa}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11.5px]">
        {n.severity ? (
          <span className="rounded-full px-2 py-0.5 font-medium capitalize text-white" style={{ background: SEV_FILL[n.severity] }}>
            {n.severity}
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">No alert</span>
        )}
        {n.level > 0 && <span className={cn('rounded-full px-2 py-0.5 font-medium', n.level >= 2 ? 'bg-ok-bg text-ok' : 'bg-sev-medium-bg text-sev-medium')}>{LEVEL_LABEL[n.level]}</span>}
        {n.test && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-brand-2">Test scam</span>}
      </div>
      <dl className="mt-3 grid gap-1.5 text-[12.5px]">
        {n.detector && <Row k="Detector" v={DETECTOR_LABEL[n.detector] ?? n.detector} />}
        {n.gnnMax !== null && <Row k="Highest GNN score" v={n.gnnMax.toFixed(3)} />}
        <Row k="Shown paid in" v={`${inrShort(sum(ins))} · ${ins.length} payer${ins.length === 1 ? '' : 's'}`} />
        <Row k="Shown paid out" v={`${inrShort(sum(outs))} · ${outs.length} payee${outs.length === 1 ? '' : 's'}`} />
      </dl>
      {n.alertId && (
        <Link href={`/console?alert=${encodeURIComponent(n.alertId)}`} className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md bg-brand-1 px-3 text-[12.5px] font-medium text-white hover:bg-brand-1/90">
          Open this alert <ArrowRight className="size-3.5" />
        </Link>
      )}
    </div>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right font-medium">{v}</dd>
    </div>
  )
}

function Figure({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <dd className={cn('figure text-[20px] font-semibold leading-none', tone)}>{value}</dd>
      <dt className="mt-1 text-[11.5px] text-muted-foreground">{label}</dt>
    </div>
  )
}

function Legend({ swatch, children }: { swatch: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <svg width={18} height={18} className="shrink-0" aria-hidden>
        {swatch}
      </svg>
      {children}
    </li>
  )
}
