'use client'

import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ScatterChart, Scatter } from 'recharts'

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
  { name: 'Micro-Expression Stress', value: 97, risk: 'Critical', color: '#ef4444' },
  { name: 'Pupil Dilation (Fear)', value: 89, risk: 'High', color: '#f97316' },
  { name: 'Video Call Detected', value: 85, risk: 'High', color: '#f97316' },
  { name: 'Instruction-Following Pattern', value: 78, risk: 'High', color: '#f97316' },
  { name: 'Facial Asymmetry (Pressure)', value: 71, risk: 'Medium', color: '#eab308' },
  { name: 'Eye Contact Avoidance', value: 65, risk: 'Medium', color: '#eab308' },
]

export default function BiometricAlert() {
  return (
    <div className="w-full h-full space-y-4 text-xs">
      {/* Top: Stress Timeline */}
      <div className="bg-secondary/10 rounded border border-border p-4 h-1/2">
        <h4 className="text-sm font-semibold mb-3 text-primary">Real-Time Stress Index During Transaction</h4>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={stressData}>
            <defs>
              <linearGradient id="stressGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8}/>
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0.1}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="timestamp" tick={{ fill: '#999', fontSize: 10 }} angle={-45} textAnchor="end" height={60} />
            <YAxis tick={{ fill: '#999', fontSize: 11 }} domain={[0, 100]} />
            <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }} />
            <Area type="monotone" dataKey="stress" stroke="#ef4444" fill="url(#stressGradient)" strokeWidth={2} name="Stress Index" />
            <Line type="monotone" dataKey="confidence" stroke="#f97316" strokeWidth={2} name="Detection Confidence" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Bottom: Biometric Markers */}
      <div className="grid grid-cols-2 gap-3 h-1/2">
        {biometricMarkers.map((marker, idx) => (
          <div key={idx} className="bg-secondary/10 rounded border border-border p-3">
            <div className="flex justify-between items-start mb-2">
              <h5 className="text-xs font-semibold text-foreground flex-1">{marker.name}</h5>
              <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                marker.risk === 'Critical' ? 'bg-destructive/20 text-destructive' :
                marker.risk === 'High' ? 'bg-primary/20 text-primary' :
                'bg-yellow-900/20 text-yellow-400'
              }`}>
                {marker.risk}
              </span>
            </div>
            <div className="space-y-2">
              <div className="w-full bg-secondary/30 rounded h-2">
                <div 
                  className="h-2 rounded transition-all"
                  style={{
                    width: `${marker.value}%`,
                    background: marker.color
                  }}
                />
              </div>
              <p className="text-xs text-muted-foreground">Detection: {marker.value}% confidence</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
