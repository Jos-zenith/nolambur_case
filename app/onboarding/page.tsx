'use client'

import { useEffect, useState } from 'react'

import { BackendGate } from '@/components/rail/BackendGate'
import { Table } from '@/components/rail/bits'
import { stamp } from '@/lib/rail/format'
import { railPost, useRail } from '@/lib/rail/store'
import { cn } from '@/lib/utils'

type Party = { accountId: string; vpa: string; frozen: boolean; alerts: string[]; via?: string }
type Result = {
  decision: 'approve' | 'hold'
  reason: string
  latencyMs: number
  checkedAgainstRows: number
  results: { vpa: string; known: boolean; txns: number; counterparties?: number; selfFlagged?: boolean; direct: Party[]; secondHop: Party[]; gnnMax: number }[]
}

export default function OnboardingPage() {
  const [vpas, setVpas] = useState('')
  const [presets, setPresets] = useState<{ label: string; vpas: string[] }[]>([])
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const backend = useRail(s => s.backend)
  const rowsReplayed = useRail(s => s.metrics?.rowsReplayed ?? 0)
  const audit = useRail(s => s.audit)

  useEffect(() => {
    if (backend !== 'live') return
    fetch('/api/rail/onboarding/presets', { cache: 'no-store' })
      .then(r => r.json())
      .then(p => Array.isArray(p) && setPresets(p))
      .catch(() => {})
  }, [backend, rowsReplayed > 400]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (list: string[]) => {
    setBusy(true)
    const { data } = await railPost<Result>('onboarding/check', { vpas: list })
    setResult(data)
    setBusy(false)
  }
  const parse = (s: string) => s.split(/[\s,]+/).map(v => v.trim()).filter(Boolean)

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-[18px] font-semibold">Onboarding check</h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted-foreground">
          Before a merchant goes live, check the settlement VPAs it gives you against the transaction graph the replay has seen so far. A direct
          transfer with a flagged or frozen account holds the merchant. A second-hop link only means watch it. Company-director links need MCA data,
          which this dataset does not have.
        </p>
      </div>
      <BackendGate>
        <div className="grid gap-4 lg:grid-cols-[400px_1fr]">
          <form
            className="grid content-start gap-3 border bg-card p-4"
            onSubmit={e => {
              e.preventDefault()
              submit(parse(vpas))
            }}
          >
            <div>
              <p className="mb-1.5 text-[12px] text-muted-foreground">Applicants picked from the replayed data</p>
              {presets.length === 0 ? (
                <p className="text-[12.5px] text-muted-foreground">Samples appear once the replay has passed the fraud window.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {presets.map(p => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => {
                        setVpas(p.vpas.join('\n'))
                        submit(p.vpas)
                      }}
                      className="h-7 rounded-sm border px-2 text-[12px] hover:bg-accent"
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <hr />
            <label className="grid gap-1">
              <span className="text-[12px] text-muted-foreground">Settlement VPAs (one per line)</span>
              <textarea value={vpas} onChange={e => setVpas(e.target.value)} rows={4} placeholder="abcd1234@ybl" className="rounded-sm border bg-background px-2.5 py-1.5 font-mono text-[13px] outline-none focus:border-primary" />
            </label>
            <button disabled={busy || !parse(vpas).length} className="h-9 rounded-sm bg-primary text-[13px] font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {busy ? 'Checking…' : 'Run check'}
            </button>
          </form>

          <div className="grid content-start gap-4">
            <section className="border bg-card">
              {!result ? (
                <p className="p-4 text-[13px] text-muted-foreground">Pick a sample applicant or paste VPAs from the transaction tape.</p>
              ) : (
                <>
                  <div className={cn('border-b px-4 py-3', result.decision === 'hold' ? 'bg-sev-critical-bg' : 'bg-ok-bg')}>
                    <p className={cn('text-[12px] font-medium uppercase tracking-wide', result.decision === 'hold' ? 'text-sev-critical' : 'text-ok')}>Recommendation</p>
                    <p className="mt-0.5 text-[20px] font-semibold">{result.decision === 'hold' ? 'Hold for review' : 'Approve'}</p>
                    <p className="mt-1 text-[13px]">{result.reason}</p>
                  </div>
                  <p className="border-b px-4 py-2 text-[12px] text-muted-foreground">
                    Checked against <span className="text-foreground">{result.checkedAgainstRows.toLocaleString('en-IN')}</span> replayed rows in{' '}
                    <span className="font-mono text-foreground">{result.latencyMs.toFixed(1)} ms</span>
                  </p>
                  <div className="grid gap-4 p-4">
                    {result.results.map(r => (
                      <div key={r.vpa}>
                        <p className="text-[13px]">
                          <span className="font-mono">{r.vpa}</span>{' '}
                          <span className="text-muted-foreground">
                            {r.known ? `· ${r.txns} transfers with ${r.counterparties} counterparties · highest GNN score ${r.gnnMax.toFixed(3)}` : '· not in the dataset'}
                            {r.selfFlagged && ' · itself under alert'}
                          </span>
                        </p>
                        {[...r.direct.map(d => ({ ...d, hop: 'direct' })), ...r.secondHop.map(d => ({ ...d, hop: 'second hop' }))].length > 0 && (
                          <div className="mt-2">
                            <Table head={['Link', 'Flagged account', 'Via', 'Status']}>
                              {[...r.direct.map(d => ({ ...d, hop: 'direct' })), ...r.secondHop.map(d => ({ ...d, hop: 'second hop' }))].map(d => (
                                <tr key={d.accountId + d.hop} className="border-b last:border-0">
                                  <td className="py-1.5 pr-3">{d.hop}</td>
                                  <td className="py-1.5 pr-3 font-mono text-[12px]">{d.vpa}</td>
                                  <td className="py-1.5 pr-3 font-mono text-[12px]">{d.via ?? '—'}</td>
                                  <td className="py-1.5 text-[12.5px]">{d.frozen ? 'frozen' : `alerts ${d.alerts.join(', ')}`}</td>
                                </tr>
                              ))}
                            </Table>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
            <section className="border bg-card">
              <h2 className="border-b px-4 py-2 text-[13px] font-semibold">Recent analyst activity</h2>
              {audit.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted-foreground">None yet.</p>
              ) : (
                <ul className="text-[13px]">
                  {audit.slice(0, 6).map(e => (
                    <li key={e.id} className="grid grid-cols-[130px_1fr] gap-3 border-b px-4 py-1.5 last:border-0">
                      <span className="font-mono text-[12px] text-muted-foreground">{stamp(e.simT)}</span>
                      <span>
                        {e.actor} · {e.action.replace(/_/g, ' ')}. {e.note}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </BackendGate>
    </div>
  )
}
