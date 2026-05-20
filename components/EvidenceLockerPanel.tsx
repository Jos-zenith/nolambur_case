'use client'

import { FileText, Image, Volume2, Download, Eye } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface Evidence {
  id: string
  name: string
  type: 'document' | 'screenshot' | 'recording'
  size: string
  uploadedAt: string
}

export function EvidenceLockerPanel() {
  const evidence: Evidence[] = [
    {
      id: '1',
      name: 'Victim_Screen_Recording_1.mp4',
      type: 'recording',
      size: '124 MB',
      uploadedAt: '2026-05-20 14:22',
    },
    {
      id: '2',
      name: 'UPI_Transaction_History_Cleaned.pdf',
      type: 'document',
      size: '2.3 MB',
      uploadedAt: '2026-05-20 14:25',
    },
    {
      id: '3',
      name: 'Screenshot_Mule_Account_1001.png',
      type: 'screenshot',
      size: '1.2 MB',
      uploadedAt: '2026-05-20 14:28',
    },
    {
      id: '4',
      name: 'Bank_Confirmation_Letter.pdf',
      type: 'document',
      size: '0.8 MB',
      uploadedAt: '2026-05-20 14:30',
    },
    {
      id: '5',
      name: 'Call_Recording_Scammer.m4a',
      type: 'recording',
      size: '8.5 MB',
      uploadedAt: '2026-05-20 14:35',
    },
  ]

  const getIcon = (type: string) => {
    switch (type) {
      case 'document':
        return FileText
      case 'screenshot':
        return Image
      case 'recording':
        return Volume2
      default:
        return FileText
    }
  }

  const getTypeBadgeColor = (type: string) => {
    switch (type) {
      case 'document':
        return 'bg-blue-500/20 text-blue-200'
      case 'screenshot':
        return 'bg-purple-500/20 text-purple-200'
      case 'recording':
        return 'bg-orange-500/20 text-orange-200'
      default:
        return 'bg-gray-500/20 text-gray-200'
    }
  }

  return (
    <Card className="border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Evidence Locker</CardTitle>
          <Button size="sm" variant="outline" className="text-xs">
            + Add Evidence
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {evidence.map((item) => {
            const Icon = getIcon(item.type)
            return (
              <div
                key={item.id}
                className="flex items-center justify-between rounded-lg border border-border/40 bg-secondary/10 p-3 hover:bg-secondary/20 transition"
              >
                <div className="flex items-center gap-3 flex-1">
                  <div className="flex-shrink-0">
                    <Icon className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">{item.name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge className={`text-xs capitalize ${getTypeBadgeColor(item.type)}`}>
                        {item.type}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{item.size}</span>
                      <span className="text-xs text-muted-foreground">• {item.uploadedAt}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                  <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
                    <Download className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
