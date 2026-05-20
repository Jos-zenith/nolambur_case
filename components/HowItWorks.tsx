'use client'

import { BarChart3, Lock, TrendingUp, Zap } from 'lucide-react'

export function HowItWorks() {
  const steps = [
    {
      number: '1',
      title: 'Detect',
      description: 'T-GNN spots mule chains and suspicious patterns in real-time',
      icon: Zap,
      stat: '94.2% accuracy',
    },
    {
      number: '2',
      title: 'Freeze',
      description: 'ZKP-based instant cross-state account freeze in 2.8 seconds',
      icon: Lock,
      stat: '28 states covered',
    },
    {
      number: '3',
      title: 'Recover',
      description: 'Golden Hour window recovery before money exits banking system',
      icon: TrendingUp,
      stat: '₹22.495 Cr recovered',
    },
  ]

  return (
    <section className="border-t border-border/60 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mb-16 text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">How It Works</p>
          <h2 className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl">Three-Stage Detection Pipeline</h2>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">From pattern recognition to recovery, every second counts in the fight against digital arrest scams.</p>
        </div>

        <div className="grid gap-8 md:grid-cols-3">
          {steps.map((step, idx) => {
            const Icon = step.icon
            return (
              <div key={idx} className="group relative">
                {/* Connector line for desktop */}
                {idx < steps.length - 1 && (
                  <div className="absolute -right-4 top-16 hidden h-0.5 w-8 bg-gradient-to-r from-red-500/60 to-transparent md:block" />
                )}

                <div className="rounded-2xl border border-border/60 bg-card/50 p-8 backdrop-blur-sm transition-all duration-300 group-hover:-translate-y-1 group-hover:border-primary/60 group-hover:bg-card/80 group-hover:shadow-lg">
                  {/* Step number */}
                  <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-r from-red-500/20 to-orange-500/20">
                    <span className="text-lg font-bold text-red-400">{step.number}</span>
                  </div>

                  {/* Icon */}
                  <div className="mb-4 rounded-xl border border-border/40 bg-secondary/20 p-3 w-fit">
                    <Icon className="h-6 w-6 text-primary" />
                  </div>

                  {/* Content */}
                  <h3 className="mb-2 text-2xl font-semibold text-foreground">{step.title}</h3>
                  <p className="mb-4 text-sm leading-6 text-muted-foreground">{step.description}</p>

                  {/* Stat badge */}
                  <div className="inline-block rounded-full border border-border/60 bg-secondary/20 px-3 py-1 text-xs font-semibold text-primary">
                    {step.stat}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
