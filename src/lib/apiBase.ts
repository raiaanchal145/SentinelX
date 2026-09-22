/**
 * Where the browser finds the SentinelX API.
 *
 * Plain `npm run dev` (page served from localhost) keeps today's
 * hardcoded http://localhost:8000 base, byte-for-byte.
 *
 * Share mode (`npm run dev:share` -- see README "Sharing the dev
 * environment"): the page is loaded from the machine's LAN IP or the
 * tunnel URL, and Vite is configured (only in that mode) to proxy /api
 * to the local backend -- so the API base follows window.location.origin.
 * Falling back to localhost here would make a phone call ITSELF instead
 * of the machine running the dev stack.
 */
function computeApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:8000/api/v1"

  const { protocol, hostname, port } = window.location
  const isLoopback =
    hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]"

  // The standard local setup: Vite's default port on the loopback.
  if (isLoopback && (port === "5173" || port === "")) {
    return "http://localhost:8000/api/v1"
  }

  // Share mode (or any non-default origin): same origin, proxied by Vite.
  return `${protocol}//${hostname}${port ? `:${port}` : ""}/api/v1`
}

export const API_BASE = computeApiBase()
