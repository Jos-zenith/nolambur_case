'use client'

import { CircleDashed, Store } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { Table } from '@/components/rail/bits'
import { PageHeader } from '@/components/rail/kit'
import { duration, inr, inrShort, pct } from '@/lib/rail/format'
import { railPost } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

/** /rail/p2m/* from the bridge (Multi-GNN/infra/p2m_service.py): rules p1.0 on a finished replay of synthetic merchants. */
type Status = {
  status: 'starting' | 'waiting' | 'warming' | 'ready' | 'error' | 'disabled' | 'absent'
  error: string | null
  stream: number
  rules?: string
  merchants?: number
  payments?: number
  collects?: number
  testDays?: [string, string]
  parameters?: { d1Count: number; d2States: number; d3Requests: number; d3FailShare: number }
  detectors?: Record<string, string>
  note?: string
}
type Merchant = {
  id: string
  vpa: string
  category: string
  state: string
  legalEntity: string
  settlementAccount: string
  onboardedAt: string
  chain: string | null
  payments: number
  inflow: number
  detectors: string[]
  firstAlert: string | null
  heldBatches: number
  heldAmount: number
  sharedSettlement: number
  truth: { fraud: boolean; scenario: string | null }
}
type Detail = Merchant & {
  alerts: { detector: string; label: string; at: string; why: string }[]
  batches: { at: string; payments: number; amount: number; held: boolean; holdUntil: string | null; fraudAmount: number }[]
  collects: { customers: Record<string, number>; nonCustomers: Record<string, number> }
  recentPayments: { at: string; payerVpa: string; payerState: string; amount: number; initiation: string; fraud: boolean }[]
  peers: Merchant[]
}
type Draw = { file: string; label: string; activeFraudMerchants: number; activeFlagged: number; holdPrecision: number | null; fraudHeldShare: number | null; medianSecondsToHoldAlert: number | null }
type Evaluation = { draws: Draw[]; caveats: string }
type Onboarding = { decision: 'approve' | 'review' | 'hold'; reason: string; sharedWith: Merchant[] }

const DECISION = {
  hold: { label: 'Hold for review', cls: 'bg-sev-critical-bg text-sev-critical' },
  review: { label: 'Approve after manual review', cls: 'bg-sev-medium-bg text-sev-medium' },
  approve: { label: 'Approve', cls: 'bg-ok-bg text-ok' },
} as const

/** "2024-03-19T06:00:00" → "19 Mar 06:00", in the data's own clock. */
function when(iso: string | null) {
  if (!iso) return '—'
  const [d, t] = iso.split('T')
  const [, m, day] = d.split('-')
  return `${day} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(m) - 1]} ${t.slice(0, 5)}`
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: 'hot' | 'muted' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px]',
        tone === 'hot' ? 'bg-sev-critical-bg text-sev-critical' : tone === 'muted' ? 'bg-muted text-muted-foreground' : 'bg-brand-soft text-brand-2',
      )}
    >
      {children}
    </span>
  )
}

