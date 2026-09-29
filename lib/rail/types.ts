// Shapes returned by Multi-GNN/rail_engine.py (the /rail routes on the GNN bridge).

export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type AlertStatus = 'open' | 'held' | 'escalated' | 'frozen' | 'cleared' | 'superseded'
export type RoleName = 'analyst' | 'supervisor' | 'admin'
export type Detector = 'inflow_new_payers' | 'pass_through' | 'structuring' | 'hop_from_flagged' | 'model_only'
/** The decision router's graded actions (rail_engine.LEVELS) */
export type ActionLevel = 'alert_only' | 'delay_settlement' | 'hold_outbound' | 'full_hold'
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
  /** held back by a delay-settlement restriction on the payer */
  delayed?: boolean
  channel?: 'P2P' | 'P2M'
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
  /** the router's level for this alert */
  action?: ActionLevel
  truth: { role: Role; isMule: boolean }
}

/** A graded restriction on an account (rail_engine RailEngine.held) */
export interface Restriction {
  at: number
  by: string
  alertId: string
  policy: string
  level: 1 | 2 | 3
  action: ActionLevel
  label: string
  expiresT: number
  appeal: {
    at: number
    by: string
    statement: string
    dueT: number
    status: 'open' | 'upheld' | 'released' | 'lapsed'
    decidedBy?: string
    decidedT?: number
    note?: string
  } | null
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
  /** accounts at hold-outbound or full hold, awaiting a supervisor */
  heldAccounts: number
  /** accounts whose outgoing transfers are delayed */
  delayedAccounts?: number
  restrictionsByLevel?: Record<'delay_settlement' | 'hold_outbound' | 'full_hold', number>
  appealsOpen?: number
  delayedAmount?: number
  recoveredFraudAmount?: number
  modelThreshold?: number
  ruleVersion?: string
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
  version?: 'v1' | 'v2'
  splits?: Record<'train' | 'val' | 'test', [string, string]> | null
  scores?: string
  file: string
  rows: number
  accounts: number
  fraudRows: number
  start: string
  end: string
  fraudWindow: [string | null, string | null]
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
  held?: Restriction | null
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
    source: {
      backend: string
      state: string
      received: number
      acked?: number
      deadLettered?: number
      pausedForBacklog?: boolean
      /** Kafka: messages behind the high-water marks. Kinesis: max MillisBehindLatest. */
      lag?: number | null
      lastError: string | null
      lastAt: number | null
      lastCommitAt?: number | null
      partitions?: string[]
      shards?: { id: string; state: string; millisBehind?: number | null; resumedFrom?: string | null; parents?: string[] }[]
      [k: string]: unknown
    }
    webhook: { endpoint: string; signed: boolean }
    inboxDepth: number
    highWater?: number
    deadLetters?: { id: number; source: string; position: string | null; error: string; at: number }[]
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
    durable?: boolean
    warning?: string | null
    runs?: number
    auditEvents?: number
    decisions?: Record<string, number>
    agentActions?: number
    outbox?: Record<string, number>
    sandbox?: Record<string, number>
    deadLetters?: number
  }
  registry?: RegistryCounts
  scoring?: {
    mode: string
    scoringMode?: 'exact' | 'cached'
    edges?: number
    edgesInWindow?: number
    nodes?: number
    windowHours?: number
    exact?: boolean
    features?: string[]
    refreshSeconds?: number | null
    cacheRefreshes?: number
    lastRefreshMs?: number | null
    batches?: number
    lastMs?: number | null
    lastSubgraphEdges?: number | null
    threshold?: { threshold: number; source: string } | null
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

/** public/rail-snapshot.json: what a real bridge reported, captured by scripts/capture-rail-snapshot.mjs */
export interface RailSnapshotFile {
  capturedAt: string
  capturedFrom: string
  metrics: Metrics
  dataset: DatasetFacts
  evaluation: Record<string, unknown>
}

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

export interface RegistryCounts {
  companies?: number
  directors?: number
  directorships?: number
  disqualifiedDirectors?: number
  linkedAccounts?: number
  provider?: { mode: string; url: string | null; errors: number; lastError: string | null }
  error?: string
}

export type FindingSeverity = 'high' | 'medium' | 'low'

export interface RegistryReport {
  cin: string
  cinFacts: { valid: boolean; kind: string; listed?: boolean; state?: string; year?: number; type?: string }
  company: {
    cin: string
    name: string | null
    status: string | null
    company_class: string | null
    incorporated_on: string | null
    state: string | null
    roc: string | null
    paid_up_capital: number | null
    authorized_capital: number | null
    activity: string | null
    address: string | null
    last_annual_return: number | null
    source: string | null
  } | null
  directors: { din: string; name: string | null; designation: string | null; declared: boolean; disqualified: boolean; currentDirectorships: number; otherCompanies: { cin: string; name: string | null; status: string | null; current: boolean }[] }[]
  commonControl: { cin: string; name: string | null; status: string | null; incorporatedOn: string | null; sharedDirectors: string[] }[]
  sameAddress: { cin: string; name: string | null; status: string | null; incorporated_on: string | null }[]
  sameAddressCount: number
  crossover: { cin: string; vpa: string; via: string; frozen: boolean; held: boolean; flagged: boolean; alerts: string[] }[]
  findings: { severity: FindingSeverity; code: string; text: string }[]
  decision: 'approve' | 'review' | 'hold'
  provider: string
}
