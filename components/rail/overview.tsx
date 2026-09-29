'use client'

import { Activity, ArrowRight, BookOpen, Briefcase, ListChecks, ScanSearch, CheckCircle2, CircleDashed, FlaskConical, History, Layers, Scale, Users, GitFork, Hourglass, Network, ScanEye, ShieldAlert, ShieldCheck, Zap } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { clock, duration, inr, inrShort, pct } from '@/lib/rail/format'
import { capturedLabel } from '@/lib/rail/snapshot'
import { useDisplayMetrics, useRail } from '@/lib/rail/store'
import type { Detector } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { BackendGate, useWaitSeconds } from './BackendGate'
import { GLOSSARY, Term, useCountUp, type TermKey } from './kit'
import { MetricStrip } from './MetricStrip'

/** The parts of /rail/evaluation (rail_engine.evaluate_temporal: test days only) this page shows. */
type Evaluation = {
  evaluation: 'temporal'
  detectors: {
    accountLevel: { precision: number; recall: number; tp: number }
    combined: { precision: number; recall: number; tp: number }
    mulesActive: number
    precisionAtK: { k: number; precision: number }[]
    alertsPerAnalystPerDay: number
    analysts: number
    leadSeconds: { median: number | null; p10: number | null; n: number; alertedBeforeMoneyLeft: number }
  }
  policy: { fraudTotal: number; fraudStopped: number; innocentRestricted: number; innocentRestrictionHours: number; restrictedMules: number; restrictedAccounts: number }
  test: { edges: number; positives: number }
  dataset: { rows: number; accounts: number; fraudRows: number }
}

/**
 * /rail/evaluation from the running bridge once it answers; until then the pre-run's copy, which
 * is in the page from the first render. Both come from the same full replay with nobody acting.
 */
