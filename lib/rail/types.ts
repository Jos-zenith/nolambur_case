// Shapes returned by Multi-GNN/rail_engine.py (the /rail routes on the GNN bridge).

export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type AlertStatus = 'open' | 'escalated' | 'frozen' | 'cleared' | 'superseded'
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
  label: { isFraud: boolean; layer: string }
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
  rowsReplayed: number
  rowsTotal: number
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
  blockedFraudAmount: number
  blockedGenuineAmount: number
}

export interface AuditEntry {
  id: string
  at: number
  simT: number
  action: string
  actor: string
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
