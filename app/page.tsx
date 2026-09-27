import Link from 'next/link'

import { BackendGate } from '@/components/rail/BackendGate'
import { MetricStrip } from '@/components/rail/MetricStrip'

export const metadata = {
  title: 'Merchant Risk Console',
  description: 'Mule-chain detection for a payment aggregator: a GNN-scored replay of UPI transactions, rule detectors, analyst actions and evidence packs.',
}

const DETECTORS = [
  {
    pattern: 'Victims pushed into large transfers',
    rule: '₹4.5 lakh or more from a payer who has never paid this account before, from another state.',
    name: 'High-value inflow from new payers',
  },
  {
    pattern: 'First-layer mules forwarding money',
    rule: 'Within 60 minutes, ₹2 lakh or more comes in and at least 60% of it leaves in two or more transfers.',
    name: 'Rapid pass-through',
  },
  {
    pattern: 'The next hop in the chain',
    rule: 'Money received from an account a rule flagged in the last 24 hours, or one that is frozen. Propagates one hop only.',
    name: 'Funds from a flagged account',
  },
  {
    pattern: 'Structure the rules miss',
    rule: 'The GIN checkpoint scores an inbound transfer at 0.9 or higher and no rule has fired. A lead, not a finding.',
    name: 'Model-only flag',
  },
]

const STATUS = [
  { part: 'Transactions', state: 'Real data', note: 'nolambur_transactions.csv, replayed row by row in timestamp order. Synthetic dataset, not a bank feed.' },
  { part: 'GNN score on every row', state: 'Working', note: 'Trained GIN checkpoint, one full-graph pass at bridge start-up (about 30 s on CPU).' },
  { part: 'Detectors, queue, lead time', state: 'Working', note: 'Multi-GNN/rail_engine.py. Detectors never read the fraud labels.' },
  { part: 'Precision and recall', state: 'Working', note: 'Measured against nolambur_labels.csv, live in the console and for the full dataset on the model page.' },
  { part: 'Agent investigation', state: 'Working', note: 'score_transfer_chain calls /predict live; check_suspect_registry is a labelled mock.' },
  { part: 'Freeze, 1930 report, SMS', state: 'Simulated', note: 'Agent tools write to agents/action_log.jsonl. No bank, NPCI or CFCFRMS call. SMS is real only with Twilio keys.' },
  { part: 'Director / MCA linkage', state: 'Not built', note: 'The dataset has no company or director data. The onboarding check uses transaction links instead.' },
]

export default function Home() {
  return (
    <div className="grid gap-8">
      <section className="grid gap-4 border-b pb-8 lg:grid-cols-[1.2fr_1fr] lg:gap-10">
        <div>
          <p className="text-[12px] font-medium uppercase tracking-wide text-muted-foreground">Operation Nolambur · payment aggregator risk</p>
          <h1 className="mt-2 max-w-2xl text-[30px] font-semibold leading-tight tracking-tight">Freeze the mule before the money moves on.</h1>
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            Scam money reaches a first-layer mule and is forwarded within minutes. This console replays a UPI dataset through a trained graph neural
            network and rule detectors, raises alerts while the money is still in the first account, and gives an analyst the trail, the agent
            tools and an evidence pack to act on.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link href="/console" className="grid h-9 place-items-center rounded-sm bg-primary px-4 text-[13px] font-medium text-primary-foreground hover:opacity-90">
              Open the alert queue
            </Link>
            <Link href="/model" className="grid h-9 place-items-center rounded-sm border bg-card px-4 text-[13px] font-medium hover:bg-accent">
              See the model and evaluation
            </Link>
          </div>
        </div>
        <div className="grid content-start gap-3 text-[13.5px]">
          <Step n="1" title="Onboarding" href="/onboarding">
            A merchant&apos;s settlement VPA is checked against the transaction graph. Direct transfers with flagged accounts put it on hold.
          </Step>
          <Step n="2" title="Live monitoring" href="/console">
            Every row is scored and checked as it arrives. The analyst clears, escalates or freezes, and must write down why.
          </Step>
          <Step n="3" title="Incident response" href="/cases">
            Linked accounts group into cases, with an evidence pack and a 1930 report filed through the agent tools.
          </Step>
        </div>
      </section>

      <section className="grid gap-3">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-[15px] font-semibold">Running now</h2>
          <Link href="/console" className="text-[13px] text-primary underline underline-offset-2">Go to queue</Link>
        </div>
        <BackendGate>
          <MetricStrip />
        </BackendGate>
      </section>

      <section className="grid gap-3">
        <h2 className="text-[15px] font-semibold">Detectors</h2>
        <div className="overflow-x-auto border bg-card">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b text-left text-[12px] text-muted-foreground">
                <th className="px-4 py-2 font-normal">What happens in a mule chain</th>
                <th className="px-4 py-2 font-normal">What fires the alert</th>
                <th className="px-4 py-2 font-normal">Detector</th>
              </tr>
            </thead>
            <tbody>
              {DETECTORS.map(d => (
                <tr key={d.name} className="border-b align-top last:border-0">
                  <td className="px-4 py-2.5 font-medium">{d.pattern}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{d.rule}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">{d.name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-3">
        <h2 className="text-[15px] font-semibold">What is real</h2>
        <div className="overflow-x-auto border bg-card">
          <table className="w-full text-[13px]">
            <tbody>
              {STATUS.map(s => (
                <tr key={s.part} className="border-b align-top last:border-0">
                  <td className="w-[28%] px-4 py-2.5 font-medium">{s.part}</td>
                  <td className="w-[110px] px-4 py-2.5">
                    <span className={s.state === 'Working' || s.state === 'Real data' ? 'text-ok' : s.state === 'Simulated' ? 'text-sev-medium' : 'text-muted-foreground'}>{s.state}</span>
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">{s.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="border-t pt-4 text-[12px] text-muted-foreground">
        Run it: <code className="font-mono">cd Multi-GNN && python bridge_api.py</code>, then <code className="font-mono">npm run dev</code>. All accounts and
        transactions come from the synthetic Nolambur dataset.
      </footer>
    </div>
  )
}

function Step({ n, title, href, children }: { n: string; title: string; href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="grid grid-cols-[28px_1fr] gap-3 border bg-card p-3 hover:border-primary/40">
      <span className="grid size-6 place-items-center rounded-sm border font-mono text-[12px]">{n}</span>
      <span>
        <span className="block font-medium">{title}</span>
        <span className="mt-0.5 block text-muted-foreground">{children}</span>
      </span>
    </Link>
  )
}
