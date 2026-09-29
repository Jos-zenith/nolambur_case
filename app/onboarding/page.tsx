'use client'

import { useEffect, useState } from 'react'

import { BackendGate } from '@/components/rail/BackendGate'
import { Table } from '@/components/rail/bits'
import { stamp } from '@/lib/rail/format'
import { railPost, useRail } from '@/lib/rail/store'
import { cn } from '@/lib/utils'
import { ScanSearch } from 'lucide-react'
import { PageHeader, Term } from '@/components/rail/kit'
import type { RegistryCounts, RegistryReport } from '@/lib/rail/types'

type Party = { accountId: string; vpa: string; frozen: boolean; alerts: string[]; via?: string }
type Result = {
  decision: 'approve' | 'review' | 'hold'
  reason: string
  registry?: RegistryReport
  registryError?: string
  registered?: number
  latencyMs: number
  checkedAgainstRows: number
  results: { vpa: string; known: boolean; txns: number; counterparties?: number; selfFlagged?: boolean; direct: Party[]; secondHop: Party[]; gnnMax: number }[]
}

const DECISION = {
  hold: { label: 'Hold for review', bg: 'bg-sev-critical-bg', fg: 'text-sev-critical' },
  review: { label: 'Approve after manual review', bg: 'bg-sev-medium-bg', fg: 'text-sev-medium' },
  approve: { label: 'Approve', bg: 'bg-ok-bg', fg: 'text-ok' },
} as const

const SEV = { high: 'text-sev-critical', medium: 'text-sev-medium', low: 'text-muted-foreground' } as const

