'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DataFreshness } from '@/components/data-freshness'

const burstPattern = [
  { burst: 'B1', amount: 500, risk: 45, detected: 'No' },
  { burst: 'B2', amount: 500, risk: 48, detected: 'No' },
  { burst: 'B3', amount: 500, risk: 52, detected: 'No' },
  { burst: 'B4', amount: 550, risk: 85, detected: 'Yes' },
  { burst: 'B5', amount: 520, risk: 92, detected: 'Yes' },
  { burst: 'B6', amount: 500, risk: 89, detected: 'Yes' },
]

export function BurstPatternDetection() {
  const thresholdScore = 70

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">₹5L Burst Pattern Detection</CardTitle>
          <Badge className="bg-orange-500/20 text-orange-200">Threshold: {thresholdScore}</Badge>
        </div>
        <DataFreshness className="text-xs text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={burstPattern}>
                <defs>
                  <linearGradient id="freezeGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.9} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0.4} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="burst" tick={{ fill: '#999', fontSize: 11 }} />
                <YAxis tick={{ fill: '#999', fontSize: 11 }} />
                <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
                {/* Animated threshold line */}
                <ReferenceLine
                  y={thresholdScore}
                  stroke="#f97316"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  label={{
                    value: `Freeze Threshold (${thresholdScore})`,
                    position: 'insideTopRight',
                    offset: -10,
                    fill: '#f97316',
                    fontSize: 11,
                  }}
                  className="animate-pulse"
                />
                <Bar dataKey="risk" fill="url(#freezeGradient)" radius={[4, 4, 0, 0]}>
                  {burstPattern.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.risk >= thresholdScore ? '#ef4444' : '#f97316'}
                      opacity={entry.risk >= thresholdScore ? 0.9 : 0.6}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Stats */}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border/40 bg-secondary/10 p-3">
              <p className="text-xs text-muted-foreground">Total Bursts</p>
              <p className="text-lg font-semibold text-foreground">{burstPattern.length}</p>
            </div>
            <div className="rounded-lg border border-border/40 bg-secondary/10 p-3">
              <p className="text-xs text-muted-foreground">Above Threshold</p>
              <p className="text-lg font-semibold text-red-400">{burstPattern.filter((b) => b.risk >= thresholdScore).length}</p>
            </div>
            <div className="rounded-lg border border-border/40 bg-secondary/10 p-3">
              <p className="text-xs text-muted-foreground">Frozen</p>
              <p className="text-lg font-semibold text-emerald-400">100%</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
