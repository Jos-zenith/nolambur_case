'use client'

import { useEffect, useState } from 'react'

import { Section, Table } from '@/components/rail/bits'
import { ScoreHistogram, TrainingCurve } from '@/components/rail/charts'
import { duration, inr, inrShort, pct } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import { BrainCircuit } from 'lucide-react'
import { PageHeader, Term } from '@/components/rail/kit'
import { WakeBanner } from '@/components/rail/BackendGate'
import { DataHonesty } from '@/components/rail/overview'
import { cn } from '@/lib/utils'

type PRF = { tp: number; fp: number; fn: number; precision: number; recall: number; f1: number }
export type TemporalEvaluation = {
  evaluation: 'temporal'
  dataset: { version: string; file: string; rows: number; accounts: number; fraudRows: number; start: string; end: string; scores: string }
  split: Record<'train' | 'val' | 'test', [string, string]>
  model: { architecture: string; checkpoint: string; edgeFeatures: string[]; training: string; scoring: string; checkpointModified: string | null }
  trainingLog: {
    epochs: { epoch: number; train: number; val: number; test: number }[]
    lastEpochAt: string | null
  }
  test: {
    edges: number
    positives: number
    rocAuc: number | null
    averagePrecision: number | null
    threshold: number
    thresholdSource: string
    validation: (PRF & { edges: number }) | null
    atThreshold: PRF & { threshold: number }
    thresholds: (PRF & { threshold: number; chosen: boolean })[]
    precisionAtK: { k: number; precision: number }[]
    flaggedPerDay: number
    perLayer: { layer: string; rows: number; flagged: number; amountMedian: number; amountMax: number }[]
    histogram: { bin: string; fraud: number; clean: number }[]
  }
  detectors: {
    accountLevel: PRF
    combined: PRF
    modelOnlyAccounts: number
    modelOnlyMules: number
    mulesActive: number
    byDetector: { detector: string; label: string; alerts: number; mules: number; precision: number | null }[]
    precisionAtK: { k: number; precision: number }[]
    alertsPerDay: number
    analysts: number
    alertsPerAnalystPerDay: number
    leadSeconds: { n: number; median: number | null; p10: number | null; p90: number | null; alertedBeforeMoneyLeft: number; note: string }
    secondsToAlert: { n: number; median: number | null; p90: number | null; note: string }
    ruleVersion: string
  }
  policy: {
    ladder: { level: number; action: string; label: string; limitHours: number | null }[]
    appealSlaHours: number
    fraudTotal: number
    fraudBlocked: number
    fraudRecoveredFromDelay: number
    fraudStopped: number
    fraudLost: number
    genuineBlocked: number
    genuineDelayedThenReleased: number
    restrictions: Record<string, number>
    restrictedAccounts: number
    restrictedMules: number
    innocentRestricted: number
    innocentRestrictionHours: number
    lifted: Record<string, number>
    note: string
  }
}

type LoadRun = {
  targetTps: number
  sustainedTps: number
  keepsUp: boolean
  batchPerTick: number
  tickMs: { p50: number; p99: number; max: number }
  scoreMs: { p50: number; p99: number }
  rulesMs: { p50: number; p99: number }
  paymentLatencyMs: { p50: number; p99: number }
  medianSubgraphEdges: number
}
type LoadHttpRun = { targetTps: number; offeredTps: number; ingestedTps: number; rejected429: number; httpMs: { p50: number; p99: number }; endToEndMs: { p50: number | null; p99: number | null } }
type EngineReport = { at: string; hardware: { cpu: string; logicalCpus: number; ramGb?: number; torchThreads?: number }; seconds: number; runs: (LoadRun & { scoring?: string; refreshSeconds?: number | null; lastRefreshMs?: number | null; shards?: number; accounts?: number; p99WithinTick?: boolean })[] }
type LoadReport = {
  loadtest?: EngineReport
  loadtest_cached?: EngineReport
  loadtest_http?: { at: string; seconds: number; runs: LoadHttpRun[] }
}

