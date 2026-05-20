'use client'

import { AlertCircle, Lock, DollarSign, FileText, CheckCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export function CaseTimelinePanel() {
  const timeline = [
    {
      id: 1,
      label: 'Fraud Detected',
      description: 'T-GNN model identified suspicious transaction pattern',
      time: '2026-05-20 14:20:34',
      icon: AlertCircle,
      status: 'completed',
      details: 'Mule velocity spike (0.92 txns/min) detected across 12 accounts',
    },
    {
      id: 2,
      label: 'ZKP Freeze Order',
      description: 'Cross-state freeze initiated via Zero-Knowledge Proof',
      time: '2026-05-20 14:20:36',
      icon: Lock,
      status: 'completed',
      details: '₹25.0L frozen in 53 seconds across 12 mule accounts',
    },
    {
      id: 3,
      label: 'Bank Execution',
      description: 'NPCI confirmed freeze execution across states',
      time: '2026-05-20 14:20:38',
      icon: CheckCircle,
      status: 'completed',
      details: '28 state-level banking APIs synchronized, 100% confirmation',
    },
    {
      id: 4,
      label: 'Amount Recovered',
      description: 'Victim funds successfully recovered to original account',
      time: '2026-05-20 14:21:30',
      icon: DollarSign,
      status: 'completed',
      details: '₹25.0L returned to HDFC account ending in 0123',
    },
    {
      id: 5,
      label: 'CFCFRMS Filing',
      description: 'Case details auto-filed with Crime and Fraud Case Filing',
      time: '2026-05-20 14:35:00',
      icon: FileText,
      status: 'completed',
      details: 'FIR Reference: OP-2026-45782, Status: Verified',
    },
  ]

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="text-lg">Action Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {timeline.map((event, idx) => {
            const Icon = event.icon
            return (
              <div key={event.id} className="relative">
                {/* Connecting line */}
                {idx < timeline.length - 1 && (
                  <div className="absolute left-6 top-12 h-6 w-0.5 bg-gradient-to-b from-primary to-transparent" />
                )}

                {/* Event */}
                <div className="flex gap-4">
                  {/* Icon circle */}
                  <div className="relative flex-shrink-0">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-primary bg-primary/10">
                      <Icon className="h-5 w-5 text-primary" />
                    </div>
                  </div>

                  {/* Content */}
                  <div className="flex-1 rounded-lg border border-border/40 bg-secondary/10 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-foreground">{event.label}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{event.description}</p>
                        <p className="mt-2 text-xs text-secondary-foreground">{event.details}</p>
                      </div>
                      <Badge className="flex-shrink-0 bg-green-500/20 text-green-200 text-xs">
                        Complete
                      </Badge>
                    </div>
                    <p className="mt-3 text-xs font-mono text-muted-foreground">{event.time}</p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
