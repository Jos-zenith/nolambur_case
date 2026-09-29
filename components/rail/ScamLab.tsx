'use client'

import { ArrowRight, CircleDashed, FlaskConical, GitFork, Network, RotateCcw, Send, ShieldCheck, Zap } from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'

import { inrShort } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import type { Alert, Severity, TestScam } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { Term } from './kit'

// Stage 1 as rail_engine.demo_payments sends it; later stages move 90%, then 95%, of what arrived.
const VICTIM_TOTAL = 297_499

const STEPS = [
  {
    n: 1,
    icon: Zap,
    title: 'Victims pay a stranger',
    body: 'Three people pay one new account, each just under the ₹1 lakh UPI cap.',
    send: 'Send 3 victim payments',
  },
  {
    n: 2,
    icon: GitFork,
    title: 'The mule forwards it',
    body: (
      <>
        The <Term k="l1 mule">first-layer mule</Term> passes 90% on to three accounts. If it is already on <Term k="hold">hold</Term>, these transfers bounce.
      </>
    ),
    send: 'Forward to 3 accounts',
  },
  {
    n: 3,
    icon: Network,
    title: 'The next hop cashes out',
    body: (
      <>
        The <Term k="l2 mule">second-layer mules</Term> send it to one cash-out account. Only money that got through stage 2 can move.
      </>
    ),
    send: 'Send to cash-out',
  },
]

const SEV: Record<Severity, string> = { critical: 'var(--sev-critical)', high: 'var(--sev-high)', medium: 'var(--sev-medium)', low: 'var(--sev-low)' }
const ACTION_LABEL: Record<string, string> = {
  alert_only: 'Alert only',
  delay_settlement: 'Settlement delayed',
  hold_outbound: 'Outbound held',
  full_hold: 'Full hold',
  frozen: 'Frozen',
}

function worst(alerts: Alert[]) {
  const rank = { critical: 3, high: 2, medium: 1, low: 0 }
  return alerts.reduce<Alert | null>((w, a) => (!w || rank[a.severity] > rank[w.severity] ? a : w), null)
}

