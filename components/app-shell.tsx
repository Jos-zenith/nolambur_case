'use client'

import { ShieldHalf } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { clock } from '@/lib/rail/format'
import { useRail, useRailStream, useRoles } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Overview' },
  { href: '/console', label: 'Alert queue' },
  { href: '/onboarding', label: 'Onboarding' },
  { href: '/cases', label: 'Cases' },
  { href: '/model', label: 'Model' },
  { href: '/platform', label: 'Platform' },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  useRailStream()
  const pathname = usePathname()

  return (
    <div className="min-h-screen">
      <header className="no-print sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto flex h-14 max-w-[1440px] items-stretch gap-6 px-4">
          <Link href="/" className="flex shrink-0 items-center gap-2.5 whitespace-nowrap">
            <span className="grid size-7 place-items-center rounded-[5px] bg-brand-1 text-white">
              <ShieldHalf className="size-4" strokeWidth={2} />
            </span>
            <span className="hidden leading-tight sm:block">
              <span className="block text-[14px] font-semibold tracking-tight">Merchant Risk Console</span>
              <span className="block text-[11px] text-muted-foreground">Operation Nolambur</span>
            </span>
          </Link>
          <nav className="flex items-stretch gap-1 overflow-x-auto">
            {NAV.map(item => {
              const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    '-mb-px flex items-center whitespace-nowrap border-b-2 px-2.5 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground',
                    active ? 'border-brand-1 font-medium text-foreground' : 'border-transparent',
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <BackendStatus />
            <ActorPicker />
          </div>
        </div>
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
    <label className="flex shrink-0 items-center gap-2 border-l pl-4 text-[12px] text-muted-foreground" title="The bridge checks this user's role on every action and records it in the audit trail.">
      <span className="hidden xl:inline">Signed in as</span>
      <select value={actor ?? ''} onChange={e => setActor(e.target.value)} className="h-8 rounded-[5px] border bg-card px-2 text-[12.5px] text-foreground">
        {roles.users.map(u => (
          <option key={u.actor} value={u.actor}>
            {u.actor} ({u.role})
          </option>
        ))}
      </select>
    </label>
  )
}

function BackendStatus() {
  const backend = useRail(s => s.backend)
  const m = useRail(s => s.metrics)
  const paused = useRail(s => s.paused)

  const dot = backend === 'live' ? 'text-ok' : backend === 'warming' || backend === 'connecting' ? 'text-sev-medium' : 'text-sev-critical'
  const label = { live: 'Bridge live', warming: 'Bridge warming up', connecting: 'Connecting', offline: 'Bridge offline', error: 'Bridge error' }[backend]

  return (
    <div className="hidden items-center gap-4 text-[12px] text-muted-foreground lg:flex">
      <span className="flex items-center gap-1.5" title="FastAPI GNN bridge (Multi-GNN/bridge_api.py)">
        <span className={cn('size-1.5 rounded-full bg-current', dot)} />
        {label}
      </span>
      {m && backend === 'live' && (
        m.rowsTotal === null ? (
          <span className="hidden 2xl:inline" title={`Stream mode: payments arrive from ${m.source}; the clock is the latest payment's time`}>
            Live · {m.source} <span className="font-mono text-foreground">{clock(m.simT)}</span> ·{' '}
            <span className="font-mono text-foreground">{m.ingested.toLocaleString('en-IN')}</span> payments · {paused ? 'paused' : 'listening'}
          </span>
        ) : (
          <span className="hidden 2xl:inline" title="Replaying nolambur_transactions.csv in timestamp order">
            Replay <span className="font-mono text-foreground">{clock(m.simT)}</span> · row{' '}
            <span className="font-mono text-foreground">{m.rowsReplayed.toLocaleString('en-IN')}</span>/{m.rowsTotal.toLocaleString('en-IN')} ·{' '}
            {paused ? 'paused' : m.done ? 'finished' : `${m.speed}×`}
            {m.ingested > 0 && <> · +{m.ingested} ingested</>}
          </span>
        )
      )}
    </div>
  )
}
