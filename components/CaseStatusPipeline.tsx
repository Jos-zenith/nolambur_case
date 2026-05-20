'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface CaseCard {
  id: string
  caseId: string
  victimName: string
  amount: number
}

interface PipelineColumn {
  status: string
  cases: CaseCard[]
  color: string
}

export function CaseStatusPipeline() {
  const pipeline: PipelineColumn[] = [
    {
      status: 'Detection',
      color: 'bg-blue-500/10 border-blue-500/40',
      cases: [
        { id: '1', caseId: 'CASE-2026-008', victimName: 'Rajesh K***', amount: 1200000 },
        { id: '2', caseId: 'CASE-2026-009', victimName: 'Priya M***', amount: 800000 },
      ],
    },
    {
      status: 'Verification',
      color: 'bg-purple-500/10 border-purple-500/40',
      cases: [
        { id: '3', caseId: 'CASE-2026-006', victimName: 'Anil D***', amount: 1500000 },
        { id: '4', caseId: 'CASE-2026-007', victimName: 'Sunita S***', amount: 950000 },
      ],
    },
    {
      status: 'Freeze',
      color: 'bg-orange-500/10 border-orange-500/40',
      cases: [
        { id: '5', caseId: 'CASE-2026-003', victimName: 'Anil D***', amount: 3200000 },
        { id: '6', caseId: 'CASE-2026-004', victimName: 'Sunita S***', amount: 950000 },
        { id: '7', caseId: 'CASE-2026-005', victimName: 'Vikram R***', amount: 4100000 },
      ],
    },
    {
      status: 'Recovery',
      color: 'bg-yellow-500/10 border-yellow-500/40',
      cases: [
        { id: '8', caseId: 'CASE-2026-002', victimName: 'Priya M***', amount: 1800000 },
      ],
    },
    {
      status: 'Closed',
      color: 'bg-green-500/10 border-green-500/40',
      cases: [
        { id: '9', caseId: 'CASE-2026-001', victimName: 'Rajesh K***', amount: 2500000 },
      ],
    },
  ]

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case 'Detection':
        return 'bg-blue-500/20 text-blue-200'
      case 'Verification':
        return 'bg-purple-500/20 text-purple-200'
      case 'Freeze':
        return 'bg-orange-500/20 text-orange-200'
      case 'Recovery':
        return 'bg-yellow-500/20 text-yellow-200'
      case 'Closed':
        return 'bg-green-500/20 text-green-200'
      default:
        return 'bg-gray-500/20 text-gray-200'
    }
  }

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle>Case Status Pipeline</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(5, minmax(250px, 1fr))' }}>
            {pipeline.map((column) => (
              <div key={column.status} className={`rounded-lg border-2 ${column.color} p-4`}>
                {/* Column header */}
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground">{column.status}</h3>
                  <Badge variant="secondary" className="text-xs">
                    {column.cases.length}
                  </Badge>
                </div>

                {/* Cases */}
                <div className="space-y-2">
                  {column.cases.length === 0 ? (
                    <div className="flex h-32 items-center justify-center rounded border border-dashed border-border/40">
                      <p className="text-xs text-muted-foreground">No cases</p>
                    </div>
                  ) : (
                    column.cases.map((caseItem) => (
                      <div
                        key={caseItem.id}
                        className="cursor-pointer rounded-lg border border-border/40 bg-card/60 p-3 hover:bg-card transition"
                      >
                        <p className="text-xs font-mono text-primary">{caseItem.caseId}</p>
                        <p className="mt-1 text-xs text-foreground">{caseItem.victimName}</p>
                        <div className="mt-2 flex items-center justify-between">
                          <span className="text-xs font-semibold text-muted-foreground">
                            ₹{(caseItem.amount / 100000).toFixed(1)}L
                          </span>
                          <Badge
                            className={`text-xs ${getStatusBadgeColor(column.status)}`}
                          >
                            {column.status}
                          </Badge>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
