'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { BackendGate } from '@/components/rail/BackendGate'
import { stamp } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import type { Snapshot } from '@/lib/rail/types'
import { Briefcase } from 'lucide-react'
import { PageHeader, Term } from '@/components/rail/kit'

export default function CasesPage() {
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const backend = useRail(s => s.backend)
  const auditCount = useRail(s => s.audit.length)

  useEffect(() => {
    if (backend !== 'live') return
    fetch('/api/rail/snapshot', { cache: 'no-store' })
      .then(r => r.json())
      .then(setSnap)
      .catch(() => {})
  }, [backend, auditCount])

  const alerts = Object.fromEntries((snap?.alerts ?? []).map(a => [a.id, a]))
  const cases = [...(snap?.cases ?? [])].sort((a, b) => b.openedT - a.openedT)

  return (
    <div className="grid gap-4">
      <PageHeader
        icon={Briefcase}
        eyebrow="Incident response"
        title="Cases"
        guideKey="cases"
        guide={[
          { title: 'A case opens itself', body: 'When an analyst escalates or freezes, or the auto-hold fires. Linked accounts join the same case.' },
          { title: 'Open the evidence pack', body: <>Accounts, transfers, alerts and every action in one <Term k="evidence pack">evidence pack</Term>, printable as a PDF.</> },
          { title: 'Report to 1930', body: <>A supervisor files the <Term k="1930">1930</Term> complaint and notifies the on-call officer by SMS.</> },
          { title: 'Everything is logged', body: <>Each step is written to the hash-chained <Term k="audit trail">audit trail</Term>.</> },
        ]}
      >
        One case per mule network, not per alert, so the whole chain is reported together.
      </PageHeader>
      <BackendGate>
        <section className="border bg-card">
          {!snap ? (
            <div className="m-4 h-24 animate-pulse rounded-sm bg-muted" />
          ) : cases.length === 0 ? (
            <p className="p-4 text-[13px] text-muted-foreground">
              No cases yet. Escalate or freeze an alert in the{' '}
              <Link href="/console" className="text-primary underline underline-offset-2">alert queue</Link> to open one.
            </p>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-[12px] text-muted-foreground">
                  <th className="px-4 py-2 font-normal">Case</th>
                  <th className="px-4 py-2 font-normal">Opened (replay time)</th>
                  <th className="px-4 py-2 font-normal">Accounts</th>
                  <th className="px-4 py-2 font-normal">Alerts</th>
                  <th className="px-4 py-2 font-normal">1930 report</th>
                  <th className="px-4 py-2 font-normal" />
                </tr>
              </thead>
              <tbody>
                {cases.map(c => (
                  <tr key={c.id} className="border-b align-top last:border-0">
                    <td className="px-4 py-2 font-mono">{c.id}</td>
                    <td className="px-4 py-2 font-mono text-[12px]">{stamp(c.openedT)}</td>
                    <td className="px-4 py-2 font-mono text-[12px]">{c.alertIds.map(id => alerts[id]?.vpa).filter((v, i, xs) => v && xs.indexOf(v) === i).join(', ')}</td>
                    <td className="px-4 py-2 tabular-nums">{c.alertIds.length}</td>
                    <td className="px-4 py-2 font-mono text-[12px]">{c.report ? String(c.report.acknowledgement_no ?? 'filed') : '—'}</td>
                    <td className="px-4 py-2 text-right">
                      <Link href={`/cases/${c.id}`} className="text-primary underline underline-offset-2">Evidence pack</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </BackendGate>
    </div>
  )
}
