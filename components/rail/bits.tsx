import { cn } from '@/lib/utils'
import { ROLE_LABEL } from '@/lib/rail/format'
import type { AlertStatus, Role, Severity } from '@/lib/rail/types'

const SEV: Record<Severity, string> = {
  critical: 'bg-sev-critical-bg text-sev-critical',
  high: 'bg-sev-high-bg text-sev-high',
  medium: 'bg-sev-medium-bg text-sev-medium',
  low: 'bg-sev-low-bg text-sev-low',
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return <span className={cn('inline-flex h-5 items-center rounded-sm px-1.5 text-[11px] font-medium capitalize', SEV[severity], className)}>{severity}</span>
}

const STATUS: Record<AlertStatus, [string, string]> = {
  open: ['Open', 'text-foreground'],
  held: ['Held', 'text-sev-critical'],
  escalated: ['Escalated', 'text-sev-high'],
  frozen: ['Frozen', 'text-sev-critical'],
  cleared: ['Cleared', 'text-muted-foreground'],
  superseded: ['Superseded', 'text-muted-foreground'],
}

export function StatusText({ status }: { status: AlertStatus }) {
  const [label, cls] = STATUS[status]
  return <span className={cn('text-[12px]', cls)}>{label}</span>
}

/** The dataset label. Shown for evaluation only; the detectors never read it. */
export function TruthTag({ role, className }: { role: Role; className?: string }) {
  const mule = role === 'l1_mule' || role === 'l2_mule'
  return (
    <span
      title="Dataset label from nolambur_labels.csv. Used only to measure precision; the detectors never see it."
      className={cn('inline-flex h-5 items-center rounded-sm border border-dashed px-1.5 font-mono text-[10.5px]', mule ? 'border-sev-critical/40 text-sev-critical' : 'text-muted-foreground', className)}
    >
      label: {ROLE_LABEL[role]}
    </span>
  )
}

/** A GNN score as a number plus a thin bar, so a column of them can be scanned. */
export function Score({ value }: { value: number }) {
  const hot = value >= 0.9
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[12px] tabular-nums" title="GIN checkpoint fraud probability for this edge">
      <span className="relative h-1.5 w-10 overflow-hidden rounded-full bg-muted">
        <span className={cn('absolute inset-y-0 left-0', hot ? 'bg-sev-critical' : 'bg-chart-2')} style={{ width: `${Math.max(2, value * 100)}%` }} />
      </span>
      <span className={hot ? 'text-sev-critical' : ''}>{value.toFixed(3)}</span>
    </span>
  )
}

export function Section({ title, note, children, className }: { title: string; note?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={className}>
      <div className="mb-2.5 flex flex-wrap items-baseline gap-x-2">
        <h3 className="flex items-center gap-2 text-[13.5px] font-semibold">
          <span className="h-3.5 w-[3px] rounded-full bg-brand-1" aria-hidden />
          {title}
        </h3>
        {note && <span className="text-[12px] text-muted-foreground">{note}</span>}
      </div>
      {children}
    </section>
  )
}

export function Table({ head, children, right = [] }: { head: string[]; children: React.ReactNode; right?: number[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b text-left text-[12px] text-muted-foreground">
            {head.map((h, i) => (
              <th key={h + i} className={cn('pb-1.5 pr-3 font-normal', right.includes(i) && 'text-right')}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}
