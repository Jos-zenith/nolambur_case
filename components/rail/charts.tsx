'use client'

import { useState } from 'react'

// Validated with the dataviz skill's validate_palette.js (light surface): all checks pass.
export const SERIES = ['#2a6fb0', '#d0620f', '#1f9e89']

type Epoch = { epoch: number; train: number; val: number; test: number }

/** Per-epoch F1 for the train, validation and test splits, from logs/logs.log. */
export function TrainingCurve({ epochs }: { epochs: Epoch[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (!epochs.length) return <p className="text-[13px] text-muted-foreground">No finetune run found in logs/logs.log.</p>
  const W = 640
  const H = 220
  const pad = { l: 40, r: 64, t: 12, b: 28 }
  const xs = (i: number) => pad.l + (i / Math.max(1, epochs.length - 1)) * (W - pad.l - pad.r)
  const ys = (v: number) => pad.t + (1 - v) * (H - pad.t - pad.b)
  const series = [
    { key: 'train' as const, label: 'Train', color: SERIES[0] },
    { key: 'val' as const, label: 'Validation', color: SERIES[1] },
    { key: 'test' as const, label: 'Test', color: SERIES[2] },
  ]
  const last = epochs[epochs.length - 1]
  const h = hover !== null ? epochs[hover] : null

  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap gap-4 text-[12px] text-muted-foreground">
        {series.map(s => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="F1 by epoch for train, validation and test splits" onMouseLeave={() => setHover(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map(v => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={ys(v)} y2={ys(v)} stroke="var(--border)" />
            <text x={pad.l - 8} y={ys(v) + 4} textAnchor="end" fontSize="11" fill="var(--muted-foreground)">
              {v.toFixed(2)}
            </text>
          </g>
        ))}
        {epochs.map((e, i) => (
          <text key={e.epoch} x={xs(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted-foreground)">
            {e.epoch}
          </text>
        ))}
        <text x={W - pad.r + 6} y={ys(Math.max(last.train, last.val, last.test)) + 4} fontSize="11" fill="var(--foreground)">
          {last.train === last.val && last.val === last.test ? `all ${last.test.toFixed(2)}` : `test ${last.test.toFixed(2)}`}
        </text>
        {h && <line x1={xs(hover!)} x2={xs(hover!)} y1={pad.t} y2={H - pad.b} stroke="var(--muted-foreground)" strokeDasharray="3 3" />}
        {series.map(s => (
          <g key={s.key}>
            <polyline points={epochs.map((e, i) => `${xs(i)},${ys(e[s.key])}`).join(' ')} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
            {h && <circle cx={xs(hover!)} cy={ys(h[s.key])} r="4" fill={s.color} stroke="var(--card)" strokeWidth="2" />}
          </g>
        ))}
        {epochs.map((_, i) => (
          <rect key={i} x={xs(i) - (W - pad.l - pad.r) / epochs.length / 2} y={pad.t} width={(W - pad.l - pad.r) / epochs.length} height={H - pad.t - pad.b} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {h && (
        <div className="pointer-events-none absolute right-2 top-8 border bg-card px-2.5 py-1.5 text-[12px] shadow-sm">
          <p className="font-medium">Epoch {h.epoch}</p>
          {series.map(s => (
            <p key={s.key} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: s.color }} />
              {s.label} <span className="ml-auto pl-3 font-mono">{h[s.key].toFixed(4)}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

/** Count of edges per score bin, one panel per class so each keeps a readable scale. */
export function ScoreHistogram({ bins, klass, title }: { bins: { bin: string; fraud: number; clean: number }[]; klass: 'fraud' | 'clean'; title: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 320
  const H = 150
  const pad = { l: 8, r: 8, t: 18, b: 22 }
  const max = Math.max(1, ...bins.map(b => b[klass]))
  const bw = (W - pad.l - pad.r) / bins.length
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b)
  const h = hover !== null ? bins[hover] : null

  return (
    <div className="relative">
      <p className="text-[12.5px] font-medium">{title}</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
        <line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} stroke="var(--border)" />
        {bins.map((b, i) => {
          const v = b[klass]
          const top = y(v)
          const height = Math.max(v ? 2 : 0, H - pad.b - top)
          return (
            <g key={b.bin} onMouseEnter={() => setHover(i)}>
              <rect x={pad.l + i * bw} y={pad.t} width={bw} height={H - pad.t - pad.b} fill="transparent" />
              <path
                d={`M${pad.l + i * bw + 1} ${H - pad.b} V${H - pad.b - height + 3} q0 -3 3 -3 H${pad.l + (i + 1) * bw - 4} q3 0 3 3 V${H - pad.b} Z`}
                fill={SERIES[0]}
                opacity={hover === null || hover === i ? 1 : 0.5}
              />
              {v > 0 && (i === 0 || i === bins.length - 1) && (
                <text x={pad.l + i * bw + bw / 2} y={H - pad.b - height - 4} textAnchor="middle" fontSize="10.5" fill="var(--foreground)">
                  {v.toLocaleString('en-IN')}
                </text>
              )}
            </g>
          )
        })}
        <text x={pad.l} y={H - 6} fontSize="10.5" fill="var(--muted-foreground)">0.0</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" fontSize="10.5" fill="var(--muted-foreground)">1.0</text>
      </svg>
      {h && (
        <div className="pointer-events-none absolute right-1 top-5 border bg-card px-2 py-1 text-[12px] shadow-sm">
          score {h.bin}: <span className="font-mono">{h[klass].toLocaleString('en-IN')}</span> edges
        </div>
      )}
    </div>
  )
}