function useP2M<T>(path: string, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  useEffect(() => {
    if (!enabled) return
    let stop = false
    fetch(`/api/rail/p2m/${path}`, { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(d => !stop && setData(d))
      .catch(() => {})
    return () => {
      stop = true
    }
  }, [path, enabled])
  return data
}

type Snapshot = { capturedAt: string; status: Status; merchants: Merchant[]; details: Record<string, Detail>; evaluation: Evaluation }

export default function MerchantsPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const poll = useCallback(() => {
    fetch('/api/rail/p2m/status', { cache: 'no-store' })
      // a 404 from a reachable bridge means it predates the merchant replay
      .then(r => (r.ok ? r.json() : r.status === 404 ? { status: 'absent', error: null, stream: 2 } : null))
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])
  useEffect(() => {
    poll()
    const id = setInterval(() => status?.status !== 'ready' && poll(), 4000)
    return () => clearInterval(id)
  }, [poll, status?.status])
  // the same replay, saved (python -m infra.p2m_service), shown whenever the bridge can't serve it
  useEffect(() => {
    fetch('/p2m-snapshot.json')
      .then(r => (r.ok ? r.json() : null))
      .then(setSnap)
      .catch(() => {})
  }, [])
  const ready = status?.status === 'ready'
  const liveMerchants = useP2M<Merchant[]>('merchants', ready)
  const liveEvaluation = useP2M<Evaluation>('evaluation', ready)
  const live = ready && !!liveMerchants
  const merchants = live ? liveMerchants : (snap?.merchants ?? null)
  const evaluation = live ? liveEvaluation : (snap?.evaluation ?? null)
  const shownStatus = live ? status : (snap?.status ?? status)
  const [selected, setSelected] = useState<string | null>(null)
  const [onlyFlagged, setOnlyFlagged] = useState(true)
  const shown = useMemo(() => (merchants ?? []).filter(m => !onlyFlagged || m.detectors.length > 0), [merchants, onlyFlagged])
  useEffect(() => {
    if (!selected && shown.length) setSelected(shown[0].id)
  }, [shown, selected])

  return (
    <div className="grid gap-6">
      <PageHeader
        icon={Store}
        eyebrow={`The aggregator's own view · rules ${shownStatus?.rules ?? 'p1.0'}`}
        title="Merchant risk"
        guideKey="merchants"
        guide={[
          { title: 'What this sees', body: 'Payments into the aggregator’s own merchants, their collect requests and outcomes, its settlement batches and its onboarding records. Nothing after settlement.' },
          { title: 'The lever', body: 'An alert before the morning batch holds that merchant’s payout. With nobody acting, a hold lifts after 24 h (72 h with a shared-account flag) and the money settles later.' },
          { title: 'D4 is a review', body: 'A settlement account shared across declared entities looks the same for a ring and for a family business, so it opens a review and never holds money by itself.' },
        ]}
      >
        A finished replay of synthetic merchants: the fresh judging draw, with parameters fixed from training days before any result (Multi-GNN/reports/README.md
        3.5). It is not a live stream. Labels are shown so the replay can be checked; no rule reads them.
      </PageHeader>

      {!live && <BridgeNote status={status} snapshotAt={snap?.capturedAt ?? null} />}

      {merchants && (
        <>
          <Evidence status={shownStatus} evaluation={evaluation} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
            <section className="rounded-lg border bg-card shadow-card">
              <div className="flex items-center justify-between border-b px-4 py-2.5 text-[13px]">
                <span className="font-medium">
                  {shown.length} of {merchants.length} merchants
                </span>
                <label className="flex items-center gap-1.5 text-muted-foreground">
                  <input type="checkbox" checked={onlyFlagged} onChange={e => setOnlyFlagged(e.target.checked)} /> flagged only
                </label>
              </div>
              <ul className="max-h-[640px] divide-y overflow-y-auto">
                {shown.map(m => (
                  <li key={m.id}>
                    <button
                      onClick={() => setSelected(m.id)}
                      className={cn('grid w-full gap-1 px-4 py-2.5 text-left text-[13px] hover:bg-muted/50', selected === m.id && 'bg-brand-soft/60')}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">
                          {m.vpa} <span className="font-normal text-muted-foreground">· {m.category.replace('_', ' ')}</span>
                        </span>
                        <span className="flex shrink-0 gap-1">
                          {m.detectors.map(d => (
                            <Chip key={d} tone={d === 'D4' ? 'muted' : 'hot'}>
                              {d}
                            </Chip>
                          ))}
                        </span>
                      </span>
                      <span className="flex justify-between text-[12px] text-muted-foreground">
                        <span>
                          {inrShort(m.inflow)} in {m.payments} payments{m.heldBatches ? ` · ${m.heldBatches} payout${m.heldBatches > 1 ? 's' : ''} held` : ''}
                        </span>
                        <span className={m.truth.fraud ? 'text-sev-critical' : ''}>{m.truth.fraud ? `label: ${m.truth.scenario}` : 'label: clean'}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            {selected && <MerchantDetail id={selected} detectors={shownStatus?.detectors ?? {}} preset={live ? undefined : (snap?.details[selected] ?? null)} />}
          </div>
          <OnboardingCheck live={live} />
        </>
      )}
    </div>
  )
}

/** Why the page isn't live, and that what's below (if anything) is the saved copy of the same replay. */
function BridgeNote({ status, snapshotAt }: { status: Status | null; snapshotAt: string | null }) {
  const why =
    status?.status === 'error'
      ? `The merchant replay failed on the bridge: ${status.error}.`
      : status?.status === 'disabled'
        ? 'The merchant replay is turned off on this bridge (RAIL_P2M=0).'
        : status?.status === 'absent'
          ? 'The running bridge predates the merchant replay.'
          : !status
            ? 'The bridge is not answering yet (it sleeps on the free plan).'
            : status.status === 'waiting'
              ? 'The bridge is loading the payment engine first; the merchant replay starts after it.'
              : status.status === 'ready'
                ? 'Loading the merchant replay from the bridge.'
                : 'The bridge is replaying the merchant data (under a minute).'
  return (
    <p className="flex items-start gap-2 rounded-md border border-sev-medium/30 bg-sev-medium-bg/60 px-3 py-2 text-[13px] leading-relaxed">
      <CircleDashed className="mt-0.5 size-4 shrink-0 animate-spin text-sev-medium" />
      <span>
        {why}{' '}
        {snapshotAt
          ? `Showing a snapshot of the same replay, captured ${snapshotAt.replace('T', ' ')} by python -m infra.p2m_service; detail for flagged merchants only, and the onboarding check needs the live bridge.`
          : 'No snapshot is available.'}
      </span>
    </p>
  )
}

function Evidence({ status, evaluation }: { status: Status | null; evaluation: Evaluation | null }) {
  const p = status?.parameters
  return (
    <section className="grid gap-3 lg:grid-cols-[1fr_1.4fr]">
      <div className="rounded-lg border bg-card p-4 text-[13px] shadow-card">
        <p className="font-semibold">The four rules, parameters from training days only</p>
        <ul className="mt-2 grid gap-1.5 text-muted-foreground">
          <li>
            <Chip tone="hot">D1</Chip> {p?.d1Count}+ first-time payers at or above the category&apos;s p99 ticket in 24 h
          </li>
          <li>
            <Chip tone="hot">D2</Chip> first-time payers from {p?.d2States}+ other states into a local shop in 24 h
          </li>
          <li>
            <Chip tone="hot">D3</Chip> {p?.d3Requests}+ collect requests to non-customers in 24 h, {pct(p?.d3FailShare)}+ failing
          </li>
          <li>
            <Chip tone="muted">D4</Chip> one settlement account behind different declared entities (review only)
          </li>
        </ul>
      </div>
      <div className="rounded-lg border bg-card p-4 shadow-card">
        <p className="text-[13px] font-semibold">Every draw judged so far</p>
        {evaluation ? (
          <>
            <Table head={['Draw', 'Fraud merchants flagged', 'Hold precision', 'Fraud money held at a batch', 'To first hold']} right={[1, 2, 3, 4]}>
              {evaluation.draws.map(d => (
                <tr key={d.file} className="border-b last:border-0">
                  <td className="py-1.5 pr-3">{d.label}</td>
                  <td className="pr-3 text-right">
                    {d.activeFlagged} / {d.activeFraudMerchants}
                  </td>
                  <td className="pr-3 text-right">{pct(d.holdPrecision)}</td>
                  <td className="pr-3 text-right">{pct(d.fraudHeldShare)}</td>
                  <td className="text-right">{duration(d.medianSecondsToHoldAlert)}</td>
                </tr>
              ))}
            </Table>
            <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
              Tiny samples: 2–4 fresh fraud merchants a draw (8 of 8 pooled is a 95% interval of 68–100%). &ldquo;Held&rdquo; is the window an analyst had to act,
              not money recovered. The scenarios are easy by construction and the costs are floors; real merchants are messier.
            </p>
          </>
        ) : (
          <p className="mt-2 text-[13px] text-muted-foreground">Loading…</p>
        )}
      </div>
    </section>
  )
}

function MerchantDetail({ id, detectors, preset }: { id: string; detectors: Record<string, string>; preset?: Detail | null }) {
  const fetched = useP2M<Detail>(`merchants/${id}`, preset === undefined)
  const d = preset === undefined ? fetched : preset
  if (preset === null) return <section className="rounded-lg border bg-card p-4 text-[13px] text-muted-foreground shadow-card">The snapshot keeps detail for flagged merchants only.</section>
  if (!d || d.id !== id) return <section className="h-[420px] animate-pulse rounded-lg border bg-card" />
  const collects = (o: Record<string, number>) => Object.entries(o).map(([k, n]) => `${n} ${k}`).join(' · ') || 'none'
  return (
    <section className="grid content-start gap-4 rounded-lg border bg-card p-4 shadow-card">
      <div>
        <p className="text-[15px] font-semibold">
          {d.vpa} <span className="font-normal text-muted-foreground">· {d.category.replace('_', ' ')} · {d.state}</span>
        </p>
        <p className="mt-0.5 text-[12.5px] text-muted-foreground">
          Entity {d.legalEntity} · settles to <span className="font-mono">{d.settlementAccount}</span>
          {d.sharedSettlement ? ` (shared with ${d.sharedSettlement} other${d.sharedSettlement > 1 ? 's' : ''})` : ''} · onboarded {when(d.onboardedAt)}
          {d.chain ? ` · chain ${d.chain}` : ''}
        </p>
        <p className={cn('mt-1 text-[12px]', d.truth.fraud ? 'text-sev-critical' : 'text-muted-foreground')}>
          Synthetic label: {d.truth.fraud ? `fraud (${d.truth.scenario})` : 'clean'}. Shown for checking the replay; no rule reads it.
        </p>
      </div>

      <div>
        <p className="text-[13px] font-semibold">Alerts</p>
        {d.alerts.length ? (
          <ul className="mt-1.5 grid gap-1.5 text-[13px]">
            {d.alerts.map(a => (
              <li key={a.detector + a.at} className="grid grid-cols-[34px_86px_1fr] gap-2">
                <Chip tone={a.detector === 'D4' ? 'muted' : 'hot'}>{a.detector}</Chip>
                <span className="text-muted-foreground">{when(a.at)}</span>
                <span>
                  <span className="font-medium">{detectors[a.detector] ?? a.label}.</span> {a.why}.
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] text-muted-foreground">None.</p>
        )}
      </div>

      <div>
        <p className="text-[13px] font-semibold">Settlement payouts</p>
        <Table head={['Batch', 'Payments', 'Amount', 'Outcome', 'Of it fraud (label)']} right={[1, 2, 4]}>
          {d.batches.map(b => (
            <tr key={b.at} className="border-b last:border-0">
              <td className="py-1.5 pr-3">{when(b.at)}</td>
              <td className="pr-3 text-right">{b.payments}</td>
              <td className="pr-3 text-right">{inr(b.amount)}</td>
              <td className="pr-3">{b.held ? <span className="text-sev-critical">held until {when(b.holdUntil)}</span> : 'paid out'}</td>
              <td className="text-right">{b.fraudAmount ? inr(b.fraudAmount) : '—'}</td>
            </tr>
          ))}
        </Table>
      </div>

      <p className="text-[12.5px] text-muted-foreground">
        Collect requests · to customers: {collects(d.collects.customers)} · to non-customers: {collects(d.collects.nonCustomers)}
      </p>

      {d.peers.length > 0 && (
        <div>
          <p className="text-[13px] font-semibold">Also settling to this account</p>
          <ul className="mt-1 grid gap-1 text-[12.5px]">
            {d.peers.map(p => (
              <li key={p.id} className="flex justify-between gap-2">
                <span>
                  {p.vpa} · {p.category.replace('_', ' ')} · entity {p.legalEntity} · {inrShort(p.inflow)} in
                </span>
                <span className="flex gap-1">
                  {p.detectors.map(x => (
                    <Chip key={x} tone={x === 'D4' ? 'muted' : 'hot'}>
                      {x}
                    </Chip>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-[13px] font-semibold">Latest payments</p>
        <div className="max-h-[260px] overflow-y-auto">
          <Table head={['When', 'Payer', 'From', 'Amount', 'How']} right={[3]}>
            {d.recentPayments.map((r, i) => (
              <tr key={r.at + i} className={cn('border-b last:border-0', r.fraud && 'text-sev-critical')}>
                <td className="py-1 pr-3">{when(r.at)}</td>
                <td className="pr-3 font-mono text-[12px]">{r.payerVpa}</td>
                <td className="pr-3">{r.payerState}</td>
                <td className="pr-3 text-right">{inr(r.amount)}</td>
                <td>{r.initiation}</td>
              </tr>
            ))}
          </Table>
        </div>
      </div>
    </section>
  )
}

function OnboardingCheck({ live }: { live: boolean }) {
  const [account, setAccount] = useState('')
  const [entity, setEntity] = useState('')
  const [result, setResult] = useState<Onboarding | null>(null)
  const [error, setError] = useState<string | null>(null)
  const check = async () => {
    setError(null)
    const { ok, data } = await railPost<Onboarding>('p2m/onboarding', { settlementAccount: account, legalEntity: entity })
    if (ok) setResult(data)
    else setError(data.error ?? 'Check failed')
  }
  return (
    <section className="grid gap-3 rounded-lg border bg-card p-4 shadow-card">
      <div>
        <p className="text-[14px] font-semibold">Onboarding check: who else settles to this account?</p>
        <p className="text-[12.5px] text-muted-foreground">
          D4 at the moment a merchant applies. Paste a settlement account from a merchant above to see a ring member, a family business or a chain.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <input value={account} onChange={e => setAccount(e.target.value)} placeholder="Settlement account, e.g. SA0a0e244757" className="h-9 w-72 rounded-md border bg-background px-2.5 font-mono text-[13px]" />
        <input value={entity} onChange={e => setEntity(e.target.value)} placeholder="Declared legal entity" className="h-9 w-56 rounded-md border bg-background px-2.5 text-[13px]" />
        <button onClick={check} disabled={!live || account.length < 3 || !entity} title={live ? undefined : 'Needs the live bridge'} className="h-9 rounded-md bg-brand-1 px-4 text-[13px] font-medium text-white disabled:opacity-50">
          Check
        </button>
      </div>
      {error && <p className="text-[13px] text-sev-critical">{error}</p>}
      {result && (
        <div className="grid gap-2 text-[13px]">
          <p>
            <span className={cn('rounded px-2 py-0.5 text-[12.5px] font-medium', DECISION[result.decision].cls)}>{DECISION[result.decision].label}</span>{' '}
            {result.reason}
          </p>
          {result.sharedWith.length > 0 && (
            <ul className="grid gap-0.5 text-[12.5px] text-muted-foreground">
              {result.sharedWith.map(m => (
                <li key={m.id}>
                  {m.vpa} · {m.category.replace('_', ' ')} · entity {m.legalEntity}
                  {m.detectors.length ? ` · alerts ${m.detectors.join(', ')}` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