export function ScamLab() {
  const backend = useRail(s => s.backend)
  const paused = useRail(s => s.paused)
  const live = backend === 'live'
  const [scam, setScam] = useState<TestScam | null>(null)
  const [sending, setSending] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastSent, setLastSent] = useState(0)

  const refresh = useCallback(async (id: string) => {
    const r = await fetch(`/api/rail/demo/scam/${id}`, { cache: 'no-store' })
    if (r.ok) setScam(await r.json())
  }, [])

  // Poll while payments are in flight, and for a little while after, so alerts and holds show up.
  useEffect(() => {
    if (!scam) return
    const inFlight = scam.payments.some(p => p.status === 'queued')
    if (!inFlight && Date.now() - lastSent > 8000) return
    const t = setTimeout(() => refresh(scam.id), 700)
    return () => clearTimeout(t)
  }, [scam, lastSent, refresh])

  const send = async (stage: number) => {
    setSending(stage)
    setError(null)
    try {
      const r = await fetch('/api/rail/demo/scam', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, id: stage === 1 ? null : scam?.id }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `The bridge answered ${r.status}`)
      setLastSent(Date.now())
      await refresh(body.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSending(null)
    }
  }

  const sent = new Set(scam?.stages ?? [])
  const next = [1, 2, 3].find(n => !sent.has(n)) ?? null
  const byStage = (n: number) => scam?.payments.filter(p => p.stage === n) ?? []
  const alertsOn = (key: string) => (scam ? scam.alerts.filter(a => a.accountId === scam.accounts[key]?.id) : [])
  const mule = scam?.accounts.mule
  const muleAlert = worst(alertsOn('mule'))
  const moved = (n: number) => byStage(n).filter(p => p.status === 'settled' || p.status === 'delayed').reduce((s, p) => s + p.amount, 0)
  const stopped = (n: number) => byStage(n).filter(p => p.status === 'blocked').reduce((s, p) => s + p.amount, 0)
  const done = sent.has(3) || (sent.has(2) && byStage(2).length > 0 && byStage(2).every(p => p.status === 'blocked'))
  const inFlight = scam?.payments.some(p => p.status === 'queued')
  const stageTotal = (n: number) => (n === 1 ? VICTIM_TOTAL : n === 2 ? moved(1) * 0.9 : moved(2) * 0.95)

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="rounded-xl border bg-card p-3 shadow-card">
        <ChainDiagram scam={scam} alertsOn={alertsOn} />
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-1 pt-2 text-[12px] text-muted-foreground">
          <span>
            {scam ? (
              <>
                Test scam <span className="font-mono text-foreground">{scam.id}</span> · accounts start with <span className="font-mono">test.</span>
              </>
            ) : (
              'Illustration until you send a test scam. After that every colour is the engine’s answer.'
            )}
          </span>
          {scam && (
            <button type="button" onClick={() => (setScam(null), setError(null))} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-accent hover:text-foreground">
              <RotateCcw className="size-3.5" /> New test
            </button>
          )}
        </div>
      </div>

      <div className="grid content-start gap-2">
        {!live && (
          <p className="rounded-lg border border-sev-medium/30 bg-sev-medium-bg/60 px-3 py-2 text-[12.5px]">
            Sending needs the running bridge; the snapshot shown while it wakes cannot take payments.
          </p>
        )}
        {live && paused && sent.size > 0 && inFlight && (
          <p className="rounded-lg border border-sev-medium/30 bg-sev-medium-bg/60 px-3 py-2 text-[12.5px]">The replay is paused, so payments wait in the queue until it resumes.</p>
        )}
        <ol className="grid gap-2">
          {STEPS.map(s => {
            const isSent = sent.has(s.n)
            const rows = byStage(s.n)
            const isNext = next === s.n && !done
            return (
              <li key={s.n} className={cn('grid grid-cols-[32px_1fr] gap-3 rounded-lg border bg-card p-3 shadow-card', isNext && 'border-brand-2/50 ring-1 ring-brand-2/20')}>
                <span className={cn('grid size-8 place-items-center rounded-full text-white', isSent ? 'bg-brand-1' : isNext ? 'bg-brand-2' : 'bg-muted-foreground/40')}>
                  <s.icon className="size-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold">
                    {s.n}. {s.title}
                  </p>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{s.body}</p>
                  {isNext && (
                    <button
                      type="button"
                      onClick={() => send(s.n)}
                      disabled={!live || sending !== null || !!inFlight}
                      className="mt-2 inline-flex h-9 items-center gap-2 rounded-md bg-brand-2 px-3.5 text-[13px] font-medium text-white shadow-sm hover:bg-brand-2/90 disabled:opacity-50"
                    >
                      {sending === s.n ? <CircleDashed className="size-4 animate-spin" /> : <Send className="size-4" />}
                      {s.send} · {inrShort(stageTotal(s.n))}
                    </button>
                  )}
                  {isSent && rows.length > 0 && <StageResult n={s.n} rows={rows} alerts={s.n === 1 ? alertsOn('mule') : s.n === 2 ? ['layer2_1', 'layer2_2', 'layer2_3'].flatMap(alertsOn) : alertsOn('cashout')} />}
                </div>
              </li>
            )
          })}
        </ol>
        {error && <p className="rounded-lg border border-sev-critical/30 bg-sev-critical-bg px-3 py-2 text-[12.5px] text-sev-critical">{error}</p>}
        {scam && sent.size > 0 && !inFlight && (
          <div className={cn('rounded-lg border p-3 shadow-card', stopped(2) + stopped(3) > 0 ? 'border-ok/30 bg-ok-bg/60' : 'bg-card')}>
            <p className="flex items-center gap-2 text-[13.5px] font-semibold">
              <ShieldCheck className="size-4 text-ok" />
              {sent.has(2)
                ? stopped(2) > 0
                  ? `${inrShort(stopped(2))} stayed in the first account. ${moved(2) > 0 ? `${inrShort(moved(2))} got out.` : 'Nothing got out.'}`
                  : `${inrShort(moved(2))} left the first account${sent.has(3) ? `, ${inrShort(moved(3))} reached cash-out` : ''}.`
                : mule && mule.level >= 2
                  ? `The first account is on ${ACTION_LABEL[mule.action].toLowerCase()} before it could forward anything.`
                  : 'The engine has not restricted the first account yet.'}
            </p>
            <p className="mt-1 text-[12.5px] text-muted-foreground">
              {scam.alerts.length} alert{scam.alerts.length === 1 ? '' : 's'} raised on this test scam{done ? '' : ' so far'}.{' '}
              {muleAlert && (
                <Link href={`/console?alert=${encodeURIComponent(muleAlert.id)}`} className="inline-flex items-center gap-1 font-medium text-brand-2 hover:underline">
                  Open the mule&apos;s alert in the queue <ArrowRight className="size-3.5" />
                </Link>
              )}
            </p>
          </div>
        )}
        <p className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
          <FlaskConical className="mt-0.5 size-3.5 shrink-0" />
          Each click posts payments into the engine&apos;s ingest queue, the same path as the payment webhook: GNN scoring, the five detectors, then the decision router.
          Nothing is decided in the browser.
        </p>
      </div>
    </div>
  )
}

