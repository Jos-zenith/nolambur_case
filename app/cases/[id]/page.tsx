'use client'

import { use } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CaseDetailPanel } from '@/components/CaseDetailPanel'
import { CaseTimelinePanel } from '@/components/CaseTimelinePanel'
import { EvidenceLockerPanel } from '@/components/EvidenceLockerPanel'
import { BiometricReplayPanel } from '@/components/BiometricReplayPanel'
import { Button } from '@/components/ui/button'
import { ChevronLeft } from 'lucide-react'
import Link from 'next/link'

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: caseId } = use(params)

  const mockCase = {
    id: caseId,
    victimName: 'Rajesh Kumar',
    victimPhone: '+91-9876543210',
    victimAccount: 'HDFC 123456789',
    totalAmount: 2500000,
    muleCount: 12,
    status: 'Recovered',
    assignedOfficer: 'Inspector Sharma',
    lastUpdated: '2026-05-20 14:45',
  }

  return (
    <div className="space-y-4">
      <div className="border-b border-border/60 bg-background/80 backdrop-blur-sm">
        <div className="flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <Link href="/cases">
              <Button variant="ghost" size="sm" className="gap-2">
                <ChevronLeft className="h-4 w-4" />
                Back to Cases
              </Button>
            </Link>
            <div>
              <p className="text-xs text-muted-foreground">Case ID</p>
              <h1 className="font-mono text-xl font-semibold text-primary">{mockCase.id}</h1>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <CaseDetailPanel caseId={mockCase.id} isOpen={true} onClose={() => {}} />
        </div>
        <div className="lg:col-span-2">
          <Tabs defaultValue="timeline" className="w-full">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="biometric">Biometric</TabsTrigger>
              <TabsTrigger value="evidence">Evidence</TabsTrigger>
            </TabsList>
            <TabsContent value="timeline" className="space-y-4">
              <CaseTimelinePanel />
            </TabsContent>
            <TabsContent value="biometric" className="space-y-4">
              <BiometricReplayPanel />
            </TabsContent>
            <TabsContent value="evidence" className="space-y-4">
              <EvidenceLockerPanel />
            </TabsContent>
          </Tabs>
        </div>
          </div>
    </div>
  )
}