function RegistryPanel({ r }: { r: RegistryReport }) {
  const c = r.company
  return (
    <div className="grid gap-3 border-b p-4">
      <div>
        <p className="text-[13px] font-semibold">
          {c?.name ?? 'Not in the registry'} <span className="font-mono text-[12px] font-normal text-muted-foreground">{r.cin}</span>
        </p>
        {c && (
          <p className="mt-0.5 text-[12.5px] text-muted-foreground">
            {[c.status, c.company_class, c.incorporated_on && `incorporated ${c.incorporated_on}`, c.paid_up_capital !== null && `paid-up ₹${c.paid_up_capital.toLocaleString('en-IN')}`, c.roc]
              .filter(Boolean)
              .join(' · ')}
            {c.address && <span className="block">{c.address}</span>}
          </p>
        )}
      </div>
      {r.findings.length > 0 ? (
        <ul className="grid gap-1 text-[13px]">
          {r.findings.map(f => (
            <li key={f.code + f.text} className="grid grid-cols-[64px_1fr] gap-2">
              <span className={cn('text-[11.5px] font-medium uppercase', SEV[f.severity])}>{f.severity}</span>
              <span>{f.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-ok">No registry findings.</p>
      )}
      {r.directors.length > 0 && (
        <Table head={['Director', 'DIN', 'Current boards', 'Other companies']}>
          {r.directors.map(d => (
            <tr key={d.din} className="border-b align-top last:border-0">
              <td className="py-1.5 pr-3">
                {d.name ?? '—'}
                {d.disqualified && <span className="ml-1.5 text-[11.5px] font-medium text-sev-critical">disqualified</span>}
                {d.declared && <span className="ml-1.5 text-[11.5px] text-muted-foreground">declared</span>}
              </td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{d.din}</td>
              <td className="py-1.5 pr-3 tabular-nums">{d.currentDirectorships}</td>
              <td className="py-1.5 text-[12px]">
                {d.otherCompanies.length === 0
                  ? '—'
                  : d.otherCompanies.slice(0, 5).map(o => (
                      <span key={o.cin} className="block">
                        <span className="font-mono">{o.cin}</span> {o.name ?? ''}{' '}
                        <span className="text-muted-foreground">{[o.status, !o.current && 'ceased'].filter(Boolean).join(', ')}</span>
                      </span>
                    ))}
                {d.otherCompanies.length > 5 && <span className="text-muted-foreground">+{d.otherCompanies.length - 5} more</span>}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {r.crossover.length > 0 && (
        <Table head={['Linked company', 'Via', 'Settlement VPA', 'In the rail']}>
          {r.crossover.map(x => (
            <tr key={x.cin + x.vpa} className="border-b last:border-0">
              <td className="py-1.5 pr-3 font-mono text-[12px]">{x.cin}</td>
              <td className="py-1.5 pr-3 text-[12.5px]">{x.via}</td>
              <td className="py-1.5 pr-3 font-mono text-[12px]">{x.vpa}</td>
              <td className="py-1.5 text-[12.5px] text-sev-critical">{x.frozen ? 'frozen' : x.held ? 'on hold' : `alerts ${x.alerts.join(', ')}`}</td>
            </tr>
          ))}
        </Table>
      )}
      <p className="text-[11.5px] text-muted-foreground">
        From the MCA registry loaded on this bridge ({r.provider === 'http' ? 'files plus live lookups' : 'loaded files only'}). {r.sameAddressCount} other companies share the registered address.
      </p>
    </div>
  )
}

export default function OnboardingPage() {
  const [vpas, setVpas] = useState('')
  const [cin, setCin] = useState('')
  const [dins, setDins] = useState('')
  const [register, setRegister] = useState(false)
  const [reg, setReg] = useState<RegistryCounts | null>(null)
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

  useEffect(() => {
    if (backend !== 'live') return
    fetch('/api/rail/registry/status', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(setReg)
      .catch(() => {})
  }, [backend, result])

  const submit = async (list: string[], withCompany = true) => {
    setBusy(true)
    const body = withCompany && cin.trim() ? { vpas: list, cin: cin.trim(), dins: parse(dins), register } : { vpas: list }
    const { data } = await railPost<Result>('onboarding/check', body)
    setResult(data)
    setBusy(false)
  }
  const parse = (s: string) => s.split(/[\s,]+/).map(v => v.trim()).filter(Boolean)

  return (
    <div className="grid gap-4">
      <PageHeader
        icon={ScanSearch}
        eyebrow="Before a merchant goes live"
        title="Onboarding check"
        guideKey="onboarding"
        guide={[
          { title: 'Enter settlement VPAs', body: <>Paste the <Term k="vpa">VPAs</Term> the merchant wants payouts sent to, or pick a sample built from the real data.</> },
          { title: 'We walk the graph', body: 'Every account these VPAs have paid or been paid by, then everyone those accounts dealt with: two hops out.' },
          { title: 'Direct link = hold', body: <>A transfer with a flagged or frozen account, or a transfer the GNN scores 0.9+, holds the merchant for review.</> },
          { title: 'Second hop = watch', body: 'A link only through someone else is a reason to monitor, not to refuse.' },
          { title: 'Company applicants', body: 'Add the CIN and the MCA registry checks the directors, their other companies and the registered address, then whether a linked company’s settlement account is flagged here.' },
        ]}
      >
        Keep <Term k="mule">mules</Term> off the platform in the first place: check a new merchant against everything the engine has seen so far.
      </PageHeader>
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
                        submit(p.vpas, false)
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
            <label className="grid gap-1">
              <span className="text-[12px] text-muted-foreground">Company CIN (optional)</span>
              <input value={cin} onChange={e => setCin(e.target.value.toUpperCase())} placeholder="U72900MH2021PTC123456" className="h-8 rounded-sm border bg-background px-2.5 font-mono text-[13px] outline-none focus:border-primary" />
            </label>
            {cin.trim() && (
              <>
                <label className="grid gap-1">
                  <span className="text-[12px] text-muted-foreground">Directors the applicant declared (DINs, optional)</span>
                  <input value={dins} onChange={e => setDins(e.target.value)} placeholder="01234567, 07654321" className="h-8 rounded-sm border bg-background px-2.5 font-mono text-[13px] outline-none focus:border-primary" />
                </label>
                <label className="flex items-start gap-2 text-[12.5px]">
                  <input type="checkbox" checked={register} onChange={e => setRegister(e.target.checked)} className="mt-0.5" />
                  <span>Record these VPAs against this CIN, so later applicants linked to this company are checked against them</span>
                </label>
              </>
            )}
            <p className="text-[12px] text-muted-foreground">
              {!reg ? (
                'Registry status unavailable.'
              ) : reg.error ? (
                `Registry unavailable: ${reg.error}`
              ) : reg.companies ? (
                <>
                  Registry: {reg.companies.toLocaleString('en-IN')} companies · {(reg.directorships ?? 0).toLocaleString('en-IN')} directorships · {reg.disqualifiedDirectors} disqualified DINs ·{' '}
                  {reg.linkedAccounts} linked VPAs{reg.provider?.mode === 'http' ? ' · live lookups on' : ''}
                </>
              ) : (
                <>
                  Registry is empty{reg.provider?.mode === 'http' ? ' (live lookups on)' : ''}. Load MCA files with <code className="font-mono">python -m infra.registry load</code>.
                </>
              )}
            </p>
            <button disabled={busy || (!parse(vpas).length && !cin.trim())} className="h-9 rounded-sm bg-primary text-[13px] font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {busy ? 'Checking…' : 'Run check'}
            </button>
          </form>

          <div className="grid content-start gap-4">
            <section className="border bg-card">
              {!result ? (
                <p className="p-4 text-[13px] text-muted-foreground">Pick a sample applicant or paste VPAs from the transaction tape.</p>
              ) : (
                <>
                  <div className={cn('border-b px-4 py-3', DECISION[result.decision].bg)}>
                    <p className={cn('text-[12px] font-medium uppercase tracking-wide', DECISION[result.decision].fg)}>Recommendation</p>
                    <p className="mt-0.5 text-[20px] font-semibold">{DECISION[result.decision].label}</p>
                    <p className="mt-1 text-[13px]">{result.reason}</p>
                    {result.registryError && <p className="mt-1 text-[12.5px] text-sev-critical">Registry check failed: {result.registryError}</p>}
                    {!!result.registered && <p className="mt-1 text-[12.5px] text-muted-foreground">Recorded {result.registered} VPA(s) against {result.registry?.cin}.</p>}
                  </div>
                  <p className="border-b px-4 py-2 text-[12px] text-muted-foreground">
                    Checked against <span className="text-foreground">{result.checkedAgainstRows.toLocaleString('en-IN')}</span> replayed rows in{' '}
                    <span className="font-mono text-foreground">{result.latencyMs.toFixed(1)} ms</span>
                  </p>
                  {result.registry && <RegistryPanel r={result.registry} />}
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
