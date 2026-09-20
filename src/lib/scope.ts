import { getSession } from "./auth"

/**
 * Everything that scopes mock data to "what this session should see" lives
 * here, in one place, so data.ts never has to re-derive it.
 *
 * IMPORTANT: this is a UI-side convenience for filtering the MOCK dataset.
 * It is not a security boundary -- the real backend already scopes every
 * query by the authenticated account's organization_id (see the Admin/User
 * models), and must keep doing so once real endpoints replace src/lib/data.ts.
 * Hiding data in the UI never substitutes for the server enforcing it.
 *
 * KNOWN GAP: the frontend session (localStorage) and the backend's UserOut
 * response don't currently carry an organization_id, so there's no real
 * multi-tenant identity to scope by yet. Every non-super-admin session is
 * pinned to one fixed demo organization ("org-1") below; only super_admin
 * gets to switch between the 3 mock organizations via OrgSwitcher. Wiring
 * this up for real needs UserOut to expose organization_id first.
 */

const DEFAULT_ORG_ID = "org-1"

export type Scope = {
  role: string | null
  accountType: string | null
  organizationId: string | "all"
  userId: string
  teamId: string | null
  displayName: string
}

export function scopeFor(orgOverride?: string | "all"): Scope {
  const session = getSession()
  const isSuperAdmin = session.role === "super_admin"
  const isOrgAdmin = session.role === "organization_admin"

  return {
    role: session.role,
    accountType: session.accountType,
    organizationId: isSuperAdmin ? (orgOverride ?? "all") : DEFAULT_ORG_ID,
    userId: "me",
    teamId:
      session.role === "it_developer"
        ? "team-it-1"
        : session.role === "soc_analyst"
          ? "team-soc-1"
          : null,
    displayName: session.name ?? "You",
  }
  // organization_admin is intentionally pinned like every other non-super
  // role above (see the known-gap note) -- `isOrgAdmin` is kept as a named
  // check so the day organization_id exists, this is the one line to change.
  void isOrgAdmin
}
