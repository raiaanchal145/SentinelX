import { ShieldCheck } from "lucide-react"

function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-surface p-8 text-center">

      <div className="rounded-full bg-brand-500/10 p-4">

        <ShieldCheck
          size={32}
          className="text-brand-400"
        />

      </div>

      <h3 className="mt-5 text-lg font-medium text-white">
        {title}
      </h3>

      <p className="mt-2 max-w-md text-sm text-fg-muted">
        {description}
      </p>

    </div>
  )
}

export default EmptyState