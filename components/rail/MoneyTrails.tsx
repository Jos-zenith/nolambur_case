'use client'

import { ArrowRight, Network as NetworkIcon, Pause, Play } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { clock, inrShort } from '@/lib/rail/format'
import { capturedLabel } from '@/lib/rail/snapshot'
import { useRail } from '@/lib/rail/store'
import type { Network, NetworkEdge, NetworkNode, Severity } from '@/lib/rail/types'
import { cn } from '@/lib/utils'

/**
 * The money around each alert, as rows read left to right: who paid in, the accounts under alert
 * (in the order money reached them), and where it went. One row per case: accounts under alert
 * that paid each other. Same data as /rail/graph/network; positions carry meaning, nothing moves.
 */

const POLL_MS = 12000
const FIRST_ROWS = 5 // cases shown before "Show all"
const SIDE_MAX = 4 // payers or payees drawn per case; the rest fold into "+N more"
const MAX_LAYERS = 3 // first account under alert, the next, and one further

const SEV_FILL: Record<Severity, string> = {
  critical: 'var(--sev-critical)',
  high: 'var(--sev-high)',
  medium: 'var(--sev-medium)',
  low: 'var(--sev-low)',
}
const SEV_RANK: Record<Severity, number> = { critical: 3, high: 2, medium: 1, low: 0 }
const LEVEL_LABEL = ['No restriction', 'Settlement delayed', 'Outbound transfers held', 'Full hold', 'Frozen']
const DETECTOR_SHORT: Record<string, string> = {
  inflow_new_payers: 'burst from new payers',
  structuring: 'split under the cap',
  pass_through: 'forwards money fast',
  hop_from_flagged: 'paid by a flagged account',
  fan_in_new_payers: 'many new payers',
  model_only: 'model lead only',
}
const DETECTOR_LABEL: Record<string, string> = {
  inflow_new_payers: 'Inflow burst from new payers',
  structuring: 'Structuring under the UPI cap',
  pass_through: 'Rapid pass-through',
  hop_from_flagged: 'Funds from a flagged account',
  fan_in_new_payers: 'Many new payers in a day',
  model_only: 'GNN lead (no rule fired)',
}

const short = (v: string, n = 14) => {
  const head = v.split('@')[0]
  return head.length > n ? `${head.slice(0, n - 1)}…` : head
}

// ---------------------------------------------------------------------------- data

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

type Side = 'in' | 'out'
type Slot = { key: string; node: NetworkNode | null; more?: { count: number; amount: number }; col: number; y: number }
type Link = { key: string; from: Slot; to: Slot; amount: number; count: number; hot: boolean; blocked: boolean; label?: boolean; minor?: boolean }
type Case = {
  key: string
  severity: Severity
  alerted: NetworkNode[]
  slots: Slot[]
  links: Link[]
  height: number
  totalIn: number
  totalOut: number
  held: number
  layers: number
}

const ROW_H = 54
const PAD = 26

