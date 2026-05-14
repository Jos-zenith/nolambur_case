import 'server-only'

import neo4j, { Driver } from 'neo4j-driver'

const NEO4J_URI = process.env.NEO4J_URI ?? 'bolt://localhost:7687'
const NEO4J_USERNAME = process.env.NEO4J_USERNAME ?? 'neo4j'
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD ?? 'password'

type GlobalNeo4j = typeof globalThis & {
  __neo4jDriver?: Driver
}

type Neo4jIntegerLike = {
  toNumber: () => number
}

type Neo4jValue =
  | string
  | number
  | boolean
  | null
  | Neo4jIntegerLike
  | Neo4jValue[]
  | { [key: string]: Neo4jValue }

export interface Neo4jGraphSummary {
  victimCount: number
  muleCount: number
  aggregatorCount: number
  beneficiaryCount: number
  transferCount: number
}

export interface Neo4jInitializationResult {
  schemaStatements: number
  seededGraph: boolean
  summary: Neo4jGraphSummary
}

const schemaStatements = [
  'CREATE CONSTRAINT victim_id IF NOT EXISTS FOR (v:Victim) REQUIRE v.id IS UNIQUE',
  'CREATE CONSTRAINT mule_id IF NOT EXISTS FOR (m:Mule) REQUIRE m.id IS UNIQUE',
  'CREATE CONSTRAINT aggregator_id IF NOT EXISTS FOR (a:Aggregator) REQUIRE a.id IS UNIQUE',
  'CREATE CONSTRAINT beneficiary_id IF NOT EXISTS FOR (b:Beneficiary) REQUIRE b.id IS UNIQUE',
]

const seedGraph = {
  victim: {
    id: 'victim-nolambur-001',
    name: 'Nolambur Victim',
    phone: '+91-90000-00001',
    location: 'Tamil Nadu',
    victimType: 'digital_arrest',
  },
  mules: [
    {
      id: 'mule-haridwar-0047',
      accountNumber: 'XXXX0471',
      ifsc: 'SBIN0000047',
      bankName: 'State Bank of India',
      location: 'Haridwar',
      riskScore: 0.95,
      inDegree: 12,
      outDegree: 11,
      velocity: 0.91,
    },
    {
      id: 'mule-jaipur-0051',
      accountNumber: 'XXXX0051',
      ifsc: 'HDFC0000051',
      bankName: 'HDFC Bank',
      location: 'Jaipur',
      riskScore: 0.92,
      inDegree: 9,
      outDegree: 8,
      velocity: 0.88,
    },
    {
      id: 'mule-rohtak-0089',
      accountNumber: 'XXXX0089',
      ifsc: 'ICIC0000089',
      bankName: 'ICICI Bank',
      location: 'Rohtak',
      riskScore: 0.89,
      inDegree: 8,
      outDegree: 7,
      velocity: 0.84,
    },
  ],
  aggregator: {
    id: 'aggregator-0012',
    accountNumber: 'AGG0012',
    consolidationRate: 0.97,
    riskScore: 0.98,
  },
  beneficiary: {
    id: 'beneficiary-0001',
    name: 'Layer 3 Beneficiary',
    location: 'Inter-state exit node',
  },
  transfers: [
    {
      sourceId: 'victim-nolambur-001',
      targetId: 'mule-haridwar-0047',
      type: 'TRANSFERS_TO',
      amount: 500000,
      timestamp: '2026-05-13T09:40:00Z',
      velocity: 0.31,
      utrNumber: 'UTR-NOL-0047',
    },
    {
      sourceId: 'victim-nolambur-001',
      targetId: 'mule-jaipur-0051',
      type: 'TRANSFERS_TO',
      amount: 500000,
      timestamp: '2026-05-13T09:41:10Z',
      velocity: 0.29,
      utrNumber: 'UTR-NOL-0051',
    },
    {
      sourceId: 'victim-nolambur-001',
      targetId: 'mule-rohtak-0089',
      type: 'TRANSFERS_TO',
      amount: 500000,
      timestamp: '2026-05-13T09:42:25Z',
      velocity: 0.27,
      utrNumber: 'UTR-NOL-0089',
    },
    {
      sourceId: 'mule-haridwar-0047',
      targetId: 'aggregator-0012',
      type: 'CONSOLIDATES_TO',
      amount: 450000,
      timestamp: '2026-05-13T09:44:10Z',
      velocity: 0.84,
      utrNumber: 'UTR-AGG-0047',
    },
    {
      sourceId: 'mule-jaipur-0051',
      targetId: 'aggregator-0012',
      type: 'CONSOLIDATES_TO',
      amount: 410000,
      timestamp: '2026-05-13T09:45:50Z',
      velocity: 0.86,
      utrNumber: 'UTR-AGG-0051',
    },
    {
      sourceId: 'aggregator-0012',
      targetId: 'beneficiary-0001',
      type: 'DISPERSES_TO',
      amount: 860000,
      timestamp: '2026-05-13T09:48:00Z',
      velocity: 0.96,
      utrNumber: 'UTR-BEN-0012',
    },
  ],
}

