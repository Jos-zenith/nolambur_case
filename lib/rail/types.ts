// Shapes returned by Multi-GNN/rail_engine.py (the /rail routes on the GNN bridge).

export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type AlertStatus = 'open' | 'held' | 'escalated' | 'frozen' | 'cleared' | 'superseded'
export type RoleName = 'analyst' | 'supervisor' | 'admin'
export type Detector = 'high_value_new_payee' | 'pass_through' | 'hop_from_flagged' | 'model_only'
export type Role = 'victim' | 'l1_mule' | 'l2_mule' | 'clean' | 'unknown'

export interface Row {
  row: number
  ts: string
  t: number
  fromId: string
  fromVpa: string
  fromState: string
  toId: string
  toVpa: string
  toState: string
  amount: number
  gnn: number
  blocked: boolean
  /** replay = a CSV row; webhook / kafka / kinesis = an ingested payment */
  source: 'replay' | 'webhook' | 'kafka' | 'kinesis'
  /** null for ingested payments: they carry no label */
  label: { isFraud: boolean; layer: string } | null
}

export interface Alert {
  id: string
  detector: Detector
  detectorLabel: string
  ruleVersion: string
  accountId: string
  vpa: string
  state: string
  severity: Severity
  score: number
  gnnMax: number
  title: string
  reason: string
  facts: { label: string; value: string }[]
  rows: number[]
  firstEvidenceT: number
  createdT: number
  updatedT: number
  status: AlertStatus
  caseId: string | null
  leadSeconds: number | null
  truth: { role: Role; isMule: boolean }
}

export interface Metrics {
  simT: number
  source: 'replay' | 'webhook' | 'kafka' | 'kinesis'
  runId: string
  rowsReplayed: number
  /** null in stream mode (no replay) */
  rowsTotal: number | null
  ingested: number
  duplicatesDropped: number
  speed: number
  done: boolean
  txnsLastMinute: number
  volumeReplayed: number
  openAlerts: number
  openBySeverity: Record<Severity, number>
  medianTimeToAlertSec: number | null
  medianLeadSec: number | null
  precision: number | null
  muleRecall: number | null
  mulesSeen: number
  mulesAlerted: number
  frozenAccounts: number
  /** accounts on automatic hold (RAIL_AUTO_HOLD), awaiting a supervisor */
  heldAccounts: number
  autoHold: boolean
  blockedFraudAmount: number
  blockedGenuineAmount: number
}

export interface AuditEntry {
  id: string
  at: number
  simT: number
  action: string
  actor: string
  role?: RoleName | 'system'
  /** true when a supervisor released a hold or cleared a model score >= 0.9 */
  override?: boolean
  note: string
  alertId?: string
  accountId?: string
  caseId?: string
  tool?: Record<string, unknown>
}

export interface Case {
  id: string
  openedT: number
  accountIds: string[]
  alertIds: string[]
  report: Record<string, unknown> | null
}

export interface DatasetFacts {
  file: string
  rows: number
  accounts: number
  fraudRows: number
  start: string
  end: string
  fraudWindow: [string, string]
}

export interface Snapshot {
  metrics: Metrics
  alerts: Alert[]
  rows: Row[]
  audit: AuditEntry[]
  cases: Case[]
  frozen: { accountId: string; at: number; by: string; reference: string | null }[]
  tickCounts: number[]
  dataset: DatasetFacts
  paused: boolean
}

export interface TrailNode {
  id: string
  label: string
  amount: number
  count: number
  gnnMax: number
  flagged: boolean
  frozen: boolean
  next?: TrailNode[]
}

export interface Profile {
  accountId: string
  vpa: string
  bank: string | null
  state: string | null
  inboundCount: number
  outboundCount: number
  totalIn: number
  totalOut: number
  distinctPayers: number
  distinctPayees: number
  firstInT: number | null
  firstOutT: number | null
  frozen: { at: number; by: string; reference: string | null } | null
  truthRole: Role
  note: string
}

