'use client'

import { useState } from 'react'
import { ArrowUpDown, ChevronDown } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface Case {
  id: string
  victimName: string
  totalAmount: number
  muleCount: number
  status: 'Active' | 'Frozen' | 'Recovered' | 'Closed'
  assignedOfficer: string
  lastUpdated: string
}

interface CaseListTableProps {
  onSelectCase: (caseItem: Case) => void
  onSelectMultiple?: (caseIds: string[]) => void
}

const mockCases: Case[] = [
  {
    id: 'CASE-2026-001',
    victimName: 'Rajesh K***',
    totalAmount: 2500000,
    muleCount: 12,
    status: 'Recovered',
    assignedOfficer: 'Inspector Sharma',
    lastUpdated: '2026-05-20 14:45',
  },
  {
    id: 'CASE-2026-002',
    victimName: 'Priya M***',
    totalAmount: 1800000,
    muleCount: 8,
    status: 'Frozen',
    assignedOfficer: 'Officer Patel',
    lastUpdated: '2026-05-20 12:30',
  },
  {
    id: 'CASE-2026-003',
    victimName: 'Anil D***',
    totalAmount: 3200000,
    muleCount: 15,
    status: 'Active',
    assignedOfficer: 'Inspector Gupta',
    lastUpdated: '2026-05-20 14:22',
  },
  {
    id: 'CASE-2026-004',
    victimName: 'Sunita S***',
    totalAmount: 950000,
    muleCount: 5,
    status: 'Active',
    assignedOfficer: 'Officer Verma',
    lastUpdated: '2026-05-20 11:15',
  },
  {
    id: 'CASE-2026-005',
    victimName: 'Vikram R***',
    totalAmount: 4100000,
    muleCount: 18,
    status: 'Frozen',
    assignedOfficer: 'Inspector Sharma',
    lastUpdated: '2026-05-20 09:50',
  },
]

export function CaseListTable({ onSelectCase, onSelectMultiple }: CaseListTableProps) {
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [sortColumn, setSortColumn] = useState<keyof Case>('lastUpdated')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  const handleSort = (column: keyof Case) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(column)
      setSortDirection('desc')
    }
  }

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      const allIds = mockCases.map((c) => c.id)
      setSelectedCases(allIds)
      onSelectMultiple?.(allIds)
    } else {
      setSelectedCases([])
      onSelectMultiple?.([])
    }
  }

  const handleSelectCase = (caseId: string, checked: boolean) => {
    let newSelected: string[]
    if (checked) {
      newSelected = [...selectedCases, caseId]
    } else {
      newSelected = selectedCases.filter((id) => id !== caseId)
    }
    setSelectedCases(newSelected)
    onSelectMultiple?.(newSelected)
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Active':
        return 'bg-red-500/20 text-red-200'
      case 'Frozen':
        return 'bg-yellow-500/20 text-yellow-200'
      case 'Recovered':
        return 'bg-green-500/20 text-green-200'
      case 'Closed':
        return 'bg-blue-500/20 text-blue-200'
      default:
        return 'bg-gray-500/20 text-gray-200'
    }
  }

  const sortedCases = [...mockCases].sort((a, b) => {
    const aVal = a[sortColumn]
    const bVal = b[sortColumn]

    let comparison = 0
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      comparison = aVal - bVal
    } else if (typeof aVal === 'string' && typeof bVal === 'string') {
      comparison = aVal.localeCompare(bVal)
    }

    return sortDirection === 'asc' ? comparison : -comparison
  })

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle>Active Cases</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border/40 hover:bg-transparent">
                <TableHead className="w-12">
                  <Checkbox
                    checked={selectedCases.length === mockCases.length}
                    onCheckedChange={handleSelectAll}
                  />
                </TableHead>
                {[
                  { key: 'id', label: 'Case ID' },
                  { key: 'victimName', label: 'Victim' },
                  { key: 'totalAmount', label: 'Amount' },
                  { key: 'muleCount', label: 'Mules' },
                  { key: 'status', label: 'Status' },
                  { key: 'assignedOfficer', label: 'Assigned' },
                  { key: 'lastUpdated', label: 'Last Updated' },
                ].map((col) => (
                  <TableHead key={col.key} className="cursor-pointer">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleSort(col.key as keyof Case)}
                      className="h-6 gap-1 px-1 text-xs"
                    >
                      {col.label}
                      {sortColumn === col.key && (
                        <ArrowUpDown className={`h-3 w-3 ${sortDirection === 'desc' ? 'rotate-180' : ''}`} />
                      )}
                    </Button>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedCases.map((caseItem) => (
                <TableRow
                  key={caseItem.id}
                  className="border-border/40 cursor-pointer hover:bg-secondary/10"
                  onClick={() => onSelectCase(caseItem)}
                >
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedCases.includes(caseItem.id)}
                      onCheckedChange={(checked) => handleSelectCase(caseItem.id, checked as boolean)}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-primary">{caseItem.id}</TableCell>
                  <TableCell className="text-sm">{caseItem.victimName}</TableCell>
                  <TableCell className="text-sm font-semibold">₹{(caseItem.totalAmount / 100000).toFixed(1)}L</TableCell>
                  <TableCell className="text-sm">{caseItem.muleCount}</TableCell>
                  <TableCell>
                    <Badge className={`text-xs ${getStatusColor(caseItem.status)}`}>{caseItem.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">{caseItem.assignedOfficer}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{caseItem.lastUpdated}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
