import { inrShort } from '@/lib/rail/format'
import type { AlertDetail, TrailNode } from '@/lib/rail/types'

const W = 920
const BOX_H = 38
const GAP = 8
const TOP = 26
const COL = { src: 0, mid: 262, dst: 486, next: 738 }
const BOX_W = { src: 196, mid: 168, dst: 196, next: 182 }

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

function tone(n: TrailNode) {
  if (n.frozen || n.flagged) return 'var(--sev-critical)'
  if (n.gnnMax >= 0.9) return 'var(--sev-high)'
  return 'var(--muted-foreground)'
}

export function MoneyTrail({ trail, vpa }: { trail: AlertDetail['trail']; vpa: string }) {
  if (!trail.sources.length && !trail.destinations.length) {
    return <p className="text-[13px] text-muted-foreground">No money movement replayed yet for this account.</p>
  }
  const maxAmt = Math.max(1, ...trail.sources.map(s => s.amount), ...trail.destinations.map(d => d.amount))
  const stroke = (amt: number) => 1 + (amt / maxAmt) * 9

  const srcY = trail.sources.map((_, i) => TOP + i * (BOX_H + GAP))
  const dstY: number[] = []
  let y = TOP
  for (const d of trail.destinations) {
    dstY.push(y)
    y += Math.max(1, d.next?.length ?? 0) * (BOX_H + GAP)
  }
  const bodyH = Math.max(srcY.length * (BOX_H + GAP), y - TOP, 2 * (BOX_H + GAP))
  const H = TOP + bodyH + 4
  const midY = TOP + bodyH / 2 - 30
  const midH = 60
  const curve = (x1: number, y1: number, x2: number, y2: number) => {
    const c = (x2 - x1) / 2
    return `M${x1} ${y1} C${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`
  }

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[680px]" role="img" aria-label={`Money trail for ${vpa}`}>
        <g fontSize="11" fill="var(--muted-foreground)">
          <text x={COL.src}>Paid in by</text>
          <text x={COL.mid}>This account</text>
          <text x={COL.dst}>Sent on to</text>
          <text x={COL.next}>Then to</text>
          <line x1="0" x2={W} y1="10" y2="10" stroke="var(--border)" />
        </g>
        <g fill="none">
          {trail.sources.map((s, i) => (
            <path key={s.id} d={curve(COL.src + BOX_W.src, srcY[i] + BOX_H / 2, COL.mid, midY + midH / 2)} stroke={tone(s)} strokeOpacity="0.3" strokeWidth={stroke(s.amount)} />
          ))}
          {trail.destinations.map((d, i) => (
            <g key={d.id}>
              <path d={curve(COL.mid + BOX_W.mid, midY + midH / 2, COL.dst, dstY[i] + BOX_H / 2)} stroke={tone(d)} strokeOpacity="0.35" strokeWidth={stroke(d.amount)} />
              {(d.next ?? []).map((n, j) => (
                <path key={n.id} d={curve(COL.dst + BOX_W.dst, dstY[i] + BOX_H / 2, COL.next, dstY[i] + j * (BOX_H + GAP) + BOX_H / 2)} stroke={tone(n)} strokeOpacity="0.35" strokeWidth={Math.max(1, stroke(n.amount))} />
              ))}
            </g>
          ))}
        </g>
        {trail.sources.map((s, i) => (
          <Node key={s.id} x={COL.src} y={srcY[i]} w={BOX_W.src} n={s} />
        ))}
        <g>
          <rect x={COL.mid} y={midY} width={BOX_W.mid} height={midH} rx="4" fill="var(--card)" stroke="var(--primary)" strokeWidth="1.5" />
          <text x={COL.mid + 10} y={midY + 20} fontSize="12" fontWeight="600" fill="var(--foreground)" fontFamily="var(--font-mono)">
            {clip(vpa, 20)}
          </text>
          <text x={COL.mid + 10} y={midY + 36} fontSize="11" fill="var(--muted-foreground)">
            In {inrShort(trail.totalIn)}
          </text>
          <text x={COL.mid + 10} y={midY + 50} fontSize="11" fill="var(--muted-foreground)">
            Out {inrShort(trail.totalOut)}
          </text>
        </g>
        {trail.destinations.map((d, i) => (
          <g key={d.id}>
            <Node x={COL.dst} y={dstY[i]} w={BOX_W.dst} n={d} />
            {(d.next ?? []).map((n, j) => (
              <Node key={n.id} x={COL.next} y={dstY[i] + j * (BOX_H + GAP)} w={BOX_W.next} n={n} />
            ))}
          </g>
        ))}
      </svg>
    </div>
  )
}

function Node({ x, y, w, n }: { x: number; y: number; w: number; n: TrailNode }) {
  const accent = tone(n)
  const marked = accent !== 'var(--muted-foreground)'
  const tag = n.frozen ? ' · frozen' : n.flagged ? ' · flagged' : ''
  return (
    <g>
      <rect x={x} y={y} width={w} height={BOX_H} rx="4" fill="var(--card)" stroke={marked ? accent : 'var(--border)'} />
      <text x={x + 8} y={y + 15} fontSize="11.5" fill="var(--foreground)" fontFamily={n.id === 'others' ? undefined : 'var(--font-mono)'}>
        {clip(n.label, 24)}
      </text>
      <text x={x + 8} y={y + 30} fontSize="11" fill="var(--muted-foreground)">
        {inrShort(n.amount)} · {n.count} txn{n.count === 1 ? '' : 's'} · gnn {n.gnnMax.toFixed(2)}
        {tag}
      </text>
    </g>
  )
}
