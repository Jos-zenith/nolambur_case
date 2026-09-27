'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { clock } from '@/lib/rail/format'
import { useRail, useRailStream } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Overview' },
  { href: '/console', label: 'Alert queue' },
  { href: '/onboarding', label: 'Onboarding check' },
  { href: '/cases', label: 'Cases' },
  { href: '/model', label: 'Model & evaluation' },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  useRailStream()
  const pathname = usePathname()

  return (
    <div className="min-h-screen">
      <header className="no-print sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto flex h-12 max-w-[1440px] items-center gap-6 px-4">
          <Link href="/" className="flex shrink-0 items-center gap-2 whitespace-nowrap font-semibold tracking-tight">
            <span className="grid size-6 place-items-center rounded-sm bg-primary text-[11px] font-semibold text-primary-foreground">MR</span>
            <span className="hidden sm:inline">Merchant Risk Console</span>
          </Link>
          <nav className="flex h-full items-stretch gap-1 overflow-x-auto">
            {NAV.map(item => {
              const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center whitespace-nowrap border-b-2 px-2.5 text-[13px] text-muted-foreground hover:text-foreground',
                    active ? 'border-primary text-foreground' : 'border-transparent',
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
          <BackendStatus />
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-5">{children}</main>
    </div>
  )
}

function BackendStatus() {
  const backend = useRail(s => s.backend)
  const m = useRail(s => s.metrics)
  const paused = useRail(s => s.paused)

  const dot = backend === 'live' ? 'bg-ok' : backend === 'warming' || backend === 'connecting' ? 'bg-sev-medium' : 'bg-sev-critical'
  const label = { live: 'Bridge live', warming: 'Bridge warming up', connecting: 'Connecting', offline: 'Bridge offline', error: 'Bridge error' }[backend]

  return (
    <div className="ml-auto hidden items-center gap-4 text-[12px] text-muted-foreground lg:flex">
      <span className="flex items-center gap-1.5" title="FastAPI GNN bridge (Multi-GNN/bridge_api.py)">
        <span className={cn('size-1.5 rounded-full', dot)} />
        {label}
      </span>
      {m && backend === 'live' && (
        <span title="Replaying nolambur_transactions.csv in timestamp order">
          Replay <span className="font-mono text-foreground">{clock(m.simT)}</span> · row{' '}
          <span className="font-mono text-foreground">{m.rowsReplayed.toLocaleString('en-IN')}</span>/{m.rowsTotal.toLocaleString('en-IN')} ·{' '}
          {paused ? 'paused' : m.done ? 'finished' : `${m.speed}×`}
        </span>
      )}
    </div>
  )
}
