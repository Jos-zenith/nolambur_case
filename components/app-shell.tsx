'use client'

import { Briefcase, Brain, LayoutDashboard, ListChecks, ScanSearch, Server, ShieldHalf, Store } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { clock, inrShort } from '@/lib/rail/format'
import { useWaitSeconds } from '@/components/rail/BackendGate'
import { Spark, useCountUp } from '@/components/rail/kit'
import { useRail, useRailStream, useRoles } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  { href: '/console', label: 'Alert queue', icon: ListChecks, badge: 'alerts' as const },
  { href: '/onboarding', label: 'Onboarding', icon: ScanSearch },
  { href: '/merchants', label: 'Merchants', icon: Store },
  { href: '/cases', label: 'Cases', icon: Briefcase },
  { href: '/model', label: 'Model', icon: Brain },
  { href: '/platform', label: 'Platform', icon: Server },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  useRailStream()
  const pathname = usePathname()
  const openAlerts = useRail(s => (s.backend === 'live' ? s.metrics?.openAlerts ?? null : null))
  const critical = useRail(s => (s.backend === 'live' ? s.metrics?.openBySeverity?.critical ?? 0 : 0))

  return (
    <div className="min-h-screen">
      <header className="no-print sticky top-0 z-30 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4">
          <Link href="/" className="flex shrink-0 items-center gap-2.5 whitespace-nowrap">
            <span className="grid size-8 place-items-center rounded-md bg-brand-1 text-white shadow-sm">
              <ShieldHalf className="size-4" strokeWidth={2} />
            </span>
            <span className="hidden leading-tight lg:block">
              <span className="block text-[14px] font-semibold tracking-tight">Merchant Risk Console</span>
              <span className="block text-[11px] text-muted-foreground">Operation Nolambur</span>
            </span>
          </Link>
          <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto overflow-y-hidden rounded-lg bg-muted/60 p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {NAV.map(item => {
              const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
              const count = item.badge === 'alerts' ? openAlerts : null
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? 'page' : undefined}
                  aria-label={item.label}
                  title={item.label}
                  className={cn(
                    'flex h-9 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[13.5px] transition-colors lg:px-3',
                    active ? 'bg-brand-1 font-semibold text-white shadow-sm' : 'font-medium text-muted-foreground hover:bg-card hover:text-foreground',
                  )}
                >
                  <item.icon className={cn('size-4 shrink-0', active ? 'text-white' : 'text-muted-foreground/80')} aria-hidden />
                  <span className={cn(!active && 'hidden md:inline')}>{item.label}</span>
                  {count !== null && count > 0 && (
                    <span
                      className={cn(
                        'figure min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold leading-[18px] tabular-nums',
                        critical > 0 ? 'bg-sev-critical text-white' : active ? 'bg-white/20 text-white' : 'bg-brand-soft text-brand-2',
                      )}
                      title={`${count} open alerts${critical ? `, ${critical} critical` : ''}`}
                    >
                      {count > 999 ? '999+' : count}
                    </span>
                  )}
                </Link>
              )
            })}
          </nav>
          <div className="ml-auto flex shrink-0 items-center">
            <ActorPicker />
          </div>
        </div>
        <LiveStrip />
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-6">{children}</main>
    </div>
  )
}

/** Who the console acts as. Stand-in for a login: the bridge enforces the role on every action. */
function ActorPicker() {
  const { roles, actor } = useRoles()
  const setActor = useRail(s => s.setActor)
  if (!roles) return null
  return (
    <label className="flex shrink-0 items-center gap-2 text-[12px] text-muted-foreground" title="The bridge checks this user's role on every action and records it in the audit trail.">
      <span className="hidden xl:inline">Signed in as</span>
      <select value={actor ?? ''} onChange={e => setActor(e.target.value)} className="h-8 max-w-[7.5rem] rounded-md border bg-card px-2 text-[12.5px] text-foreground sm:max-w-none">
        {roles.users.map(u => (
          <option key={u.actor} value={u.actor}>
            {u.actor} ({u.role})
          </option>
        ))}
      </select>
    </label>
  )
}

