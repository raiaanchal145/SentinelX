/**
 * SentinelX design tokens (JS/TS mirror).
 *
 * The real source of truth is `src/styles/theme.css` -- these are the
 * same values, exported as plain JS constants for the handful of places
 * that can't use a Tailwind class or CSS variable directly (e.g. charting
 * libraries, canvas drawing, inline styles computed at runtime, or the
 * favicon/meta-theme-color in index.html).
 *
 * Keep this file in sync with theme.css by hand -- if you change a color
 * there, change it here too.
 */

export const colors = {
  brand: {
    300: "#9cc9ff",
    400: "#5ca8ff",
    500: "#258cff",
    600: "#1c74d1",
    700: "#145493",
  },

  surface: {
    canvas: "#07111f",
    sidebar: "#091522",
    surface: "#0b1828",
    raised: "#0d1a2a",
    sunken: "#0a1624",
    hover: "#101f31",
  },

  line: {
    default: "#1b2b3d",
    strong: "#29425f",
  },

  fg: {
    primary: "#f4f8fc",
    secondary: "#dbeafe",
    subtle: "#a8b6c6",
    muted: "#8fa1b7",
    faint: "#718096",
  },

  severity: {
    critical: { base: "#ef4444", fg: "#ff9b9b" },
    high: { base: "#f97316", fg: "#ffb37d" },
    medium: { base: "#eab308", fg: "#f6d57b" },
    low: { base: "#258cff", fg: "#83b7ec" },
    info: { base: "#94a3b8", fg: "#9aa9ba" },
  },

  danger: { base: "#ef4444", fg: "#ff9b9b" },
  success: { base: "#22c55e", fg: "#4ade80" },
} as const

export const fontSans =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

export const radius = {
  control: "9px",
  panel: "12px",
  card: "14px",
  modal: "16px",
  pill: "999px",
} as const

export type SeverityLevel = keyof typeof colors.severity

/** Look up the readable "on dark surface" color for a severity level. */
export function severityColor(level: SeverityLevel) {
  return colors.severity[level]
}