export function useEvaluationState() {
  const backend = useRail(s => s.backend)
  const snapshot = useRail(s => s.snapshot)
  const [live, setLive] = useState<Evaluation | null>(null)
  useEffect(() => {
    if (live || backend !== 'live') return
    fetch('/api/rail/evaluation', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(setLive)
      .catch(() => {})
  }, [backend, live])
  const saved = snapshot?.evaluation as Evaluation | undefined
  const pre = saved?.evaluation === 'temporal' ? saved : null // an older (v1) snapshot has a different shape
  return { ev: live ?? pre, live: !!live, capturedAt: snapshot?.capturedAt ?? null }
}

export function useEvaluation() {
  return useEvaluationState().ev
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
          <p className="mt-3 flex max-w-xl items-start gap-2 rounded-md bg-white/[0.08] px-3 py-2 text-[13.5px] leading-snug text-white/90">
            <Users className="mt-0.5 size-4 shrink-0 text-white/70" />
            <span>
              <b className="font-semibold">Built for fraud-operations analysts at a payment aggregator:</b>{' '}the people who decide, within minutes, whether to stop
              an account&apos;s money.
            </span>
          </p>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
            In a scam, the victim&apos;s money lands in a stranger&apos;s account and is passed on within minutes. This console checks every UPI payment as it
            arrives, and raises the alarm while the money is still in that first account.
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
  const { metrics: m, stale, capturedAt } = useDisplayMetrics()
  const backend = useRail(s => s.backend)
  const paused = useRail(s => s.paused)
  const seconds = useWaitSeconds()
  const blocked = useCountUp(m?.blockedFraudAmount ?? 0, 900)

  if (!m) {
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
        {stale ? (
          <span className="flex items-center gap-2" title={`Captured ${capturedAt}`}>
            <CircleDashed className="size-3.5 animate-spin text-[#f5c26b]" />
            Snapshot · {backend === 'warming' ? 'bridge warming up' : `waking bridge (${seconds}s)`}
          </span>
        ) : (
          <span className="flex items-center gap-2">
            <span className="size-1.5 rounded-full bg-[#6fd49a]" />
            {m.rowsTotal === null ? `Live stream · ${m.source}` : paused ? 'Replay paused' : m.done ? 'Replay finished' : `Replaying at ${m.speed}×`}
          </span>
        )}
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
          Someone is talked into paying (a fake investment, a &ldquo;digital arrest&rdquo;). UPI caps a transfer at ₹1 lakh, so the money goes in several transfers,
          often just under the cap and over more than one day, to an account they have never paid. That account is the first-layer <Term k="mule">mule</Term>.
        </>
      ),
      detector: 'Inflow burst from new payers · Structuring',
    },
    {
      n: 2,
      icon: GitFork,
      title: 'The mule forwards it fast',
      body: (
        <>
          Within minutes or hours most of it leaves again, split across several accounts. That is <Term k="pass-through">pass-through</Term>, and the gap between
          the alert and the money leaving is the <Term k="lead time">lead time</Term>
          {ev?.detectors.leadSeconds.median != null ? `: ${duration(ev.detectors.leadSeconds.median)} on the test days (median).` : '.'}
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
          The response is graded: a high alert delays the account&apos;s settlements, a critical one holds its outgoing transfers, and a critical one the{' '}
          <Term k="gnn">GNN</Term> backs with a second detector is a full <Term k="hold">hold</Term>. Every restriction lifts itself after a time limit unless a
          supervisor confirms the <Term k="freeze">freeze</Term>, and the account holder can appeal.
        </>
      ),
      detector: 'Decision router',
    },
  ]

  const on = (n: number) => step === null || step === n
  return (
    <section id="how-it-works" className="scroll-mt-20 grid gap-4">
      <SectionTitle icon={BookOpen} eyebrow="The scam, step by step" title="How a mule chain moves money, and where we catch it">
        Hover or tap a step to see where it happens. This is an illustration of the pattern; every number elsewhere on the page comes from the engine.
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
  const { ev, live, capturedAt } = useEvaluationState()
  const p10 = ev?.detectors.precisionAtK.find(p => p.k === 10)
  const cards = ev
    ? [
        {
          icon: Network,
          tone: 'text-brand-3 bg-teal-soft',
          value: pct(ev.detectors.combined.recall),
          label: 'of active mules caught, rules + GNN',
          sub: `${pct(ev.detectors.combined.precision)} precision · rules alone ${pct(ev.detectors.accountLevel.recall)}`,
          term: 'recall' as TermKey,
        },
        {
          icon: ShieldAlert,
          tone: 'text-brand-2 bg-brand-soft',
          value: p10 ? pct(p10.precision) : '—',
          label: 'of the first 10 queue alerts are mules',
          sub: `${ev.detectors.alertsPerAnalystPerDay.toFixed(1)} alerts per analyst a day, team of ${ev.detectors.analysts}`,
          term: 'precision' as TermKey,
        },
        {
          icon: Hourglass,
          tone: 'text-sev-medium bg-sev-medium-bg',
          value: duration(ev.detectors.leadSeconds.median),
          label: 'median warning before money moves',
          sub: `${ev.detectors.leadSeconds.alertedBeforeMoneyLeft} of ${ev.detectors.leadSeconds.n} alerted before any left`,
          term: 'lead time' as TermKey,
        },
        {
          icon: ShieldCheck,
          tone: 'text-ok bg-ok-bg',
          value: inrShort(ev.policy.fraudStopped),
          label: 'of fraud stopped by graded holds alone',
          sub: `${pct(ev.policy.fraudTotal ? ev.policy.fraudStopped / ev.policy.fraudTotal : null)} of ${inrShort(ev.policy.fraudTotal)} · ${ev.policy.innocentRestricted} innocent accounts restricted`,
          term: 'hold' as TermKey,
        },
      ]
    : []
  return (
    <section className="grid gap-4">
      <SectionTitle
        icon={FlaskConical}
        eyebrow="Measured, not claimed"
        title="What the engine achieves on days the model never saw"
        right={
          ev && (
            <span
              className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px]', live ? 'border-ok/30 bg-ok-bg text-ok' : 'bg-card text-muted-foreground')}
              title="The bridge computes these at start-up by replaying every row with nobody acting. The pre-run is the same computation, saved."
            >
              {live ? <CheckCircle2 className="size-3.5" /> : <History className="size-3.5" />}
              {live ? 'Live: computed by the running bridge' : capturedAt ? `Pre-run, captured ${capturedLabel(capturedAt)}` : 'Pre-run'}
            </span>
          )
        }
      >
        The model trains on days 0–5 of {ev ? ev.dataset.rows.toLocaleString('en-IN') : 'the'} payments, picks its threshold on days 6–7, and these are days 8–9 only,
        scored as they would be live: each payment sees only what came before it. Read them with the note on the data just below. Details and confidence intervals on
        the <Link href="/model" className="text-brand-2 underline underline-offset-2">model page</Link>.
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

    </section>
  )
}

// ---------------------------------------------------------------------------- detectors

