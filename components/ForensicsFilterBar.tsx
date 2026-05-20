'use client'

import { useState } from 'react'
import { Search, Filter } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

interface FilterState {
  dateRange: 'today' | 'week' | 'month'
  amountRange: 'all' | '<5L' | '5L-10L' | '>10L'
  riskLevel: 'all' | 'critical' | 'high' | 'medium'
  state: string
  muleScore: number
}

interface ForensicsFilterBarProps {
  onFilterChange: (filters: FilterState) => void
}

export function ForensicsFilterBar({ onFilterChange }: ForensicsFilterBarProps) {
  const [filters, setFilters] = useState<FilterState>({
    dateRange: 'today',
    amountRange: 'all',
    riskLevel: 'all',
    state: '',
    muleScore: 0,
  })

  const handleFilterChange = (key: keyof FilterState, value: any) => {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
    onFilterChange(newFilters)
  }

  const states = ['Tamil Nadu', 'Rajasthan', 'Haryana', 'Maharashtra', 'Delhi', 'Karnataka', 'Punjab', 'Uttar Pradesh']

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm p-4">
      <div className="space-y-4">
        {/* Search bar */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search UTR, account, transaction ID..."
              className="pl-9 text-sm"
            />
          </div>
          <Button size="sm" variant="outline">
            <Filter className="h-4 w-4" />
          </Button>
        </div>

        {/* Filter chips */}
        <div className="grid gap-3 sm:grid-cols-5">
          {/* Date Range */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground mb-2 block">Date Range</label>
            <div className="space-y-1">
              {(['today', 'week', 'month'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => handleFilterChange('dateRange', option)}
                  className={`text-xs w-full px-2 py-1 rounded border transition ${
                    filters.dateRange === option
                      ? 'border-primary bg-primary/20 text-primary'
                      : 'border-border/40 hover:border-border/60'
                  }`}
                >
                  {option === 'today' ? 'Today' : option === 'week' ? 'This Week' : 'This Month'}
                </button>
              ))}
            </div>
          </div>

          {/* Amount Range */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground mb-2 block">Amount</label>
            <div className="space-y-1">
              {(['all', '<5L', '5L-10L', '>10L'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => handleFilterChange('amountRange', option)}
                  className={`text-xs w-full px-2 py-1 rounded border transition ${
                    filters.amountRange === option
                      ? 'border-primary bg-primary/20 text-primary'
                      : 'border-border/40 hover:border-border/60'
                  }`}
                >
                  {option === 'all' ? 'All' : option}
                </button>
              ))}
            </div>
          </div>

          {/* Risk Level */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground mb-2 block">Risk Level</label>
            <div className="space-y-1">
              {(['all', 'critical', 'high', 'medium'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => handleFilterChange('riskLevel', option)}
                  className={`text-xs w-full px-2 py-1 rounded border transition capitalize ${
                    filters.riskLevel === option
                      ? 'border-primary bg-primary/20 text-primary'
                      : 'border-border/40 hover:border-border/60'
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          {/* State */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground mb-2 block">State</label>
            <select
              value={filters.state}
              onChange={(e) => handleFilterChange('state', e.target.value)}
              className="w-full rounded border border-border/40 bg-card px-2 py-1 text-xs text-foreground"
            >
              <option value="">All States</option>
              {states.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </div>

          {/* Mule Score Threshold */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground mb-2 block">
              Mule Score Min: {(filters.muleScore * 100).toFixed(0)}%
            </label>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={filters.muleScore * 100}
              onChange={(e) => handleFilterChange('muleScore', parseInt(e.target.value) / 100)}
              className="w-full"
            />
          </div>
        </div>

        {/* Active filters display */}
        <div className="flex flex-wrap gap-2">
          {filters.dateRange !== 'today' && (
            <Badge variant="secondary" className="text-xs">
              {filters.dateRange}
            </Badge>
          )}
          {filters.amountRange !== 'all' && (
            <Badge variant="secondary" className="text-xs">
              {filters.amountRange}
            </Badge>
          )}
          {filters.riskLevel !== 'all' && (
            <Badge variant="secondary" className="text-xs">
              {filters.riskLevel}
            </Badge>
          )}
          {filters.state && (
            <Badge variant="secondary" className="text-xs">
              {filters.state}
            </Badge>
          )}
          {filters.muleScore > 0 && (
            <Badge variant="secondary" className="text-xs">
              Score ≥ {(filters.muleScore * 100).toFixed(0)}%
            </Badge>
          )}
        </div>
      </div>
    </Card>
  )
}
