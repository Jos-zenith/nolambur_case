import { KPIRibbon } from '@/components/KPIRibbon'
import { MuleGraph } from '@/components/MuleGraph'
import { RightSidebar } from '@/components/RightSidebar'
import RealTimeMonitoring from '@/components/realtime-monitoring'
import { GraphLegend } from '@/components/GraphLegend'

export const metadata = {
  title: 'Command Center | Nolambur Fraud Detection',
  description: 'Live fraud detection dashboard with T-GNN analysis and account freezing capabilities.',
}

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      <div className="border-b border-border/60 bg-background/40 p-4 md:p-4">
        <KPIRibbon />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr] xl:grid-cols-[1.65fr_0.85fr] 2xl:grid-cols-[2fr_1fr]">
        <div className="relative flex min-h-[42rem] flex-col rounded-2xl border border-border/60 bg-card/50 p-4 backdrop-blur-sm">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">Mule Cluster Graph View</p>
              <h3 className="mt-1 text-lg font-semibold text-foreground">Live Neo4j topology</h3>
            </div>
          </div>
          <div className="flex-1 min-h-0">
            <MuleGraph />
          </div>
          <GraphLegend />
        </div>

        <div className="min-h-[42rem]">
          <RightSidebar />
        </div>
      </div>

      <div className="border-t border-border/60 bg-background/40 p-4 md:p-4">
        <RealTimeMonitoring />
      </div>
    </div>
  )
}
