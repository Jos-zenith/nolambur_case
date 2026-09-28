// The pre-run: what a real bridge reported after replaying the whole dataset, captured by
// scripts/capture-rail-snapshot.mjs. Bundled (5 KB) so the numbers are in the first HTML the
// server sends, before any request to the bridge. Refresh it by re-running that script.
import data from '@/public/rail-snapshot.json'

import type { RailSnapshotFile } from './types'

export const BUNDLED_SNAPSHOT = data as unknown as RailSnapshotFile

/** Same text on the server and in the browser (no hydration mismatch), in Indian time. */
export function capturedLabel(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' }) + ' IST'
}