function StageResult({ n, rows, alerts }: { n: number; rows: TestScam['payments']; alerts: Alert[] }) {
  const queued = rows.filter(r => r.status === 'queued').length
  const blocked = rows.filter(r => r.status === 'blocked')
  const scores = rows.map(r => r.gnn).filter((x): x is number => x !== null)
  return (
    <div className="mt-2 grid gap-1.5 rounded-md bg-muted/50 p-2 text-[12px]">
      <p className="flex flex-wrap gap-x-3 gap-y-1">
        {queued > 0 ? (
          <span className="flex items-center gap-1 text-muted-foreground">
            <CircleDashed className="size-3.5 animate-spin" /> {queued} in the queue
          </span>
        ) : blocked.length === rows.length ? (
          <span className="font-medium text-ok">All {rows.length} blocked: {inrShort(blocked.reduce((s, r) => s + r.amount, 0))} did not move</span>
        ) : (
          <span>
            {rows.length - blocked.length} settled{blocked.length ? `, ${blocked.length} blocked` : ''}
          </span>
        )}
        {scores.length > 0 && (
          <span className="text-muted-foreground">
            <Term k="model score">GNN</Term> {Math.min(...scores).toFixed(3)}
            {scores.length > 1 && Math.max(...scores) !== Math.min(...scores) ? `–${Math.max(...scores).toFixed(3)}` : ''}
          </span>
        )}
      </p>
      {alerts.length > 0 ? (
        <ul className="grid gap-1">
          {alerts.map(a => (
            <li key={a.id} className="flex flex-wrap items-center gap-1.5">
              <span className="rounded px-1.5 py-px text-[11px] font-medium capitalize text-white" style={{ background: SEV[a.severity] }}>
                {a.severity}
              </span>
              <span>{a.title}</span>
              {a.action && a.action !== 'alert_only' && <span className="rounded bg-ok-bg px-1.5 py-px text-[11px] font-medium text-ok">→ {ACTION_LABEL[a.action]}</span>}
            </li>
          ))}
        </ul>
      ) : (
        queued === 0 && <p className="text-muted-foreground">{n === 1 ? 'No detector fired on the receiving account.' : 'No new alert on the receiving accounts.'}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------- the diagram

const VX = 70
const VICTIMS = [60, 140, 220].map(y => ({ x: VX, y }))
const MULE = { x: 300, y: 140 }
const L2 = [70, 140, 210].map(y => ({ x: 520, y }))
const OUT = { x: 700, y: 140 }
const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => {
  const mx = (a.x + b.x) / 2
  return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`
}

function ChainDiagram({ scam, alertsOn }: { scam: TestScam | null; alertsOn: (key: string) => Alert[] }) {
  const idle = !scam
  const status = (stage: number, i: number) => scam?.payments.find(p => p.stage === stage && p.txnId.endsWith(`.${stage}.${i}`))?.status
  const edge = (d: string, stage: number, i: number) => {
    const st = status(stage, i)
    const color = st === 'blocked' ? 'var(--ok)' : st ? 'var(--sev-high)' : 'var(--muted-foreground)'
    return (
      <path
        key={`${stage}-${i}`}
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={st && st !== 'blocked' ? 3 : 2}
        strokeOpacity={idle ? 0.55 : st ? 0.9 : 0.2}
        strokeDasharray={st === 'blocked' ? '5 4' : undefined}
        className={idle || st === 'settled' || st === 'delayed' || st === 'queued' ? 'flow' : undefined}
        strokeLinecap="round"
      />
    )
  }
  const node = (key: string, p: { x: number; y: number }, r: number, label: string) => {
    const a = worst(alertsOn(key))
    const level = scam?.accounts[key]?.level ?? 0
    const touched = !!scam?.payments.some(x => x.status !== 'queued' && (x.from === scam.accounts[key]?.id || x.to === scam.accounts[key]?.id))
    return (
      <g key={key}>
        {level >= 2 && <circle cx={p.x} cy={p.y} r={r + 7} fill="none" stroke="var(--ok)" strokeWidth={3} />}
        <circle cx={p.x} cy={p.y} r={r} fill={a ? SEV[a.severity] : touched || idle ? 'var(--card)' : 'var(--muted)'} stroke={a ? 'var(--card)' : 'var(--muted-foreground)'} strokeWidth={1.5} />
        <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize={11} fontWeight={600} fill={a ? '#fff' : 'var(--foreground)'}>
          {label}
        </text>
      </g>
    )
  }
  const mule = scam?.accounts.mule
  return (
    <svg viewBox="0 0 780 290" className="h-auto w-full" role="img" aria-label="Three victims pay one first-layer mule, who forwards to three second-layer mules, who send it to one cash-out account.">
      {[
        { x: 20, w: 100, label: 'Victims' },
        { x: 240, w: 120, label: 'First-layer mule' },
        { x: 460, w: 120, label: 'Second layer' },
        { x: 650, w: 100, label: 'Cash-out' },
      ].map(b => (
        <g key={b.label}>
          <rect x={b.x} y={14} width={b.w} height={250} rx={12} fill="var(--muted)" opacity={0.5} />
          <text x={b.x + b.w / 2} y={282} textAnchor="middle" className="fill-muted-foreground" fontSize={12}>
            {b.label}
          </text>
        </g>
      ))}
      {VICTIMS.map((v, i) => edge(curve(v, MULE), 1, i))}
      {L2.map((n, i) => edge(curve(MULE, n), 2, i))}
      {L2.map((n, i) => edge(curve(n, OUT), 3, i))}
      {VICTIMS.map((v, i) => node(`victim${i + 1}`, v, 18, '₹'))}
      {node('mule', MULE, 26, 'L1')}
      {L2.map((n, i) => node(`layer2_${i + 1}`, n, 18, 'L2'))}
      {node('cashout', OUT, 22, 'ATM')}
      {mule && mule.level >= 2 && (
        <text x={MULE.x} y={MULE.y + 50} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--ok)">
          {ACTION_LABEL[mule.action]}
        </text>
      )}
    </svg>
  )
}