const DETECTOR_CARDS: { id: Detector; icon: typeof Zap; stage: string; pattern: string; rule: string; tone: string }[] = [
  { id: 'inflow_new_payers', icon: Zap, stage: 'Stage 1', pattern: 'Victims paying a stranger', rule: 'Money from first-time payers summed over 24 h (and 72 h), above ₹1.5 lakh or 3× the account’s own busiest recent day.', tone: 'text-brand-2' },
  { id: 'structuring', icon: Layers, stage: 'Stage 1', pattern: 'Split under the UPI cap', rule: 'Three or more transfers in 24 h near the ₹1 lakh cap, or at just-under amounts like ₹49,999, from two or more payers.', tone: 'text-sev-critical' },
  { id: 'pass_through', icon: GitFork, stage: 'Stage 2', pattern: 'Mules forwarding money', rule: '₹1 lakh+ in and 60%+ of it out again within 1, 6 or 24 h. Shops that always forward alert only at 3× their usual scale.', tone: 'text-sev-high' },
  { id: 'hop_from_flagged', icon: Network, stage: 'Stage 3', pattern: 'The next hop in the chain', rule: 'Money received from an account a rule flagged in the last 24 hours, or a restricted one. One hop only.', tone: 'text-sev-medium' },
  { id: 'model_only', icon: ScanEye, stage: 'Anywhere', pattern: 'Structure the rules miss', rule: 'The GNN scores an inbound transfer above the threshold picked on the validation days and no rule has fired. A lead, not a finding.', tone: 'text-brand-3' },
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
      <SectionTitle icon={ShieldAlert} eyebrow="Five detectors · rules r2.0" title="What fires an alert">
        Rules see only what a payment processor sees: amount, time, channel, who paid whom, and each account&apos;s own history. They sum over windows, because UPI
        caps a transfer at ₹1 lakh, and they never read the fraud labels.
      </SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
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
  { part: 'Transactions', state: 'Working', note: 'Live by default: payments arrive on the webhook, a Kafka topic or a Kinesis stream and are scored online. Offsets and checkpoints are committed only after the engine has processed a batch; bad messages go to a dead-letter table. Tested against a real Kafka broker and a Kinesis emulator, not production AWS. This public demo runs RAIL_SOURCE=replay over the synthetic dataset.' },
  { part: 'GNN score on every payment', state: 'Working', note: 'Each payment is scored on its own 2-hop subgraph, using only earlier payments (infra/scorer.py). Verified equal to a full-graph pass to 1e-20; a cached mode trades exactness for speed.' },
  { part: 'Detectors, queue, lead time', state: 'Working', note: 'Rules r2.0 sum over 1 h to 72 h windows with per-account baselines, because UPI caps a transfer at ₹1 lakh. Tests replay an adversary who splits and delays money, including what still slips through.' },
  { part: 'Precision and recall', state: 'Working', note: 'Train on days 0–5, threshold from days 6–7, report days 8–9 only, with 95% intervals, precision@k and alerts per analyst. Synthetic data: shadow mode on real flows is the test that is still missing.' },
  { part: 'Agent investigation', state: 'Working', note: 'Re-scores the alert\u2019s transfers on the current graph; the NPCI registry lookup is an HTTP call to a sandbox mock whose answer comes from the label.' },
  { part: 'Graded actions and appeals', state: 'Working', note: 'A router maps rule and model evidence to alert only, delay settlement, hold outbound or full hold. Every restriction lifts after a time limit unless confirmed; appeals are recorded and must be decided in 24 h.' },
  { part: 'Freeze, 1930 report, SMS', state: 'Sandboxed', note: 'Real signed HTTP through a retrying outbox, to sandbox REST mocks of the bank gateway and 1930 portal. No real bank or CFCFRMS. SMS is real with Twilio keys.' },
  { part: 'Roles and audit', state: 'Working', note: 'Analyst / supervisor / admin enforced by the bridge. Append-only, hash-chained audit trail, verified on a real Postgres 16 with concurrent writers; /platform warns when it sits on an ephemeral disk.' },
  { part: 'Director / MCA linkage', state: 'Working, no data loaded', note: 'Onboarding takes a CIN and checks directors (disqualified, over the s.165 limit), common-control groups, registered-address farms and linked companies\u2019 flagged settlement VPAs. Loads real MCA / data.gov.in files or a vendor API; the demo ships with an empty registry.' },
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
          Hover or tap the (i) on any tile for what it measures.
        </SectionTitle>
        <BackendGate allowSnapshot>
          <MetricStrip />
        </BackendGate>
      </section>

      <MuleChainExplainer />

      <ProofPoints />

      <DataHonesty />

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

// ---------------------------------------------------------------- how the data was made

/**
 * The skeptic's question, answered before it is asked. Generator facts are from
 * Multi-GNN/nolambur_v2_gen.py (seed 7); counts come from the evaluation.
 */
export function DataHonesty() {
  const ev = useEvaluation()
  const fraudRows = ev?.dataset.fraudRows ?? 419
  const rows = ev?.dataset.rows ?? 83067
  const checks: { ok: boolean; title: string; body: React.ReactNode }[] = [
    {
      ok: true,
      title: 'Trained on the past, tested on the future',
      body: (
        <>
          The GIN learns from days 0–5, its alert threshold is picked on days 6–7, and every headline number is from days 8–9: two scam campaigns it never saw. The
          earlier dataset could not do this (all its fraud fell in one five-minute window), which is why it was replaced.
        </>
      ),
    },
    {
      ok: true,
      title: 'Scored the way production would score',
      body: (
        <>
          Each payment is scored on its own 2-hop neighbourhood using only payments that came before it. The model&apos;s inputs are time of day, amount and channel:
          no absolute timestamps to memorise an attack by, no states, no labels.
        </>
      ),
    },
    {
      ok: false,
      title: 'Still synthetic, and still easier than real traffic',
      body: (
        <>
          Clean payments here are mostly small (median around ₹600) while scam transfers run ₹10,000–₹1 lakh, so amount still carries much of the signal. The rules
          were written by someone who knew how the generator works. Real precision will be lower; the test set is small (tens of mules), so the model page shows 95%
          intervals.
        </>
      ),
    },
    {
      ok: false,
      title: 'The registry lookup is an oracle',
      body: 'The mock NPCI registry answers from the label. It appears only in the investigation panel; no detector, hold or metric uses it.',
    },
  ]

  return (
    <section className="grid gap-4">
      <SectionTitle icon={Scale} eyebrow="Read this before the numbers" title="Where the data comes from, and what the numbers can and cannot claim">
        Every account and payment here is synthetic. This is exactly how it was made, and what that means for the figures above.
      </SectionTitle>
      <div className="grid gap-3 lg:grid-cols-[1fr_1.35fr]">
        <div className="rounded-lg border bg-card p-4 shadow-card">
          <p className="text-[13.5px] font-semibold">How the dataset was generated</p>
          <p className="text-[11.5px] text-muted-foreground">
            <code className="font-mono">Multi-GNN/nolambur_v2_gen.py</code>, fixed seed, modelled on &ldquo;digital arrest&rdquo; mule networks
          </p>
          <ol className="mt-3 grid gap-2.5 text-[13px] leading-relaxed">
            <li className="grid grid-cols-[22px_1fr] gap-2">
              <span className="grid size-5 place-items-center rounded-full bg-sev-critical-bg text-[11px] font-semibold text-sev-critical">1</span>
              <span>
                <b>Ten campaigns over ten days.</b> Victims, ordinary account holders with their own history, pay first-layer mules in transfers of at most{' '}
                <b>₹1 lakh</b> (the UPI P2P cap) and at most ₹1 lakh a day, often just under the cap.
              </span>
            </li>
            <li className="grid grid-cols-[22px_1fr] gap-2">
              <span className="grid size-5 place-items-center rounded-full bg-sev-critical-bg text-[11px] font-semibold text-sev-critical">2</span>
              <span>
                Mules forward 75–97% on to second-layer mules, some within minutes and a third of them after hours; some second-layer accounts reappear in later
                campaigns. Mules also shop and send small amounts like anyone else.
              </span>
            </li>
            <li className="grid grid-cols-[22px_1fr] gap-2">
              <span className="grid size-5 place-items-center rounded-full bg-muted text-[11px] font-semibold">3</span>
              <span>
                Clean traffic from 5,200 people, 220 merchants and 70 small businesses that pass most of their takings to suppliers the same day, on a daily rhythm, with
                rent and wages.
              </span>
            </li>
          </ol>
          <p className="mt-3 border-t pt-2 text-[12px] text-muted-foreground">
            {fraudRows} scam payments in {rows.toLocaleString('en-IN')} ({((fraudRows / rows) * 100).toFixed(2)}%).
          </p>
        </div>
        <ul className="grid gap-2">
          {checks.map(c => (
            <li key={c.title} className="grid grid-cols-[24px_1fr] gap-2 rounded-lg border bg-card p-3 shadow-card">
              {c.ok ? <CheckCircle2 className="mt-0.5 size-4 text-ok" /> : <ShieldAlert className="mt-0.5 size-4 text-sev-medium" />}
              <div>
                <p className="text-[13.5px] font-medium">{c.title}</p>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-lg border border-sev-medium/30 bg-sev-medium-bg/60 p-3.5 text-[13px] leading-relaxed">
        <b>The real test is shadow mode.</b> Run silently on one partner&apos;s anonymised flows, log what would have been flagged, and compare against the fraud
        reports that come in later. That is the only evidence about real traffic; nothing on this page is.
      </div>
    </section>
  )
}
