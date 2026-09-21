import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { apiGetMe, ApiError, type ApiUser } from "./api"
import { getSession } from "./auth"

type MeState = {
  me: ApiUser | null
  loading: boolean
  error: string | null
  refetch: () => void
}

const MeContext = createContext<MeState | null>(null)

/**
 * Fetches `GET /auth/me` once per app-mount (and again whenever
 * `refetch()` is called, e.g. right after login/logout) and exposes the
 * result app-wide. This is the single source of truth for
 * `organization`/`effective_modules` -- pages should read `useMe()`
 * rather than calling `apiGetMe()` themselves. See docs/API_CONTRACT.md.
 */
export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<ApiUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  const refetch = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    if (!getSession().loggedIn) {
      setMe(null)
      setError(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    apiGetMe()
      .then((user) => {
        if (cancelled) return
        setMe(user)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setMe(null)
        setError(err instanceof ApiError ? err.message : "Failed to load your account.")
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [nonce])

  return <MeContext.Provider value={{ me, loading, error, refetch }}>{children}</MeContext.Provider>
}

/** Reads the current `/auth/me` snapshot. Must be used within `<MeProvider>`. */
export function useMe(): MeState {
  const ctx = useContext(MeContext)
  if (!ctx) {
    throw new Error("useMe() must be used within a MeProvider")
  }
  return ctx
}
