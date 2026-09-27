'use client'

import { useEffect, useState } from 'react'

import { Section, Table } from '@/components/rail/bits'
import { ScoreHistogram, TrainingCurve } from '@/components/rail/charts'
import { duration, inr, pct } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'

type PRF = { tp: number; fp: number; fn: number; precision: number; recall: number; f1: number }
type Evaluation = {
  dataset: { file: string; rows: number; accounts: number; fraudRows: number; start: string; end: string; fraudWindow: [string, string] }
  model: Record<string, string | number | string[] | null>
  trainingLog: {
    epochs: { epoch: number; train: number; val: number; test: number }[]
    test: { edges: number; positives: number; flagged: number; f1: number; precision: number; recall: number; loggedAt: string } | null
    lastEpochAt: string | null
    runsInLog: number
  }
  inSample: {
    thresholds: (PRF & { threshold: number })[]
    perLayer: { layer: string; rows: number; flaggedAt0_9: number; amountMin: number; amountMax: number; amountMedian: number }[]
    histogram: { bin: string; fraud: number; clean: number }[]
  }
  amountRule: PRF & { name: string }
  detectors: {
    accountLevel: PRF
    combined: PRF
    modelOnlyAccounts: number
    modelOnlyMules: number
    mulesLabelled: number
    mulesInTransactions: number
    mulesSendOnly: number
    medianLeadSec: number | null
    byDetector: { detector: string; label: string; alerts: number; mules: number; precision: number | null }[]
  }
}

const PIPELINE = [
  ['nolambur_synthetic_gen.py', 'generates the scam and clean traffic'],
  ['nolambur_transactions.csv', '30,353 rows · labels in nolambur_labels.csv'],
  ['prepare_datasets.py', 'encodes accounts, timestamps, amounts as a graph'],
  ['finetune_local_nolambur.py', 'trains GINe, writes the checkpoint + norm stats'],
  ['bridge_api.py', 'scores every edge in one full-graph pass; /predict for new edges'],
  ['rail_engine.py', 'replays rows in time order, runs rules, serves /rail'],
  ['agents/tools_impl.py', 'investigate, freeze, 1930 report, SMS → action_log.jsonl'],
  ['This console', 'Next.js; proxies /api/rail to the bridge'],
]