function Counter({ label, value, format = (v: number) => Math.round(v).toLocaleString('en-IN'), tone, className, title }: {
  label: string
  value: number
  format?: (v: number) => string
  tone?: 'critical' | 'warning' | 'ok'
  className?: string
  title?: string
}) {
  const v = useCountUp(value)
  return (
    <span className={cn('flex items-baseline gap-1.5 whitespace-nowrap', className)} title={title}>
      <span
        className={cn(
          'figure font-mono text-[13px] font-semibold tabular-nums text-foreground',
          tone === 'critical' && value > 0 && 'text-sev-critical',
          tone === 'warning' && value > 0 && 'text-sev-medium',
          tone === 'ok' && value > 0 && 'text-ok',
        )}
      >
        {format(v)}
      </span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}

/** The engine's pulse, on every page: mode, clock, progress and the numbers that move. */
function LiveStrip() {
  const backend = useRail(s => s.backend)
  const m = useRail(s => s.metrics)
  const paused = useRail(s => s.paused)
  const ticks = useRail(s => s.tickCounts)
  const seconds = useWaitSeconds()

  const live = backend === 'live' && m
  const waking = backend === 'connecting' || (backend === 'offline' && seconds < 90)
  const dot = live ? (paused ? 'text-sev-medium' : 'text-ok') : backend === 'warming' || waking ? 'text-sev-medium' : 'text-sev-critical'
  const status = live
    ? m.rowsTotal === null
      ? `Live · ${m.source}`
      : paused ? 'Replay paused' : m.done ? 'Replay finished' : `Replay · ${m.speed}×`
    : backend === 'warming' ? 'Bridge warming up' : waking ? `Waking bridge · ${seconds}s` : backend === 'error' ? 'Bridge error' : 'Bridge offline'
  const progress = live && m.rowsTotal ? Math.min(1, m.rowsReplayed / m.rowsTotal) : null

  return (
    <div className="border-t bg-muted/40">
      <div className="mx-auto flex h-9 max-w-[1440px] items-center gap-5 overflow-hidden px-4 text-[12px]">
        <span className="flex shrink-0 items-center gap-2 font-medium" title="FastAPI GNN bridge (Multi-GNN/bridge_api.py)">
          <span className={cn('size-2 rounded-full', dot, live && !paused && !m.done ? 'live-dot' : 'bg-current')} />
          {status}
        </span>
        {live ? (
          <>
            <span className="shrink-0 text-muted-foreground" title={m.rowsTotal === null ? "Event time of the latest payment" : 'Replay clock (dataset time)'}>
              <span className="font-mono text-[13px] font-semibold tabular-nums text-foreground">{clock(m.simT)}</span>
            </span>
            {m.rowsTotal !== null ? (
              <span className="hidden items-center gap-2 sm:flex">
                <Counter label={`of ${m.rowsTotal.toLocaleString('en-IN')} rows`} value={m.rowsReplayed} title="Rows of nolambur_transactions.csv replayed so far" />
                {progress !== null && (
                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-border" aria-hidden>
                    <span className="block h-full rounded-full bg-brand-2 transition-[width] duration-500 ease-out" style={{ width: `${Math.max(2, progress * 100)}%` }} />
                  </span>
                )}
              </span>
            ) : (
              <Counter label="payments" value={m.ingested} className="hidden sm:flex" />
            )}
            <span className="hidden items-center gap-2 md:flex" title="Payments per 0.5 s tick, last minute">
              <Spark data={ticks.slice(-40)} w={72} h={20} />
              <Counter label="/min" value={m.txnsLastMinute} />
            </span>
            <span className="ml-auto hidden h-4 w-px bg-border lg:block" />
            <Counter label="open alerts" value={m.openAlerts} tone={m.openBySeverity?.critical ? 'critical' : 'warning'} className="hidden lg:flex" />
            <Counter label="held" value={m.heldAccounts} tone="warning" className="hidden lg:flex" title="Accounts on automatic hold, awaiting a supervisor" />
            <Counter label="frozen" value={m.frozenAccounts} className="hidden xl:flex" />
            <Counter label="fraud blocked" value={m.blockedFraudAmount} format={inrShort} tone="ok" className="hidden xl:flex" title="Fraud money stopped by holds and freezes so far" />
          </>
        ) : (
          <span className="truncate text-muted-foreground">
            {waking || backend === 'warming' ? 'The free server sleeps when idle; pages show the last captured snapshot until it answers.' : 'Numbers on the pages come from the last captured snapshot.'}
          </span>
        )}
      </div>
    </div>
  )
}
