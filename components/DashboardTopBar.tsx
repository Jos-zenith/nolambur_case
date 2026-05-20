'use client'

import { useEffect, useState } from 'react'
import { Search, Server } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function DashboardTopBar() {
  const [time, setTime] = useState<string>('')
  const [systemHealth, setSystemHealth] = useState<'green' | 'yellow' | 'red'>('green')

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date()
      setTime(now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="flex items-center justify-between gap-4 px-6 py-3">
        {/* Left: Operation badge + name */}
        <div className="flex items-center gap-3">
          <Badge className="rounded-full bg-red-500/20 px-3 py-1 text-sm font-semibold text-red-200">
            LIVE
          </Badge>
          <span className="text-sm font-semibold text-foreground">Operation Nolambur</span>
        </div>

        {/* Center: Time + System Health + Connections */}
        <div className="flex items-center gap-6">
          {/* Live clock */}
          <div className="text-xs font-mono text-muted-foreground">{time || '00:00:00'}</div>

          {/* System health dot */}
          <div className="flex items-center gap-2">
            <div
              className={`h-2 w-2 rounded-full ${
                systemHealth === 'green'
                  ? 'bg-emerald-500'
                  : systemHealth === 'yellow'
                    ? 'bg-yellow-500'
                    : 'bg-red-500'
              }`}
            />
            <span className="text-xs text-muted-foreground">System Healthy</span>
          </div>

          {/* Connection status */}
          <div className="flex items-center gap-2 rounded-lg border border-border/40 bg-secondary/20 px-3 py-1">
            <Server className="h-3 w-3 text-emerald-400" />
            <span className="text-xs text-emerald-200">Neo4j • FastAPI • SSE</span>
          </div>
        </div>

        {/* Right: Command palette */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 gap-2 rounded-lg px-3 text-xs">
            <Search className="h-3 w-3" />
            <span>Cmd+K</span>
          </Button>
        </div>
      </div>
    </div>
  )
}