export default function ModelPage() {
  const [ev, setEv] = useState<Evaluation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const backend = useRail(s => s.backend)

  useEffect(() => {
    if (ev) return
    fetch('/api/rail/evaluation', { cache: 'no-store' })
      .then(async r => (r.ok ? setEv(await r.json()) : setError(r.status === 503 ? 'The bridge is still warming up.' : 'The GNN bridge is not running.')))
      .catch(() => setError('The GNN bridge is not running.'))
  }, [backend, ev])

  return (
    <div className="grid max-w-5xl gap-8">
      <div>
        <h1 className="text-[18px] font-semibold">Model and evaluation</h1>
        <p className="mt-1 max-w-3xl text-[13.5px] leading-relaxed text-muted-foreground">
          How the pieces fit, what the GIN checkpoint scores, and how the console&apos;s detectors perform against the dataset labels. Every number here is
          computed by the bridge from the files in <code className="font-mono">Multi-GNN/</code> when it starts.
        </p>
      </div>

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

      {!ev ? (
        <p className="border bg-card p-4 text-[13px] text-muted-foreground">{error ?? 'Loading evaluation from the bridge…'}</p>
      ) : (
        <>
          <Section title="Detectors against the labels" note="account level · all 30,353 rows replayed with no analyst action">
            <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed">
              Rules alone find <b>{pct(ev.detectors.accountLevel.recall)}</b> of the {ev.detectors.mulesInTransactions} mule accounts that appear in any
              transaction, at <b>{pct(ev.detectors.accountLevel.precision)}</b> precision. Adding the model&apos;s leads lifts recall to{' '}
              <b>{pct(ev.detectors.combined.recall)}</b> at the same precision.{' '}
              {ev.detectors.combined.fn === ev.detectors.mulesSendOnly
                ? `All ${ev.detectors.combined.fn} still missed are first-layer mules that only ever send money in this data, so nothing on the receiving side can see them.`
                : `Of the ${ev.detectors.combined.fn} still missed, ${ev.detectors.mulesSendOnly} are first-layer mules that only ever send money in this data, so nothing on the receiving side can see them.`}
              Median lead time from alert to the money moving on: <b>{duration(ev.detectors.medianLeadSec)}</b>.
            </p>
            <Table head={['Approach', 'Accounts flagged', 'Mules caught', 'False positives', 'Precision', 'Recall', 'F1']} right={[1, 2, 3, 4, 5, 6]}>
              {[
                ['Rules only', ev.detectors.accountLevel],
                ['Rules + model leads', ev.detectors.combined],
              ].map(([name, m]) => {
                const p = m as PRF
                return (
                  <tr key={name as string} className="border-b last:border-0">
                    <td className="py-1.5 pr-3">{name as string}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{p.tp + p.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{p.tp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{p.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{pct(p.precision)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{pct(p.recall)}</td>
                    <td className="py-1.5 text-right tabular-nums">{p.f1.toFixed(2)}</td>
                  </tr>
                )
              })}
            </Table>
            <div className="mt-4">
              <Table head={['Detector', 'Accounts alerted', 'Of which mules', 'Precision']} right={[1, 2, 3]}>
                {ev.detectors.byDetector.map(d => (
                  <tr key={d.detector} className="border-b last:border-0">
                    <td className="py-1.5 pr-3">{d.label}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{d.alerts}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{d.mules}</td>
                    <td className="py-1.5 text-right tabular-nums">{pct(d.precision)}</td>
                  </tr>
                ))}
              </Table>
            </div>
            <p className="mt-2 text-[12px] text-muted-foreground">
              {ev.detectors.mulesLabelled} accounts are labelled as mules; {ev.detectors.mulesLabelled - ev.detectors.mulesInTransactions} of them never appear in
              a transaction and are left out of recall.
            </p>
          </Section>

          <Section title="Training run" note={`last finetune in logs/logs.log · ${ev.trainingLog.lastEpochAt ?? ''}`}>
            <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
              <div className="border bg-card p-3">
                <TrainingCurve epochs={ev.trainingLog.epochs} />
              </div>
              {ev.trainingLog.test && (
                <dl className="grid content-start gap-2 border bg-card p-3 text-[13px]">
                  <p className="font-medium">Held-out test split</p>
                  {[
                    ['Edges', ev.trainingLog.test.edges.toLocaleString('en-IN')],
                    ['Fraud edges', String(ev.trainingLog.test.positives)],
                    ['Flagged', String(ev.trainingLog.test.flagged)],
                    ['Precision', ev.trainingLog.test.precision.toFixed(3)],
                    ['Recall', ev.trainingLog.test.recall.toFixed(3)],
                    ['F1', ev.trainingLog.test.f1.toFixed(3)],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between border-b pb-1 last:border-0">
                      <dt className="text-muted-foreground">{k}</dt>
                      <dd className="font-mono">{v}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </Section>

          <Section title="Why these numbers are high, and what they do not show">
            <ul className="grid max-w-3xl list-disc gap-1.5 pl-5 text-[13.5px] leading-relaxed">
              <li>
                The data is synthetic, and the generator makes fraud easy to separate. Every victim transfer is ₹5.0–5.5 lakh; no clean transfer is
                above ₹2 lakh. A single amount rule catches {ev.amountRule.tp} of {ev.amountRule.tp + ev.amountRule.fn}{' '}fraud edges with {ev.amountRule.fp}{' '}false
                positives. The model&apos;s real contribution is the {ev.inSample.perLayer.find(l => l.layer.startsWith('L1'))?.rows} second-hop transfers,
                whose amounts ({inr(ev.inSample.perLayer.find(l => l.layer.startsWith('L1'))?.amountMin ?? 0)}–
                {inr(ev.inSample.perLayer.find(l => l.layer.startsWith('L1'))?.amountMax ?? 0)}) overlap clean traffic.
              </li>
              <li>
                All {ev.dataset.fraudRows} fraud rows happen in under five minutes ({ev.dataset.fraudWindow[0].slice(11)} to {ev.dataset.fraudWindow[1].slice(11)}),
                so the train, validation and test splits are random edges from the same event, inside the same graph. That measures fit to this event,
                not generalisation to a new scam.
              </li>
              <li>
                The scores on this console come from one pass over the full graph, which includes rows the replay has not reached yet. The live{' '}
                <code className="font-mono">/predict</code> path in the investigation panel only uses the chain you send it.
              </li>
              <li>No IBM AML pretraining: that stage needs a GPU. The checkpoint is finetuned on Nolambur alone.</li>
            </ul>
          </Section>

          <Section title="Scores the checkpoint gives" note="in-sample: every edge of the graph it was trained on">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="border bg-card p-3">
                <ScoreHistogram bins={ev.inSample.histogram} klass="fraud" title={`Fraud edges (${ev.dataset.fraudRows})`} />
              </div>
              <div className="border bg-card p-3">
                <ScoreHistogram bins={ev.inSample.histogram} klass="clean" title={`Clean edges (${(ev.dataset.rows - ev.dataset.fraudRows).toLocaleString('en-IN')})`} />
              </div>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <Table head={['Threshold', 'Flagged', 'False positives', 'Precision', 'Recall', 'F1']} right={[1, 2, 3, 4, 5]}>
                {ev.inSample.thresholds.map(t => (
                  <tr key={t.threshold} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-mono">{t.threshold.toFixed(2)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.tp + t.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.fp}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.precision.toFixed(3)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{t.recall.toFixed(3)}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.f1.toFixed(3)}</td>
                  </tr>
                ))}
              </Table>
              <Table head={['Layer', 'Rows', 'Scored ≥ 0.9', 'Amount range', 'Median']} right={[1, 2, 4]}>
                {ev.inSample.perLayer.map(l => (
                  <tr key={l.layer} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-mono">{l.layer}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{l.rows.toLocaleString('en-IN')}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{l.flaggedAt0_9}</td>
                    <td className="py-1.5 pr-3 font-mono text-[12px]">
                      {inr(l.amountMin)}–{inr(l.amountMax)}
                    </td>
                    <td className="py-1.5 text-right font-mono text-[12px]">{inr(l.amountMedian)}</td>
                  </tr>
                ))}
              </Table>
            </div>
          </Section>

          <Section title="Checkpoint">
            <dl className="grid gap-x-6 border bg-card p-3 text-[13px] sm:grid-cols-2">
              {Object.entries(ev.model).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b py-1.5">
                  <dt className="text-muted-foreground">{k.replace(/([A-Z])/g, ' $1').toLowerCase()}</dt>
                  <dd className="text-right font-mono text-[12px]">{Array.isArray(v) ? v.join(', ') : typeof v === 'number' && !Number.isInteger(v) ? v.toPrecision(3) : String(v)}</dd>
                </div>
              ))}
            </dl>
          </Section>
        </>
      )}
    </div>
  )
}
