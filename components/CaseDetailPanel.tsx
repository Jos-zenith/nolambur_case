'use client'

import { useState } from 'react'
import { Eye, EyeOff, Shield, AlertCircle, Clock, DollarSign } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface CaseDetailPanelProps {
  caseId: string
  isOpen: boolean
  onClose: () => void
}

export function CaseDetailPanel({ caseId, isOpen, onClose }: CaseDetailPanelProps) {
  const [isVictimUnmasked, setIsVictimUnmasked] = useState(false)

  // Mock case data
  const caseData = {
    id: 'CASE-2026-001',
    victimPhone: isVictimUnmasked ? '9876543210' : '9876****10',
    victimName: isVictimUnmasked ? 'Rajesh Kumar' : 'Rajesh K***',
    victimBank: 'HDFC Bank',
    victimAccount: isVictimUnmasked ? '1234567890123' : '1234****0123',
    victimAge: '45',
    victimOccupation: 'Business Owner',
    totalAmount: 2500000,
    muleCount: 12,
    status: 'Recovered',
    detectionTime: '2026-05-20 14:20:34',
    freezeTime: '2026-05-20 14:20:38',
    recoveryTime: '2026-05-20 14:21:30',
    recoveredAmount: 2500000,
    muleChain: [
      { level: 'Victim', name: 'Rajesh Kumar', bank: 'HDFC', amount: 2500000, status: 'Transferred' },
      { level: 'L1 Mule', name: '3-12 accounts', bank: 'Multiple', amount: 2500000, status: 'Frozen' },
      { level: 'L2 Aggregator', name: '1-3 accounts', bank: 'Multiple', amount: 2500000, status: 'Frozen' },
      { level: 'Beneficiary', name: 'Unknown', bank: 'Out-of-state', amount: 0, status: 'Recovered' },
    ],
  }

  if (!isOpen) return null

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="fixed right-0 top-0 z-50 h-screen w-full max-w-2xl transform overflow-y-auto border-l border-border/60 bg-background/95 backdrop-blur-md">
        <div className="sticky top-0 border-b border-border/60 bg-background/80 backdrop-blur-sm">
          <div className="flex items-center justify-between p-6">
            <div>
              <p className="text-xs text-muted-foreground">Case ID</p>
              <h2 className="mt-1 font-mono text-lg font-semibold text-primary">{caseData.id}</h2>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              ✕
            </Button>
          </div>
        </div>

        <div className="space-y-6 p-6">
          {/* Victim Information */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-foreground">Victim Information</h3>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsVictimUnmasked(!isVictimUnmasked)}
                className="gap-2 text-xs"
              >
                {isVictimUnmasked ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                {isVictimUnmasked ? 'Hide' : 'Unmask'}
              </Button>
            </div>

            <div className="space-y-3 rounded-lg border border-border/40 bg-secondary/10 p-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-muted-foreground">Name</p>
                  <p className="mt-1 font-semibold text-foreground">{caseData.victimName}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Phone</p>
                  <p className="mt-1 font-mono text-sm">{caseData.victimPhone}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Bank Account</p>
                  <p className="mt-1 font-mono text-sm">{caseData.victimAccount}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Bank</p>
                  <p className="mt-1 text-sm">{caseData.victimBank}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Age</p>
                  <p className="mt-1 text-sm">{caseData.victimAge}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Occupation</p>
                  <p className="mt-1 text-sm">{caseData.victimOccupation}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Mule Chain Visualization */}
          <div className="space-y-3">
            <h3 className="text-lg font-semibold text-foreground">Mule Chain</h3>
            <div className="space-y-2">
              {caseData.muleChain.map((node, idx) => (
                <div key={idx} className="flex items-center gap-3">
                  <div className="flex-shrink-0">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-full ${
                      node.level === 'Victim' ? 'bg-blue-500/20' :
                      node.level === 'Beneficiary' ? 'bg-purple-500/20' :
                      'bg-red-500/20'
                    }`}>
                      <span className="text-xs font-semibold">{idx + 1}</span>
                    </div>
                  </div>
                  <div className="flex-1 rounded border border-border/40 bg-card/40 p-3">
                    <p className="text-xs font-semibold text-muted-foreground">{node.level}</p>
                    <p className="mt-1 text-sm font-semibold text-foreground">{node.name}</p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-xs text-muted-foreground">{node.bank}</span>
                      <Badge className={`text-xs ${
                        node.status === 'Frozen' ? 'bg-green-500/20 text-green-200' :
                        node.status === 'Transferred' ? 'bg-yellow-500/20 text-yellow-200' :
                        'bg-blue-500/20 text-blue-200'
                      }`}>
                        {node.status}
                      </Badge>
                    </div>
                  </div>
                  {idx < caseData.muleChain.length - 1 && (
                    <div className="text-2xl text-primary">→</div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Case Metrics */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-border/40 bg-secondary/10 p-3">
              <div className="flex items-center gap-2 mb-2">
                <DollarSign className="h-4 w-4 text-primary" />
                <p className="text-xs text-muted-foreground">Total Amount</p>
              </div>
              <p className="text-2xl font-bold text-foreground">₹{(caseData.totalAmount / 100000).toFixed(1)}L</p>
            </div>
            <div className="rounded-lg border border-border/40 bg-secondary/10 p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="h-4 w-4 text-primary" />
                <p className="text-xs text-muted-foreground">Mule Accounts</p>
              </div>
              <p className="text-2xl font-bold text-foreground">{caseData.muleCount}</p>
            </div>
          </div>

          {/* Timeline */}
          <div className="space-y-3">
            <h3 className="text-lg font-semibold text-foreground">Key Milestones</h3>
            <div className="space-y-2">
              {[
                { label: 'Detection', time: caseData.detectionTime, icon: AlertCircle },
                { label: 'Freeze Order', time: caseData.freezeTime, icon: Shield },
                { label: 'Recovery', time: caseData.recoveryTime, icon: DollarSign },
              ].map((item, idx) => {
                const Icon = item.icon
                return (
                  <div key={idx} className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-1">
                      <Icon className="h-4 w-4 text-primary" />
                    </div>
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-muted-foreground">{item.label}</p>
                      <p className="mt-1 text-sm text-foreground">{item.time}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
