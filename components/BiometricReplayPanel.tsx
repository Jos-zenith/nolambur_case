'use client'

import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { AlertCircle } from 'lucide-react'
import { DataFreshness } from '@/components/data-freshness'

const stressData = [
  { timestamp: '14:22:00', stress: 20, confidence: 45 },
  { timestamp: '14:23:00', stress: 25, confidence: 52 },
  { timestamp: '14:24:00', stress: 35, confidence: 68 },
  { timestamp: '14:25:00', stress: 65, confidence: 91 },
  { timestamp: '14:26:00', stress: 78, confidence: 97 },
  { timestamp: '14:27:00', stress: 82, confidence: 99 },
  { timestamp: '14:28:00', stress: 45, confidence: 78 },
  { timestamp: '14:29:00', stress: 28, confidence: 61 },
  { timestamp: '14:30:00', stress: 15, confidence: 38 },
]

const biometricMarkers = [
  { name: 'Micro-Expression Stress', value: 97, risk: 'Critical' },
  { name: 'Pupil Dilation (Fear)', value: 89, risk: 'High' },
  { name: 'Video Call Detected', value: 85, risk: 'High' },
  { name: 'Instruction-Following Pattern', value: 78, risk: 'High' },
  { name: 'Facial Asymmetry (Pressure)', value: 71, risk: 'Medium' },
]

export function BiometricReplayPanel() {
  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="text-lg">Biometric Session Replay</CardTitle>
        <DataFreshness className="text-xs text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Stress Timeline */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Real-Time Stress Index During Transaction</p>
            <div className="h-48 w-full rounded-lg border border-border/40 bg-secondary/10 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stressData}>
                  <defs>
                    <linearGradient id="stressGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0.1} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="timestamp" tick={{ fill: '#999', fontSize: 9 }} />
                  <YAxis tick={{ fill: '#999', fontSize: 9 }} domain={[0, 100]} />
                  <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
                  <Area
                    type="monotone"
                    dataKey="stress"
                    stroke="#ef4444"
                    fill="url(#stressGradient)"
                    strokeWidth={2}
                    name="Stress"
                  />
                  <Line
                    type="monotone"
                    dataKey="confidence"
                    stroke="#f97316"
                    strokeWidth={2}
                    name="Confidence"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Biometric Markers */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Detected Stress Indicators</p>
            <div className="space-y-2">
              {biometricMarkers.map((marker, idx) => (
                <div key={idx} className="flex items-center justify-between rounded-lg border border-border/40 bg-secondary/10 p-3">
                  <div className="flex items-start gap-2 flex-1">
                    <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-semibold text-foreground">{marker.name}</p>
                      <p className="mt-1 text-xs text-muted-foreground">Confidence: {marker.value}%</p>
                    </div>
                  </div>
                  <Badge
                    className={`flex-shrink-0 text-xs ${
                      marker.risk === 'Critical'
                        ? 'bg-red-500/20 text-red-200 animate-alert-pulse'
                        : marker.risk === 'High'
                          ? 'bg-orange-500/20 text-orange-200'
                          : marker.risk === 'Medium'
                            ? 'bg-yellow-500/20 text-yellow-200'
                            : 'bg-blue-500/20 text-blue-100'
                    }`}
                  >
                    {marker.risk}
                  </Badge>
                </div>
              ))}
            </div>
          </div>

          {/* Summary */}
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0" />
              <div>
                <p className="text-sm font-semibold text-red-400">Strong Duress Indicators Detected</p>
                <p className="mt-1 text-xs text-red-300/80">
                  This victim exhibited classic stress patterns consistent with coercion: peak stress at 82%, sustained high confidence (97%), and reaction patterns matching known scam scripts.
                </p>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
