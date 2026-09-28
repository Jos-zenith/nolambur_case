'use client'

import { ChevronDown, Info, Lightbulb, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------- glossary

/** Plain-language definitions shown on hover wherever a term appears. */
export const GLOSSARY = {
  mule: 'A bank account used to receive scam money and pass it on, so it is harder to trace and recover. Often rented from someone for a fee.',
  'l1 mule': 'First-layer mule: receives money straight from the victim, then forwards it within minutes.',
  'l2 mule': 'Second-layer mule: receives from a first-layer mule. By now the money is split across several accounts.',
  layering: 'Moving money through several accounts in quick succession so the trail back to the victim goes cold.',
  vpa: 'Virtual Payment Address, the UPI handle (like name@bank) that stands in for an account number.',
  gnn: 'Graph neural network. It scores a transfer by looking at the accounts around it, not just the transfer itself.',
  gin: 'Graph Isomorphism Network, the kind of GNN used here. It learns patterns in how money flows between neighbouring accounts.',
  'model score': 'The GNN\'s fraud probability for a transfer, 0 to 1. At 0.9 or above it counts as the model backing a rule.',
  'lead time': 'How long between the alert and the mule sending the money on. That is the window in which a freeze saves money.',
  precision: 'Of the accounts the detectors alerted on, the share that really are mules. Low precision means analysts waste time.',
  recall: 'Of all the mule accounts, the share the detectors caught. Low recall means mules slip through.',
  hold: 'An automatic, temporary block. Money in or out of the account stops until a supervisor confirms (freeze) or releases it.',
  freeze: 'A confirmed block, sent to the bank as a signed instruction. Only a supervisor can freeze.',
  '1930': 'India\'s cybercrime helpline. Reports go to CFCFRMS, the system banks use to put liens on stolen money.',
  'pass-through': 'Money that comes in and goes straight out again. A normal account keeps most of what it receives; a mule does not.',
  'evidence pack': 'Everything about a case in one file: accounts, transfers, alerts and every analyst action, ready for law enforcement.',
  'audit trail': 'An append-only record of every action. Each row is hash-chained to the one before, so edits are detectable.',
  replay: 'The console plays back a recorded dataset in time order, as if the payments were arriving now.',
  onboarding: 'Checking a new merchant before it can receive payments, to keep mules off the platform.',
} as const

export type TermKey = keyof typeof GLOSSARY

/** A word with a dotted underline that explains itself on hover. */
export function Term({ k, children }: { k: TermKey; children?: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="dotted-term">
          {children ?? k}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[280px] text-[12.5px] leading-snug">{GLOSSARY[k]}</TooltipContent>
    </Tooltip>
  )
}

/** A small (i) that explains the thing next to it. */
export function InfoTip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" aria-label="What is this?" className={cn('inline-grid size-4 place-items-center rounded-full text-muted-foreground hover:text-brand-2', className)}>
          <Info className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[300px] text-[12.5px] leading-snug">{children}</TooltipContent>
    </Tooltip>
  )
}

// ---------------------------------------------------------------------------- page header

