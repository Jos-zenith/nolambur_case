'use client'

import { Activity, ArrowRight, BookOpen, Briefcase, ChevronDown, ListChecks, ScanSearch, CheckCircle2, CircleDashed, FlaskConical, History, Layers, Scale, Send, Users, GitFork, Hourglass, Network, ScanEye, ShieldAlert, ShieldCheck, Zap } from 'lucide-react'
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
import { NetworkGraph } from './NetworkGraph'
import { ScamLab } from './ScamLab'

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
          <p className="flex items-center gap-1.5 text-[12px] font-medium uppercase tracking-[0.08em] text-white/65">
            <Users className="size-3.5" /> For fraud-operations analysts · UPI
          </p>
          <h1 className="mt-3 max-w-2xl text-[32px] font-semibold leading-[1.15] tracking-tight md:text-[40px]">Stop the campaign, not just the first payment.</h1>
          <p className="mt-3 max-w-xl text-[16px] leading-relaxed text-white/80">
            Every UPI payment is scored as it arrives by rules and a graph model. Graded holds and settlement delays stop a scam&apos;s later instalments and onward
            transfers. A mule that forwards within seconds usually moves the first transfer before anyone can act.
          </p>
          <div className="mt-7 flex flex-wrap gap-2.5">
            <Link
              href="/console"
              className="group inline-flex h-11 items-center gap-2 rounded-md bg-white px-5 text-[14.5px] font-semibold text-brand-1 shadow-[0_6px_20px_-6px_rgb(0_0_0/0.5)] hover:bg-white/90"
            >
              Open the alert queue <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a href="#test-scam" className="inline-flex h-11 items-center gap-2 rounded-md border border-white/35 bg-white/[0.06] px-4 text-[14px] font-medium text-white hover:bg-white/15">
              <Send className="size-4" /> Send a test scam
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
        <Mini label="Mules caught" value={`${m.mulesAlerted} of ${m.mulesSeen}`} />
        <Mini label="Median lead" value={duration(m.medianLeadSec)} />
      </div>
      <p className="mt-3 text-[11.5px] text-white/55">This replay so far. Held-out test figures are further down.</p>
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

// ---------------------------------------------------------------------------- proof points

/**
 * Ranges across every draw of the test campaigns, not one run: Multi-GNN/reports/README.md 3.3-3.4
 * (stress_v2.json, rules_r21.json). The "this run" figure under each comes from the live evaluation.
 */
