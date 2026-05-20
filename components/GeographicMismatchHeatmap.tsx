'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DataFreshness } from '@/components/data-freshness'

const stateData = [
  { state: 'Tamil Nadu', mismatch: 85, intensity: 'critical' },
  { state: 'Rajasthan', mismatch: 72, intensity: 'high' },
  { state: 'Haryana', mismatch: 58, intensity: 'high' },
  { state: 'Karnataka', mismatch: 45, intensity: 'medium' },
  { state: 'Delhi', mismatch: 35, intensity: 'medium' },
  { state: 'Punjab', mismatch: 22, intensity: 'low' },
  { state: 'Maharashtra', mismatch: 68, intensity: 'high' },
  { state: 'Uttar Pradesh', mismatch: 55, intensity: 'medium' },
]

function getStateColor(intensity: string) {
  switch (intensity) {
    case 'critical':
      return '#dc2626' // deep red
    case 'high':
      return '#f97316' // orange
    case 'medium':
      return '#eab308' // yellow
    case 'low':
      return '#3b82f6' // blue
    default:
      return '#6b7280'
  }
}

export function GeographicMismatchHeatmap() {
  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="text-lg">Geographic-Transactional Mismatch Heatmap</CardTitle>
        <DataFreshness className="text-xs text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Simplified India Map */}
          <div className="rounded-lg border border-border/40 bg-secondary/10 p-6">
            <svg viewBox="0 0 400 500" className="w-full" style={{ maxHeight: '300px' }}>
              {/* Simplified India outline */}
              <path
                d="M 150 80 L 200 70 L 220 90 L 240 80 L 250 110 L 260 130 L 280 140 L 290 170 L 300 190 L 310 210 L 305 240 L 315 260 L 320 290 L 310 310 L 290 320 L 270 330 L 240 340 L 200 350 L 160 345 L 140 340 L 120 330 L 100 310 L 90 280 L 85 250 L 80 220 L 75 180 L 70 150 L 75 120 L 85 100 L 110 85 L 130 75 Z"
                fill="rgba(59, 130, 246, 0.1)"
                stroke="#3b82f6"
                strokeWidth="2"
              />

              {/* State regions with color intensity */}
              {/* Tamil Nadu (south) - critical */}
              <circle cx="280" cy="340" r="25" fill="#dc2626" opacity="0.7" />
              <text x="280" y="345" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="bold">
                TN
              </text>

              {/* Rajasthan (northwest) - high */}
              <circle cx="140" cy="160" r="30" fill="#f97316" opacity="0.7" />
              <text x="140" y="165" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="bold">
                RJ
              </text>

              {/* Haryana (north) - high */}
              <circle cx="180" cy="100" r="20" fill="#f97316" opacity="0.7" />
              <text x="180" y="105" textAnchor="middle" fill="#fff" fontSize="10" fontWeight="bold">
                HR
              </text>

              {/* Maharashtra (west) - high */}
              <circle cx="150" cy="240" r="25" fill="#f97316" opacity="0.7" />
              <text x="150" y="245" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="bold">
                MH
              </text>

              {/* Karnataka (south-west) - medium */}
              <circle cx="220" cy="310" r="22" fill="#eab308" opacity="0.7" />
              <text x="220" y="315" textAnchor="middle" fill="#fff" fontSize="10" fontWeight="bold">
                KA
              </text>

              {/* Delhi (north) - medium */}
              <circle cx="175" cy="115" r="15" fill="#eab308" opacity="0.7" />
              <text x="175" y="120" textAnchor="middle" fill="#fff" fontSize="9" fontWeight="bold">
                DL
              </text>

              {/* Punjab (northwest) - low */}
              <circle cx="120" cy="80" r="18" fill="#3b82f6" opacity="0.7" />
              <text x="120" y="85" textAnchor="middle" fill="#fff" fontSize="10" fontWeight="bold">
                PB
              </text>

              {/* Uttar Pradesh (north-central) - medium */}
              <circle cx="220" cy="160" r="25" fill="#eab308" opacity="0.7" />
              <text x="220" y="165" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="bold">
                UP
              </text>
            </svg>
          </div>

          {/* Legend */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Mismatch Intensity Scale</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                { label: 'Critical (≥80%)', color: 'bg-red-600' },
                { label: 'High (60-79%)', color: 'bg-orange-500' },
                { label: 'Medium (40-59%)', color: 'bg-yellow-500' },
                { label: 'Low (<40%)', color: 'bg-blue-500' },
              ].map((item, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <div className={`h-3 w-3 rounded ${item.color}`} />
                  <span className="text-xs text-muted-foreground">{item.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* State rankings */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Top Affected States</p>
            <div className="space-y-1">
              {stateData.sort((a, b) => b.mismatch - a.mismatch).slice(0, 5).map((state, idx) => (
                <div key={idx} className="flex items-center justify-between rounded border border-border/40 bg-secondary/10 px-3 py-2">
                  <span className="text-xs text-muted-foreground">{state.state}</span>
                  <Badge
                    className={`text-xs ${
                      state.intensity === 'critical'
                        ? 'bg-red-500/20 text-red-200 animate-alert-pulse'
                        : state.intensity === 'high'
                          ? 'bg-orange-500/20 text-orange-200'
                          : state.intensity === 'medium'
                            ? 'bg-yellow-500/20 text-yellow-200'
                            : 'bg-blue-500/20 text-blue-100'
                    }`}
                  >
                    {state.mismatch}%
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