const PIPELINE = [
  ['nolambur_v2_gen.py', '10 days, 10 campaigns, UPI-capped amounts'],
  ['nolambur_v2/transactions.csv', 'labels in nolambur_v2/labels.csv'],
  ['prepare_datasets.py --dataset v2', 'encodes accounts, time and amounts as a graph'],
  ['finetune_local_nolambur.py --dataset v2', 'trains GINe on days 0–5; writes checkpoint + norm stats'],
  ['infra/scorer.py', 'scores each payment on its 2-hop subgraph, using only the past'],
  ['rail_engine.py', 'rules r2.0, the decision router, evaluation on days 8–9'],
  ['infra/', 'streams in, audit and decisions out, registry, feedback'],
  ['This console', 'Next.js; proxies /api/rail to the bridge'],
]

const f2 = (x: number | null | undefined) => (x === null || x === undefined ? '—' : x.toFixed(2))
const day = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' })

export default function ModelPage() {
  const [liveEv, setEv] = useState<TemporalEvaluation | null>(null)
  const [load, setLoad] = useState<LoadReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const backend = useRail(s => s.backend)
  const snapshot = useRail(s => s.snapshot)
  const snapEv = snapshot?.evaluation as TemporalEvaluation | undefined
  const ev = liveEv ?? (snapEv?.evaluation === 'temporal' ? snapEv : null)
  const fromSnapshot = !liveEv && !!ev

  useEffect(() => {
    if (liveEv) return
    fetch('/api/rail/evaluation', { cache: 'no-store' })
      .then(async r => (r.ok ? setEv(await r.json()) : setError(r.status === 503 ? 'The bridge is still warming up.' : 'The GNN bridge is not running.')))
      .catch(() => setError('The GNN bridge is not running.'))
    fetch('/api/rail/loadtest', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(setLoad)
      .catch(() => {})
  }, [backend, liveEv])

  return (
    <div className="grid max-w-5xl gap-8">
      <PageHeader
        icon={BrainCircuit}
        eyebrow="Measured on days the model never saw"
        title="Model and evaluation"
        guideKey="model"
        guide={[
          { title: 'Train on the past', body: 'The GIN trains on days 0–5, picks its alert threshold on days 6–7, and every number here is from days 8–9.' },
          { title: 'Scored as it would be live', body: 'Each payment is scored on its 2-hop neighbourhood using only payments before it: no peeking at later edges.' },
          { title: 'What an analyst sees', body: <>Precision@k is the share of mules at the top of the queue; alerts per analyst per day is the workload.</> },
          { title: 'What a hold costs', body: 'The policy section counts money stopped and the hours innocent accounts spent restricted.' },
        ]}
      >
        Every number is computed by the bridge from the files in <code className="font-mono">Multi-GNN/</code> when it starts. Nothing is typed in by hand.
      </PageHeader>

      {fromSnapshot && <WakeBanner />}

      {!ev ? (
        <p className="border bg-card p-4 text-[13px] text-muted-foreground">{error ? `${error} The page keeps retrying.` : 'Loading evaluation from the bridge…'}</p>
      ) : (
        <>
          <Headline ev={ev} />
          <SplitTimeline ev={ev} />

          <Section title="The model on the test days" note={`edge level · ${ev.test.edges.toLocaleString('en-IN')} payments, ${ev.test.positives} fraud · online, time-respecting scores`}>
            <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed">
              At the threshold picked on the validation days ({ev.test.threshold.toFixed(2)}), the GIN flags <b>{ev.test.atThreshold.tp + ev.test.atThreshold.fp}</b> test payments:{' '}
              <b>{ev.test.atThreshold.tp}</b> fraud and <b>{ev.test.atThreshold.fp}</b> clean, catching <b>{pct(ev.test.atThreshold.recall)}</b> of the fraud at{' '}
              <b>{pct(ev.test.atThreshold.precision)}</b> precision. That is about <b>{Math.round(ev.test.flaggedPerDay)}</b> model flags a day. ROC AUC{' '}
              <b>{f2(ev.test.rocAuc)}</b>, average precision <b>{f2(ev.test.averagePrecision)}</b>.
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <Table head={['Threshold', 'Flagged', 'False pos.', 'Precision', 'Recall', 'F1']} right={[1, 2, 3, 4, 5]}>
                {ev.test.thresholds.map(t => (
                  <tr key={t.threshold} className={cn('border-b last:border-0', t.chosen && 'bg-brand-soft/50 font-medium')}>
                    <td className="py-1.5 pr-3 font-mono">
                      {t.threshold.toFixed(2)}
                      {t.chosen && <span className="ml-1.5 text-[11px] text-brand-2">chosen on val</span>}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.tp + t.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.precision.toFixed(3)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.recall.toFixed(3)}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.f1.toFixed(3)}</td>
                  </tr>
                ))}
              </Table>
              <div className="grid content-start gap-4">
                <Table head={['Top k payments by score', 'Fraud among them']} right={[1]}>
                  {ev.test.precisionAtK.map(p => (
                    <tr key={p.k} className="border-b last:border-0">
                      <td className="py-1.5 pr-3">top {p.k}</td>
                      <td className="py-1.5 text-right tabular-nums">{pct(p.precision)}</td>
                    </tr>
                  ))}
                </Table>
                <Table head={['Layer', 'Payments', 'Flagged', 'Median', 'Largest']} right={[1, 2, 3, 4]}>
                  {ev.test.perLayer.map(l => (
                    <tr key={l.layer} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 font-mono">{l.layer}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{l.rows.toLocaleString('en-IN')}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{l.flagged}</td>
                      <td className="py-1.5 pr-3 text-right font-mono text-[12px]">{inr(l.amountMedian)}</td>
                      <td className="py-1.5 text-right font-mono text-[12px]">{inr(l.amountMax)}</td>
                    </tr>
                  ))}
                </Table>
              </div>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="border bg-card p-3">
                <ScoreHistogram bins={ev.test.histogram} klass="fraud" title={`Fraud payments, test days (${ev.test.positives})`} />
              </div>
              <div className="border bg-card p-3">
                <ScoreHistogram bins={ev.test.histogram} klass="clean" title={`Clean payments, test days (${(ev.test.edges - ev.test.positives).toLocaleString('en-IN')})`} />
              </div>
            </div>
          </Section>

          <Section title="Rules and the analyst queue" note={`account level · rules ${ev.detectors.ruleVersion} · ${ev.detectors.mulesActive} mules active on the test days`}>
            <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed">
              Rules alone alert on <b>{pct(ev.detectors.accountLevel.recall)}</b> of the mules active on the test days at <b>{pct(ev.detectors.accountLevel.precision)}</b>{' '}
              precision; with the model&apos;s leads, <b>{pct(ev.detectors.combined.recall)}</b> at <b>{pct(ev.detectors.combined.precision)}</b>. The queue gets{' '}
              <b>{ev.detectors.alertsPerDay.toFixed(1)}</b> accounts a day: <b>{ev.detectors.alertsPerAnalystPerDay.toFixed(1)}</b> per analyst for a team of{' '}
              {ev.detectors.analysts}.
            </p>
            <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
              <Table head={['Detector', 'Accounts', 'Mules', 'Precision']} right={[1, 2, 3]}>
                {ev.detectors.byDetector.map(d => (
                  <tr key={d.detector} className="border-b last:border-0">
                    <td className="py-1.5 pr-3">{d.label}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{d.alerts}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{d.mules}</td>
                    <td className="py-1.5 text-right tabular-nums">{pct(d.precision)}</td>
                  </tr>
                ))}
              </Table>
              <Table head={['Top of the queue', 'Mules']} right={[1]}>
                {ev.detectors.precisionAtK.map(p => (
                  <tr key={p.k} className="border-b last:border-0">
                    <td className="py-1.5 pr-3">first {p.k} accounts</td>
                    <td className="py-1.5 text-right tabular-nums">{pct(p.precision)}</td>
                  </tr>
                ))}
              </Table>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Fact label="Lead time, median" value={duration(ev.detectors.leadSeconds.median)} note="first alert → first time fraud money left that mule" />
              <Fact
                label="Lead time, p10"
                value={ev.detectors.leadSeconds.p10 === null ? '—' : ev.detectors.leadSeconds.p10 < 0 ? `${duration(-ev.detectors.leadSeconds.p10)} late` : duration(ev.detectors.leadSeconds.p10)}
                note={`${ev.detectors.leadSeconds.alertedBeforeMoneyLeft} of ${ev.detectors.leadSeconds.n} alerted before any money left`}
              />
              <Fact label="Time to alert, median" value={duration(ev.detectors.secondsToAlert.median)} note={`from a mule's first fraud inflow; p90 ${duration(ev.detectors.secondsToAlert.p90)}`} />
            </div>
          </Section>

          <Section title="What the graded actions stop, and what they cost" note="test days · the router acting alone, nobody deciding">
            <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
              <Table head={['Level', 'Action', 'Lifts itself after']}>
                {ev.policy.ladder.map(l => (
                  <tr key={l.level} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 tabular-nums">{l.level}</td>
                    <td className="py-1.5 pr-3">{l.label}</td>
                    <td className="py-1.5 text-[12.5px] text-muted-foreground">{l.limitHours ? `${l.limitHours} h unless a supervisor confirms` : '—'}</td>
                  </tr>
                ))}
              </Table>
              <dl className="grid content-start gap-1.5 border bg-card p-3 text-[13px]">
                {[
                  ['Fraud on the test days', inr(ev.policy.fraudTotal)],
                  ['Stopped: blocked outright', inr(ev.policy.fraudBlocked)],
                  ['Stopped: delayed, then cancelled', inr(ev.policy.fraudRecoveredFromDelay)],
                  ['Lost (arrived before any alert, or not caught)', inr(ev.policy.fraudLost)],
                  ['Genuine money blocked', inr(ev.policy.genuineBlocked)],
                  ['Genuine money delayed, then released', inr(ev.policy.genuineDelayedThenReleased)],
                  ['Innocent accounts restricted', `${ev.policy.innocentRestricted} · ${ev.policy.innocentRestrictionHours.toFixed(1)} account-hours`],
                  ['Mules restricted', `${ev.policy.restrictedMules} of ${ev.policy.restrictedAccounts} restricted accounts`],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 border-b pb-1 last:border-0">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="text-right font-mono text-[12.5px]">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <p className="mt-2 max-w-3xl text-[12.5px] text-muted-foreground">
              {ev.policy.note} An appeal must be decided within {ev.policy.appealSlaHours} h or the restriction lifts. Restrictions by level:{' '}
              {Object.entries(ev.policy.restrictions).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}.
            </p>
          </Section>

          <LoadSection load={load} />

          <Section title="Training run" note={`last finetune in logs/logs.log · ${ev.trainingLog.lastEpochAt ?? ''}`}>
            <div className="border bg-card p-3">
              <TrainingCurve epochs={ev.trainingLog.epochs} />
            </div>
            <p className="mt-2 max-w-3xl text-[12.5px] text-muted-foreground">
              The curve is Multi-GNN&apos;s own per-epoch F1, which scores each split with the whole graph as context (later edges included). The figures above use the
              online scorer instead, which only ever sees the past; that is what production would get.
            </p>
          </Section>

          <DataHonesty />

          <Section title="Pipeline">
            <ol className="grid gap-px border bg-border sm:grid-cols-2 lg:grid-cols-4">
              {PIPELINE.map(([file, what], i) => (
                <li key={file} className="bg-card p-3">
                  <p className="text-[11px] text-muted-foreground">{i + 1}</p>
                  <p className="font-mono text-[12.5px]">{file}</p>
                  <p className="mt-0.5 text-[12.5px] text-muted-foreground">{what}</p>
                </li>
              ))}
            </ol>
          </Section>

          <Section title="Checkpoint">
            <dl className="grid gap-x-6 border bg-card p-3 text-[13px] sm:grid-cols-2">
              {Object.entries(ev.model).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b py-1.5">
                  <dt className="shrink-0 text-muted-foreground">{k.replace(/([A-Z])/g, ' $1').toLowerCase()}</dt>
                  <dd className="text-right font-mono text-[12px]">{Array.isArray(v) ? v.join(', ') : String(v)}</dd>
                </div>
              ))}
            </dl>
          </Section>
        </>
      )}
    </div>
  )
}

