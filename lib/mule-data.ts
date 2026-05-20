export type MuleNodeType = 'victim' | 'layer1' | 'layer2' | 'beneficiary'

export interface MuleGraphNode {
  id: string
  label: string
  type: MuleNodeType
  mule_score: number
  location?: string
  amount?: number
  in_velocity?: number
  out_velocity?: number
  geo_mismatch?: boolean
}

export interface MuleGraphLink {
  source: string
  target: string
  amount: number
  velocity: number
  timestamp: string
  relationship: string
}

export interface MuleGraphPayload {
  nodes: MuleGraphNode[]
  links: MuleGraphLink[]
  generated_at: string
  source: 'neo4j' | 'fallback'
}

export interface MulePulseAlert {
  id: string
  accountId: string
  label: string
  muleScore: number
  inVelocity: number
  outVelocity: number
  geoMismatch: boolean
  statePair: string
  timestamp: string
}

const fallbackGraph: MuleGraphPayload = {
  source: 'fallback',
  generated_at: new Date().toISOString(),
  nodes: [
    { id: 'victim-001', label: 'Victim (TN)', type: 'victim', mule_score: 0.08, location: 'Tamil Nadu' },
    { id: 'mule-047', label: 'MU-0047', type: 'layer1', mule_score: 0.95, location: 'Haridwar', amount: 2350000, in_velocity: 0.31, out_velocity: 0.84, geo_mismatch: true },
    { id: 'mule-051', label: 'MU-0051', type: 'layer1', mule_score: 0.92, location: 'Jaipur', amount: 1820000, in_velocity: 0.29, out_velocity: 0.82, geo_mismatch: true },
    { id: 'mule-089', label: 'MU-0089', type: 'layer1', mule_score: 0.89, location: 'Rohtak', amount: 1570000, in_velocity: 0.27, out_velocity: 0.79, geo_mismatch: true },
    { id: 'agg-012', label: 'AG-0012', type: 'layer2', mule_score: 0.98, location: 'Delhi', amount: 6740000, in_velocity: 0.84, out_velocity: 0.96, geo_mismatch: true },
    { id: 'agg-019', label: 'AG-0019', type: 'layer2', mule_score: 0.94, location: 'Delhi', amount: 4510000, in_velocity: 0.81, out_velocity: 0.93, geo_mismatch: true },
    { id: 'beneficiary-001', label: 'Beneficiary', type: 'beneficiary', mule_score: 0.99, location: 'Out-of-state exit' },
  ],
  links: [
    { source: 'victim-001', target: 'mule-047', amount: 500000, velocity: 0.31, timestamp: '2026-05-20T08:14:00Z', relationship: 'TRANSFERS_TO' },
    { source: 'victim-001', target: 'mule-051', amount: 500000, velocity: 0.29, timestamp: '2026-05-20T08:15:15Z', relationship: 'TRANSFERS_TO' },
    { source: 'victim-001', target: 'mule-089', amount: 500000, velocity: 0.27, timestamp: '2026-05-20T08:16:10Z', relationship: 'TRANSFERS_TO' },
    { source: 'mule-047', target: 'agg-012', amount: 450000, velocity: 0.84, timestamp: '2026-05-20T08:18:00Z', relationship: 'CONSOLIDATES_TO' },
    { source: 'mule-051', target: 'agg-012', amount: 380000, velocity: 0.82, timestamp: '2026-05-20T08:19:30Z', relationship: 'CONSOLIDATES_TO' },
    { source: 'mule-089', target: 'agg-019', amount: 420000, velocity: 0.79, timestamp: '2026-05-20T08:20:40Z', relationship: 'CONSOLIDATES_TO' },
    { source: 'agg-012', target: 'beneficiary-001', amount: 830000, velocity: 0.96, timestamp: '2026-05-20T08:24:00Z', relationship: 'DISPERSES_TO' },
    { source: 'agg-019', target: 'beneficiary-001', amount: 420000, velocity: 0.93, timestamp: '2026-05-20T08:25:20Z', relationship: 'DISPERSES_TO' },
  ],
}

const pulseAlerts: MulePulseAlert[] = [
  { id: 'pulse-001', accountId: 'MU-0047', label: 'Haridwar mule flagged', muleScore: 0.95, inVelocity: 0.31, outVelocity: 0.84, geoMismatch: true, statePair: 'TN → UK', timestamp: '2026-05-20T08:14:00Z' },
  { id: 'pulse-002', accountId: 'MU-0051', label: 'Jaipur mule flagged', muleScore: 0.92, inVelocity: 0.29, outVelocity: 0.82, geoMismatch: true, statePair: 'TN → RJ', timestamp: '2026-05-20T08:15:15Z' },
  { id: 'pulse-003', accountId: 'AG-0012', label: 'Aggregator surge', muleScore: 0.98, inVelocity: 0.84, outVelocity: 0.96, geoMismatch: true, statePair: 'RJ → DL', timestamp: '2026-05-20T08:24:00Z' },
  { id: 'pulse-004', accountId: 'MU-0089', label: 'Rohtak mule flagged', muleScore: 0.89, inVelocity: 0.27, outVelocity: 0.79, geoMismatch: true, statePair: 'TN → HR', timestamp: '2026-05-20T08:20:40Z' },
  { id: 'pulse-005', accountId: 'BEN-0001', label: 'Beneficiary exit detected', muleScore: 0.99, inVelocity: 0.93, outVelocity: 0.99, geoMismatch: true, statePair: 'DL → exit', timestamp: '2026-05-20T08:25:20Z' },
]

export function getFallbackMuleGraph(): MuleGraphPayload {
  return {
    ...fallbackGraph,
    generated_at: new Date().toISOString(),
    nodes: fallbackGraph.nodes.map(node => ({ ...node })),
    links: fallbackGraph.links.map(link => ({ ...link })),
  }
}

export function getPulseAlerts(): MulePulseAlert[] {
  return pulseAlerts.map(alert => ({ ...alert }))
}