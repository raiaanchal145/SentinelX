import type { ButtonHTMLAttributes } from "react"
import type { LucideIcon } from "lucide-react"

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: LucideIcon
  /** Required -- becomes the accessible name for this icon-only button. */
  label: string
  active?: boolean
  size?: number
}

function IconButton({
  icon: Icon,
  label,
  active = false,
  size = 18,
  className = "",
  ...rest
}: IconButtonProps) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={`inline-flex h-9 w-9 items-center justify-center rounded-control border transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 ${
        active
          ? "border-brand-500/40 bg-brand-500/10 text-brand-400"
          : "border-line bg-surface text-fg-subtle hover:border-line-strong hover:bg-surface-hover hover:text-fg-primary"
      } ${className}`.trim()}
    >
      <Icon size={size} aria-hidden="true" />
    </button>
  )
}

export default IconButton
