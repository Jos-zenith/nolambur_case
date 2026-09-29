'use client'

import { useEffect, useState } from 'react'

import { Section, Table } from '@/components/rail/bits'
import { useRail } from '@/lib/rail/store'
import type { AuditVerify, Feedback, Platform, Roles } from '@/lib/rail/types'
import { cn } from '@/lib/utils'
import { Server } from 'lucide-react'
import { PageHeader, Term } from '@/components/rail/kit'

const ENV = [
  ['RAIL_SOURCE', 'webhook (default) · kafka · kinesis · replay (demo / evaluation)'],
  ['KAFKA_BOOTSTRAP / KAFKA_TOPIC / KAFKA_GROUP', 'broker, topic (upi.payments), consumer group; KAFKA_OFFSET_RESET for a new group'],
  ['KINESIS_STREAM / KINESIS_START', 'stream name; TRIM_HORIZON (default) or LATEST for a shard with no checkpoint'],
  ['MCA_PROVIDER / MCA_API_URL', 'none (loaded files only) · http (live company and director lookups)'],
  ['RAIL_GRAPH', 'memory · neo4j (also Memgraph)'],
  ['RAIL_DB_URL', 'sqlite:///… · postgresql+psycopg://…'],
  ['GATEWAY_WEBHOOK_URL', 'bank gateway receiving freeze instructions'],
  ['CFCFRMS_URL', '1930 portal base URL'],
  ['TWILIO_*', 'SMS to officers; dry run when unset'],
  ['NPCI_REGISTRY_URL', 'suspect registry; default is the sandbox mock'],
  ['RAIL_AUTO_HOLD', 'on (default) · off'],
  ['RAIL_USERS', 'JSON map of user → analyst | supervisor | admin'],
]

function when(t: number | null | undefined) {
  return t ? new Date(t * 1000).toLocaleTimeString('en-IN', { hour12: false }) : '—'
}

function Card({ title, backend, ok, children }: { title: string; backend: string; ok: boolean; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-hidden border bg-card p-3">
      <div className="flex items-center gap-2">
        <span className={cn('size-1.5 rounded-full', ok ? 'bg-ok' : 'bg-sev-critical')} />
        <h3 className="text-[13px] font-semibold">{title}</h3>
        <span className="ml-auto rounded-sm bg-accent px-1.5 font-mono text-[11.5px]">{backend}</span>
      </div>
      <dl className="grid min-w-0 grid-cols-[minmax(0,1fr)] text-[12.5px]">{children}</dl>
    </div>
  )
}

function Row({ k, v, mono = true }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b py-1 last:border-0">
      <dt className="shrink-0 text-muted-foreground">{k}</dt>
      <dd className={cn('min-w-0 truncate text-right', mono && 'font-mono text-[12px]')} title={typeof v === 'string' ? v : undefined}>
        {v}
      </dd>
    </div>
  )
}

