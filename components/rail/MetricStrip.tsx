'use client'

import { Activity, Radar, ShieldCheck, Siren, Target, Timer } from 'lucide-react'

import { duration, inrShort, pct } from '@/lib/rail/format'
import type { Metrics } from '@/lib/rail/types'
import { useDisplayMetrics, useRail } from '@/lib/rail/store'
import { StatTile, Term } from './kit'

/**
 * The disclosed false positive: non-scam money the holds stopped, what it was, and how a hold ends.
 * Durations fall back to rail_engine.py LEVEL_SECONDS / APPEAL_SLA_SECONDS for snapshots that predate
 * the restriction fields.
 */
export function collateralNote(m: Metrics): string | null {
  if (m.blockedGenuineAmount <= 0) return null
  const hold = m.restrictionHours?.hold_outbound ?? 24
  const full = m.restrictionHours?.full_hold ?? 72
  const appeal = m.appealSlaHours ?? 24
  const what =
    m.blockedGenuinePayments !== undefined
      ? `${m.blockedGenuinePayments} non-scam payments (largest ${inrShort(m.blockedGenuineMaxAmount ?? 0)}) into or out of held accounts`
      : 'non-scam payments into or out of held accounts'
  const who =
    m.restrictedAccounts !== undefined && m.restrictedNonMules !== undefined
      ? m.restrictedNonMules === 0
        ? ` All ${m.restrictedAccounts} held accounts were mules; this is their everyday spending.`
        : ` ${m.restrictedNonMules} of ${m.restrictedAccounts} held accounts were not mules.`
      : ''
  return `${inrShort(m.blockedGenuineAmount)} genuine money stopped too: ${what}.${who} A hold lifts itself after ${hold} h (full hold ${full} h), and an appeal not decided within ${appeal} h releases it.`
}

/** The live numbers cover every replayed day, the model's training days included: never the figures to quote. */
export function ReplayScopeNote({ className }: { className?: string }) {
  return (
    <p className={className}>
      <b className="font-semibold">Full-dataset replay:</b> all 10 days, including the 8 the model trained on, so recall and precision here run high. Quote the
      held-out test ranges instead: <b className="font-semibold">58–77% of mules caught, 58–78% precision</b>.
    </p>
  )
}

/**
 * The running replay, so far. Same definitions as /rail/evaluation (account level, rules + model,
 * lead per mule), but over every day replayed, including the days the model trained on.
 */
export function MetricStrip() {
  const { metrics: m, stale } = useDisplayMetrics()
  const liveTicks = useRail(s => s.tickCounts)
  const ticks = stale ? undefined : liveTicks
  if (!m) return null

  const stopped = m.frozenAccounts + m.heldAccounts
  const finished = m.rowsTotal !== null && m.done
  const collateral = collateralNote(m)
  return (
    <section className="grid gap-3">
    <ReplayScopeNote className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[12.5px] leading-snug text-muted-foreground" />
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatTile
        i={0}
        icon={ShieldCheck}
        tone={m.blockedFraudAmount > 0 ? 'ok' : 'neutral'}
        label="Fraud blocked"
        value={m.blockedFraudAmount}
        format={v => inrShort(v)}
        note={
          stopped === 0 && m.blockedFraudAmount > 0 ? (
            `no holds active now: earlier ones expired · ${inrShort(m.blockedGenuineAmount)} genuine`
          ) : stopped === 0 ? (
            m.autoHold ? (
              <>
                auto-<Term k="hold">hold</Term> on: waiting for a critical alert
              </>
            ) : (
              'freeze an account to block its transfers'
            )
          ) : (
            `${m.heldAccounts} held · ${m.frozenAccounts} frozen · ${inrShort(m.blockedGenuineAmount)} genuine`
          )
        }
        help={`Scam money in transfers the engine stopped because one side was held or frozen. ${collateral ?? 'No genuine payments were caught by the same blocks.'}`}
      />
      <StatTile
        i={1}
        icon={Siren}
        tone={m.openBySeverity.critical ? 'critical' : 'neutral'}
        label="Open alerts"
        value={m.openAlerts}
        note={`${m.openBySeverity.critical} critical · ${m.openBySeverity.high} high · ${m.openBySeverity.medium} medium`}
        help="Alerts nobody has cleared, escalated or frozen yet. Critical means several signals at once, such as two victims paying the same new account."
      />
      <StatTile
        i={2}
        icon={Radar}
        tone="neutral"
        label="Mules caught"
        value={m.muleRecall === null ? null : m.muleRecall * 100}
        format={v => `${Math.round(v)}%`}
        note={`${m.mulesAlerted} of ${m.mulesSeen} · rules alone ${pct(m.muleRecallRules ?? null)} · in-sample`}
        help={
          <>
            <Term k="recall">Recall</Term>, rules + GNN: of the mule accounts scam money has reached so far, the share with an alert. A mule that has only bought
            groceries yet is not counted: nothing could catch it.
          </>
        }
      />
      <StatTile
        i={3}
        icon={Target}
        tone="neutral"
        label="Precision"
        value={m.precision === null ? null : m.precision * 100}
        format={v => `${Math.round(v)}%`}
        note="of alerted accounts are mules · in-sample"
        help="Of the labelled accounts with any alert (rules or GNN), the share the dataset labels as mules. The detectors never see these labels; they are used only to score them. Over the full replay, training days included: held-out test precision is 58–78%, and at a realistic UPI fraud rate it would fall to a few per cent (reports/README.md 3.2)."
      />
      <StatTile
        i={4}
        icon={Timer}
        tone="teal"
        label="Median lead time"
        value={m.medianLeadSec}
        format={v => duration(v)}
        note={m.leadN ? `${m.alertedBeforeMoneyLeft} of ${m.leadN} mules alerted before money left` : 'per mule: alert → money leaves'}
        help={
          <>
            The <b>window to act</b>, per mule: from its first alert to the first scam money leaving it. Negative means the alert came after. Freeze inside it and the
            money stays put.
          </>
        }
      />
      <StatTile
        i={5}
        icon={Activity}
        tone="brand"
        label="Transactions / min"
        value={finished ? null : m.txnsLastMinute}
        display={finished ? 'Done' : undefined}
        trend={finished ? undefined : ticks}
        note={finished ? `replay finished · ${m.rowsTotal?.toLocaleString('en-IN')} payments, ${inrShort(m.volumeReplayed)}` : `${inrShort(m.volumeReplayed)} moved so far`}
        help="Payments processed in the last minute of replay (or stream) time. The sparkline is rows per tick (0.5 s), so you can see a scam burst arrive. A finished replay processes nothing more; measured throughput is in reports/README.md section 4."
      />
    </div>
    </section>
  )
}