/** Cases from the network: connected accounts under alert, their layers, and their biggest outside payers and payees. */
function buildCases(net: Network, threshold: number): Case[] {
  const byId = new Map(net.nodes.map(n => [n.id, n]))
  const alerted = net.nodes.filter(n => n.severity)
  const isAlert = (id: string) => !!byId.get(id)?.severity
  // components over alert-to-alert payments
  const parent = new Map(alerted.map(n => [n.id, n.id]))
  const find = (x: string): string => (parent.get(x) === x ? x : (parent.set(x, find(parent.get(x)!)), parent.get(x)!))
  for (const e of net.edges) if (isAlert(e.source) && isAlert(e.target)) parent.set(find(e.source), find(e.target))
  const groups = new Map<string, NetworkNode[]>()
  for (const n of alerted) groups.set(find(n.id), [...(groups.get(find(n.id)) ?? []), n])

  const cases: Case[] = []
  for (const [root, members] of groups) {
    const ids = new Set(members.map(m => m.id))
    const inner = net.edges.filter(e => ids.has(e.source) && ids.has(e.target) && e.source !== e.target)
    // layer = how many accounts under alert the money passed through first (longest path, capped: cycles stop)
    const layer = new Map(members.map(m => [m.id, 0]))
    for (let i = 0; i < members.length; i++)
      for (const e of inner) {
        const next = Math.min(MAX_LAYERS - 1, layer.get(e.source)! + 1)
        if (layer.get(e.target)! < next) layer.set(e.target, next)
      }
    const layers = Math.max(...layer.values()) + 1
    const outside = (side: Side) => {
      const edges = net.edges.filter(e => (side === 'in' ? ids.has(e.target) && !ids.has(e.source) : ids.has(e.source) && !ids.has(e.target)))
      const party = (e: NetworkEdge) => (side === 'in' ? e.source : e.target)
      const totals = new Map<string, number>()
      for (const e of edges) totals.set(party(e), (totals.get(party(e)) ?? 0) + e.amount)
      const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      return { edges, party, shown: new Set(ranked.slice(0, SIDE_MAX).map(r => r[0])), rest: ranked.slice(SIDE_MAX) }
    }
    const ins = outside('in')
    const outs = outside('out')

    // columns: 0 = paid in by, 1..layers = under alert, layers+1 = paid out to
    const slots: Slot[] = []
    const slotOf = new Map<string, Slot>()
    const columns: Slot[][] = Array.from({ length: layers + 2 }, () => [])
    const add = (s: Slot) => (slots.push(s), columns[s.col].push(s), slotOf.set(s.key, s), s)
    const amountOf = (id: string) => net.edges.filter(e => e.source === id || e.target === id).reduce((t, e) => t + e.amount, 0)
    // accounts under alert: the SIDE_MAX biggest per column are drawn, the rest fold into "+N more under alert"
    const folded = new Map<string, string>() // member id -> its column's "more" slot key
    for (let l = 0; l < layers; l++) {
      const inLayer = members.filter(m => layer.get(m.id) === l).sort((a, b) => amountOf(b.id) - amountOf(a.id) || a.id.localeCompare(b.id))
      for (const m of inLayer.slice(0, SIDE_MAX)) add({ key: m.id, node: m, col: 1 + l, y: 0 })
      const rest = inLayer.slice(SIDE_MAX)
      if (rest.length) {
        add({ key: `L${l}:more`, node: null, more: { count: rest.length, amount: rest.reduce((t, m) => t + amountOf(m.id), 0) }, col: 1 + l, y: 0 })
        for (const m of rest) folded.set(m.id, `L${l}:more`)
      }
    }
    const keyOf = (id: string) => folded.get(id) ?? id
    for (const id of [...ins.shown].sort((a, b) => amountOf(b) - amountOf(a))) add({ key: `in:${id}`, node: byId.get(id) ?? null, col: 0, y: 0 })
    for (const id of [...outs.shown].sort((a, b) => amountOf(b) - amountOf(a))) add({ key: `out:${id}`, node: byId.get(id) ?? null, col: layers + 1, y: 0 })
    if (ins.rest.length) add({ key: 'in:more', node: null, more: { count: ins.rest.length, amount: ins.rest.reduce((t, r) => t + r[1], 0) }, col: 0, y: 0 })
    if (outs.rest.length) add({ key: 'out:more', node: null, more: { count: outs.rest.length, amount: outs.rest.reduce((t, r) => t + r[1], 0) }, col: layers + 1, y: 0 })
    const tallest = Math.max(...columns.map(c => c.length))
    const height = PAD * 2 + tallest * ROW_H
    for (const col of columns) col.forEach((s, i) => (s.y = height / 2 + (i - (col.length - 1) / 2) * ROW_H))

    // links, folding the "+N more" parties into one line per account under alert
    const merged = new Map<string, Link>()
    const link = (fromId: string, toId: string, e: NetworkEdge) => {
      const fromKey = keyOf(fromId)
      const toKey = keyOf(toId)
      const from = slotOf.get(fromKey)
      const to = slotOf.get(toKey)
      if (!from || !to || from === to) return
      const k = `${fromKey}>${toKey}`
      const cur = merged.get(k)
      if (cur) Object.assign(cur, { amount: cur.amount + e.amount, count: cur.count + e.count, hot: cur.hot || e.gnnMax >= threshold, blocked: cur.blocked || e.blocked })
      else merged.set(k, { key: k, from, to, amount: e.amount, count: e.count, hot: e.gnnMax >= threshold, blocked: e.blocked })
    }
    for (const e of inner) link(e.source, e.target, e)
    for (const e of ins.edges) link(ins.shown.has(e.source) ? `in:${e.source}` : 'in:more', e.target, e)
    for (const e of outs.edges) link(e.source, outs.shown.has(e.target) ? `out:${e.target}` : 'out:more', e)

    // label only the case's main flows, so the figures stay readable
    const ranked = [...merged.values()].sort((a, b) => b.amount - a.amount)
    const top = ranked[0]?.amount ?? 1
    for (const [i, l] of ranked.entries()) Object.assign(l, { label: i < 6 && l.amount >= top * 0.2, minor: i >= 10 })

    cases.push({
      key: root,
      severity: members.reduce<Severity>((s, m) => (SEV_RANK[m.severity!] > SEV_RANK[s] ? m.severity! : s), 'low'),
      alerted: members,
      slots,
      links: [...merged.values()],
      height,
      totalIn: ins.edges.reduce((t, e) => t + e.amount, 0),
      totalOut: outs.edges.reduce((t, e) => t + e.amount, 0),
      held: members.filter(m => m.level >= 2).length,
      layers,
    })
  }
  return cases.sort((a, b) => SEV_RANK[b.severity] - SEV_RANK[a.severity] || b.alerted.length - a.alerted.length || b.totalIn - a.totalIn)
}

