import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react"
import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react"
import IconButton from "./IconButton"

type ToastTone = "success" | "info" | "danger"

type ToastItem = {
  id: string
  message: string
  tone: ToastTone
  actionLabel?: string
  onAction?: () => void
}

type ToastContextValue = {
  show: (message: string, opts?: { tone?: ToastTone; actionLabel?: string; onAction?: () => void }) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const TONE_ICON: Record<ToastTone, typeof CheckCircle2> = {
  success: CheckCircle2,
  info: Info,
  danger: TriangleAlert,
}

const TONE_CLASSES: Record<ToastTone, string> = {
  success: "border-success/25 bg-surface-raised text-fg-primary",
  info: "border-line-strong bg-surface-raised text-fg-primary",
  danger: "border-danger/25 bg-surface-raised text-fg-primary",
}

let toastCounter = 0

/** Toasts render bottom-right and never cover the top nav (fixed, well
 * below the header/sub-bar height). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const show = useCallback<ToastContextValue["show"]>((message, opts) => {
    toastCounter += 1
    const id = `toast-${toastCounter}`
    setToasts((prev) => [...prev, { id, message, tone: opts?.tone ?? "info", actionLabel: opts?.actionLabel, onAction: opts?.onAction }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 6000)
  }, [])

  const dismiss = (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id))

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
      >
        {toasts.map((toast) => {
          const Icon = TONE_ICON[toast.tone]
          return (
            <div
              key={toast.id}
              className={`pointer-events-auto flex items-start gap-2 rounded-panel border p-3 text-sm shadow-xl ${TONE_CLASSES[toast.tone]}`}
            >
              <Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span className="flex-1">{toast.message}</span>
              {toast.actionLabel && toast.onAction && (
                <button
                  type="button"
                  onClick={() => {
                    toast.onAction?.()
                    dismiss(toast.id)
                  }}
                  className="shrink-0 text-xs font-semibold text-brand-400 hover:text-brand-300"
                >
                  {toast.actionLabel}
                </button>
              )}
              <IconButton icon={X} label="Dismiss" size={14} onClick={() => dismiss(toast.id)} className="h-6 w-6 shrink-0" />
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>")
  return ctx
}
