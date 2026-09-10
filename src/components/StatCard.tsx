import type { LucideIcon } from "lucide-react"

function StatCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string
  value: string | number
  description: string
  icon: LucideIcon
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-surface p-5 transition hover:border-brand-500/40">

      <div className="flex items-start justify-between">

        <div>

          <p className="text-sm text-fg-subtle">
            {title}
          </p>

          <h3 className="mt-3 text-3xl font-semibold text-white">
            {value}
          </h3>

        </div>

        <div className="rounded-xl bg-brand-500/10 p-3">

          <Icon
            size={22}
            className="text-brand-400"
          />

        </div>

      </div>

      <p className="mt-4 text-xs text-fg-muted">
        {description}
      </p>

    </div>
  )
}

export default StatCard