export interface AlertDetail {
  alert: Alert
  profile: Profile
  trail: { sources: TrailNode[]; destinations: TrailNode[]; totalIn: number; totalOut: number }
  evidence: Row[]
  otherAlerts: Alert[]
  audit: AuditEntry[]
  /** Analyst decisions on this account in earlier runs, from the durable store */
  history: { runId: string; alertId: string; detector: string; decision: string; actor: string; note: string; at: number }[]
}

export interface PathNode {
  id: string
  vpa: string
  flagged: boolean
  frozen: boolean
  truthRole: Role
}

export interface Downstream {
  accountId: string
  hops: number
  graph: 'memory' | 'neo4j'
  truncated: boolean
  paths: { nodes: PathNode[]; legs: { amount: number; t: number; row: number; gnn: number }[] }[]
  longest: Downstream['paths']
  accountsReached: number
  byHop: { hop: number; accounts: number }[]
  flaggedReached: number
}

export interface Platform {
  runId: string | null
  ingest: {
    mode: 'replay' | 'webhook' | 'kafka' | 'kinesis'
    source: { backend: string; state: string; received: number; lastError: string | null; lastAt: number | null; [k: string]: unknown }
    webhook: { endpoint: string; signed: boolean }
    inboxDepth: number
    webhookAccepted: number
    rejected: number
    scored: number
    scoreErrors: number
    lastScoreError: string | null
    lastScoreMs: number | null
    ingestedThisRun: number
    duplicatesDropped: number
    lastTickError?: string
  }
  graph: { backend: string; persistent: boolean; edges?: number; edgesWritten?: number; pending?: number; uri?: string; error?: string | null; fallbackReason: string | null }
  store: {
    backend: string | null
    url?: string
    error: string | null
    writeErrors?: number
    runs?: number
    auditEvents?: number
    decisions?: Record<string, number>
    agentActions?: number
    outbox?: Record<string, number>
    sandbox?: Record<string, number>
  }
  integrations: {
    gateway?: { url: string; sandbox: boolean; signed: boolean }
    cfcfrms?: { url: string; sandbox: boolean }
    sms?: { provider: string; mode: string; recipients: number }
    workerAlive?: boolean
    recent?: { id: number; kind: string; reference: string | null; status: string; attempts: number; last_error: string | null; created_at: number; delivered_at: number | null; response: Record<string, unknown> | null }[]
    error?: string | null
  }
}

export interface Feedback {
  decisions: Record<string, number>
  runs: number
  labelledEdges: number
  fraudLabels: number
  cleanLabels: number
  agreeWithDataset: number
  wouldFlip: number
  freezes: number
  freezesOnTrueMules: number
  clears: number
  clearsOnTrueMules: number
  lastRetrain: { at: string; exitCode: number; epochs: number; checkpoint: string; promoted: boolean } | null
}

export interface Investigation {
  legs: { sender: string; receiver: string; amount_inr: number; timestamp: string; row: number; gnnPrecomputed: number }[]
  scored: {
    legs: { sender: string; receiver: string; amount_inr: number; timestamp: string; fraud_probability: number }[]
    nodes: { handle: string; dataset_role: string; state: string | null; in_background_graph: boolean }[]
    scoredWithBackgroundGraph: boolean
    linkedAccounts: number
    normalized: boolean
  }
  seconds: number
  registry: Record<string, unknown> | null
}

export type StreamEvent =
  | { type: 'tick'; rows: Row[]; metrics: Metrics }
  | { type: 'alert'; alert: Alert }
  | { type: 'audit'; entry: AuditEntry }
  | { type: 'frozen'; accountId: string; vpa: string; reference: string | null }
  | { type: 'reset'; snapshot: Snapshot }
  | { type: 'held'; accountId: string; vpa: string; alertId: string }
  | { type: 'released'; accountId: string; vpa: string }

export interface Roles {
  users: { actor: string; role: RoleName }[]
  permissions: Record<RoleName, string[]>
  overrideScore: number
}

export interface AuditVerify {
  ok: boolean
  checked: number
  firstBad: { id: number; entryId: string; action: string; runId: string; reason: string } | null
  head: string | null
  unchainedLegacyRows: number
  checkedAt: number
}
