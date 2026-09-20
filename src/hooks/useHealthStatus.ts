import { useEffect, useRef, useState } from "react"

export type ConnectivityStatus = "operational" | "degraded" | "offline"

const HEALTH_URL = "http://localhost:8000/api/v1/health"
const POLL_MS = 30_000
const TIMEOUT_MS = 5_000

/**
 * Polls the backend health endpoint periodically so the top bar's status
 * dot and connectivity banner reflect whether the SentinelX server is
 * actually reachable.
 */
export function useHealthStatus(): ConnectivityStatus {
  const [status, setStatus] = useState<ConnectivityStatus>("operational")
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller
      const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS)

      try {
        const response = await fetch(HEALTH_URL, { signal: controller.signal })
        if (cancelled) return
        setStatus(response.ok ? "operational" : "degraded")
      } catch {
        if (cancelled) return
        setStatus("offline")
      } finally {
        clearTimeout(timeout)
      }
    }

    poll()
    const interval = setInterval(poll, POLL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
      controllerRef.current?.abort()
    }
  }, [])

  return status
}
