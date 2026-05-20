'use client'

import { Shield, Database, Lock, Zap } from 'lucide-react'

export function TrustBar() {
  const trust = [
    { label: 'Neo4j', icon: Database, description: '127K mule nodes tracked' },
    { label: 'NPCI Compliant', icon: Shield, description: 'Banking API certified' },
    { label: 'Zero-Knowledge', icon: Lock, description: 'Circom + SnarkyJS' },
    { label: '340ms Detection', icon: Zap, description: 'Real-time T-GNN inference' },
  ]

  return (
    <section className="border-t border-border/60 bg-secondary/5 py-16 sm:py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <p className="text-center text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">Powered By</p>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {trust.map((item, idx) => {
            const Icon = item.icon
            return (
              <div key={idx} className="rounded-xl border border-border/60 bg-card/40 p-6 text-center backdrop-blur-sm">
                <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-border/60 bg-secondary/20">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <p className="font-semibold text-foreground">{item.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
