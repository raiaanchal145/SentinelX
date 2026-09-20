type SkeletonProps = {
  className?: string
  /** Number of stacked skeleton lines/blocks to render. */
  count?: number
}

function Skeleton({ className = "h-4 w-full", count = 1 }: SkeletonProps) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className={`animate-pulse rounded-control bg-surface-hover ${className}`}
          style={{ animationDuration: "1.6s" }}
        />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}

export default Skeleton
