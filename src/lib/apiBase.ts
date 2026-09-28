/**
 * Where the browser finds the SentinelX API.
 *
 * Plain `npm run dev` (page served from localhost) keeps the hardcoded
 * direct-to-uvicorn base, byte-for-byte -- except it names 127.0.0.1
 * explicitly instead of localhost (see the comment on LOOPBACK_API_BASE).
 *
 * Share mode (`npm run dev:share` -- see README "Sharing the dev
 * environment"): the page is loaded from the machine's LAN IP or the
 * tunnel URL, and Vite is configured (only in that mode) to proxy /api
 * to the local backend -- so the API base follows window.location.origin.
 * Falling back to localhost here would make a phone call ITSELF instead
 * of the machine running the dev stack.
 */

/**
 * The dev backend, named by IPv4 literally. Why not localhost: on
 * Windows, `localhost` resolves to ::1 AND 127.0.0.1 (in that order,
 * per getaddrinfo), while uvicorn's default bind is 127.0.0.1 only --
 * so a client that lands on ::1 first gets connection-refused. Browsers
 * are supposed to fall back (Happy Eyeballs), but the failure mode
 * "page says the backend is down while curl works" is exactly this gap,
 * and naming 127.0.0.1 removes the dead first hop entirely. The CORS
 * allow-list matches the PAGE origin (http://localhost:5173), which is
 * unchanged -- the API base's host form doesn't affect it.
 */
const LOOPBACK_API_BASE = "http://127.0.0.1:8000/api/v1"

function computeApiBase(): string {
  if (typeof window === "undefined") return LOOPBACK_API_BASE

  const { protocol, hostname, port } = window.location
  const isLoopback =
    hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]"

  // The standard local setup: Vite's default port on the loopback.
  if (isLoopback && (port === "5173" || port === "")) {
    return LOOPBACK_API_BASE
  }

  // Share mode (or any non-default origin): same origin, proxied by Vite.
  return `${protocol}//${hostname}${port ? `:${port}` : ""}/api/v1`
}

export const API_BASE = computeApiBase()
