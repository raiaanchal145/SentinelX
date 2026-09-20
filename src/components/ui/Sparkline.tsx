type SparklinePoint = { label: string; value: number }

type SparklineProps = {
  points: SparklinePoint[]
  /** One-line text alternative for screen readers / no-JS. */
  summary: string
  width?: number
  height?: number
}

function Sparkline({ points, summary, width = 240, height = 48 }: SparklineProps) {
  const max = Math.max(1, ...points.map((p) => p.value))
  const stepX = points.length > 1 ? width / (points.length - 1) : width

  const path = points
    .map((p, i) => {
      const x = i * stepX
      const y = height - (p.value / max) * height
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label={summary}
        className="overflow-visible"
      >
        <path d={path} fill="none" stroke="var(--color-brand-400)" strokeWidth={2} />
      </svg>
      <figcaption className="sr-only">{summary}</figcaption>
    </figure>
  )
}

export default Sparkline