function Fact({ label, value, note }: { label: React.ReactNode; value: string; note: string }) {
  return (
    <div className="rounded-lg border bg-card p-3 shadow-card">
      <p className="text-[12px] text-muted-foreground">{label}</p>
      <p className="figure mt-1 text-[22px] font-semibold leading-tight">{value}</p>
      <p className="mt-1 text-[11.5px] text-muted-foreground">{note}</p>
    </div>
  )
}

/** Train, validation and test as a strip over the ten days. */
function SplitTimeline({ ev }: { ev: TemporalEvaluation }) {
  const parts: { key: 'train' | 'val' | 'test'; label: string; cls: string }[] = [
    { key: 'train', label: 'Train (model weights)', cls: 'bg-brand-soft text-brand-2' },
    { key: 'val', label: 'Validation (threshold)', cls: 'bg-sev-medium-bg text-sev-medium' },
    { key: 'test', label: 'Test (every number here)', cls: 'bg-ok-bg text-ok' },
  ]
  const start = new Date(ev.split.train[0]).getTime()
  const end = new Date(ev.split.test[1]).getTime()
  return (
    <section className="grid gap-2">
      <div className="flex overflow-hidden rounded-lg border text-[12px]">
        {parts.map(p => {
          const [a, b] = ev.split[p.key].map(x => new Date(x).getTime())
          return (
            <div key={p.key} className={cn('px-3 py-2', p.cls)} style={{ width: `${((b - a) / (end - start)) * 100}%` }}>
              <p className="font-medium">{p.label}</p>
              <p className="opacity-80">
                {day(ev.split[p.key][0])} – {day(new Date(new Date(ev.split[p.key][1]).getTime() - 1).toISOString())}
              </p>
            </div>
          )
        })}
      </div>
      <p className="text-[12px] text-muted-foreground">
        {ev.dataset.rows.toLocaleString('en-IN')} payments in <code className="font-mono">{ev.dataset.file}</code>, split by day. {ev.test.thresholdSource}: {ev.test.threshold.toFixed(2)}.
        Scores are {ev.dataset.scores}.
      </p>
    </section>
  )
}

