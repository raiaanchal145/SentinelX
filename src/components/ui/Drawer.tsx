import { useEffect, type ReactNode } from "react"
import { X } from "lucide-react"
import IconButton from "./IconButton"

type DrawerProps = {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** Which edge it slides from. Defaults to "left" (the mobile nav usage). */
  side?: "left" | "right"
  /** Panel width classes. Defaults to the narrow nav-menu size. */
  widthClassName?: string
}

function Drawer({
  open,
  onClose,
  title,
  children,
  side = "left",
  widthClassName = "w-72 max-w-[85vw]",
}: DrawerProps) {
  useEffect(() => {
    if (!open) return

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }

    document.addEventListener("keydown", onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"

    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className={`fixed inset-0 z-50 flex ${side === "right" ? "justify-end" : ""}`}>
      <div
        className="absolute inset-0 bg-canvas/70"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`relative flex h-full ${widthClassName} flex-col ${
          side === "right" ? "border-l" : "border-r"
        } border-line bg-sidebar p-4 shadow-2xl`}
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="text-sm font-semibold text-fg-primary">{title}</span>
          <IconButton icon={X} label={`Close ${title}`} onClick={onClose} />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

export default Drawer
