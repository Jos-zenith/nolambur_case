'use client'

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CaseListTable } from '@/components/CaseListTable'
import { CaseTimelinePanel } from '@/components/CaseTimelinePanel'
import { EvidenceLockerPanel } from '@/components/EvidenceLockerPanel'
import { BiometricReplayPanel } from '@/components/BiometricReplayPanel'
import { BulkActionsToolbar } from '@/components/BulkActionsToolbar'
import { CaseStatusPipeline } from '@/components/CaseStatusPipeline'

export default function CasesPage() {
  const [selectedCase, setSelectedCase] = useState<any>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [selectedCases, setSelectedCases] = useState<string[]>([])

  const handleSelectCase = (caseItem: any) => {
    setSelectedCase(caseItem)
    setIsDetailOpen(true)
  }

  const handleSelectMultiple = (caseIds: string[]) => {
    setSelectedCases(caseIds)
  }

  return (
    <div className="space-y-4">
      <Tabs defaultValue="list" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="list">Case List</TabsTrigger>
          <TabsTrigger value="pipeline">Pipeline View</TabsTrigger>
        </TabsList>

        <TabsContent value="list" className="space-y-4">
          <CaseListTable onSelectCase={handleSelectCase} onSelectMultiple={handleSelectMultiple} />
        </TabsContent>

        <TabsContent value="pipeline" className="space-y-4">
          <CaseStatusPipeline />
        </TabsContent>
      </Tabs>

      {/* Detail Panel */}
      {selectedCase && isDetailOpen && (
        <div className="space-y-6 fixed right-0 top-0 h-screen w-full max-w-3xl transform overflow-y-auto border-l border-border/60 bg-background/95 backdrop-blur-md z-50">
          <div className="sticky top-0 border-b border-border/60 bg-background/80 backdrop-blur-sm flex items-center justify-between p-6">
            <div>
              <p className="text-xs text-muted-foreground">Case ID</p>
              <h2 className="mt-1 font-mono text-lg font-semibold text-primary">{selectedCase.id}</h2>
            </div>
            <button
              onClick={() => setIsDetailOpen(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              ✕
            </button>
          </div>

          <div className="space-y-6 px-6 pb-6">
            {/* Tabs within detail */}
            <Tabs defaultValue="timeline" className="w-full">
              <TabsList className="grid w-full max-w-2xl grid-cols-3">
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
      )}

      <BulkActionsToolbar
        selectedCount={selectedCases.length}
        onFreezeAll={() => alert(`Freezing ${selectedCases.length} cases...`)}
        onExportReport={() => alert(`Exporting ${selectedCases.length} reports...`)}
        onFileWith1930={() => alert(`Filing ${selectedCases.length} cases with 1930...`)}
        onClearSelection={() => {
          setSelectedCases([])
          handleSelectMultiple([])
        }}
      />
    </div>
  )
}
