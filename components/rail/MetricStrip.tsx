'use client'

import { Activity, Radar, ShieldCheck, Siren, Target, Timer } from 'lucide-react'

import { duration, inrShort, pct } from '@/lib/rail/format'
import { useDisplayMetrics, useRail } from '@/lib/rail/store'
import { StatTile, Term } from './kit'

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
  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatTile
        i={0}
        icon={ShieldCheck}
        tone={m.blockedFraudAmount > 0 ? 'ok' : 'neutral'}
        label="Fraud blocked"
        value={m.blockedFraudAmount}
        format={v => inrShort(v)}
        note={
          stopped === 0 ? (
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
        help="Scam money in transfers the engine stopped because one side was held or frozen. Genuine is the collateral: clean payments caught by the same block."
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
        note={`${m.mulesAlerted} of ${m.mulesSeen} · rules alone ${pct(m.muleRecallRules ?? null)}`}
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
        note="of alerted accounts are mules"
        help="Of the labelled accounts with any alert (rules or GNN), the share the dataset labels as mules. The detectors never see these labels; they are used only to score them."
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
        value={m.txnsLastMinute}
        trend={ticks}
        note={`${inrShort(m.volumeReplayed)} moved so far`}
        help="Payments processed in the last minute of replay (or stream) time. The sparkline is rows per tick (0.5 s), so you can see a scam burst arrive."
      />
    </section>
  )
}