function EngineTable({ report, title }: { report: EngineReport; title: string }) {
  return (
    <div className="grid gap-2">
      <p className="text-[13px] font-medium">{title}</p>
      <Table head={['Target TPS', 'Accounts', 'Sustained', 'Tick p50 / p99', 'Scoring p50', 'Rules p50', 'Payment latency p50 / p99', 'Keeps up']} right={[0, 1, 2]}>
        {report.runs.map(r => (
          <tr key={r.targetTps} className="border-b last:border-0">
            <td className="py-1.5 pr-3 text-right tabular-nums">{r.targetTps.toLocaleString('en-IN')}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums">{r.accounts?.toLocaleString('en-IN') ?? '—'}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums">{r.sustainedTps.toLocaleString('en-IN')}</td>
            <td className="py-1.5 pr-3 font-mono text-[12px]">{r.tickMs.p50} / {r.tickMs.p99} ms</td>
            <td className="py-1.5 pr-3 font-mono text-[12px]">{r.scoreMs.p50} ms</td>
            <td className="py-1.5 pr-3 font-mono text-[12px]">{r.rulesMs.p50} ms</td>
            <td className="py-1.5 pr-3 font-mono text-[12px]">{r.paymentLatencyMs.p50} / {r.paymentLatencyMs.p99} ms</td>
            <td className={cn('py-1.5', r.keepsUp ? (r.p99WithinTick === false ? 'text-sev-medium' : 'text-ok') : 'text-sev-critical')}>
              {r.keepsUp ? (r.p99WithinTick === false ? 'on average' : 'yes') : 'no'}
            </td>
          </tr>
        ))}
      </Table>
    </div>
  )
}

