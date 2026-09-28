'use client'

import { Activity, ArrowRight, BookOpen, Briefcase, ListChecks, ScanSearch, CheckCircle2, CircleDashed, FlaskConical, GitFork, Hourglass, Network, ScanEye, ShieldAlert, ShieldCheck, Zap } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { clock, duration, inr, inrShort, pct } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import type { Detector } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { BackendGate } from './BackendGate'
import { GLOSSARY, Term, useCountUp, type TermKey } from './kit'
import { MetricStrip } from './MetricStrip'

type Evaluation = {
  detectors: { accountLevel: { precision: number; recall: number }; combined: { precision: number; recall: number }; medianLeadSec: number | null; mulesInTransactions: number }
  autoHold?: { accountsHeld: number; mulesHeld: number; fraudTotal: number; fraudBlocked: number; genuineBlocked: number; medianSecondsToHold: number | null }
  dataset: { rows: number; accounts: number; fraudRows: number }
}

/** /rail/evaluation, fetched once the bridge is live. */
export function useEvaluation() {
  const backend = useRail(s => s.backend)
  const [ev, setEv] = useState<Evaluation | null>(null)
  useEffect(() => {
    if (ev || backend !== 'live') return
    fetch('/api/rail/evaluation', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(setEv)
      .catch(() => {})
  }, [backend, ev])
  return ev
}

// ---------------------------------------------------------------------------- hero

export function Hero() {
  return (
    <section className="relative overflow-hidden rounded-lg bg-brand-1 text-white">
      <div className="relative grid gap-8 p-6 md:p-8 lg:grid-cols-[1.25fr_1fr] lg:items-center">
        <div className="enter">
          <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-white/60">Payment-aggregator risk · UPI</p>
          <h1 className="mt-3 max-w-2xl text-[30px] font-semibold leading-[1.2] tracking-tight md:text-[34px]">
            Freeze the mule before the money moves on.
          </h1>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
            Scam money lands in a first account and is forwarded within minutes. This console watches every UPI payment with a graph neural network and four
            rules, and raises the alarm while the money is still in the first account.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link href="/console" className="group inline-flex h-10 items-center gap-2 rounded-[5px] bg-white px-4 text-[13.5px] font-medium text-brand-1 hover:bg-white/90">
              Open the alert queue <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a href="#how-it-works" className="inline-flex h-10 items-center gap-2 rounded-[5px] border border-white/30 px-4 text-[13.5px] font-medium text-white hover:bg-white/10">
              <BookOpen className="size-4" /> How a mule chain works
            </a>
          </div>
        </div>
        <HeroLive />
      </div>
    </section>
  )
}

/** The page's one hero figure: fraud money blocked, live from the engine. */
function HeroLive() {
  const m = useRail(s => s.metrics)
  const backend = useRail(s => s.backend)
  const paused = useRail(s => s.paused)
  const blocked = useCountUp(m?.blockedFraudAmount ?? 0, 900)

  if (!m || backend !== 'live') {
    return (
      <div className="rounded-md border border-white/15 bg-white/[0.06] p-5">
        <p className="flex items-center gap-2 text-[13px] text-white/80">
          <CircleDashed className="size-4 animate-spin" /> {backend === 'offline' || backend === 'error' ? 'Bridge not running' : 'Connecting to the GNN bridge…'}
        </p>
        <p className="mt-2 text-[12.5px] text-white/60">
          Start it with <code className="font-mono">cd Multi-GNN &amp;&amp; python bridge_api.py</code>. Live numbers appear here on their own.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-white/15 bg-white/[0.06] p-5">
      <div className="flex items-center justify-between text-[12px] text-white/70">
        <span className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-[#6fd49a]" />
          {m.rowsTotal === null ? `Live stream · ${m.source}` : paused ? 'Replay paused' : m.done ? 'Replay finished' : `Replaying at ${m.speed}×`}
        </span>
        <span className="font-mono">{clock(m.simT)}</span>
      </div>
      <p className="mt-4 text-[12.5px] text-white/70">Fraud money blocked</p>
      <p className="figure text-[48px] font-semibold leading-none tracking-tight">{inrShort(blocked)}</p>
      <p className="mt-1.5 text-[12.5px] text-white/65">
        {m.heldAccounts} held · {m.frozenAccounts} frozen{m.blockedGenuineAmount > 0 ? ` · ${inrShort(m.blockedGenuineAmount)} genuine caught too` : ' · no genuine payments blocked'}
      </p>
      <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/10 pt-4 text-[12px]">
        <Mini label="Open alerts" value={String(m.openAlerts)} hot={m.openBySeverity.critical > 0} />
        <Mini label="Lead time" value={duration(m.medianLeadSec)} />
        <Mini label="Mules caught" value={`${m.mulesAlerted}/${m.mulesSeen}`} />
      </div>
    </div>
  )
}

function Mini({ label, value, hot }: { label: string; value: string; hot?: boolean }) {
  return (
    <div>
      <p className="text-white/60">{label}</p>
      <p className={cn('figure mt-0.5 text-[18px] font-semibold', hot && 'text-[#ffb4a8]')}>{value}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------- how a mule chain works

function useReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const q = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(q.matches)
    const on = () => setReduced(q.matches)
    q.addEventListener('change', on)
    return () => q.removeEventListener('change', on)
  }, [])
  return reduced
}

const V = [
  { id: 'v1', x: 80, y: 80 },
  { id: 'v2', x: 80, y: 180 },
]
const L1 = { x: 300, y: 130 }
const L2 = [
  { x: 520, y: 60 },
  { x: 520, y: 130 },
  { x: 520, y: 200 },
]
const OUT = { x: 700, y: 130 }

const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => {
  const mx = (a.x + b.x) / 2
  return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`
}

/** An illustration, not data: the shape every Nolambur fraud case takes, and where each detector fires. */
export function MuleChainExplainer() {
  const reduced = useReducedMotion()
  const ev = useEvaluation()
  const [step, setStep] = useState<number | null>(null)
  const inEdges = V.map(v => curve(v, L1))
  const midEdges = L2.map(n => curve(L1, n))
  const outEdges = L2.map(n => curve(n, OUT))

  const STEPS = [
    {
      n: 1,
      icon: Zap,
      title: 'Victims pay a stranger',
      body: (
        <>
          Someone is talked into a big transfer (a fake investment, a &ldquo;digital arrest&rdquo;). They pay ₹4.5 lakh or more to an account they have never paid,
          often in another state. That account is the first-layer <Term k="mule">mule</Term>.
        </>
      ),
      detector: 'High-value inflow from new payers',
    },
    {
      n: 2,
      icon: GitFork,
      title: 'The mule forwards it fast',
      body: (
        <>
          Within minutes most of it leaves again, split across several accounts. That is <Term k="pass-through">pass-through</Term>, and the gap before it is the{' '}
          <Term k="lead time">lead time</Term>
          {ev?.detectors.medianLeadSec != null ? `: ${duration(ev.detectors.medianLeadSec)} in this data (median).` : '.'}
        </>
      ),
      detector: 'Rapid pass-through',
    },
    {
      n: 3,
      icon: Network,
      title: 'The next hop lights up',
      body: (
        <>
          Anyone receiving from a flagged account is flagged too: the <Term k="l2 mule">second-layer mules</Term>. The graph model adds leads the rules miss by
          looking at who is connected to whom.
        </>
      ),
      detector: 'Funds from a flagged account',
    },
    {
      n: 4,
      icon: ShieldCheck,
      title: 'Hold at the first account',
      body: (
        <>
          A critical alert that the <Term k="gnn">GNN</Term> backs puts the account on <Term k="hold">hold</Term> at once. Everything downstream stops, then a
          supervisor confirms the <Term k="freeze">freeze</Term> and files a <Term k="1930">1930</Term> report.
        </>
      ),
      detector: 'Auto-hold policy',
    },
  ]

  const on = (n: number) => step === null || step === n
  return (
    <section id="how-it-works" className="scroll-mt-20 grid gap-4">
      <SectionTitle icon={BookOpen} eyebrow="The 5-minute scam" title="How a mule chain moves money, and where we catch it">
        Hover a step to see where it happens. This is an illustration of the pattern; every number elsewhere on the page comes from the engine.
      </SectionTitle>
      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <div className="relative overflow-hidden rounded-xl border bg-card p-3 shadow-card">
          <svg viewBox="0 0 780 260" className="h-auto w-full" role="img" aria-label="Two victims pay one first-layer mule, who forwards to three second-layer mules, who cash out.">
            <defs>
              <linearGradient id="mule" x1="0" x2="1">
                <stop offset="0" stopColor="var(--sev-critical)" stopOpacity="0.9" />
                <stop offset="1" stopColor="var(--sev-high)" stopOpacity="0.9" />
              </linearGradient>
            </defs>
            {/* stage bands */}
            {[
              { x: 20, w: 140, label: 'Victims' },
              { x: 230, w: 140, label: 'First-layer mule' },
              { x: 450, w: 140, label: 'Second-layer mules' },
              { x: 640, w: 120, label: 'Cash-out' },
            ].map(b => (
              <g key={b.label}>
                <rect x={b.x} y={14} width={b.w} height={232} rx={12} fill="var(--muted)" opacity={0.55} />
                <text x={b.x + b.w / 2} y={238} textAnchor="middle" className="fill-muted-foreground" fontSize={12}>
                  {b.label}
                </text>
              </g>
            ))}
            {/* edges */}
            {[...inEdges.map(d => ({ d, n: 1 })), ...midEdges.map(d => ({ d, n: 2 })), ...outEdges.map(d => ({ d, n: 3 }))].map((e, i) => (
              <path
                key={i}
                d={e.d}
                fill="none"
                stroke={e.n === 1 ? 'var(--brand-2)' : 'var(--sev-high)'}
                strokeWidth={e.n === 1 ? 3 : 2}
                strokeLinecap="round"
                opacity={on(e.n) || (step === 4 && e.n > 1) ? (step === 4 && e.n > 1 ? 0.25 : 0.85) : 0.18}
                className={reduced || (step === 4 && e.n > 1) ? undefined : 'flow'}
              />
            ))}
            {/* money packets */}
            {!reduced && step !== 4 &&
              [...inEdges, ...midEdges, ...outEdges].map((d, i) => (
                <circle key={i} r={4.5} fill={i < 2 ? 'var(--brand-2)' : 'var(--sev-high)'} stroke="var(--card)" strokeWidth={1.5}>
                  <animateMotion dur="2.6s" repeatCount="indefinite" path={d} begin={`${(i < 2 ? 0 : i < 5 ? 1.2 : 2.2) + (i % 3) * 0.25}s`} />
                </circle>
              ))}
            {/* nodes */}
            {V.map(v => (
              <g key={v.id}>
                <circle cx={v.x} cy={v.y} r={20} fill="var(--card)" stroke="var(--brand-2)" strokeWidth={2} />
                <text x={v.x} y={v.y + 4} textAnchor="middle" fontSize={13} className="fill-brand-1" fontWeight={600}>
                  ₹
                </text>
              </g>
            ))}
            <g>
              {step === 4 && <circle cx={L1.x} cy={L1.y} r={40} fill="none" stroke="var(--ok)" strokeWidth={3} strokeDasharray="4 4" />}
              <circle cx={L1.x} cy={L1.y} r={28} fill="url(#mule)" />
              <text x={L1.x} y={L1.y + 5} textAnchor="middle" fontSize={13} fill="#fff" fontWeight={600}>
                L1
              </text>
            </g>
            {L2.map((n, i) => (
              <g key={i}>
                <circle cx={n.x} cy={n.y} r={18} fill="url(#mule)" opacity={step === 4 ? 0.35 : 0.85} />
                <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={11} fill="#fff" fontWeight={600}>
                  L2
                </text>
              </g>
            ))}
            <g opacity={step === 4 ? 0.35 : 1}>
              <rect x={OUT.x - 26} y={OUT.y - 18} width={52} height={36} rx={8} fill="var(--card)" stroke="var(--muted-foreground)" strokeWidth={1.5} />
              <text x={OUT.x} y={OUT.y + 4} textAnchor="middle" fontSize={11} className="fill-muted-foreground">
                ATM
              </text>
            </g>
            {/* detector markers */}
            {[
              { n: 1, x: 190, y: 104 },
              { n: 2, x: 340, y: 86 },
              { n: 3, x: 420, y: 72 },
              { n: 4, x: 300, y: 184 },
            ].map(d => (
              <g key={d.n} opacity={on(d.n) ? 1 : 0.3}>
                <circle cx={d.x} cy={d.y} r={11} fill={d.n === 4 ? 'var(--ok)' : 'var(--brand-1)'} stroke="var(--card)" strokeWidth={2} />
                <text x={d.x} y={d.y + 4} textAnchor="middle" fontSize={11} fill="#fff" fontWeight={600}>
                  {d.n}
                </text>
              </g>
            ))}
          </svg>
          <p className="px-2 pb-1 text-[11.5px] text-muted-foreground">Dots are money moving. Numbered markers are where each detector fires.</p>
        </div>
        <ol className="grid gap-2">
          {STEPS.map((s, i) => (
            <li
              key={s.n}
              onMouseEnter={() => setStep(s.n)}
              onMouseLeave={() => setStep(null)}
              onFocus={() => setStep(s.n)}
              onBlur={() => setStep(null)}
              tabIndex={0}
              className={cn(
                'enter lift grid cursor-default grid-cols-[32px_1fr] gap-3 rounded-lg border bg-card p-3 shadow-card outline-none',
                step === s.n && 'border-brand-2/40 bg-brand-soft/40',
              )}
              style={{ '--i': i } as React.CSSProperties}
            >
              <span className={cn('grid size-8 place-items-center rounded-full text-white', s.n === 4 ? 'bg-ok' : 'bg-brand-1')}>
                <s.icon className="size-4" />
              </span>
              <div>
                <p className="flex flex-wrap items-center gap-x-2 text-[13.5px] font-medium">
                  {s.n}. {s.title}
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-normal text-muted-foreground">{s.detector}</span>
                </p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------- proof points

export function ProofPoints() {
  const ev = useEvaluation()
  const cards = ev
    ? [
        {
          icon: ShieldAlert,
          tone: 'text-brand-2 bg-brand-soft',
          value: pct(ev.detectors.accountLevel.recall),
          label: 'of mules caught by rules alone',
          sub: `at ${pct(ev.detectors.accountLevel.precision)} precision`,
          term: 'recall' as TermKey,
        },
        {
          icon: Network,
          tone: 'text-brand-3 bg-teal-soft',
          value: pct(ev.detectors.combined.recall),
          label: 'caught with the GNN\'s leads added',
          sub: `precision holds at ${pct(ev.detectors.combined.precision)}`,
          term: 'gnn' as TermKey,
        },
        {
          icon: Hourglass,
          tone: 'text-sev-medium bg-sev-medium-bg',
          value: duration(ev.detectors.medianLeadSec),
          label: 'median warning before money moves',
          sub: 'the window to freeze',
          term: 'lead time' as TermKey,
        },
        ev.autoHold && {
          icon: ShieldCheck,
          tone: 'text-ok bg-ok-bg',
          value: inrShort(ev.autoHold.fraudBlocked),
          label: 'blocked by auto-hold alone',
          sub: `${ev.autoHold.mulesHeld} of ${ev.autoHold.accountsHeld} held are mules · ${inr(ev.autoHold.genuineBlocked)} genuine`,
          term: 'hold' as TermKey,
        },
      ].filter(Boolean)
    : []
  return (
    <section className="grid gap-4">
      <SectionTitle icon={FlaskConical} eyebrow="Measured, not claimed" title="What the engine achieves on the full dataset">
        The bridge replays all {ev ? ev.dataset.rows.toLocaleString('en-IN') : '30,353'} transactions at start-up with nobody acting and scores the detectors against the
        labels. Details on the <Link href="/model" className="text-brand-2 underline underline-offset-2">model page</Link>.
      </SectionTitle>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {!ev
          ? [0, 1, 2, 3].map(i => <div key={i} className="h-[124px] animate-pulse rounded-lg border bg-card" />)
          : cards.map((c, i) =>
              c ? (
                <div key={c.label} className="enter lift rounded-lg border bg-card p-4 shadow-card" style={{ '--i': i } as React.CSSProperties}>
                  <span className={cn('grid size-8 place-items-center rounded-md', c.tone)}>
                    <c.icon className="size-4" />
                  </span>
                  <p className="figure mt-3 text-[30px] font-semibold leading-none">{c.value}</p>
                  <p className="mt-1.5 text-[13px]">
                    <Term k={c.term}>{c.label}</Term>
                  </p>
                  <p className="mt-0.5 text-[12px] text-muted-foreground">{c.sub}</p>
                </div>
              ) : null,
            )}
      </div>
      {ev && (
        <p className="text-[12px] text-muted-foreground">
          Caveat: the data is synthetic and easy to separate (victims' transfers are ₹5–5.5 lakh, clean ones stay under ₹2 lakh), so these are pipeline numbers, not a
          claim about real traffic.
        </p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------- detectors

const DETECTOR_CARDS: { id: Detector; icon: typeof Zap; stage: string; pattern: string; rule: string; tone: string }[] = [
  { id: 'high_value_new_payee', icon: Zap, stage: 'Stage 1', pattern: 'Victims pushed into large transfers', rule: '₹4.5 lakh or more, from a payer who has never paid this account, from another state.', tone: 'text-brand-2' },
  { id: 'pass_through', icon: GitFork, stage: 'Stage 2', pattern: 'First-layer mules forwarding money', rule: 'Within 60 minutes, ₹2 lakh or more comes in and at least 60% of it leaves in two or more transfers.', tone: 'text-sev-high' },
  { id: 'hop_from_flagged', icon: Network, stage: 'Stage 3', pattern: 'The next hop in the chain', rule: 'Money received from an account a rule flagged in the last 24 hours, or a frozen one. One hop only.', tone: 'text-sev-medium' },
  { id: 'model_only', icon: ScanEye, stage: 'Anywhere', pattern: 'Structure the rules miss', rule: 'The GNN scores an inbound transfer 0.9 or higher and no rule has fired. A lead to check, not a finding.', tone: 'text-brand-3' },
]

export function DetectorCards() {
  const alerts = useRail(s => s.alerts)
  const live = useRail(s => s.backend === 'live')
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const a of Object.values(alerts)) if (a.status !== 'superseded') c[a.detector] = (c[a.detector] ?? 0) + 1
    return c
  }, [alerts])
  return (
    <section className="grid gap-4">
      <SectionTitle icon={ShieldAlert} eyebrow="Four detectors" title="What fires an alert">
        Rules see only what a payment processor sees: amount, time, who paid whom, and their states. They never read the fraud labels.
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {DETECTOR_CARDS.map((d, i) => (
          <div key={d.id} className={cn('enter flex flex-col rounded-lg border bg-card p-4 shadow-card', d.tone)} style={{ '--i': i } as React.CSSProperties}>
            <div className="flex items-center justify-between">
              <span className="grid size-8 place-items-center rounded-md border bg-muted/60">
                <d.icon className="size-4" />
              </span>
              <span className="text-[11px] font-medium uppercase tracking-wide opacity-80">{d.stage}</span>
            </div>
            <p className="mt-3 text-[14px] font-semibold text-foreground">{d.pattern}</p>
            <p className="mt-1 flex-1 text-[12.5px] leading-relaxed text-muted-foreground">{d.rule}</p>
            <div className="mt-3 flex items-baseline justify-between border-t pt-2 text-[12px] text-muted-foreground">
              <span>alerts this run</span>
              <span className="figure text-[18px] font-semibold text-foreground">{live ? (counts[d.id] ?? 0) : '—'}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------- what is real

export function RealityGrid({ items }: { items: { part: string; state: string; note: string }[] }) {
  const style = (state: string) =>
    state === 'Working'
      ? { icon: CheckCircle2, cls: 'bg-ok-bg text-ok' }
      : state === 'Sandboxed'
        ? { icon: FlaskConical, cls: 'bg-sev-medium-bg text-sev-medium' }
        : { icon: CircleDashed, cls: 'bg-muted text-muted-foreground' }
  return (
    <section className="grid gap-4">
      <SectionTitle icon={CheckCircle2} eyebrow="No smoke and mirrors" title="What is real, what is sandboxed, what is not built">
        Every alert, score and number comes from the Python backend. Nothing is generated in the browser.
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((s, i) => {
          const st = style(s.state)
          return (
            <div key={s.part} className="enter rounded-lg border bg-card p-3.5 shadow-card" style={{ '--i': i } as React.CSSProperties}>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[13.5px] font-medium">{s.part}</p>
                <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium', st.cls)}>
                  <st.icon className="size-3.5" />
                  {s.state}
                </span>
              </div>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">{s.note}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------- glossary

const GLOSSARY_SHOWN: TermKey[] = ['mule', 'l1 mule', 'l2 mule', 'layering', 'vpa', 'gnn', 'lead time', 'precision', 'recall', 'hold', 'freeze', '1930', 'evidence pack', 'audit trail']

export function GlossaryGrid() {
  const [q, setQ] = useState('')
  const shown = GLOSSARY_SHOWN.filter(k => !q || k.includes(q.toLowerCase()) || GLOSSARY[k].toLowerCase().includes(q.toLowerCase()))
  return (
    <section className="grid gap-4">
      <SectionTitle
        icon={BookOpen}
        eyebrow="Terms in 30 seconds"
        title="The vocabulary"
        right={
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search terms"
            className="h-8 w-44 rounded-md border bg-card px-2.5 text-[12.5px] shadow-card outline-none focus:border-brand-2"
          />
        }
      >
        These words have a dotted underline wherever they appear; hover one for its meaning.
      </SectionTitle>
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map(k => (
          <div key={k} className="rounded-lg border bg-card p-3 shadow-card">
            <dt className="text-[13px] font-semibold capitalize text-brand-1">{k === 'vpa' || k === 'gnn' ? k.toUpperCase() : k}</dt>
            <dd className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{GLOSSARY[k]}</dd>
          </div>
        ))}
        {shown.length === 0 && <p className="text-[13px] text-muted-foreground">No term matches “{q}”.</p>}
      </dl>
    </section>
  )
}

// ---------------------------------------------------------------------------- shared

export function SectionTitle({ icon: Icon, eyebrow, title, children, right }: { icon: typeof Zap; eyebrow: string; title: string; children?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          <Icon className="size-3.5" /> {eyebrow}
        </p>
        <h2 className="mt-1 text-[19px] font-semibold tracking-tight">{title}</h2>
        {children && <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted-foreground">{children}</p>}
      </div>
      {right}
    </div>
  )
}

// ---------------------------------------------------------------------------- the page

const STATUS = [
  { part: 'Transactions', state: 'Working', note: 'CSV replay by default (synthetic, not a bank feed). RAIL_SOURCE=webhook | kafka | kinesis switches to a live stream; payments are scored online as they arrive.' },
  { part: 'GNN score on every row', state: 'Working', note: 'Trained GIN checkpoint, one full-graph pass at bridge start-up (about 30 s on CPU).' },
  { part: 'Detectors, queue, lead time', state: 'Working', note: 'Multi-GNN/rail_engine.py. Detectors never read the fraud labels.' },
  { part: 'Precision and recall', state: 'Working', note: 'Measured against nolambur_labels.csv, live in the console and for the full dataset on the model page.' },
  { part: 'Agent investigation', state: 'Working', note: 'score_transfer_chain calls /predict live; the NPCI registry lookup is an HTTP call to a sandbox mock whose answer comes from the label.' },
  { part: 'Automatic hold', state: 'Working', note: 'A critical alert the model scores 0.9+ holds the account at once; its transfers are blocked until a supervisor confirms or releases.' },
  { part: 'Freeze, 1930 report, SMS', state: 'Sandboxed', note: 'Real signed HTTP through a retrying outbox, to sandbox REST mocks of the bank gateway and 1930 portal. No real bank or CFCFRMS. SMS is real with Twilio keys.' },
  { part: 'Roles and audit', state: 'Working', note: 'Analyst / supervisor / admin enforced by the bridge. Audit trail in SQLite or Postgres, append-only and hash-chained; /platform verifies it.' },
  { part: 'Director / MCA linkage', state: 'Not built', note: 'The dataset has no company or director data. The onboarding check uses transaction links instead.' },
]

const JOURNEY = [
  { icon: ScanSearch, title: 'Onboarding', href: '/onboarding', body: "Check a new merchant's settlement VPAs against the transaction graph before it goes live." },
  { icon: ListChecks, title: 'Live monitoring', href: '/console', body: 'Every payment is scored as it arrives. Analysts clear, escalate or freeze, and write down why.' },
  { icon: Briefcase, title: 'Incident response', href: '/cases', body: 'Linked accounts group into cases, with an evidence pack and a 1930 report.' },
]

export function OverviewPage() {
  return (
    <div className="grid gap-12">
      <Hero />

      <section className="grid gap-4">
        <SectionTitle
          icon={Activity}
          eyebrow="Running now"
          title="The engine, live"
          right={
            <Link href="/console" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-2 hover:underline">
              Go to the queue <ArrowRight className="size-3.5" />
            </Link>
          }
        >
          Hover the (i) on any tile for what it measures.
        </SectionTitle>
        <BackendGate>
          <MetricStrip />
        </BackendGate>
      </section>

      <MuleChainExplainer />

      <ProofPoints />

      <DetectorCards />

      <section className="grid gap-4">
        <SectionTitle icon={ArrowRight} eyebrow="Where to go next" title="Three jobs, three screens" />
        <div className="grid gap-3 md:grid-cols-3">
          {JOURNEY.map((j, i) => (
            <Link key={j.href} href={j.href} className="enter lift group flex gap-3 rounded-lg border bg-card p-4 shadow-card" style={{ '--i': i } as React.CSSProperties}>
              <span className="grid size-9 shrink-0 place-items-center rounded-md bg-brand-1 text-white">
                <j.icon className="size-4" />
              </span>
              <span>
                <span className="flex items-center gap-1 font-medium">
                  {i + 1}. {j.title} <ArrowRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                </span>
                <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted-foreground">{j.body}</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <RealityGrid items={STATUS} />

      <GlossaryGrid />

      <footer className="border-t pt-4 text-[12px] text-muted-foreground">
        Run it: <code className="font-mono">cd Multi-GNN && python bridge_api.py</code>, then <code className="font-mono">npm run dev</code>. All accounts and
        transactions come from the synthetic Nolambur dataset.
      </footer>
    </div>
  )
}
