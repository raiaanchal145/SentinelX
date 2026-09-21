import { useEffect, useRef, type ReactNode } from "react"
import { X } from "lucide-react"
import IconButton from "./IconButton"

type DialogProps = {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}

function Dialog({ open, onClose, title, children, footer }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  // Callers almost always pass an inline (or otherwise per-render-fresh)
  // onClose, e.g. onClose={() => setOpen(false)}. Reading it through a
  // ref -- instead of putting it in the effect's dependency array --
  // means typing into a field inside the dialog (which re-renders the
  // caller and hands us a new onClose reference every keystroke) can't
  // re-trigger this effect. Without this, the effect below re-ran on
  // every keystroke and called panelRef.current?.focus(), stealing
  // focus off the input the user was typing into after every character.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return

    function getFocusable(): HTMLElement[] {
      const panel = panelRef.current
      if (!panel) return []
      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.offsetParent !== null)
    }

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseRef.current()
        return
      }

      if (event.key !== "Tab") return

      // Focus trap: keep Tab/Shift+Tab cycling within the dialog panel
      // rather than escaping into the page behind the overlay.
      const focusable = getFocusable()
      if (focusable.length === 0) {
        event.preventDefault()
        panelRef.current?.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || active === panelRef.current) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    panelRef.current?.focus()

    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = previousOverflow
    }
    // Deliberately just [open]: this effect should only run when the
    // dialog opens/closes, not on every render where onClose is a new
    // function reference -- see the onCloseRef comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-canvas/80" onClick={onClose} aria-hidden="true" />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative w-full max-w-md rounded-modal border border-line bg-surface-raised p-5 shadow-2xl outline-none"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-fg-primary">{title}</h2>
          <IconButton icon={X} label="Close dialog" onClick={onClose} />
        </div>

        <div className="text-sm text-fg-subtle">{children}</div>

        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

export default Dialog
