import { NextResponse } from 'next/server'

import { getGraphSummary, initializeNeo4jGraph } from '@/lib/graph-db'

export const runtime = 'nodejs'

export async function GET() {
  try {
    const summary = await getGraphSummary()

    return NextResponse.json({
      status: 'ready',
      summary,
    })
  } catch (error) {
    return NextResponse.json(
      {
        status: 'unavailable',
        message: error instanceof Error ? error.message : 'Neo4j graph database is not available',
      },
      { status: 503 },
    )
  }
}

export async function POST() {
  try {
    const initializationResult = await initializeNeo4jGraph()

    return NextResponse.json({
      status: 'initialized',
      ...initializationResult,
    })
  } catch (error) {
    return NextResponse.json(
      {
        status: 'error',
        message: error instanceof Error ? error.message : 'Failed to initialize the Neo4j graph setup',
      },
      { status: 500 },
    )
  }
}