function LoadSection({ load }: { load: LoadReport | null }) {
  const eng = load?.loadtest
  const cached = load?.loadtest_cached
  const http = load?.loadtest_http
  if (!eng && !cached && !http) {
    return (
      <Section title="Throughput and latency" note="python -m infra.loadtest">
        <p className="text-[13px] text-muted-foreground">No load-test report on this bridge yet.</p>
      </Section>
    )
  }
  return (
    <Section title="Throughput and latency" note={eng ? `${eng.hardware.cpu} · ${eng.hardware.logicalCpus} logical CPUs${eng.hardware.ramGb ? ` · ${eng.hardware.ramGb} GB` : ''} · ${eng.at}` : ''}>
      <p className="mb-3 max-w-3xl text-[13px] leading-relaxed">
        In process: payments resampled from the v2 accounts, spread over one copy of the account space per 100 TPS and seeded with 72 hours of history, go through
        the scorer and the r2.0 rules in 0.5-second micro-batches, as the bridge runs them. A laptop, not a server: read these as a floor. One process holds the whole
        window; at real volume the scorer would be sharded by account.
      </p>
      <div className="grid gap-4">
        {eng && <EngineTable report={eng} title="Exact 2-hop scoring" />}
        {cached && (
          <EngineTable
            report={cached}
            title={`Cached layer-1 embeddings, refreshed every ${cached.runs[0]?.refreshSeconds ?? '—'} s (one refresh: ${cached.runs.map(r => `${r.lastRefreshMs ?? '—'} ms`).join(' / ')})`}
          />
        )}
      </div>
      {http && (
        <div className="mt-4">
          <p className="mb-2 text-[13px]">Over HTTP, into a running bridge&apos;s webhook ({http.seconds} s per rate):</p>
          <Table head={['Target TPS', 'Offered', 'Ingested', '429s', 'HTTP p50 / p99', 'Sent → ingested p50 / p99']} right={[0, 1, 2, 3]}>
            {http.runs.map(r => (
              <tr key={r.targetTps} className="border-b last:border-0">
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.targetTps.toLocaleString('en-IN')}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.offeredTps.toLocaleString('en-IN')}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.ingestedTps.toLocaleString('en-IN')}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.rejected429}</td>
                <td className="py-1.5 pr-3 font-mono text-[12px]">{r.httpMs.p50} / {r.httpMs.p99} ms</td>
                <td className="py-1.5 font-mono text-[12px]">
                  {r.endToEndMs.p50 ?? '—'} / {r.endToEndMs.p99 ?? '—'} ms
                </td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </Section>
  )
}

/** The test-day numbers up front, each with where it comes from. */
function Headline({ ev }: { ev: TemporalEvaluation }) {
  const t = ev.test.atThreshold
  const cards: { title: string; where: string; p: number; r: number; f1: number; note: string }[] = [
    { title: 'GNN on test-day payments', where: `edge level · threshold ${ev.test.threshold.toFixed(2)} from validation`, p: t.precision, r: t.recall, f1: t.f1, note: `ROC AUC ${f2(ev.test.rocAuc)} · average precision ${f2(ev.test.averagePrecision)}` },
    { title: 'Rules only', where: 'account level · test days', p: ev.detectors.accountLevel.precision, r: ev.detectors.accountLevel.recall, f1: ev.detectors.accountLevel.f1, note: `${ev.detectors.accountLevel.tp} of ${ev.detectors.mulesActive} active mules` },
    { title: 'Rules + GNN leads', where: 'account level · test days', p: ev.detectors.combined.precision, r: ev.detectors.combined.recall, f1: ev.detectors.combined.f1, note: `${ev.detectors.combined.tp} of ${ev.detectors.mulesActive} active mules` },
  ]
  const p10 = ev.detectors.precisionAtK.find(p => p.k === 10)
  return (
    <section className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-3">
        {cards.map(c => (
          <div key={c.title} className="rounded-lg border bg-card p-4 shadow-card">
            <p className="text-[13.5px] font-semibold">{c.title}</p>
            <p className="text-[11.5px] text-muted-foreground">{c.where}</p>
            <dl className="mt-3 grid grid-cols-3 gap-2">
              {[
                ['Precision', pct(c.p)],
                ['Recall', pct(c.r)],
                ['F1', c.f1.toFixed(2)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[11.5px] text-muted-foreground">{k}</dt>
                  <dd className="figure text-[22px] font-semibold leading-tight">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-[11.5px] text-muted-foreground">{c.note}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <Fact label={<Term k="precision">Precision@10 of the queue</Term>} value={p10 ? pct(p10.precision) : '—'} note="mules among the first 10 accounts an analyst opens" />
        <Fact label="Alerts per analyst per day" value={ev.detectors.alertsPerAnalystPerDay.toFixed(1)} note={`${ev.detectors.alertsPerDay.toFixed(1)} a day, team of ${ev.detectors.analysts}`} />
        <Fact label="Lead time, median / p10" value={`${duration(ev.detectors.leadSeconds.median)} / ${ev.detectors.leadSeconds.p10 !== null && ev.detectors.leadSeconds.p10 < 0 ? `−${duration(-ev.detectors.leadSeconds.p10)}` : duration(ev.detectors.leadSeconds.p10)}`} note="alert → money first leaves a mule" />
        <Fact label="Fraud money stopped" value={inrShort(ev.policy.fraudStopped)} note={`${pct(ev.policy.fraudTotal ? ev.policy.fraudStopped / ev.policy.fraudTotal : null)} of ${inr(ev.policy.fraudTotal)} on the test days`} />
      </div>
    </section>
  )
}
