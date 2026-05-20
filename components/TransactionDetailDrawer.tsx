'use client'

import { X, AlertCircle, MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

interface Transaction {
  utr: string
  from: string
  to: string
  amount: number
  timestamp: string
  muleScore: number
  geoMismatch: boolean
  status: string
}

interface TransactionDetailDrawerProps {
  transaction: Transaction | null
  isOpen: boolean
  onClose: () => void
}

export function TransactionDetailDrawer({ transaction, isOpen, onClose }: TransactionDetailDrawerProps) {
  if (!transaction) return null

  return (
    <>
      {/* Overlay */}
      {isOpen && <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />}

      {/* Drawer */}
      <div
        className={`fixed right-0 top-0 z-50 h-screen w-full max-w-md transform overflow-y-auto border-l border-border/60 bg-background/95 backdrop-blur-md transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="sticky top-0 border-b border-border/60 bg-background/80 backdrop-blur-sm">
          <div className="flex items-center justify-between p-6">
            <h2 className="text-lg font-semibold text-foreground">Transaction Details</h2>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="space-y-6 p-6">
          {/* Transaction ID */}
          <div>
            <p className="text-xs text-muted-foreground">UTR Number</p>
            <p className="mt-1 font-mono text-sm font-semibold text-foreground">{transaction.utr}</p>
          </div>

          {/* Amount */}
          <div className="rounded-lg border border-border/40 bg-secondary/10 p-4">
            <p className="text-xs text-muted-foreground">Transaction Amount</p>
            <p className="mt-2 text-3xl font-bold text-foreground">₹{(transaction.amount / 100000).toFixed(2)}L</p>
          </div>

          {/* Sender & Receiver */}
          <div className="space-y-3">
            <div>
              <p className="text-xs font-semibold text-foreground">Sender</p>
              <p className="mt-1 font-mono text-xs text-muted-foreground break-all">{transaction.from}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-foreground">Receiver</p>
              <p className="mt-1 font-mono text-xs text-muted-foreground break-all">{transaction.to}</p>
            </div>
          </div>

          {/* Timestamp */}
          <div>
            <p className="text-xs text-muted-foreground">Timestamp</p>
            <p className="mt-1 text-sm text-foreground">{transaction.timestamp}</p>
          </div>

          {/* Mule Score */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-foreground">Mule Risk Score</p>
              <Badge
                className={`text-xs ${
                  transaction.muleScore >= 0.95
                    ? 'bg-red-500/20 text-red-200'
                    : transaction.muleScore >= 0.85
                      ? 'bg-orange-500/20 text-orange-200'
                      : transaction.muleScore >= 0.65
                        ? 'bg-yellow-500/20 text-yellow-200'
                        : 'bg-blue-500/20 text-blue-200'
                }`}
              >
                {(transaction.muleScore * 100).toFixed(1)}%
              </Badge>
            </div>
            <div className="h-2 w-full rounded-full bg-secondary/20">
              <div
                className="h-full rounded-full bg-gradient-to-r from-red-500 to-orange-500"
                style={{ width: `${transaction.muleScore * 100}%` }}
              />
            </div>
          </div>

          {/* Geographic Mismatch */}
          {transaction.geoMismatch && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 flex-shrink-0 text-red-500" />
                <div>
                  <p className="text-sm font-semibold text-red-400">Geographic Mismatch Detected</p>
                  <p className="mt-1 text-xs text-red-300/80">Sender and receiver in different states with unusual flow pattern</p>
                </div>
              </div>
            </div>
          )}

          {/* Status Badge */}
          <div>
            <p className="text-xs font-semibold text-foreground mb-2">Status</p>
            <Badge
              className={`text-xs ${
                transaction.status === 'FROZEN'
                  ? 'bg-green-500/20 text-green-200'
                  : transaction.status === 'FREEZING'
                    ? 'bg-yellow-500/20 text-yellow-200'
                    : 'bg-blue-500/20 text-blue-200'
              }`}
            >
              {transaction.status}
            </Badge>
          </div>

          {/* Action Buttons */}
          <div className="space-y-2 border-t border-border/40 pt-6">
            <Button className="w-full" size="sm">
              Freeze Account
            </Button>
            <Button variant="outline" className="w-full" size="sm">
              Escalate
            </Button>
            <Button variant="ghost" className="w-full" size="sm">
              Dismiss Alert
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