export function ProofPoints() {
  const { ev, live, capturedAt } = useEvaluationState()
  const cards = ev
    ? [
        {
          icon: Network,
          tone: 'text-brand-3 bg-teal-soft',
          value: '58–77%',
          label: 'of active mules caught, rules r2.0 + GNN',
          sub: `Across three draws of the two test campaigns · this run ${pct(ev.detectors.combined.recall)}`,
          term: 'recall' as TermKey,
        },
        {
          icon: ShieldAlert,
          tone: 'text-brand-2 bg-brand-soft',
          value: '58–78%',
          label: 'of alerted accounts are mules (r2.0)',
          sub: `39–50% under r2.1, which raises recall on evasive rings · this run ${pct(ev.detectors.combined.precision)}`,
          term: 'precision' as TermKey,
        },
        {
          icon: Hourglass,
          tone: 'text-sev-medium bg-sev-medium-bg',
          value: '17 s – 4 h',
          label: 'median warning before a mule moves the money',
          sub: 'Hours with a human-paced mule; seconds when mules forward automatically, too fast for an analyst',
          term: 'lead time' as TermKey,
        },
        {
          icon: ShieldCheck,
          tone: 'text-ok bg-ok-bg',
          value: '11–19%',
          label: 'of fraud money stopped by graded holds alone',
          sub: `Later instalments and onward transfers, not the first payment · this run ${pct(ev.policy.fraudTotal ? ev.policy.fraudStopped / ev.policy.fraudTotal : null)}, ${ev.policy.innocentRestricted} innocent accounts restricted`,
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
        The model trains on days 0–5, picks its threshold on days 6–7, and these are days 8–9 only, scored as live: each payment sees only what came before it. The
        test days hold two campaigns, so each figure is a range over redraws of them. Method and intervals in{' '}
        <code className="font-mono text-[12.5px]">Multi-GNN/reports/README.md</code> and on the{' '}
        <Link href="/model" className="text-brand-2 underline underline-offset-2">model page</Link>.
      </SectionTitle>
      <p className="-mt-1 flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-[12.5px] leading-relaxed text-muted-foreground">
        <Scale className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <b className="font-medium text-foreground">Why &ldquo;this run&rdquo; differs from the live figures above:</b> same definitions, different days. The live strip
          covers every day replayed so far, including the six the model trained on; these cover only the two it never saw. Quote the ranges.
        </span>
      </p>
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
      <div className="rounded-lg border border-sev-medium/30 bg-sev-medium-bg/60 p-3.5 text-[13px] leading-relaxed">
        <p className="font-semibold">Scope: what these figures do not cover</p>
        <ul className="mt-1.5 grid list-disc gap-1 pl-5 text-[12.5px]">
          <li>Synthetic data, with scenarios and rules written by the same person. Shadow mode on a partner&apos;s real flows is the test that is still missing.</li>
          <li>
            At real UPI fraud rates (about 500× rarer than here) most alerts would be false: roughly 50–400 false accounts per real mule under r2.0. Restrictions
            should need rules and model to agree, or an outside signal.
          </li>
          <li>
            Rings that split money into ₹2,000–5,000 payments get past r2.0 (holds stop nothing). Below about ₹2,500 a payment, no rules version and no model,
            even retrained, detects the ring.
          </li>
          <li>
            A payment aggregator does not see a mule&apos;s onward transfers at other banks. The chain view above assumes data an aggregator lacks; the part that
            fits an aggregator is the merchant-side rules and onboarding checks below.
          </li>
        </ul>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------- aggregator side

/**
 * Multi-GNN/reports/README.md 3.5 (reports/p2m/*.json): rules p1.0 on the aggregator's own view,
 * judged on fresh draws. Offline replay; not wired into the live console yet.
 */
const P2M_CARDS: { icon: typeof Zap; value: string; label: string; sub: string }[] = [
  {
    icon: ShieldCheck,
    value: '8 of 8',
    label: 'fresh fraud merchants flagged before their first settlement payout',
    sub: '95% interval 68–100%. Three fresh draws of 2–4 merchants each: a very small sample',
  },
  {
    icon: ShieldAlert,
    value: '8 of 8',
    label: 'settlement holds were on fraud merchants',
    sub: '95% interval 68–100%; 4 of 4 in a single draw is 51–100%',
  },
  {
    icon: Hourglass,
    value: '63–68%',
    label: 'of fraud money held at a settlement batch',
    sub: 'The window an analyst had to act. With nobody acting, a hold lifts and the money settles later',
  },
  {
    icon: Briefcase,
    value: 'All rings',
    label: 'shared settlement accounts caught at onboarding',
    sub: 'Also every legitimate family business sharing an account: a review, not a hold. Real cost unknown until partner data',
  },
]

export function AggregatorSide() {
  return (
    <section className="grid gap-4">
      <SectionTitle icon={Briefcase} eyebrow="The aggregator's own view · rules p1.0" title="Merchant-side fraud: fake merchants, collect scams, settlement rings">
        What a payment aggregator actually sees: payments into its merchants, their collect requests and outcomes, its settlement batches and its onboarding
        records. The lever is the settlement payout. Measured on synthetic merchants, with parameters fixed from training days before any result. The{' '}
        <Link href="/merchants" className="text-brand-2 underline underline-offset-2">Merchants page</Link> shows the replay, merchant by merchant.
      </SectionTitle>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {P2M_CARDS.map((c, i) => (
          <div key={c.label} className="enter rounded-lg border bg-card p-4 shadow-card" style={{ '--i': i } as React.CSSProperties}>
            <span className="grid size-8 place-items-center rounded-md bg-brand-soft text-brand-2">
              <c.icon className="size-4" />
            </span>
            <p className="figure mt-3 text-[26px] font-semibold leading-none">{c.value}</p>
            <p className="mt-1.5 text-[13px]">{c.label}</p>
            <p className="mt-0.5 text-[12px] text-muted-foreground">{c.sub}</p>
          </div>
        ))}
      </div>
      <p className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-[12.5px] leading-relaxed text-muted-foreground">
        <Scale className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <b className="font-medium text-foreground">Easy by construction, and costs are floors.</b> Victim payments of ₹10,000+ into shops whose usual top ticket is
          ₹1,200–7,300 are what the rules look for. A fake electronics merchant escapes once its payments halve. The 0.5 false holds per 1,000 merchants a day
          come from a generator&apos;s tidy merchants; real ones will cost more.
        </span>
      </p>
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

export function RealityGrid({ items, bare }: { items: { part: string; state: string; note: string }[]; bare?: boolean }) {
  const style = (state: string) =>
    state === 'Working'
      ? { icon: CheckCircle2, cls: 'bg-ok-bg text-ok' }
      : state === 'Sandboxed'
        ? { icon: FlaskConical, cls: 'bg-sev-medium-bg text-sev-medium' }
        : { icon: CircleDashed, cls: 'bg-muted text-muted-foreground' }
  return (
    <section className="grid gap-4">
      {bare ? (
        <p className="text-[13px] text-muted-foreground">Every alert, score and number comes from the Python backend. Nothing is generated in the browser.</p>
      ) : (
        <SectionTitle icon={CheckCircle2} eyebrow="No smoke and mirrors" title="What is real, what is sandboxed, what is not built">
          Every alert, score and number comes from the Python backend. Nothing is generated in the browser.
        </SectionTitle>
      )}
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

export function GlossaryGrid({ bare }: { bare?: boolean }) {
  const [q, setQ] = useState('')
  const shown = GLOSSARY_SHOWN.filter(k => !q || k.includes(q.toLowerCase()) || GLOSSARY[k].toLowerCase().includes(q.toLowerCase()))
  const search = (
    <input
      value={q}
      onChange={e => setQ(e.target.value)}
      placeholder="Search terms"
      className="h-8 w-44 rounded-md border bg-card px-2.5 text-[12.5px] shadow-card outline-none focus:border-brand-2"
    />
  )
  return (
    <section className="grid gap-4">
      {bare ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted-foreground">
          These words have a dotted underline wherever they appear; hover one for its meaning.
          {search}
        </div>
      ) : (
        <SectionTitle icon={BookOpen} eyebrow="Terms in 30 seconds" title="The vocabulary" right={search}>
          These words have a dotted underline wherever they appear; hover one for its meaning.
        </SectionTitle>
      )}
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
        <p className="flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-brand-2">
          <Icon className="size-3.5" /> {eyebrow}
        </p>
        <h2 className="mt-1 text-[22px] font-semibold leading-tight tracking-tight">{title}</h2>
        {children && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">{children}</p>}
      </div>
      {right}
    </div>
  )
}

/** A collapsed section: the title and a one-line hint stay visible, the detail opens on click. */
function Disclosure({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-lg border bg-card shadow-card [&[open]>summary]:border-b">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="text-[14px] font-medium">{title}</span>
        <span className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          {hint}
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="p-4">{children}</div>
    </details>
  )
}

// ---------------------------------------------------------------------------- the page

const STATUS = [
  { part: 'Transactions', state: 'Working', note: 'Live by default: payments arrive on the webhook, a Kafka topic or a Kinesis stream and are scored online. Offsets and checkpoints are committed only after the engine has processed a batch; bad messages go to a dead-letter table. Tested against a real Kafka broker and a Kinesis emulator, not production AWS. This public demo runs RAIL_SOURCE=replay over the synthetic dataset.' },
  { part: 'GNN score on every payment', state: 'Working', note: 'Each payment is scored on its own 2-hop subgraph, using only earlier payments (infra/scorer.py). Verified equal to a full-graph pass to 1e-20; a cached mode trades exactness for speed.' },
  { part: 'Detectors, queue, lead time', state: 'Working', note: 'Rules r2.0 sum over 1 h to 72 h windows with per-account baselines, because UPI caps a transfer at ₹1 lakh. r2.1 (relative floors, a new-payers count, friction) is opt-in: it catches structured rings but triples the queue. Stress tests and fresh redraws are in the evidence report.' },
  { part: 'Merchant-side rules (P2M)', state: 'Working, replay', note: 'Ticket anomaly, payer spread, collect-request pattern and shared settlement accounts, with settlement holds, on the aggregator’s own view. The bridge replays a fresh synthetic draw at start-up and the Merchants page shows it, with an onboarding check; it does not take live merchant traffic yet.' },
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
    <div className="grid gap-14">
      <Hero />

      <section className="grid gap-4">
        <SectionTitle
          icon={Activity}
          eyebrow="Running now · this replay so far"
          title="The engine, live"
          right={
            <Link href="/console" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-2 hover:underline">
              Go to the queue <ArrowRight className="size-3.5" />
            </Link>
          }
        />
        <BackendGate allowSnapshot>
          <MetricStrip />
        </BackendGate>
      </section>

      <section className="grid gap-4">
        <SectionTitle icon={Network} eyebrow="Follow the money" title="Who is paying whom, around every alert">
          The accounts under alert and the money flowing in and out of them, redrawn as payments arrive. Click an account to open its alert.
        </SectionTitle>
        <NetworkGraph />
      </section>

      <section id="test-scam" className="grid scroll-mt-24 gap-4">
        <SectionTitle icon={Send} eyebrow="Try it" title="Send a test scam and watch the engine respond">
          Walk a mule chain through the live engine one stage at a time. See which detectors fire, what the GNN scores, and whether the hold stops the money.
        </SectionTitle>
        <ScamLab />
      </section>

      <ProofPoints />

      <AggregatorSide />

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

      <section className="grid gap-3">
        <SectionTitle icon={Scale} eyebrow="Before you quote a number" title="Method, caveats and vocabulary" />
        <Disclosure title="Where the data comes from, and what the numbers can and cannot claim" hint="Synthetic data · still easier than real traffic">
          <DataHonesty bare />
        </Disclosure>
        <Disclosure title="What is real, what is sandboxed, what is not built" hint={`${STATUS.filter(s => s.state.startsWith('Working')).length} of ${STATUS.length} parts working`}>
          <RealityGrid items={STATUS} bare />
        </Disclosure>
        <Disclosure title="The vocabulary" hint="Mule, lead time, hold, 1930 and more">
          <GlossaryGrid bare />
        </Disclosure>
      </section>

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
export function DataHonesty({ bare }: { bare?: boolean } = {}) {
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
          Clean payments here are mostly small (median around ₹600) while scam transfers run ₹10,000–₹1 lakh, so amount still carries much of the signal: retrained
          without amount, the model collapses. The rules were written by someone who knew how the generator works. Real precision will be lower; the test set is
          small (two campaigns, tens of mules), so recall moves between 58% and 77% just by redrawing them.
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
      {!bare && (
        <SectionTitle icon={Scale} eyebrow="Read this before the numbers" title="Where the data comes from, and what the numbers can and cannot claim">
          Every account and payment here is synthetic. This is exactly how it was made, and what that means for the figures above.
        </SectionTitle>
      )}
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