function getNeo4jDriver(): Driver {
  const globalForNeo4j = globalThis as GlobalNeo4j

  if (!globalForNeo4j.__neo4jDriver) {
    globalForNeo4j.__neo4jDriver = neo4j.driver(
      NEO4J_URI,
      neo4j.auth.basic(NEO4J_USERNAME, NEO4J_PASSWORD),
      {
        maxConnectionLifetime: 60_000,
        maxConnectionPoolSize: 10,
        connectionAcquisitionTimeout: 5_000,
      },
    )
  }

  return globalForNeo4j.__neo4jDriver
}

function isNeo4jIntegerLike(value: unknown): value is Neo4jIntegerLike {
  return typeof value === 'object' && value !== null && typeof (value as Neo4jIntegerLike).toNumber === 'function'
}

function normalizeValue(value: Neo4jValue): unknown {
  if (isNeo4jIntegerLike(value)) {
    return value.toNumber()
  }

  if (Array.isArray(value)) {
    return value.map(item => normalizeValue(item))
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [key, normalizeValue(nestedValue as Neo4jValue)]),
    )
  }

  return value
}

export async function runGraphQuery<T extends Record<string, unknown>>(
  query: string,
  parameters: Record<string, unknown> = {},
): Promise<T[]> {
  const session = getNeo4jDriver().session()

  try {
    const result = await session.run(query, parameters)
    return result.records.map(record => normalizeValue(record.toObject() as Neo4jValue) as T)
  } finally {
    await session.close()
  }
}

export async function ensureNeo4jSchema(): Promise<{ schemaStatements: number }> {
  const session = getNeo4jDriver().session()

  try {
    for (const statement of schemaStatements) {
      await session.run(statement)
    }

    return {
      schemaStatements: schemaStatements.length,
    }
  } finally {
    await session.close()
  }
}

export async function seedPilotGraph(): Promise<void> {
  const session = getNeo4jDriver().session()

  try {
    await session.run(
      `MERGE (v:Victim {id: $victim.id})
       SET v.name = $victim.name,
           v.phone = $victim.phone,
           v.location = $victim.location,
           v.victimType = $victim.victimType,
           v.createdAt = datetime()
       WITH v
       UNWIND $mules AS mule
       MERGE (m:Mule {id: mule.id})
       SET m.accountNumber = mule.accountNumber,
           m.ifsc = mule.ifsc,
           m.bankName = mule.bankName,
           m.location = mule.location,
           m.riskScore = mule.riskScore,
           m.inDegree = mule.inDegree,
           m.outDegree = mule.outDegree,
           m.velocity = mule.velocity,
           m.lastActive = datetime()
       WITH v
       MERGE (a:Aggregator {id: $aggregator.id})
       SET a.accountNumber = $aggregator.accountNumber,
           a.consolidationRate = $aggregator.consolidationRate,
           a.riskScore = $aggregator.riskScore
       WITH v, a
       MERGE (b:Beneficiary {id: $beneficiary.id})
       SET b.name = $beneficiary.name,
           b.location = $beneficiary.location
      `,
      {
        victim: seedGraph.victim,
        mules: seedGraph.mules,
        aggregator: seedGraph.aggregator,
        beneficiary: seedGraph.beneficiary,
      },
    )

    for (const transfer of seedGraph.transfers) {
      await session.run(
        `MATCH (source {id: $sourceId})
         MATCH (target {id: $targetId})
         MERGE (source)-[t:${transfer.type} {utrNumber: $utrNumber}]->(target)
         SET t.amount = $amount,
             t.timestamp = datetime($timestamp),
             t.velocity = $velocity`,
        transfer,
      )
    }
  } finally {
    await session.close()
  }
}

export async function initializeNeo4jGraph(): Promise<Neo4jInitializationResult> {
  const schemaResult = await ensureNeo4jSchema()
  await seedPilotGraph()

  return {
    schemaStatements: schemaResult.schemaStatements,
    seededGraph: true,
    summary: await getGraphSummary(),
  }
}

export async function getGraphSummary(): Promise<Neo4jGraphSummary> {
  const summaryRows = await runGraphQuery<{
    victimCount: number
    muleCount: number
    aggregatorCount: number
    beneficiaryCount: number
    transferCount: number
  }>(
    `MATCH (v:Victim)
     OPTIONAL MATCH (v)-[t:TRANSFERS_TO]->(m:Mule)
     OPTIONAL MATCH (m)-[:CONSOLIDATES_TO]->(a:Aggregator)
     OPTIONAL MATCH (a)-[:DISPERSES_TO]->(b:Beneficiary)
     RETURN
       count(DISTINCT v) AS victimCount,
       count(DISTINCT m) AS muleCount,
       count(DISTINCT a) AS aggregatorCount,
       count(DISTINCT b) AS beneficiaryCount,
       count(DISTINCT t) AS transferCount`,
  )

  const summary = summaryRows[0]

  return {
    victimCount: summary?.victimCount ?? 0,
    muleCount: summary?.muleCount ?? 0,
    aggregatorCount: summary?.aggregatorCount ?? 0,
    beneficiaryCount: summary?.beneficiaryCount ?? 0,
    transferCount: summary?.transferCount ?? 0,
  }
}
