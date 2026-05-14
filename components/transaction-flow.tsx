'use client'

import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts'

const velocityData = [
  { time: '14:20', velocity: 0.1, txns: 2, avgAmount: 500000 },
  { time: '14:25', velocity: 0.28, txns: 3, avgAmount: 450000 },
  { time: '14:30', velocity: 0.75, txns: 2, avgAmount: 420000 },
  { time: '14:35', velocity: 0.88, txns: 2, avgAmount: 825000 },
  { time: '14:40', velocity: 0.92, txns: 1, avgAmount: 840000 },
  { time: '14:45', velocity: 0.15, txns: 0, avgAmount: 0 },
]

const geoMismatchData = [
  { state: 'Tamil Nadu', received: 50, sent: 10, mismatch: 40 },
  { state: 'Rajasthan', received: 120, sent: 85, mismatch: 35 },
  { state: 'Haryana', received: 95, sent: 70, mismatch: 25 },
  { state: 'Punjab', received: 40, sent: 38, mismatch: 2 },
  { state: 'Delhi', received: 30, sent: 28, mismatch: 2 },
]

const burstPattern = [
  { burst: 'B1', amount: 500, risk: 45, detected: 'Yes' },
  { burst: 'B2', amount: 500, risk: 48, detected: 'Yes' },
  { burst: 'B3', amount: 500, risk: 52, detected: 'Yes' },
  { burst: 'B4', amount: 550, risk: 85, detected: 'Yes' },
  { burst: 'B5', amount: 520, risk: 92, detected: 'Yes' },
  { burst: 'B6', amount: 500, risk: 89, detected: 'Yes' },
]

export default function TransactionFlow() {
  return (
    <div className="w-full h-full space-y-4 text-xs">
      {/* Top: Velocity Pattern */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-1/2">
        <div className="bg-secondary/10 rounded border border-border p-4">
          <h4 className="text-sm font-semibold mb-3 text-primary">Transaction Velocity (Golden Hour)</h4>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={velocityData}>
              <defs>
                <linearGradient id="velocityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="time" tick={{ fill: '#999', fontSize: 11 }} />
              <YAxis tick={{ fill: '#999', fontSize: 11 }} />
              <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
              <Legend wrapperStyle={{ paddingTop: '10px' }} />
              <Line type="monotone" dataKey="velocity" stroke="#ef4444" strokeWidth={2} dot={{ fill: '#ef4444', r: 3 }} name="Mule Velocity" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-secondary/10 rounded border border-border p-4">
          <h4 className="text-sm font-semibold mb-3 text-accent">₹5L Burst Pattern Detection</h4>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={burstPattern}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="burst" tick={{ fill: '#999', fontSize: 11 }} />
              <YAxis tick={{ fill: '#999', fontSize: 11 }} />
              <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
              <Bar dataKey="risk" fill="#f97316" name="Fraud Risk Score" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Bottom: Geographic Mismatch */}
      <div className="bg-secondary/10 rounded border border-border p-4 h-1/3">
        <h4 className="text-sm font-semibold mb-3 text-primary">Geographic-Transactional Mismatch (State-wise)</h4>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={geoMismatchData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis type="number" tick={{ fill: '#999', fontSize: 11 }} />
            <YAxis dataKey="state" type="category" tick={{ fill: '#999', fontSize: 11 }} />
            <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
            <Legend wrapperStyle={{ paddingTop: '10px' }} />
            <Bar dataKey="received" stackId="a" fill="#60a5fa" name="Received" />
            <Bar dataKey="sent" stackId="a" fill="#22c55e" name="Sent" />
            <Bar dataKey="mismatch" stackId="a" fill="#ef4444" name="Mismatch (High Risk)" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
