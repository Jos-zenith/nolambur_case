'use client'

import { Activity, Radar, ShieldCheck, Siren, Target, Timer } from 'lucide-react'

import { duration, inrShort } from '@/lib/rail/format'
import { useRail } from '@/lib/rail/store'
import { StatTile, Term } from './kit'

export function MetricStrip() {
  const m = useRail(s => s.metrics)
  const ticks = useRail(s => s.tickCounts)
  if (!m) return null

  const stopped = m.frozenAccounts + m.heldAccounts
  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatTile
        i={0}
        icon={Activity}
        tone="brand"
        label="Transactions / min"
        value={m.txnsLastMinute}
        trend={ticks}
        note={`${inrShort(m.volumeReplayed)} moved so far`}
        help="Payments processed in the last minute of replay (or stream) time. The sparkline is rows per tick (0.5 s), so you can see the fraud burst arrive."
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
        icon={Timer}
        tone="teal"
        label="Median lead time"
        value={m.medianLeadSec}
        format={v => duration(v)}
        note="from alert to the mule forwarding the money"
        help={
          <>
            The <b>window to act</b>: how long after the alert the mule starts sending the money on. Freeze inside it and the money stays put.
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
        note="rule alerts that really are mules"
        help="Of the accounts the rules alerted on, the share the dataset labels as mules. The detectors never see these labels; they are used only to score the detectors."
      />
      <StatTile
        i={4}
        icon={Radar}
        tone="neutral"
        label="Mule recall"
        value={m.muleRecall === null ? null : m.muleRecall * 100}
        format={v => `${Math.round(v)}%`}
        note={`${m.mulesAlerted} of ${m.mulesSeen} mules seen caught`}
        help="Of the mule accounts that have appeared in the replay so far, the share with at least one rule alert."
      />
      <StatTile
        i={5}
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
            `${m.heldAccounts} held · ${m.frozenAccounts} frozen · ${inrShort(m.blockedGenuineAmount)} genuine blocked`
          )
        }
        help="Scam money in transfers the engine stopped because one side was held or frozen. Genuine blocked is the collateral: clean payments caught by the same block."
      />
    </section>
  )
}

