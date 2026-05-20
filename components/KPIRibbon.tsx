'use client'

import { TrendingDown, TrendingUp } from 'lucide-react'
import { AnimatedCounter } from '@/components/animated-counter'
import { DataFreshness } from '@/components/data-freshness'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

function MiniSparkline({ data }: { data: number[] }) {
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1

  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100
      const y = ((max - v) / range) * 100
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg viewBox="0 0 100 40" className="h-8 w-full">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
        className="text-primary/60"
      />
    </svg>
  )
}

export function KPIRibbon() {
  const kpis = [
    {
      label: 'Active Fraud Alerts',
      value: 23,
      decimals: 0,
      prefix: '',
      suffix: '',
      delta: '+4',
      trend: 'up',
      sparkline: [2, 5, 3, 8, 6, 12, 10, 15, 13, 18, 20, 23],
      badge: 'Live',
      badgeColor: 'bg-red-500/20 text-red-200 animate-alert-pulse',
      risk: 'critical',
    },
    {
      label: 'T-GNN Confidence',
      value: 94.2,
      decimals: 1,
      prefix: '',
      suffix: '%',
      delta: '+2.1%',
      trend: 'up',
      sparkline: [85, 87, 89, 91, 90, 92, 93, 94, 94, 94.2, 94.2, 94.2],
      badge: 'Model V2',
      badgeColor: 'bg-orange-500/20 text-orange-200',
      risk: 'high',
    },
    {
      label: 'Frozen Accounts',
      value: 156,
      decimals: 0,
      prefix: '',
      suffix: '',
      delta: '+12',
      trend: 'up',
      sparkline: [120, 125, 128, 132, 135, 138, 140, 145, 148, 150, 153, 156],
      badge: 'Last 24h',
      badgeColor: 'bg-emerald-500/20 text-emerald-200',
      risk: 'frozen',
    },
    {
      label: 'Recovered Amount',
      value: 8.2,
      decimals: 1,
      prefix: '₹',
      suffix: ' Cr',
      delta: '+₹1.1 Cr',
      trend: 'up',
      sparkline: [2.1, 2.5, 3.2, 4.1, 4.8, 5.5, 6.2, 6.9, 7.2, 7.8, 8.0, 8.2],
      badge: 'Golden Hour',
      badgeColor: 'bg-emerald-500/20 text-emerald-200',
      risk: 'frozen',
    },
  ]

  return (
    <div className="space-y-3">
      <DataFreshness />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {kpis.map((kpi, idx) => (
        <Card key={idx} data-risk={kpi.risk} className="border-border/60 bg-card/50 backdrop-blur-sm">
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">{kpi.label}</p>
                <p className="text-2xl font-bold text-foreground">
                  <AnimatedCounter
                    value={kpi.value}
                    decimals={kpi.decimals}
                    prefix={kpi.prefix}
                    suffix={kpi.suffix}
                  />
                </p>
              </div>
              <Badge className={`${kpi.badgeColor} rounded-full text-xs`}>{kpi.badge}</Badge>
            </div>

            {/* Sparkline */}
            <div className="h-6 w-full text-emerald-500">
              <MiniSparkline data={kpi.sparkline} />
            </div>

            {/* Delta */}
            <div className="flex items-center gap-1">
              {kpi.trend === 'up' ? (
                <TrendingUp className="h-3 w-3 text-emerald-500" />
              ) : (
                <TrendingDown className="h-3 w-3 text-red-500" />
              )}
              <span className={`text-xs font-semibold ${kpi.trend === 'up' ? 'text-emerald-500' : 'text-red-500'}`}>
                {kpi.delta} vs 1h ago
              </span>
            </div>
          </CardContent>
        </Card>
      ))}
      </div>
    </div>
  )
}
