'use client'

export function GraphLegend() {
  const legends = [
    { color: 'bg-red-500', label: 'Critical (≥95%)' },
    { color: 'bg-orange-500', label: 'High (≥85%)' },
    { color: 'bg-yellow-500', label: 'Medium (≥65%)' },
    { color: 'bg-blue-500', label: 'Low (<65%)' },
  ]

  return (
    <div className="absolute bottom-4 left-4 rounded-xl border border-border/60 bg-card/80 p-3 backdrop-blur-sm">
      <p className="mb-2 text-xs font-semibold text-foreground">Mule Score</p>
      <div className="space-y-1">
        {legends.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${item.color}`} />
            <span className="text-xs text-muted-foreground">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
