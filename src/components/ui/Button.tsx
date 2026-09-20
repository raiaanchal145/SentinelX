import type { ButtonHTMLAttributes, ReactNode } from "react"
import { Loader2 } from "lucide-react"

type Variant = "primary" | "secondary" | "danger" | "ghost"

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  loading?: boolean
  icon?: ReactNode
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "border border-brand-500 bg-brand-500 text-fg-primary hover:bg-brand-600 hover:border-brand-600",
  secondary:
    "border border-line bg-surface text-fg-secondary hover:border-line-strong hover:bg-surface-hover",
  danger:
    "border border-danger/30 bg-danger/10 text-danger-fg hover:bg-danger/20",
  ghost:
    "border border-transparent bg-transparent text-fg-subtle hover:bg-surface-hover hover:text-fg-primary",
}

function Button({
  variant = "secondary",
  loading = false,
  icon,
  disabled,
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-control px-4 py-2 text-sm font-medium transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 disabled:cursor-not-allowed disabled:opacity-60 ${VARIANT_CLASSES[variant]} ${className}`.trim()}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      ) : (
        icon
      )}
      {children}
    </button>
  )
}

export default Button
