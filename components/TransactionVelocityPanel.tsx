'use client'

import { useState } from 'react'
import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataFreshness } from '@/components/data-freshness'

const velocityData = [
  { time: '14:20', velocity: 0.1, txns: 2, avgAmount: 500000 },
  { time: '14:25', velocity: 0.28, txns: 3, avgAmount: 450000 },
  { time: '14:30', velocity: 0.75, txns: 2, avgAmount: 420000 },
  { time: '14:35', velocity: 0.88, txns: 2, avgAmount: 825000 },
  { time: '14:40', velocity: 0.92, txns: 1, avgAmount: 840000 },
  { time: '14:45', velocity: 0.15, txns: 0, avgAmount: 0 },
]

const detailedTransactions = {
  '14:20': [
    { utr: 'UPI123001', from: 'victim_9876543@okhdfcbank', to: 'mule_1001@axis', amount: 250000, status: 'FROZEN' },
    { utr: 'UPI123002', from: 'victim_9876543@okhdfcbank', to: 'mule_1002@icici', amount: 250000, status: 'FROZEN' },
  ],
  '14:25': [
    { utr: 'UPI123003', from: 'victim_9876543@okhdfcbank', to: 'mule_1003@rbl', amount: 150000, status: 'FROZEN' },
  ],
  '14:30': [
    { utr: 'UPI123004', from: 'mule_1001@axis', to: 'aggregator_001@icici', amount: 420000, status: 'FROZEN' },
  ],
}

export function TransactionVelocityPanel({ onSelectTransaction }: { onSelectTransaction: (txn: any) => void }) {
  const [selectedTime, setSelectedTime] = useState<string | null>(null)

  const handleTimeClick = (time: string) => {
    setSelectedTime(selectedTime === time ? null : time)
  }

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Transaction Velocity Profile</CardTitle>
          <Badge className="bg-red-500/20 text-red-200 animate-alert-pulse">Critical Spike</Badge>
        </div>
        <DataFreshness className="text-xs text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Main chart */}
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={velocityData}>
                <defs>
                  <linearGradient id="velocityGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="time" tick={{ fill: '#999', fontSize: 11 }} />
                <YAxis tick={{ fill: '#999', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                  formatter={(value: any) => `${(value as number).toFixed(2)} txns/min`}
                />
                <ReferenceLine y={0.7} stroke="#f97316" strokeDasharray="5 5" label="Freeze Threshold" />
                <Area type="monotone" dataKey="velocity" stroke="#ef4444" fill="url(#velocityGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Drill-down section */}
          {selectedTime && detailedTransactions[selectedTime as keyof typeof detailedTransactions] && (
            <div className="space-y-3 rounded-lg border border-border/40 bg-secondary/10 p-4">
              <p className="text-sm font-semibold text-foreground">Transactions at {selectedTime}</p>
              <div className="space-y-2">
                {detailedTransactions[selectedTime as keyof typeof detailedTransactions].map((txn, idx) => (
                  <div
                    key={idx}
                    className="flex cursor-pointer items-center justify-between rounded border border-border/40 bg-card/40 p-2 hover:bg-card/60"
                    onClick={() => onSelectTransaction(txn)}
                  >
                    <div className="flex-1">
                      <p className="text-xs font-mono text-primary">{txn.utr}</p>
                      <p className="text-xs text-muted-foreground">{txn.from} → {txn.to}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-foreground">₹{(txn.amount / 100000).toFixed(1)}L</p>
                      <Badge className="mt-1 bg-green-500/20 text-xs text-green-200">{txn.status}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Time buttons */}
          <div className="flex flex-wrap gap-2">
            {velocityData.map((d) => (
              <Button
                key={d.time}
                size="sm"
                variant={selectedTime === d.time ? 'default' : 'outline'}
                onClick={() => handleTimeClick(d.time)}
                className="text-xs"
              >
                {d.time} ({d.txns} txns)
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
