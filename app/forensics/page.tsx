'use client'

import { useState } from 'react'
import { ForensicsFilterBar } from '@/components/ForensicsFilterBar'
import { GoldenHourTimeline } from '@/components/GoldenHourTimeline'
import { TransactionVelocityPanel } from '@/components/TransactionVelocityPanel'
import { BurstPatternDetection } from '@/components/BurstPatternDetection'
import { GeographicMismatchHeatmap } from '@/components/GeographicMismatchHeatmap'
import { TransactionDetailDrawer } from '@/components/TransactionDetailDrawer'


export default function ForensicsPage() {
  const [selectedTransaction, setSelectedTransaction] = useState<any>(null)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)

  const handleSelectTransaction = (txn: any) => {
    setSelectedTransaction({
      utr: txn.utr,
      from: txn.from,
      to: txn.to,
      amount: txn.amount,
      timestamp: '2026-05-20 14:20:34',
      muleScore: 0.92,
      geoMismatch: true,
      status: txn.status,
    })
    setIsDrawerOpen(true)
  }

  return (
    <div className="space-y-4">
      <ForensicsFilterBar
        onFilterChange={(filters) => {
          // Handle filter changes
          console.log('Filters changed:', filters)
        }}
      />

      <GoldenHourTimeline />

      <div className="grid gap-4 lg:grid-cols-2">
        <TransactionVelocityPanel onSelectTransaction={handleSelectTransaction} />
        <BurstPatternDetection />
      </div>

      <GeographicMismatchHeatmap />

      <TransactionDetailDrawer
        transaction={selectedTransaction}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
      />
    </div>
  )
}
