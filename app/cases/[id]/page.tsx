'use client'

import Link from 'next/link'
import { use, useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Score, SeverityBadge, Table, TruthTag } from '@/components/rail/bits'
import { duration, inr, stamp } from '@/lib/rail/format'
import { railPost } from '@/lib/rail/store'
import type { Alert, Profile, Row } from '@/lib/rail/types'

type Pack = {
  caseId: string
  generatedAt: string
  simT: number
  source: Record<string, string>
  summary: { accounts: number; alerts: number; transactions: number; moneyIn: number; exited: number; blocked: number }
  accounts: (Omit<Profile, 'frozen'> & { frozen: boolean; freeze: { reference: string | null } | null })[]
  alerts: Alert[]
  links: { fromVpa: string; toVpa: string; amount: number; ts: string; row: number }[]
  timeline: { simT: number; kind: string; text: string }[]
  transactions: Row[]
  report: Record<string, unknown> | null
}

export default function EvidencePackPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [pack, setPack] = useState<Pack | null>(null)
  const [missing, setMissing] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await fetch(`/api/rail/cases/${id}/evidence-pack`, { cache: 'no-store' })
    if (!res.ok) return setMissing(true)
    setPack(await res.json())
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const tool = async (kind: 'report' | 'notify') => {
    setBusy(kind)
    const { ok, data } = await railPost<{ tool: Record<string, unknown> }>(`cases/${id}/${kind}`)
    setBusy(null)
    if (!ok) return toast.error(data.error ?? 'Tool call failed')
    toast.success(kind === 'report' ? `1930 report filed: ${String(data.tool.acknowledgement_no ?? '')}` : `Officer notified (${String(data.tool.delivery ?? data.tool.status ?? 'sent')})`, {
      description: `${String(data.tool.tool)} · ${String(data.tool.note ?? 'logged to agents/action_log.jsonl')}`,
    })
    load()
  }

  const download = () => {
    if (!pack) return
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${pack.caseId}-evidence-pack.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (missing)
    return (
      <p className="text-[13px]">
        Case {id} was not found. Cases live in the bridge&apos;s memory and reset when the replay restarts.{' '}
        <Link href="/cases" className="text-primary underline">Back to cases</Link>
      </p>
    )
  if (!pack) return <div className="h-40 animate-pulse border bg-card" />

  return (
    <article className="mx-auto grid max-w-5xl gap-5 border bg-card p-6 print:border-0 print:p-0">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-4">
        <div>
          <p className="text-[12px] uppercase tracking-wide text-muted-foreground">Evidence pack</p>
          <h1 className="mt-0.5 font-mono text-[22px] font-semibold">{pack.caseId}</h1>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            Generated {pack.generatedAt.replace('T', ' ')} · replay time {stamp(pack.simT)}
          </p>
        </div>
        <div className="no-print flex flex-wrap gap-2">
          <button onClick={() => tool('notify')} disabled={busy !== null} className="h-8 rounded-sm border px-3 text-[13px] hover:bg-accent disabled:opacity-50">
            {busy === 'notify' ? 'Sending…' : 'Notify officer (SMS)'}
          </button>
          <button onClick={() => tool('report')} disabled={busy !== null || !!pack.report} className="h-8 rounded-sm border px-3 text-[13px] hover:bg-accent disabled:opacity-50">
            {pack.report ? 'Report filed' : busy === 'report' ? 'Filing…' : 'File 1930 report'}
          </button>
          <button onClick={download} className="h-8 rounded-sm border px-3 text-[13px] hover:bg-accent">Download JSON</button>
          <button onClick={() => window.print()} className="h-8 rounded-sm bg-primary px-3 text-[13px] font-medium text-primary-foreground hover:opacity-90">Print / save as PDF</button>
        </div>
      </header>

      <dl className="grid gap-x-6 gap-y-1 border-l-2 border-sev-medium bg-sev-medium-bg px-3 py-2 text-[12.5px] sm:grid-cols-2">
        {Object.entries(pack.source).map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono text-[12px]">{v}</dd>
          </div>
        ))}
      </dl>

      {pack.report && (
        <p className="border px-3 py-2 text-[13px]">
          1930 report acknowledgement <span className="font-mono">{String(pack.report.acknowledgement_no)}</span>{' '}
          <span className="text-muted-foreground">· {String(pack.report.note ?? '')}</span>
        </p>
      )}

      <dl className="grid grid-cols-2 border sm:grid-cols-6">
        {[
          ['Accounts', String(pack.summary.accounts)],
          ['Alerts', String(pack.summary.alerts)],
          ['Rows', String(pack.summary.transactions)],
          ['Money in', inr(pack.summary.moneyIn)],
          ['Sent onward', inr(pack.summary.exited)],
          ['Blocked', inr(pack.summary.blocked)],
        ].map(([k, v]) => (
          <div key={k} className="border-r p-3 last:border-r-0">
            <dt className="text-[12px] text-muted-foreground">{k}</dt>
            <dd className="mt-0.5 text-[15px] font-medium tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>

      <Block title="1. Accounts">
        <Table head={['VPA', 'Bank', 'State', 'In', 'Out', 'First in → out', 'Freeze ref', 'Label']}>
          {pack.accounts.map(a => (
            <tr key={a.accountId} className="border-b align-top last:border-0">
              <td className="py-1.5 pr-3 font-mono text-[12px]">{a.vpa}</td>
              <td className="py-1.5 pr-3">{a.bank}</td>
              <td className="py-1.5 pr-3">{a.state}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{inr(a.totalIn)}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{inr(a.totalOut)}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{a.firstInT && a.firstOutT ? duration(a.firstOutT - a.firstInT) : '—'}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{a.freeze?.reference ?? '—'}</td>
              <td className="py-1.5"><TruthTag role={a.truthRole} /></td>
            </tr>
          ))}
        </Table>
      </Block>

      <Block title="2. Transfers between case accounts">
        {pack.links.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">None of the case accounts transacted with each other.</p>
        ) : (
          <Table head={['CSV row', 'Time', 'From', 'To', 'Amount']} right={[4]}>
            {pack.links.map(l => (
              <tr key={l.row} className="border-b last:border-0">
                <td className="py-1.5 pr-3 font-mono text-[12px]">#{l.row}</td>
                <td className="py-1.5 pr-3 font-mono text-[12px]">{l.ts.replace('T', ' ')}</td>
                <td className="py-1.5 pr-3 font-mono text-[12px]">{l.fromVpa}</td>
                <td className="py-1.5 pr-3 font-mono text-[12px]">{l.toVpa}</td>
                <td className="py-1.5 text-right font-mono">{inr(l.amount)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Block>

      <Block title="3. Alerts">
        <Table head={['Alert', 'Severity', 'Detector', 'Account', 'Raised', 'Max GNN', 'Status']}>
          {pack.alerts.map(a => (
            <tr key={a.id} className="border-b last:border-0">
              <td className="py-1.5 pr-3 font-mono text-[12px]">{a.id}</td>
              <td className="py-1.5 pr-3"><SeverityBadge severity={a.severity} /></td>
              <td className="py-1.5 pr-3">{a.detectorLabel} <span className="text-[11px] text-muted-foreground">{a.ruleVersion}</span></td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{a.vpa}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{stamp(a.createdT)}</td>
              <td className="py-1.5 pr-3"><Score value={a.gnnMax} /></td>
              <td className="py-1.5 capitalize">{a.status}</td>
            </tr>
          ))}
        </Table>
      </Block>

      <Block title="4. Timeline">
        <ol className="text-[13px]">
          {pack.timeline.map((e, i) => (
            <li key={i} className="grid grid-cols-[130px_60px_1fr] gap-3 border-b py-1.5 last:border-0">
              <span className="font-mono text-[12px] text-muted-foreground">{stamp(e.simT)}</span>
              <span className="text-[12px] text-muted-foreground">{e.kind}</span>
              <span>{e.text}</span>
            </li>
          ))}
        </ol>
      </Block>

      <Block title={`5. Transactions (${pack.transactions.length} rows; the JSON has all of them)`}>
        <Table head={['CSV row', 'Time', 'From', 'To', 'Amount', 'GNN', 'Blocked']} right={[4]}>
          {pack.transactions.slice(-150).reverse().map(t => (
            <tr key={`${t.row}-${t.t}`} className="border-b last:border-0">
              <td className="py-1 pr-3 font-mono text-[12px]">#{t.row}</td>
              <td className="py-1 pr-3 font-mono text-[12px]">{stamp(t.t)}</td>
              <td className="max-w-[180px] truncate py-1 pr-3 font-mono text-[12px]">{t.fromVpa}</td>
              <td className="max-w-[180px] truncate py-1 pr-3 font-mono text-[12px]">{t.toVpa}</td>
              <td className="py-1 pr-3 text-right font-mono">{inr(t.amount)}</td>
              <td className="py-1 pr-3"><Score value={t.gnn} /></td>
              <td className="py-1 text-[12px]">{t.blocked ? 'blocked' : ''}</td>
            </tr>
          ))}
        </Table>
      </Block>
    </article>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="break-inside-avoid-page">
      <h2 className="mb-2 text-[14px] font-semibold">{title}</h2>
      {children}
    </section>
  )
}
