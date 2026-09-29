import type { Role } from './types'

export function inr(n: number) {
  return `₹${Math.round(n).toLocaleString('en-IN')}`
}

/** Indian short form: ₹4.2 L, ₹1.3 Cr. */
export function inrShort(n: number) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(1)}k`
  return `₹${Math.round(n)}`
}

// Dataset timestamps are naive local times; the engine encodes them as if UTC,
// so formatting in UTC shows exactly what the CSV says.
export function clock(t: number, seconds = true) {
  return new Date(t * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, timeZone: 'UTC' })
}

export function stamp(t: number) {
  const d = new Date(t * 1000)
  return `${d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })} ${clock(t)}`
}

export function duration(sec: number | null | undefined) {
  if (sec === null || sec === undefined) return '—'
  const s = Math.round(Math.abs(sec))
  const sign = sec <= -0.5 ? '−' : '' // a negative lead: the alert came after the money left
  if (s < 60) return `${sign}${s}s`
  if (s < 3600) return `${sign}${Math.floor(s / 60)}m ${s % 60}s`
  return `${sign}${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

export function ago(now: number, t: number) {
  const s = Math.max(0, now - t)
  return s < 5 ? 'just now' : `${duration(s)} ago`
}

export const ROLE_LABEL: Record<Role, string> = {
  victim: 'victim',
  l1_mule: 'L1 mule',
  l2_mule: 'L2 mule',
  clean: 'clean',
  unknown: 'unknown',
}

export const pct = (x: number | null | undefined) => (x === null || x === undefined ? '—' : `${Math.round(x * 100)}%`)

/** Dataset label for a row; ingested payments have none. */
export const rowLabel = (r: { label: { isFraud: boolean; layer: string } | null }) => (r.label ? (r.label.isFraud ? r.label.layer : 'clean') : 'unlabelled')
