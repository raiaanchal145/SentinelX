import type { ReactNode } from "react"
import { ShieldCheck } from "lucide-react"
import Button from "./ui/Button"

function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  /** Optional retry/primary action, e.g. { label: "Retry", onClick: refetch }. */
  action?: {
    label: string
    onClick: () => void
    icon?: ReactNode
  }
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

      {action && (
        <Button variant="secondary" icon={action.icon} onClick={action.onClick} className="mt-4">
          {action.label}
        </Button>
      )}

    </div>
  )
}

export default EmptyState
