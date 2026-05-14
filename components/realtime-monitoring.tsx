'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import { TrendingUp, TrendingDown, Zap, Clock } from 'lucide-react'

const metricsTrend = [
  { time: '00:00', detections: 12, frozen: 2, recovered: 450000 },
  { time: '04:00', detections: 18, frozen: 4, recovered: 1200000 },
  { time: '08:00', detections: 25, frozen: 6, recovered: 2100000 },
  { time: '12:00', detections: 32, frozen: 8, recovered: 3450000 },
  { time: '16:00', detections: 28, frozen: 7, recovered: 2850000 },
  { time: '20:00', detections: 35, frozen: 9, recovered: 4200000 },
  { time: '24:00', detections: 42, frozen: 12, recovered: 5100000 },
]

const recoveryBreakdown = [
  { name: 'Instant Freeze (ZKP)', value: 65, fill: '#22c55e' },
  { name: 'In-Transit Recovery', value: 25, fill: '#eab308' },
  { name: 'Beneficiary Chase', value: 10, fill: '#f97316' },
]

const topAlerts = [
  { id: 'ALERT-001', cluster: 'Mannady-Nolambur', risk: 'Critical', txns: 12, amount: '₹7.2L', eta: '2 mins', status: 'FROZEN' },
  { id: 'ALERT-002', cluster: 'Delhi-UP Corridor', risk: 'High', txns: 8, amount: '₹4.1L', eta: '8 mins', status: 'FREEZING' },
  { id: 'ALERT-003', cluster: 'Bangalore-Chennai', risk: 'High', txns: 6, amount: '₹2.8L', eta: '15 mins', status: 'MONITORING' },
  { id: 'ALERT-004', cluster: 'Mumbai-Pune Circuit', risk: 'Medium', txns: 5, amount: '₹1.9L', eta: '22 mins', status: 'PENDING' },
  { id: 'ALERT-005', cluster: 'Kolkata-Assam Route', risk: 'Medium', txns: 3, amount: '₹0.8L', eta: '35 mins', status: 'ANALYZING' },
]

const systemMetrics = [
  { label: 'Avg Detection Latency', value: '340ms', change: -12, unit: 'ms' },
  { label: 'ZKP Proof Generation', value: '1.2s', change: -8, unit: 's' },
  { label: 'Cross-State Freeze', value: '2.8s', change: -15, unit: 's' },
  { label: 'API Response Time', value: '180ms', change: -5, unit: 'ms' },
]

export default function RealTimeMonitoring() {
  return (
    <div className="space-y-4 w-full">
      {/* Key Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {systemMetrics.map((metric, idx) => (
          <Card key={idx} className="bg-card/50 border-border">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">{metric.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-baseline justify-between">
                <span className="text-2xl font-bold text-primary">{metric.value}</span>
                <span className={`flex items-center gap-1 text-xs ${metric.change < 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {metric.change < 0 ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                  {Math.abs(metric.change)}%
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-2">vs 1 hour ago</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Trends and Recovery */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="bg-card/50 border-border lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">24-Hour Detection & Recovery Trend</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={metricsTrend}>
                <defs>
                  <linearGradient id="detectGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f97316" stopOpacity={0.8}/>
                    <stop offset="95%" stopColor="#f97316" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="frozenGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.8}/>
                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="time" tick={{ fill: '#999', fontSize: 11 }} />
                <YAxis tick={{ fill: '#999', fontSize: 11 }} />
                <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
                <Area type="monotone" dataKey="detections" stroke="#f97316" fill="url(#detectGradient)" name="Detections" />
                <Area type="monotone" dataKey="frozen" stroke="#22c55e" fill="url(#frozenGradient)" name="Frozen Accounts" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-card/50 border-border">
          <CardHeader>
            <CardTitle className="text-sm">Recovery Method Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center justify-center h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={recoveryBreakdown}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name} ${value}%`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {recoveryBreakdown.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Top Active Alerts */}
      <Card className="bg-card/50 border-border">
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            Top 5 Active Mule Clusters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {topAlerts.map((alert, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 bg-secondary/20 rounded border border-border/50 hover:bg-secondary/30 transition-colors">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="font-mono text-xs text-primary">{alert.id}</span>
                    <Badge className={
                      alert.risk === 'Critical' ? 'bg-destructive/80 text-destructive-foreground' :
                      alert.risk === 'High' ? 'bg-primary/60 text-primary-foreground' :
                      'bg-muted text-muted-foreground'
                    }>
                      {alert.risk}
                    </Badge>
                    <Badge variant="outline" className="bg-secondary/40">{alert.cluster}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{alert.txns} transactions • {alert.amount} • ETA: {alert.eta}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className="text-xs font-mono text-accent mb-1">{alert.amount}</p>
                    <Badge className={
                      alert.status === 'FROZEN' ? 'bg-green-600/80 text-green-100' :
                      alert.status === 'FREEZING' ? 'bg-yellow-600/80 text-yellow-100' :
                      alert.status === 'MONITORING' ? 'bg-blue-600/80 text-blue-100' :
                      'bg-gray-600/80 text-gray-100'
                    }>
                      {alert.status}
                    </Badge>
                  </div>
                  <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center">
                    <Clock className="w-4 h-4 text-primary" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Performance Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="bg-card/50 border-border">
          <CardHeader>
            <CardTitle className="text-xs text-muted-foreground">Golden Hour Recovery Rate</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-accent">73.2%</div>
            <p className="text-xs text-muted-foreground mt-2">₹82.4 Cr recovered in last 7 days</p>
            <div className="mt-4 w-full bg-secondary/30 rounded h-2">
              <div className="w-[73.2%] h-2 rounded bg-accent transition-all" />
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card/50 border-border">
          <CardHeader>
            <CardTitle className="text-xs text-muted-foreground">Avg Case Resolution Time</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-primary">47 mins</div>
            <p className="text-xs text-muted-foreground mt-2">From alert to final seizure</p>
            <p className="text-xs text-green-400 mt-2">↓ 18% faster than last month</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 border-border">
          <CardHeader>
            <CardTitle className="text-xs text-muted-foreground">Annual Loss Prevention</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-green-400">₹22.5 Cr</div>
            <p className="text-xs text-muted-foreground mt-2">9% of total UPI fraud losses</p>
            <p className="text-xs text-green-400 mt-2">↑ 31% higher than baseline</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