/** Title block for every page, with an optional "how to read this page" guide that remembers being closed. */
export function PageHeader({
  icon: Icon,
  eyebrow,
  title,
  children,
  guide,
  guideKey,
  right,
}: {
  icon: LucideIcon
  eyebrow?: string
  title: React.ReactNode
  children?: React.ReactNode
  guide?: { title: string; body: React.ReactNode }[]
  guideKey?: string
  right?: React.ReactNode
}) {
  const storageKey = `rail.guide.${guideKey ?? String(title)}`
  const [open, setOpen] = useState(true)
  useEffect(() => {
    try {
      if (localStorage.getItem(storageKey) === 'closed') setOpen(false)
    } catch {}
  }, [storageKey])
  const toggle = () => {
    setOpen(o => {
      try {
        localStorage.setItem(storageKey, o ? 'closed' : 'open')
      } catch {}
      return !o
    })
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-md border bg-card text-brand-1">
            <Icon className="size-5" />
          </span>
          <div className="min-w-0">
            {eyebrow && <p className="text-[11.5px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{eyebrow}</p>}
            <h1 className="text-[20px] font-semibold leading-tight tracking-tight">{title}</h1>
            {children && <div className="mt-1 max-w-3xl text-[13.5px] leading-relaxed text-muted-foreground">{children}</div>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {right}
          {guide && (
            <button onClick={toggle} className="flex h-8 items-center gap-1.5 rounded-md border bg-card px-2.5 text-[12.5px] hover:bg-accent" aria-expanded={open}>
              <Lightbulb className="size-3.5 text-muted-foreground" />
              How to read this
              <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
            </button>
          )}
        </div>
      </div>
      {guide && open && (
        <ol className="grid gap-px overflow-hidden rounded-lg border bg-border shadow-card sm:grid-cols-2 xl:grid-cols-4">
          {guide.map((g, i) => (
            <li key={g.title} className="bg-card p-3">
              <p className="flex items-center gap-2 text-[13px] font-medium">
                <span className="grid size-5 place-items-center rounded-full border border-brand-1/30 text-[11px] font-semibold text-brand-1">{i + 1}</span>
                {g.title}
              </p>
              <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{g.body}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------- numbers

/** Eases a number toward its new value so live changes are visible, not jumpy. */
export function useCountUp(target: number, ms = 700) {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const start = performance.now()
    const a = from.current
    if (a === target) return
    let raf = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      const eased = 1 - Math.pow(1 - t, 3)
      const v = a + (target - a) * eased
      setValue(v)
      if (t < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => {
      cancelAnimationFrame(raf)
      from.current = target
    }
  }, [target, ms])
  return value
}

type Tone = 'neutral' | 'brand' | 'teal' | 'critical' | 'warning' | 'ok'

const TONE: Record<Tone, { icon: string; ring: string }> = {
  neutral: { icon: 'bg-muted text-foreground', ring: 'border-border' },
  brand: { icon: 'bg-brand-soft text-brand-2', ring: 'border-border' },
  teal: { icon: 'bg-teal-soft text-brand-3', ring: 'border-border' },
  critical: { icon: 'bg-sev-critical-bg text-sev-critical', ring: 'border-sev-critical/30' },
  warning: { icon: 'bg-sev-medium-bg text-sev-medium', ring: 'border-sev-medium/30' },
  ok: { icon: 'bg-ok-bg text-ok', ring: 'border-ok/30' },
}

/** label · value · note, with an icon, a tone and an optional sparkline. Value counts up when it changes. */
export function StatTile({
  icon: Icon,
  label,
  value,
  format = v => Math.round(v).toLocaleString('en-IN'),
  display,
  note,
  help,
  tone = 'neutral',
  trend,
  big,
  i = 0,
}: {
  icon: LucideIcon
  label: string
  value: number | null
  format?: (v: number) => string
  display?: string
  note?: React.ReactNode
  help?: React.ReactNode
  tone?: Tone
  trend?: number[]
  big?: boolean
  i?: number
}) {
  const animated = useCountUp(value ?? 0)
  const t = TONE[tone]
  return (
    <div
      className={cn('enter grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-hidden rounded-lg border bg-card p-3.5 shadow-card', t.ring)}
      style={{ '--i': i } as React.CSSProperties}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className={cn('grid size-7 shrink-0 place-items-center rounded-md', t.icon)}>
          <Icon className="size-4" />
        </span>
        <p className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground" title={label}>
          {label}
        </p>
        {help && <InfoTip className="shrink-0">{help}</InfoTip>}
      </div>
      <div className="flex min-w-0 items-end justify-between gap-2">
        <p className={cn('figure min-w-0 truncate font-semibold leading-none', big ? 'text-[34px]' : 'text-[26px]')}>{display ?? (value === null ? '—' : format(animated))}</p>
        {trend && <Spark data={trend} w={64} />}
      </div>
      {note && <p className="line-clamp-2 min-h-[2lh] text-[11.5px] leading-snug text-muted-foreground">{note}</p>}
    </div>
  )
}

/** Recent activity as a small area sparkline in the de-emphasis hue, latest point marked. */
export function Spark({ data, w = 84, h = 26 }: { data: number[]; w?: number; h?: number }) {
  if (data.length < 2) return null
  const max = Math.max(...data, 1)
  const xy = data.map((v, i) => [(i / (data.length - 1)) * w, h - 2 - (v / max) * (h - 4)] as const)
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const [lx, ly] = xy[xy.length - 1]
  return (
    <svg width={w} height={h} className="shrink-0 text-chart-2" aria-hidden>
      <polygon points={`0,${h} ${line} ${w},${h}`} fill="currentColor" opacity={0.12} />
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r={2.5} className="fill-brand-2" />
    </svg>
  )
}

// ---------------------------------------------------------------------------- callout

export function Callout({ icon: Icon = Lightbulb, tone = 'brand', title, children, className }: { icon?: LucideIcon; tone?: 'brand' | 'teal' | 'warning' | 'critical'; title?: string; children: React.ReactNode; className?: string }) {
  const cls = {
    brand: 'border-brand-2/20 bg-brand-soft/60 [&_svg]:text-brand-2',
    teal: 'border-brand-3/20 bg-teal-soft/70 [&_svg]:text-brand-3',
    warning: 'border-sev-medium/25 bg-sev-medium-bg/70 [&_svg]:text-sev-medium',
    critical: 'border-sev-critical/25 bg-sev-critical-bg/70 [&_svg]:text-sev-critical',
  }[tone]
  return (
    <div className={cn('flex gap-2.5 rounded-lg border p-3 text-[13px] leading-relaxed', cls, className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div>
        {title && <p className="font-medium">{title}</p>}
        <div className={cn(title && 'mt-0.5', 'text-foreground/85')}>{children}</div>
      </div>
    </div>
  )
}
