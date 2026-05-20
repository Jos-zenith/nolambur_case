'use client'

import { ChevronDown } from 'lucide-react'

export function ScamExplainer() {
  return (
    <section className="border-t border-border/60 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mb-16 text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">Understanding the Threat</p>
          <h2 className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl">Digital Arrest Scam Anatomy</h2>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">How fraudsters use mule networks to move victim funds across state lines before recovery is possible.</p>
        </div>

        <div className="grid gap-8 lg:grid-cols-2">
          {/* Left: Flowchart */}
          <div className="rounded-2xl border border-border/60 bg-card/50 p-8 backdrop-blur-sm">
            <div className="space-y-6">
              {/* Layer 0: Victim */}
              <div className="rounded-xl border-2 border-blue-500/40 bg-blue-500/10 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">Layer 0</p>
                <p className="mt-2 font-semibold text-foreground">Victim</p>
                <p className="mt-1 text-sm text-muted-foreground">Digital arrest victim receives threatening call, transfers funds to "police account"</p>
              </div>

              <div className="flex justify-center">
                <ChevronDown className="h-5 w-5 text-muted-foreground/60" />
              </div>

              {/* Layer 1: Mules */}
              <div className="rounded-xl border-2 border-red-500/40 bg-red-500/10 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-red-400">Layer 1 — Mule Accounts</p>
                <p className="mt-2 font-semibold text-foreground">Direct receivers</p>
                <p className="mt-1 text-sm text-muted-foreground">3-12 accounts per scam, geographic spread (Haridwar, Jaipur, Rohtak), velocity 0.25-0.35 transfers/min</p>
              </div>

              <div className="flex justify-center">
                <ChevronDown className="h-5 w-5 text-muted-foreground/60" />
              </div>

              {/* Layer 2: Aggregators */}
              <div className="rounded-xl border-2 border-orange-500/40 bg-orange-500/10 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-orange-400">Layer 2 — Consolidators</p>
                <p className="mt-2 font-semibold text-foreground">Pool & relay nodes</p>
                <p className="mt-1 text-sm text-muted-foreground">1-3 accounts, consolidate funds, velocity 0.80-0.96 transfers/min, detect via in/out ratio anomaly</p>
              </div>

              <div className="flex justify-center">
                <ChevronDown className="h-5 w-5 text-muted-foreground/60" />
              </div>

              {/* Layer 3: Beneficiary */}
              <div className="rounded-xl border-2 border-purple-500/40 bg-purple-500/10 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-purple-400">Layer 3 — Exit Node</p>
                <p className="mt-2 font-semibold text-foreground">Final beneficiary</p>
                <p className="mt-1 text-sm text-muted-foreground">Out-of-state gateway, money withdraws to cash or international transfer, 2.8s from mule to exit</p>
              </div>
            </div>
          </div>

          {/* Right: Key insights */}
          <div className="space-y-6">
            <div className="rounded-xl border border-border/60 bg-card/50 p-6 backdrop-blur-sm">
              <h3 className="mb-3 font-semibold text-foreground">🚨 Detection Challenge</h3>
              <p className="text-sm leading-6 text-muted-foreground">Traditional rules miss the velocity spike because transfers happen in seconds across multiple accounts. The T-GNN learns temporal patterns of legitimate UPI vs. mule chains.</p>
            </div>

            <div className="rounded-xl border border-border/60 bg-card/50 p-6 backdrop-blur-sm">
              <h3 className="mb-3 font-semibold text-foreground">⏱️ The Golden Hour</h3>
              <p className="text-sm leading-6 text-muted-foreground">Money must exit the banking system within 60-90 minutes. After that, NPCI freeze is nearly impossible. Nolambur detects fraud in 340ms, freeze in 2.8s total.</p>
            </div>

            <div className="rounded-xl border border-border/60 bg-card/50 p-6 backdrop-blur-sm">
              <h3 className="mb-3 font-semibold text-foreground">🔐 Our Approach</h3>
              <p className="text-sm leading-6 text-muted-foreground">1) Graph-based detection (Neo4j). 2) Temporal neural network scoring (T-GNN). 3) Zero-knowledge proof for cross-state freezes. 4) Biometric duress check to confirm victim stress levels.</p>
            </div>

            <div className="rounded-xl border border-border/60 bg-card/50 p-6 backdrop-blur-sm">
              <h3 className="mb-3 font-semibold text-foreground">📊 Real Numbers</h3>
              <p className="text-sm leading-6 text-muted-foreground">NPCI reports 23.05L suspect accounts. Each active scam runs 3-12 mules and costs ₹1-5L per victim. Nolambur target: stop 90% before exit.</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