// ---------------------------------------------------------------------------- view

const W = 980
const colX = (col: number, layers: number) => {
  const left = 150
  const right = W - 150
  return left + ((right - left) * col) / (layers + 1)
}

export function MoneyTrails() {
  const [paused, setPaused] = useState(false)
  const { net, live } = useNetwork(paused)
  const threshold = useRail(s => s.metrics?.modelThreshold ?? 0.9)
  const capturedAt = useRail(s => s.snapshot?.capturedAt ?? null)
  const cases = useMemo(() => (net ? buildCases(net, threshold) : []), [net, threshold])
  const [showAll, setShowAll] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const shown = showAll ? cases : cases.slice(0, FIRST_ROWS)
  const layers = Math.max(1, ...shown.map(c => c.layers))
  const maxAmt = Math.max(1, ...shown.flatMap(c => c.links.map(l => l.amount)))
  const focusNode = focus ? (net?.nodes.find(n => n.id === focus) ?? null) : null

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="overflow-hidden rounded-xl border bg-card shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2 text-[12px] text-muted-foreground">
          <span className="flex items-center gap-2">
            <span className={cn('size-2 rounded-full', live && !paused ? 'live-dot bg-ok text-ok' : 'bg-sev-medium')} />
            {live ? (paused ? 'Paused' : `Live · updates every ${POLL_MS / 1000}s`) : capturedAt ? `Snapshot, ${capturedLabel(capturedAt)}` : 'Waiting for the bridge'}
            {net && <span className="font-mono">· {clock(net.simT)}</span>}
          </span>
          <button
            type="button"
            onClick={() => setPaused(p => !p)}
            disabled={!live && !paused}
            className="inline-flex h-7 items-center gap-1 rounded-md border bg-card px-2 text-[12px] text-foreground hover:bg-accent disabled:opacity-50"
          >
            {paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
            {paused ? 'Resume' : 'Pause'}
          </button>
        </div>

        {!net ? (
          <Empty>
            <NetworkIcon className="mx-auto mb-2 size-7 text-brand-2/60" />
            The money trails appear once the GNN bridge answers.
          </Empty>
        ) : cases.length === 0 ? (
          <Empty>No accounts under alert yet. A case appears here the moment a detector fires.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[760px]">
              <ColumnHeads layers={layers} />
              {shown.map((c, i) => (
                <CaseRow key={c.key} c={c} index={i} layers={layers} maxAmt={maxAmt} focus={focus} hover={hover} onFocus={setFocus} onHover={setHover} />
              ))}
            </div>
          </div>
        )}
        {cases.length > FIRST_ROWS && (
          <button type="button" onClick={() => setShowAll(s => !s)} className="w-full border-t px-3 py-2 text-[12.5px] font-medium text-brand-2 hover:bg-muted/40">
            {showAll ? 'Show the first five cases' : `Show all ${cases.length} cases`}
          </button>
        )}
      </div>

      <aside className="grid content-start gap-3">
        <div className="rounded-lg border bg-card p-3.5 shadow-card">
          {focusNode ? (
            <NodeDetail node={focusNode} edges={net?.edges ?? []} onClose={() => setFocus(null)} />
          ) : (
            <>
              <p className="text-[13px] font-semibold">How to read it</p>
              <ol className="mt-1.5 grid list-decimal gap-1 pl-4 text-[12.5px] leading-relaxed text-muted-foreground">
                <li>Each row is one case: accounts under alert that sent money to each other.</li>
                <li>Read left to right: who paid in, the account that received it first, the accounts it passed it to, and where it left.</li>
                <li>Line width is the amount; the figure on a line is what moved along it.</li>
                <li>Click an account for its alert.</li>
              </ol>
              <dl className="mt-3 grid grid-cols-3 gap-2 border-t pt-3 text-center">
                <Figure label="cases" value={cases.length} />
                <Figure label="accounts under alert" value={cases.reduce((t, c) => t + c.alerted.length, 0)} />
                <Figure label="held" value={cases.reduce((t, c) => t + c.held, 0)} tone="text-ok" />
              </dl>
              {net && net.alertedAccounts > net.shown && (
                <p className="mt-2 text-[11.5px] text-muted-foreground">
                  The {net.shown} most severe of {net.alertedAccounts} accounts under alert.
                </p>
              )}
            </>
          )}
        </div>
        <div className="rounded-lg border bg-card p-3.5 text-[12px] shadow-card">
          <p className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Legend</p>
          <ul className="grid gap-1.5">
            <Legend swatch={<circle cx={9} cy={9} r={6} fill="var(--sev-critical)" />}>Under alert: critical</Legend>
            <Legend swatch={<circle cx={9} cy={9} r={6} fill="var(--sev-high)" />}>Under alert: high · medium in amber</Legend>
            <Legend swatch={<><circle cx={9} cy={9} r={5} fill="var(--sev-high)" /><circle cx={9} cy={9} r={8} fill="none" stroke="var(--ok)" strokeWidth={1.6} /></>}>Held or frozen: money stopped</Legend>
            <Legend swatch={<circle cx={9} cy={9} r={3.5} fill="var(--muted-foreground)" fillOpacity={0.45} />}>Paid in or paid out, no alert</Legend>
            <Legend swatch={<line x1={1} y1={9} x2={17} y2={9} stroke="var(--sev-high)" strokeOpacity={0.6} strokeWidth={3} />}>Model scored it {threshold.toFixed(2)}+ (likely fraud)</Legend>
            <Legend swatch={<line x1={1} y1={9} x2={17} y2={9} stroke="var(--muted-foreground)" strokeOpacity={0.5} strokeWidth={2} strokeDasharray="3 3" />}>Blocked by a hold</Legend>
          </ul>
        </div>
      </aside>
    </div>
  )
}

