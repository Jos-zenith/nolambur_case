import { NextResponse } from 'next/server'

import { runGraphQuery } from '@/lib/graph-db'
import { getFallbackMuleGraph, type MuleGraphPayload, type MuleNodeType } from '@/lib/mule-data'

export const runtime = 'nodejs'

function resolveNodeType(labels: string[]): MuleNodeType {
  if (labels.includes('Victim')) return 'victim'
  if (labels.includes('Aggregator')) return 'layer2'
  if (labels.includes('Beneficiary')) return 'beneficiary'
  return 'layer1'
}

export async function GET() {
  try {
    const nodeRows = await runGraphQuery<{
      id: string
      labels: string[]
      props: Record<string, unknown>
    }>(
      `MATCH (n)
       WHERE n.id IS NOT NULL
       RETURN coalesce(n.id, elementId(n)) AS id, labels(n) AS labels, properties(n) AS props
       LIMIT 150`,
    )

    const linkRows = await runGraphQuery<{
      sourceId: string
      targetId: string
      relationship: string
      props: Record<string, unknown>
    }>(
      `MATCH (source)-[rel]->(target)
       WHERE source.id IS NOT NULL AND target.id IS NOT NULL
       RETURN
         source.id AS sourceId,
         target.id AS targetId,
         type(rel) AS relationship,
         properties(rel) AS props
       LIMIT 250`,
    )

    const payload: MuleGraphPayload = {
      source: 'neo4j',
      generated_at: new Date().toISOString(),
      nodes: nodeRows.map(row => {
        const muleScore = Number(row.props.mule_score ?? row.props.riskScore ?? (row.labels.includes('Victim') ? 0.08 : 0.9))
        return {
          id: row.id,
          label: String(row.props.name ?? row.props.accountNumber ?? row.id),
          type: resolveNodeType(row.labels),
          mule_score: Number.isFinite(muleScore) ? muleScore : 0.9,
          location: typeof row.props.location === 'string' ? row.props.location : undefined,
          amount: typeof row.props.amount === 'number' ? row.props.amount : undefined,
          in_velocity: typeof row.props.inVelocity === 'number' ? row.props.inVelocity : undefined,
          out_velocity: typeof row.props.outVelocity === 'number' ? row.props.outVelocity : undefined,
          geo_mismatch: typeof row.props.geoMismatch === 'boolean' ? row.props.geoMismatch : undefined,
        }
      }),
      links: linkRows.map(row => ({
        source: row.sourceId,
        target: row.targetId,
        relationship: row.relationship,
        amount: Number(row.props.amount ?? 0),
        velocity: Number(row.props.velocity ?? 0.5),
        timestamp: String(row.props.timestamp ?? new Date().toISOString()),
      })),
    }

    if (payload.nodes.length === 0 || payload.links.length === 0) {
      return NextResponse.json(getFallbackMuleGraph(), { status: 200 })
    }

    return NextResponse.json(payload, { status: 200 })
  } catch (error) {
    return NextResponse.json(
      {
        ...getFallbackMuleGraph(),
        status: 'fallback',
        message: error instanceof Error ? error.message : 'Falling back to bundled mule graph data',
      },
      { status: 200 },
    )
  }
}