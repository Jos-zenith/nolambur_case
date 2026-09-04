type DataFreshnessProps = {
  className?: string
  label?: string
}

export function DataFreshness({ className, label = 'Live data • Updated just now' }: DataFreshnessProps) {
  return <span className={className}>{label}</span>
}