function ColumnHeads({ layers }: { layers: number }) {
  const titles = ['Paid in by', 'First account under alert', 'Received from it', 'Further on'].slice(0, layers + 1)
  titles.push('Paid out to')
  return (
    <svg viewBox={`0 0 ${W} 34`} className="block w-full border-b bg-muted/30" aria-hidden>
      {titles.map((t, i) => (
        <text key={t} x={colX(i, layers)} y={21} textAnchor="middle" className="fill-muted-foreground" fontSize={12} fontWeight={600}>
          {t}
        </text>
      ))}
      {Array.from({ length: layers + 1 }, (_, i) => (
        <path key={i} d={`M${(colX(i, layers) + colX(i + 1, layers)) / 2 - 5},13 l6,4 -6,4`} fill="none" stroke="var(--muted-foreground)" strokeOpacity={0.5} />
      ))}
    </svg>
  )
}

function CaseRow({
  c,
  index,
  layers,
  maxAmt,
  focus,
  hover,
  onFocus,
  onHover,
}: {
  c: Case
  index: number
  layers: number
  maxAmt: number
  focus: string | null
  hover: string | null
  onFocus: (id: string | null) => void
  onHover: (id: string | null) => void
}) {
  const lit = hover ?? focus
  const touches = (l: Link) => !!lit && (l.from.node?.id === lit || l.to.node?.id === lit)
  const anyLit = !!lit && c.slots.some(s => s.node?.id === lit)
  const x = (s: Slot) => colX(s.col, layers)
  return (
    <div className={cn('border-b last:border-b-0', index % 2 && 'bg-muted/20')}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pt-2 text-[12px]">
        <span className="rounded-full px-2 py-0.5 text-[11px] font-medium capitalize text-white" style={{ background: SEV_FILL[c.severity] }}>
          {c.severity}
        </span>
        <span className="text-muted-foreground">
          {c.alerted.length} account{c.alerted.length > 1 ? 's' : ''} under alert · {inrShort(c.totalIn)} in from outside · {inrShort(c.totalOut)} out
          {c.held ? ` · ${c.held} held` : ''}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${c.height}`} className="block w-full" role="img" aria-label={`Case ${index + 1}: ${c.alerted.length} accounts under alert`}>
        {c.links.map(l => {
          const x1 = x(l.from) + 10
          const x2 = x(l.to) - 12
          const mid = (x1 + x2) / 2
          const width = 1 + 6 * Math.sqrt(l.amount / maxAmt)
          const on = touches(l)
          const off = (anyLit && !on) || (!anyLit && l.minor) // a case's smaller flows stay faint until an account is hovered
          const label = l.label || on
          return (
            <g key={l.key} opacity={off ? 0.12 : 1}>
              <path
                d={`M${x1},${l.from.y} C${mid},${l.from.y} ${mid},${l.to.y} ${x2},${l.to.y}`}
                fill="none"
                stroke={l.hot ? 'var(--sev-high)' : 'var(--muted-foreground)'}
                strokeOpacity={l.hot ? (on ? 0.85 : 0.45) : on ? 0.6 : 0.25}
                strokeWidth={width}
                strokeLinecap="round"
                strokeDasharray={l.blocked ? '4 4' : undefined}
              />
              <path d={`M${x2 - 6},${l.to.y - 4} L${x2 + 1},${l.to.y} L${x2 - 6},${l.to.y + 4}`} fill="none" stroke={l.hot ? 'var(--sev-high)' : 'var(--muted-foreground)'} strokeOpacity={0.6} strokeWidth={1.3} />
              {label && (
                <text x={mid} y={(l.from.y + l.to.y) / 2 - 5} textAnchor="middle" fontSize={10.5} className="fill-foreground" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
                  {inrShort(l.amount)}
                  {l.count > 1 ? ` · ${l.count}×` : ''}
                  {l.blocked ? ' · blocked' : ''}
                </text>
              )}
            </g>
          )
        })}
        {c.slots.map(s => (
          <SlotMark key={s.key} s={s} x={x(s)} layers={layers} dim={anyLit && s.node?.id !== lit && !c.links.some(l => touches(l) && (l.from === s || l.to === s))} onFocus={onFocus} onHover={onHover} />
        ))}
      </svg>
    </div>
  )
}

function SlotMark({ s, x, layers, dim, onFocus, onHover }: { s: Slot; x: number; layers: number; dim: boolean; onFocus: (id: string | null) => void; onHover: (id: string | null) => void }) {
  const n = s.node
  if (s.more && s.col > 0 && s.col <= layers) {
    // folded accounts under alert in a middle column
    return (
      <g opacity={dim ? 0.3 : 1}>
        <circle cx={x} cy={s.y} r={7} fill="var(--card)" stroke="var(--sev-medium)" strokeWidth={1.3} strokeDasharray="2 2" />
        <text x={x} y={s.y + 20} textAnchor="middle" fontSize={10.5} className="fill-muted-foreground" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
          +{s.more.count} more under alert · {inrShort(s.more.amount)}
        </text>
      </g>
    )
  }
  if (s.more) {
    const left = s.col === 0
    return (
      <text x={left ? x + 8 : x - 8} y={s.y + 4} textAnchor={left ? 'end' : 'start'} fontSize={11.5} className="fill-muted-foreground" opacity={dim ? 0.3 : 1}>
        +{s.more.count} more · {inrShort(s.more.amount)}
      </text>
    )
  }
  if (!n) return null
  const outside = s.col === 0 || s.col === layers + 1
  if (outside || !n.severity) {
    const left = s.col === 0
    return (
      <g opacity={dim ? 0.3 : 1} className="cursor-pointer" onClick={() => onFocus(n.id)} onPointerEnter={() => onHover(n.id)} onPointerLeave={() => onHover(null)}>
        <circle cx={x} cy={s.y} r={4} fill={n.severity ? SEV_FILL[n.severity] : 'var(--muted-foreground)'} fillOpacity={n.severity ? 0.9 : 0.45} />
        <text x={left ? x - 10 : x + 10} y={s.y + 4} textAnchor={left ? 'end' : 'start'} fontSize={11.5} className="fill-muted-foreground font-mono">
          {short(n.vpa, 16)}
        </text>
      </g>
    )
  }
  const r = n.severity === 'critical' ? 9 : n.severity === 'high' ? 8 : 7
  return (
    <g opacity={dim ? 0.3 : 1} className="cursor-pointer" onClick={() => onFocus(n.id)} onPointerEnter={() => onHover(n.id)} onPointerLeave={() => onHover(null)}>
      {n.level >= 2 && <circle cx={x} cy={s.y} r={r + 4} fill="none" stroke="var(--ok)" strokeWidth={1.6} />}
      {n.level === 1 && <circle cx={x} cy={s.y} r={r + 4} fill="none" stroke="var(--sev-medium)" strokeWidth={1.3} strokeDasharray="2 2" />}
      <circle cx={x} cy={s.y} r={r} fill={SEV_FILL[n.severity]} stroke={n.test ? 'var(--brand-2)' : 'var(--card)'} strokeWidth={n.test ? 2 : 1.5} strokeDasharray={n.test ? '2 2' : undefined} />
      <text x={x} y={s.y - r - 6} textAnchor="middle" fontSize={11.5} fontWeight={600} className="fill-foreground font-mono" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
        {short(n.vpa)}
      </text>
      <text x={x} y={s.y + r + 13} textAnchor="middle" fontSize={10.5} className="fill-muted-foreground" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
        {n.level >= 2 ? `held · ${DETECTOR_SHORT[n.detector ?? ''] ?? ''}` : (DETECTOR_SHORT[n.detector ?? ''] ?? '')}
      </text>
    </g>
  )
}

function NodeDetail({ node: n, edges, onClose }: { node: NetworkNode; edges: NetworkEdge[]; onClose: () => void }) {
  const ins = edges.filter(e => e.target === n.id)
  const outs = edges.filter(e => e.source === n.id)
  const sum = (xs: NetworkEdge[]) => xs.reduce((s, e) => s + e.amount, 0)
  return (
    <div>
      <div className="flex items-start justify-between gap-2">
        <p className="break-all font-mono text-[12.5px] font-medium">{n.vpa}</p>
        <button type="button" onClick={onClose} className="text-[12px] text-muted-foreground hover:text-foreground">
          Close
        </button>
      </div>
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
        {n.gnnMax !== null && <Row k="Highest model score" v={n.gnnMax.toFixed(3)} />}
        <Row k="Paid in (shown)" v={`${inrShort(sum(ins))} · ${ins.length} payer${ins.length === 1 ? '' : 's'}`} />
        <Row k="Paid out (shown)" v={`${inrShort(sum(outs))} · ${outs.length} payee${outs.length === 1 ? '' : 's'}`} />
      </dl>
      {n.alertId && (
        <Link href={`/console?alert=${encodeURIComponent(n.alertId)}`} className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md bg-brand-1 px-3 text-[12.5px] font-medium text-white hover:bg-brand-1/90">
          Open this alert <ArrowRight className="size-3.5" />
        </Link>
      )}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-[220px] place-items-center p-6 text-center text-[13px] text-muted-foreground">{children}</div>
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
      <dt className="mt-1 text-[11px] leading-tight text-muted-foreground">{label}</dt>
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
