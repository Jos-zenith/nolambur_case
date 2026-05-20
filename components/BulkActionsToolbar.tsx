'use client'

import { Lock, Download, FileText, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

interface BulkActionsToolbarProps {
  selectedCount: number
  onFreezeAll?: () => void
  onExportReport?: () => void
  onFileWith1930?: () => void
  onClearSelection?: () => void
}

export function BulkActionsToolbar({
  selectedCount,
  onFreezeAll,
  onExportReport,
  onFileWith1930,
  onClearSelection,
}: BulkActionsToolbarProps) {
  if (selectedCount === 0) return null

  return (
    <div className="sticky bottom-0 border-t border-border/60 bg-background/80 backdrop-blur-md p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Badge className="bg-primary/20 text-primary">{selectedCount} selected</Badge>
          <Button size="sm" variant="ghost" onClick={onClearSelection} className="text-xs">
            Clear
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={onFreezeAll}
            className="gap-2 text-xs"
            title="Freeze all selected accounts immediately"
          >
            <Lock className="h-4 w-4" />
            Freeze All
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={onExportReport}
            className="gap-2 text-xs"
            title="Export case details and evidence"
          >
            <Download className="h-4 w-4" />
            Export Report
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={onFileWith1930}
            className="gap-2 text-xs"
            title="File with CFCFRMS (Crime and Fraud Case Filing)"
          >
            <FileText className="h-4 w-4" />
            File with 1930
          </Button>

          <div className="h-6 w-px bg-border/40" />

          <Button size="sm" variant="ghost" onClick={onClearSelection} className="text-xs text-red-400 hover:text-red-300">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