export default function PlatformPage() {
  const backend = useRail(s => s.backend)
  const [p, setP] = useState<Platform | null>(null)
  const [fb, setFb] = useState<Feedback | null>(null)
  const [chain, setChain] = useState<AuditVerify | null>(null)
  const [roles, setRoles] = useState<Roles | null>(null)
  const [verifying, setVerifying] = useState(false)

  const verify = async () => {
    setVerifying(true)
    const res = await fetch('/api/rail/audit/verify', { cache: 'no-store' }).catch(() => null)
    if (res?.ok) setChain(await res.json())
    setVerifying(false)
  }
  useEffect(() => {
    if (backend !== 'live') return
    verify()
    fetch('/api/rail/roles', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(setRoles)
      .catch(() => {})
  }, [backend])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [a, b] = await Promise.all([fetch('/api/rail/platform', { cache: 'no-store' }), fetch('/api/rail/feedback', { cache: 'no-store' })])
        if (!alive) return
        if (a.ok) setP(await a.json())
        else setError(a.status === 503 ? 'The bridge is still warming up.' : 'The GNN bridge is not running.')
        if (b.ok) setFb(await b.json())
      } catch {
        if (alive) setError('The GNN bridge is not running.')
      }
    }
    load()
    const t = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [backend])

  const i = p?.ingest
  const it = p?.integrations
  return (
    <div className="grid max-w-5xl gap-8">
      <PageHeader
        icon={Server}
        eyebrow="Under the hood"
        title="Platform"
        guideKey="platform"
        guide={[
          { title: 'Five cards, five jobs', body: 'Ingest (payments in), graph (who paid whom), audit store (decisions), integrations (actions out), company registry (who owns the merchant).' },
          { title: 'Green dot = healthy', body: 'Each card shows its backend and its last error. Local defaults need no extra services.' },
          { title: 'Every action is delivered', body: 'Freezes and 1930 reports go through an outbox that retries until the other side confirms.' },
          { title: 'Tamper-evident', body: <>Verify re-computes the hash chain of the <Term k="audit trail">audit trail</Term> and names any altered row.</> },
        ]}
      >
        Where payments come from, where the graph lives, where decisions are stored and where actions go. Refreshes every 3 seconds.
      </PageHeader>

      {!p || !i || !it ? (
        <p className="border bg-card p-4 text-[13px] text-muted-foreground">{error ?? 'Loading from the bridge…'}</p>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Card title="Ingest" backend={i.mode} ok={!i.source.lastError && !i.lastScoreError && !i.lastTickError}>
              <Row k="Clock" v={i.mode === 'replay' ? 'CSV replay; webhook payments join at the replay clock' : 'event time of incoming payments'} mono={false} />
              {(i.mode === 'kafka' || i.mode === 'kinesis') && (
                <>
                  <Row k="Consumer" v={`${i.source.backend} · ${i.source.state}`} />
                  <Row k="Received / committed" v={`${i.source.received} / ${i.source.acked ?? 0}${i.source.lastCommitAt ? ` · last commit ${when(i.source.lastCommitAt)}` : ''}`} />
                  <Row
                    k="Lag"
                    v={i.source.lag === null || i.source.lag === undefined ? '—' : i.mode === 'kafka' ? `${i.source.lag} messages` : `${Math.round(i.source.lag / 1000)} s behind`}
                  />
                  {i.mode === 'kafka' && <Row k="Partitions" v={i.source.partitions?.join(', ') || 'none assigned'} />}
                  {i.mode === 'kinesis' && <Row k="Shards" v={(i.source.shards ?? []).map(sh => `${sh.id.replace('shardId-', '')} ${sh.state}`).join(' · ') || '—'} />}
                </>
              )}
              <Row k="Webhook" v={`${i.webhook.endpoint}${i.webhook.signed ? ' · HMAC required' : ' · unsigned'}`} />
              <Row k="Webhook accepted / rejected" v={`${i.webhookAccepted} / ${i.rejected}`} />
              <Row k="Ingested this run" v={`${i.ingestedThisRun} · ${i.duplicatesDropped} duplicates dropped`} />
              <Row k="Inbox depth" v={`${i.inboxDepth}${i.highWater ? ` · consumers pause above ${i.highWater.toLocaleString('en-IN')}` : ''}${i.source.pausedForBacklog ? ' · paused now' : ''}`} />
              <Row k="Dead letters" v={i.deadLetters?.length ? `${p.store.deadLetters ?? i.deadLetters.length} · last ${i.deadLetters[0].position ?? i.deadLetters[0].source}` : '0'} />
              <Row k="Scored online" v={`${i.scored}${i.lastScoreMs !== null ? ` · last batch ${i.lastScoreMs} ms` : ''}${i.scoreErrors ? ` · ${i.scoreErrors} failed` : ''}`} />
              {(i.source.lastError || i.lastScoreError || i.lastTickError) && (
                <Row k="Last error" v={<span className="text-sev-critical">{i.source.lastError || i.lastScoreError || i.lastTickError}</span>} />
              )}
            </Card>

            <Card title="Graph store" backend={p.graph.backend} ok={!p.graph.error && !p.graph.fallbackReason}>
              <Row k="Persistent" v={p.graph.persistent ? 'yes' : 'no, rebuilt from the replay'} mono={false} />
              {p.graph.uri && <Row k="URI" v={p.graph.uri} />}
              <Row k="Edges" v={p.graph.edges ?? `${p.graph.edgesWritten} written · ${p.graph.pending} pending`} />
              <Row k="Serves" v="onboarding 2-hop check · follow the money" mono={false} />
              {(p.graph.fallbackReason || p.graph.error) && <Row k="Note" v={<span className="text-sev-critical">{p.graph.fallbackReason || p.graph.error}</span>} />}
            </Card>

            <Card title="Audit store" backend={p.store.backend ?? 'none'} ok={!p.store.error && !p.store.writeErrors}>
              {p.store.url && <Row k="URL" v={p.store.url} />}
              <Row k="Runs recorded" v={p.store.runs ?? 0} />
              <Row k="Audit events" v={p.store.auditEvents ?? 0} />
              <Row k="Decisions" v={Object.entries(p.store.decisions ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '0'} />
              <Row k="Agent actions" v={p.store.agentActions ?? 0} />
              {p.store.error && <Row k="Error" v={<span className="text-sev-critical">{p.store.error}</span>} />}
            </Card>

            <Card title="Integrations" backend="outbox" ok={!!it.workerAlive && !(p.store.outbox?.failed)}>
              <Row k="Bank gateway" v={`${it.gateway?.sandbox ? 'sandbox' : it.gateway?.url} · HMAC signed`} />
              <Row k="1930 portal" v={it.cfcfrms?.sandbox ? 'sandbox (mock, not the real CFCFRMS)' : it.cfcfrms?.url} />
              <Row k="SMS" v={`${it.sms?.provider} · ${it.sms?.mode} · ${it.sms?.recipients} recipients`} />
              <Row k="Outbox" v={Object.entries(p.store.outbox ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'empty'} />
              <Row k="Sandbox received" v={`gateway ${p.store.sandbox?.gateway ?? 0} · 1930 ${p.store.sandbox?.cfcfrms ?? 0}`} />
              <Row k="Delivery worker" v={it.workerAlive ? 'running' : 'stopped'} />
            </Card>
          </div>

          {p.registry && (
            <div className="grid gap-3 md:grid-cols-2">
              <Card title="Company registry (MCA)" backend={p.registry.provider?.mode === 'http' ? 'files + api' : 'files'} ok={!p.registry.error && !p.registry.provider?.lastError}>
                {p.registry.error ? (
                  <Row k="Error" v={<span className="text-sev-critical">{p.registry.error}</span>} />
                ) : (
                  <>
                    <Row k="Companies" v={(p.registry.companies ?? 0).toLocaleString('en-IN')} />
                    <Row k="Directorships" v={`${(p.registry.directorships ?? 0).toLocaleString('en-IN')} · ${p.registry.directors ?? 0} directors · ${p.registry.disqualifiedDirectors ?? 0} disqualified`} />
                    <Row k="Merchant VPAs linked to a CIN" v={p.registry.linkedAccounts ?? 0} />
                    <Row k="Live lookups" v={p.registry.provider?.mode === 'http' ? p.registry.provider.url ?? 'on' : 'off (MCA_PROVIDER=none)'} />
                    <Row k="Serves" v="onboarding: directors, common control, address farms, linked flagged accounts" mono={false} />
                    {!p.registry.companies && <Row k="Note" v="Empty. Load files with python -m infra.registry load" mono={false} />}
                  </>
                )}
              </Card>
              {!!i.deadLetters?.length && (
                <Card title="Dead letters" backend="ingest" ok={false}>
                  {i.deadLetters.slice(0, 6).map(d => (
                    <Row key={d.id} k={`${d.source} ${when(d.at)}`} v={<span title={d.error}>{d.position ?? '—'}: {d.error}</span>} />
                  ))}
                </Card>
              )}
            </div>
          )}

          <Section title="Recent deliveries" note="every freeze and 1930 complaint goes through the outbox; failures retry with backoff">
            {!it.recent?.length ? (
              <p className="text-[13px] text-muted-foreground">Nothing sent yet. Freeze an account or file a 1930 report from a case.</p>
            ) : (
              <Table head={['#', 'Kind', 'Reference', 'Status', 'Attempts', 'Queued', 'Response']} right={[4]}>
                {it.recent.map(o => (
                  <tr key={o.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[12px]">{o.id}</td>
                    <td className="py-1.5 pr-3 font-mono text-[12px]">{o.kind}</td>
                    <td className="py-1.5 pr-3 font-mono text-[12px]">{o.reference}</td>
                    <td className={cn('py-1.5 pr-3', o.status === 'failed' && 'text-sev-critical', o.status === 'pending' && 'text-sev-medium')}>{o.status}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{o.attempts}</td>
                    <td className="py-1.5 pr-3 font-mono text-[12px]">{when(o.created_at)}</td>
                    <td className="max-w-[260px] truncate py-1.5 font-mono text-[12px]" title={o.last_error ?? JSON.stringify(o.response)}>
                      {o.response ? String(o.response.lienReference ?? o.response.acknowledgementNo ?? o.response.status ?? '') : o.last_error ?? '—'}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Section>

          {fb && (
            <Section title="Analyst feedback" note="decisions become edge labels for retraining: freeze → fraud, clear → clean">
              <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed">
                {fb.freezes + fb.clears === 0 ? (
                  'No labelling decisions yet. Freeze or clear alerts in the queue and they appear here.'
                ) : (
                  <>
                    {fb.freezes} freezes and {fb.clears} clears across {fb.runs} run{fb.runs === 1 ? '' : 's'} label <b>{fb.labelledEdges}</b> transfers. Against the
                    dataset labels, {fb.agreeWithDataset} agree and <b className={fb.wouldFlip ? 'text-sev-high' : ''}>{fb.wouldFlip}</b> would flip.{' '}
                    {fb.freezesOnTrueMules} of {fb.freezes} freezes hit real mules; {fb.clearsOnTrueMules} of {fb.clears} clears were on real mules.
                  </>
                )}
              </p>
              <p className="text-[12.5px] text-muted-foreground">
                Retrain with <code className="font-mono">python -m infra.feedback retrain</code> in <code className="font-mono">Multi-GNN/</code>. It writes to{' '}
                <code className="font-mono">models/feedback/</code> and never replaces the live checkpoint.{' '}
                {fb.lastRetrain ? `Last retrain ${fb.lastRetrain.at}, exit code ${fb.lastRetrain.exitCode}.` : 'Not retrained yet.'}
              </p>
            </Section>
          )}

          <Section title="Audit trail integrity" note="each row stores the SHA-256 of the previous row plus its own content; database triggers reject UPDATE and DELETE">
            <div className="flex flex-wrap items-center gap-3 border bg-card p-3 text-[13px]">
              {chain ? (
                chain.ok ? (
                  <span className="text-ok">Chain intact: {chain.checked.toLocaleString('en-IN')} rows verified.</span>
                ) : (
                  <span className="text-sev-critical">
                    Chain broken at row {chain.firstBad?.id} ({chain.firstBad?.entryId}, {chain.firstBad?.action}): {chain.firstBad?.reason}. {chain.checked} rows before it verify.
                  </span>
                )
              ) : (
                <span className="text-muted-foreground">Not checked yet.</span>
              )}
              {chain?.head && <span className="font-mono text-[11.5px] text-muted-foreground" title="Hash of the newest row">head {chain.head.slice(0, 16)}…</span>}
              {!!chain?.unchainedLegacyRows && <span className="text-[12px] text-muted-foreground">{chain.unchainedLegacyRows} rows from before hashing are not covered.</span>}
              <button onClick={verify} disabled={verifying} className="ml-auto h-7 rounded-sm border px-2.5 text-[12px] hover:bg-accent">
                {verifying ? 'Verifying…' : 'Verify now'}
              </button>
            </div>
          </Section>

          {roles && (
            <Section title="Roles" note="enforced by the bridge on every action; identity comes from the header picker (no login in this build)">
              <Table head={['User', 'Role', 'Can']}>
                {roles.users.map(u => (
                  <tr key={u.actor} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[12px]">{u.actor}</td>
                    <td className="py-1.5 pr-3">{u.role}</td>
                    <td className="py-1.5 text-[12.5px] text-muted-foreground">{roles.permissions[u.role].map(p => p.replace(/_/g, ' ')).join(', ')}</td>
                  </tr>
                ))}
              </Table>
            </Section>
          )}

          <Section title="Configuration" note="env vars on the bridge process; see Multi-GNN/infra/settings.py">
            <Table head={['Variable', 'Options']}>
              {ENV.map(([k, v]) => (
                <tr key={k} className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-[12px]">{k}</td>
                  <td className="py-1.5 text-[12.5px] text-muted-foreground">{v}</td>
                </tr>
              ))}
            </Table>
          </Section>
        </>
      )}
    </div>
  )
}
