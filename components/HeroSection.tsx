'use client'

import { ArrowRight } from 'lucide-react'
import Link from 'next/link'

import { AnimatedCounter } from '@/components/animated-counter'
import { Button } from '@/components/ui/button'

export function HeroSection() {
  return (
    <section className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(239,68,68,0.18),_transparent_25%),radial-gradient(circle_at_bottom_right,_rgba(249,115,22,0.14),_transparent_30%),linear-gradient(180deg,#050505_0%,#0a0a0a_50%,#090909_100%)]">
      {/* Animated grid background */}
      <div className="pointer-events-none absolute inset-0 opacity-20 [background-image:linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] [background-size:64px_64px]" />

      {/* Pulsing accent orbs */}
      <div className="pointer-events-none absolute left-[10%] top-[15%] h-96 w-96 rounded-full bg-red-600/5 blur-3xl opacity-50 animate-pulse" />
      <div className="pointer-events-none absolute right-[8%] bottom-[20%] h-80 w-80 rounded-full bg-orange-600/5 blur-3xl opacity-40 animate-pulse [animation-delay:1.5s]" />

      <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col items-center justify-center gap-12 px-4 py-24 sm:px-6 lg:px-8">
        {/* Hero content */}
        <div className="text-center">
          <p className="mb-6 text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">
            Operation Nolambur
          </p>

          <h1 className="mb-6 text-5xl font-bold tracking-tight sm:text-6xl lg:text-7xl">
            <span className="block text-foreground">Stop UPI Fraud</span>
            <span className="block bg-gradient-to-r from-red-500 via-orange-500 to-yellow-500 bg-clip-text text-transparent">Before the Money Leaves</span>
          </h1>

          <p className="mx-auto mb-10 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Real-time fraud detection using Temporal Graph Neural Networks, Zero-Knowledge Proofs, and biometric duress analysis.
            Stop digital arrest scams in the golden hour.
          </p>

          <div className="flex flex-col gap-4 sm:flex-row sm:justify-center">
            <Button asChild size="lg" className="h-12 rounded-xl px-8">
              <Link href="/dashboard">
                Enter Command Center
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-12 rounded-xl px-8">
              <a href="#case-study">Read the Case Study</a>
            </Button>
          </div>
        </div>

        {/* Metrics row */}
        <div className="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { value: 22495, prefix: '₹', suffix: ' Cr', decimals: 0, sublabel: 'Annual loss target' },
            { value: 340, prefix: '', suffix: 'ms', decimals: 0, sublabel: 'Detection latency' },
            { value: 73.2, prefix: '', suffix: '%', decimals: 1, sublabel: 'Golden Hour recovery' },
            { value: 23, prefix: '', suffix: '', decimals: 0, sublabel: 'Accounts frozen' },
          ].map((metric, idx) => (
            <div key={idx} className="rounded-2xl border border-border/60 bg-card/40 p-4 backdrop-blur-xl transition hover:-translate-y-0.5 hover:shadow-[0_10px_28px_rgba(0,0,0,0.26)]">
              <p className="text-sm text-muted-foreground">{metric.sublabel}</p>
              <p className="mt-2 text-2xl font-bold text-foreground sm:text-3xl">
                <AnimatedCounter
                  value={metric.value}
                  prefix={metric.prefix}
                  suffix={metric.suffix}
                  decimals={metric.decimals}
                />
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
