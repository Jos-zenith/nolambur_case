// Capture what a running GNN bridge reports, for the console to show while the live bridge wakes up.
//
//   node scripts/capture-rail-snapshot.mjs [bridge-url]      default: $GNN_FASTAPI_URL or http://127.0.0.1:8001
//
// Writes public/rail-snapshot.json: the bridge's /rail/status metrics, /rail/evaluation and /rail/graph/network, verbatim,
// plus where and when they were captured. The console labels everything from this file as a snapshot
// and replaces it with live data as soon as the bridge answers. Capture once the replay (RAIL_SOURCE=replay)
// is a few days into the v2 data, so the numbers show campaigns, alerts and holds, not an empty start.

import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const bridge = (process.argv[2] || process.env.GNN_FASTAPI_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')

async function get(path) {
  const res = await fetch(`${bridge}${path}`, { signal: AbortSignal.timeout(120_000) })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return res.json()
}

const status = await get('/rail/status')
if (status.status !== 'ready') throw new Error(`bridge is ${status.status}, not ready`)
const evaluation = await get('/rail/evaluation')
const network = await get('/rail/graph/network?limit=40')
if (status.metrics.rowsReplayed < 20000) {
  console.warn(`warning: only ${status.metrics.rowsReplayed} rows replayed; few campaigns have played yet`)
}

const snapshot = {
  capturedAt: new Date().toISOString(),
  capturedFrom: bridge,
  metrics: status.metrics,
  dataset: status.dataset,
  evaluation,
  network,
}
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'rail-snapshot.json')
writeFileSync(out, JSON.stringify(snapshot))
console.log(`wrote ${out}: row ${status.metrics.rowsReplayed}, ${status.metrics.openAlerts} open alerts, ₹${Math.round(status.metrics.blockedFraudAmount).toLocaleString('en-IN')} blocked`)
