'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { duration, inr, rowLabel, stamp } from '@/lib/rail/format'
import { railPost, useRail, useRoles } from '@/lib/rail/store'
import type { AlertDetail as Detail, Downstream, Investigation } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { Lock, MessageSquareText } from 'lucide-react'

import { Callout } from './kit'
import { MoneyTrail } from './MoneyTrail'
import { Score, Section, SeverityBadge, StatusText, Table, TruthTag } from './bits'

export function AlertDetail({ alertId, onSelect, showLabels }: { alertId: string; onSelect: (id: string) => void; showLabels: boolean }) {
  const live = useRail(s => s.alerts[alertId])
  const frozenRef = useRail(s => (live ? s.frozen[live.accountId] : undefined))
  const [detail, setDetail] = useState<Detail | null>(null)
  const [missing, setMissing] = useState(false)

  const load = useCallback(async () => {
    const res = await fetch(`/api/rail/alerts/${alertId}`, { cache: 'no-store' })
    if (!res.ok) return setMissing(true)
    setMissing(false)
    setDetail(await res.json())
  }, [alertId])

  useEffect(() => {
    setDetail(null)
    load()
    const t = setInterval(load, 6000)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    if (live) load()
  }, [live?.updatedT, live?.status, frozenRef, load]) // eslint-disable-line react-hooks/exhaustive-deps

  if (missing) return <Panel><p className="p-4 text-[13px] text-muted-foreground">This alert is gone (the replay was restarted).</p></Panel>
  if (!detail) return <Panel><div className="m-4 h-40 animate-pulse rounded-sm bg-muted" /></Panel>

  const a = live ?? detail.alert
  const p = detail.profile

  return (
    <Panel>
      <header className={cn('border-b px-4 py-3.5', HEADER_WASH[a.severity])}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground">
          <SeverityBadge severity={a.severity} />
          <span>{a.detectorLabel}</span>
          <span>·</span>
          <span className="font-mono">{a.id}</span>
          <span>·</span>
          <span>rule {a.ruleVersion}</span>
          <span>·</span>
          <span>raised {stamp(a.createdT)}</span>
          <span className="ml-auto flex items-center gap-3">
            <StatusText status={a.status} />
            <span className="font-mono text-[13px] text-foreground" title="Rule base score + 10 × highest GNN score in the evidence">
              score {a.score}
            </span>
          </span>
        </div>
        <h2 className="mt-2 text-[18px] font-semibold leading-snug tracking-tight">{a.title}</h2>
        {a.status === 'held' && (
          <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-sev-critical px-2 py-1 text-[12px] font-medium text-white">
            <Lock className="size-3.5" /> On hold: transfers to and from this account are blocked until a supervisor decides
          </p>
        )}
        <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
          <span className="font-mono text-foreground">{a.vpa}</span>
          <span>
            {p.bank} · {p.state}
          </span>
          {showLabels && <TruthTag role={a.truth.role} />}
        </p>
      </header>

      <div className="grid gap-5 px-4 py-4">
        <section>
          <Callout icon={MessageSquareText} title="Why this fired" className="max-w-3xl">
            {a.reason}
          </Callout>
          <dl className="mt-3 grid grid-cols-1 border-t sm:grid-cols-2">
            {[...a.facts, { label: 'Highest GNN score in evidence', value: a.gnnMax.toFixed(3) }, ...(a.leadSeconds !== null ? [{ label: 'Lead time before money moved on', value: duration(a.leadSeconds) }] : [])].map(f => (
              <div key={f.label} className="flex justify-between gap-4 border-b py-1.5 text-[13px] sm:odd:mr-4">
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className="text-right font-mono text-[12.5px]">{f.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <ActionBar alertId={a.id} status={a.status} caseId={a.caseId} gnnMax={a.gnnMax} />

        <Investigate alertId={a.id} />

        <Section title="Money trail" note="replayed rows only · line width is amount · red = flagged or frozen, orange = GNN ≥ 0.9">
          <MoneyTrail trail={detail.trail} vpa={a.vpa} />
        </Section>

        <Section title="Account so far" note={p.note}>
          <dl className="grid grid-cols-2 gap-x-6 text-[13px] sm:grid-cols-4">
            {[
              ['Inbound', `${p.inboundCount} · ${inr(p.totalIn)}`],
              ['Outbound', `${p.outboundCount} · ${inr(p.totalOut)}`],
              ['Distinct payers', String(p.distinctPayers)],
              ['Distinct payees', String(p.distinctPayees)],
              ['First inflow', p.firstInT ? stamp(p.firstInT) : '—'],
              ['First outflow', p.firstOutT ? stamp(p.firstOutT) : '—'],
              ['First in → first out', p.firstInT && p.firstOutT ? duration(p.firstOutT - p.firstInT) : '—'],
              ['Freeze reference', p.frozen?.reference ?? '—'],
            ].map(([k, v]) => (
              <div key={k} className="border-b py-1.5">
                <dt className="text-[12px] text-muted-foreground">{k}</dt>
                <dd className="font-mono text-[12.5px]">{v}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section title="Evidence rows" note={`${a.rows.length} transfers, latest ${detail.evidence.length} shown`}>
          <Table head={['Row', 'Time', 'From', 'To', 'Amount', 'GNN', ...(showLabels ? ['Label'] : [])]} right={[4]}>
            {detail.evidence.map(r => (
              <tr key={r.row} className="border-b last:border-0">
                <td className="py-1.5 pr-3 font-mono text-[12px]">{r.source === 'replay' ? `#${r.row}` : r.source}</td>
                <td className="py-1.5 pr-3 font-mono text-[12px]">{stamp(r.t)}</td>
                <td className="max-w-[170px] truncate py-1.5 pr-3 font-mono text-[12px]">{r.fromVpa}</td>
                <td className="max-w-[170px] truncate py-1.5 pr-3 font-mono text-[12px]">{r.toVpa}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12.5px]">{inr(r.amount)}</td>
                <td className="py-1.5 pr-3"><Score value={r.gnn} /></td>
                {showLabels && <td className="py-1.5 font-mono text-[11.5px] text-muted-foreground">{rowLabel(r)}</td>}
              </tr>
            ))}
          </Table>
        </Section>

        {detail.otherAlerts.length > 0 && (
          <Section title="Other alerts on this account">
            <ul className="text-[13px]">
              {detail.otherAlerts.map(o => (
                <li key={o.id} className="flex items-center gap-2 border-b py-1.5 last:border-0">
                  <SeverityBadge severity={o.severity} />
                  <button className="hover:underline" onClick={() => onSelect(o.id)}>{o.title}</button>
                  <StatusText status={o.status} />
                  <span className="ml-auto font-mono text-[12px] text-muted-foreground">{o.id}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <FollowMoney accountId={a.accountId} onSelect={onSelect} />

        {detail.history.length > 0 && (
          <Section title="Earlier decisions on this account" note="from the audit store, across restarts">
            <ol className="text-[13px]">
              {detail.history.map(h => (
                <li key={`${h.runId}-${h.alertId}-${h.at}`} className="grid grid-cols-[130px_1fr] gap-3 border-b py-1.5 last:border-0">
                  <span className="font-mono text-[12px] text-muted-foreground">{new Date(h.at * 1000).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })}</span>
                  <span>
                    <span className="font-medium">{h.actor}</span> · {h.decision} on {h.alertId} ({h.detector.replace(/_/g, ' ')}). {h.note}
                    <span className="ml-1 font-mono text-[11.5px] text-muted-foreground">run {h.runId}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Section>
        )}

        <Section title="Activity" note="append-only; persisted to the audit store, tool calls also to agents/action_log.jsonl">
          {detail.audit.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">No analyst activity yet.</p>
          ) : (
            <ol className="text-[13px]">
              {detail.audit.map(e => (
                <li key={e.id} className="grid grid-cols-[130px_1fr] gap-3 border-b py-1.5 last:border-0">
                  <span className="font-mono text-[12px] text-muted-foreground">{stamp(e.simT)}</span>
                  <span>
                    <span className="font-medium">{e.actor}</span>
                    {e.role && e.role !== 'system' && <span className="text-muted-foreground"> ({e.role})</span>} · {e.action.replace(/_/g, ' ')}
                    {e.override && <span className="ml-1 rounded-sm bg-sev-high-bg px-1 text-[11px] text-sev-high">model override</span>}. {e.note}
                    {e.tool && typeof e.tool.freeze_reference === 'string' && <span className="ml-1 font-mono text-[12px] text-muted-foreground">[{e.tool.freeze_reference}]</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>
      </div>
    </Panel>
  )
}

function Investigate({ alertId }: { alertId: string }) {
  const [result, setResult] = useState<Investigation | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => setResult(null), [alertId])

  const run = async () => {
    setBusy(true)
    const { ok, data } = await railPost<Investigation>(`alerts/${alertId}/investigate`)
    setBusy(false)
    if (!ok) return toast.error('Investigation failed', { description: data.error })
    setResult(data)
  }

  return (
    <section className="border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-background px-3 py-2">
        <div>
          <h3 className="text-[13px] font-semibold">Agent investigation</h3>
          <p className="text-[12px] text-muted-foreground">
            Runs <code className="font-mono">score_transfer_chain</code> (live <code className="font-mono">/predict</code>, spliced onto the real graph) and{' '}
            <code className="font-mono">check_suspect_registry</code> from <code className="font-mono">agents/tools_impl.py</code>.
          </p>
        </div>
        <button onClick={run} disabled={busy} className="h-8 rounded-sm border bg-card px-3 text-[13px] font-medium hover:bg-accent disabled:opacity-50">
          {busy ? 'Running tools…' : result ? 'Run again' : 'Run agent tools'}
        </button>
      </div>
      {result && (
        <div className="grid gap-3 p-3">
          <p className="text-[12px] text-muted-foreground">
            {result.scored.legs.length} legs scored in {result.seconds.toFixed(2)}s · {result.scored.linkedAccounts} accounts linked into the background graph ·
            features {result.scored.normalized ? 'z-normalised with the checkpoint stats' : 'NOT normalised'}
          </p>
          <Table head={['CSV row', 'Sender', 'Receiver', 'Amount', 'Full-graph score', 'Live /predict score']} right={[3]}>
            {result.legs.map((leg, i) => (
              <tr key={leg.row} className="border-b last:border-0">
                <td className="py-1.5 pr-3 font-mono text-[12px]">#{leg.row}</td>
                <td className="max-w-[160px] truncate py-1.5 pr-3 font-mono text-[12px]">{leg.sender}</td>
                <td className="max-w-[160px] truncate py-1.5 pr-3 font-mono text-[12px]">{leg.receiver}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12.5px]">{inr(leg.amount_inr)}</td>
                <td className="py-1.5 pr-3"><Score value={leg.gnnPrecomputed} /></td>
                <td className="py-1.5"><Score value={result.scored.legs[i]?.fraud_probability ?? 0} /></td>
              </tr>
            ))}
          </Table>
          {result.registry && (
            <p className="text-[12.5px]">
              <span className="font-medium">Suspect registry:</span>{' '}
              {'error' in result.registry ? (
                <span className="text-sev-critical">{String(result.registry.error)}</span>
              ) : (
                <>
                  {result.registry.listed ? 'listed' : 'not listed'}{' '}
                  <span className="text-muted-foreground">· {String(result.registry.source)}</span>
                </>
              )}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

const ACTIONS = [
  { id: 'clear', label: 'Clear as false positive', cls: 'border bg-card hover:bg-accent' },
  { id: 'escalate', label: 'Escalate to case', cls: 'border bg-card hover:bg-accent' },
  { id: 'freeze', label: 'Freeze account', cls: 'bg-sev-critical text-white hover:opacity-90' },
] as const

function ActionBar({ alertId, status, caseId, gnnMax }: { alertId: string; status: string; caseId: string | null; gnnMax: number }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const { roles, role, can } = useRoles()
  useEffect(() => setNote(''), [alertId])
  const overrideAt = roles?.overrideScore ?? 0.9
  // Mirrors the bridge's check; the bridge is what actually enforces it.
  const needs = (id: string) => (id === 'clear' && (status === 'held' || gnnMax >= overrideAt) ? 'override' : id)
  const label = (id: string, fallback: string) => (id === 'clear' && status === 'held' ? 'Release hold' : id === 'freeze' && status === 'held' ? 'Confirm freeze' : fallback)

  const run = async (action: string) => {
    if (!note.trim()) return toast.error('Add a note first', { description: 'Every action is logged with its reason.' })
    setBusy(action)
    const { ok, data } = await railPost<{ alert: { caseId: string }; tool: Record<string, unknown> | null }>(`alerts/${alertId}/actions`, { action, note })
    setBusy(null)
    if (!ok) return toast.error(data.error ?? 'Action failed')
    setNote('')
    if (action === 'freeze') {
      toast.success('Frozen: instruction queued to the bank gateway', {
        description: `${String(data.tool?.freeze_reference ?? '')} · outbox · ${data.alert.caseId}`,
      })
    } else toast.success(action === 'clear' ? (status === 'held' ? 'Hold released' : 'Alert cleared') : `Filed to ${data.alert.caseId}`)
  }

  const done = status === 'cleared' || status === 'frozen' || status === 'superseded'
  return (
    <section className="border bg-background p-3">
      {done ? (
        <p className="text-[13px]">
          {status === 'cleared' ? 'Cleared. This detector stays quiet on this account.' : status === 'superseded' ? 'Superseded by a rule alert on the same account.' : 'Account frozen. Further transfers to or from it are blocked in the replay.'}
          {caseId && (
            <>
              {' '}
              <Link href={`/cases/${caseId}`} className="text-primary underline underline-offset-2">Open {caseId}</Link>
            </>
          )}
        </p>
      ) : (
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start">
          {status === 'held' && (
            <p className="text-[13px] lg:hidden">Held automatically. Transfers are blocked until a supervisor confirms or releases.</p>
          )}
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            rows={2}
            placeholder="Reason for your decision (required, goes into the audit log)"
            className="min-h-[52px] flex-1 resize-y rounded-sm border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
          />
          <div className="flex flex-wrap gap-2">
            {ACTIONS.filter(x => !(status === 'escalated' && x.id === 'escalate')).map(x => {
              const allowed = can(needs(x.id))
              const why = allowed ? undefined : `${needs(x.id) === 'override' ? 'Overriding the model' : x.label} needs a supervisor. You are ${role ?? 'not signed in'}.`
              return (
                <button
                  key={x.id}
                  onClick={() => run(x.id)}
                  disabled={busy !== null || !allowed}
                  title={why}
                  className={cn('h-8 rounded-sm px-3 text-[13px] font-medium disabled:cursor-not-allowed disabled:opacity-40', x.cls)}
                >
                  {busy === x.id ? 'Saving…' : label(x.id, x.label)}
                </button>
              )
            })}
          </div>
        </div>
      )}
      {!done && (
        <p className="mt-2 text-[12px] text-muted-foreground">
          {status === 'held' && <span className="hidden text-sev-critical lg:inline">Held automatically: transfers are blocked until a supervisor confirms or releases. </span>}
          {caseId && (
            <>
              Part of <Link href={`/cases/${caseId}`} className="text-primary underline underline-offset-2">{caseId}</Link>.{' '}
            </>
          )}
          {role === 'analyst' && 'Freezing, and clearing anything the model scored 0.9 or higher, needs a supervisor.'}
        </p>
      )}
    </section>
  )
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="min-w-0 overflow-hidden rounded-lg border bg-card shadow-card">{children}</div>
}

const HEADER_WASH = {
  critical: 'bg-sev-critical-bg/60',
  high: 'bg-sev-high-bg/60',
  medium: 'bg-sev-medium-bg/60',
  low: 'bg-sev-low-bg/60',
} as const

/** Time-respecting paths out of the account, from the graph store (memory or Neo4j). */
function FollowMoney({ accountId, onSelect }: { accountId: string; onSelect: (id: string) => void }) {
  const alerts = useRail(s => s.alerts)
  const [hops, setHops] = useState(3)
  const [result, setResult] = useState<Downstream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => setResult(null), [accountId])

  const run = async (n: number) => {
    setHops(n)
    setBusy(true)
    setError(null)
    const res = await fetch(`/api/rail/graph/downstream/${encodeURIComponent(accountId)}?hops=${n}`, { cache: 'no-store' })
    const body = await res.json()
    if (res.ok) setResult(body)
    else setError(typeof body.detail === 'string' ? body.detail : 'Graph query failed')
    setBusy(false)
  }
  const alertFor = (id: string) => Object.values(alerts).find(x => x.accountId === id && x.status !== 'cleared' && x.status !== 'superseded')

  return (
    <Section
      title="Follow the money"
      note={result ? `${result.graph} graph · each hop at or after the one before it · blocked transfers excluded` : 'multi-hop query on the graph store'}
    >
      <div className="mb-2 flex flex-wrap items-center gap-1">
        {[2, 3, 4, 5].map(n => (
          <button key={n} disabled={busy} onClick={() => run(n)} className={cn('h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent', result && hops === n && 'border-primary bg-accent')}>
            {n} hops
          </button>
        ))}
        {busy && <span className="text-[12px] text-muted-foreground">Querying…</span>}
      </div>
      {error && <p className="text-[13px] text-sev-critical">{error}</p>}
      {result && (
        <div className="grid gap-2 text-[13px]">
          <p>
            Reaches <span className="font-medium">{result.accountsReached}</span> accounts
            {result.byHop.length > 0 && <> ({result.byHop.map(h => `hop ${h.hop}: ${h.accounts}`).join(', ')})</>}.{' '}
            <span className={result.flaggedReached ? 'text-sev-high' : ''}>{result.flaggedReached} already flagged.</span>
            {result.truncated && <span className="text-muted-foreground"> Capped at {result.paths.length} paths.</span>}
          </p>
          {result.longest.length > 0 && (
            <ol className="grid gap-1">
              {result.longest.slice(0, 8).map((p, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1 border-b pb-1 font-mono text-[11.5px] last:border-0">
                  {p.nodes.map((n, j) => {
                    const hit = j > 0 ? alertFor(n.id) : undefined
                    return (
                      <span key={j} className="flex items-center gap-1">
                        {j > 0 && <span className="text-muted-foreground">→ {inr(p.legs[j - 1].amount)} →</span>}
                        {hit ? (
                          <button onClick={() => onSelect(hit.id)} className={cn('hover:underline', n.frozen ? 'text-sev-critical' : 'text-sev-high')}>{n.vpa}</button>
                        ) : (
                          <span className={cn(n.frozen && 'text-sev-critical', n.flagged && 'text-sev-high')}>{n.vpa}</span>
                        )}
                      </span>
                    )
                  })}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Section>
  )
}
