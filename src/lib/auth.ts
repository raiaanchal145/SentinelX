// TODO: replace with real auth (backend already issues a JWT) -- this
// mirrors the localStorage mock-session approach already used by
// App.tsx/Sidebar.tsx/Topbar.tsx rather than introducing a new one.

export type AccountType = "admin" | "user"

export type Role =
  | "super_admin"
  | "organization_admin"
  | "soc_analyst"
  | "security_manager"
  | "it_developer"
  | "auditor"

export type Session = {
  loggedIn: boolean
  role: Role | null
  accountType: AccountType | null
  name: string | null
  email: string | null
  token: string | null
}

const ROLE_LABELS: Record<Role, string> = {
  super_admin: "Super Administrator",
  organization_admin: "Organization Admin",
  soc_analyst: "SOC Analyst",
  security_manager: "Security Manager",
  it_developer: "IT / Developer",
  auditor: "Auditor",
}

const ROLE_HOME: Record<Role, string> = {
  super_admin: "/admin",
  organization_admin: "/organization-dashboard",
  soc_analyst: "/soc",
  security_manager: "/manager",
  it_developer: "/it",
  auditor: "/auditor",
}

const KNOWN_ROLES = Object.keys(ROLE_HOME) as Role[]

function isRole(value: string | null): value is Role {
  return !!value && (KNOWN_ROLES as string[]).includes(value)
}

/** Reads the current mock session out of localStorage. */
export function getSession(): Session {
  const loggedIn =
    localStorage.getItem("sentinelx_logged_in") === "true"
  const roleRaw = localStorage.getItem("sentinelx_role")
  const accountTypeRaw = localStorage.getItem(
    "sentinelx_account_type",
  )

  return {
    loggedIn,
    role: isRole(roleRaw) ? roleRaw : null,
    accountType:
      accountTypeRaw === "admin" || accountTypeRaw === "user"
        ? accountTypeRaw
        : null,
    name: localStorage.getItem("sentinelx_name"),
    email: localStorage.getItem("sentinelx_email"),
    token: localStorage.getItem("sentinelx_token"),
  }
}

/** Human-readable label for a role, for the Topbar/UserLayout user menu. */
export function roleLabel(role: string | null | undefined): string {
  return isRole(role ?? null) ? ROLE_LABELS[role as Role] : "User"
}

/** Where a logged-in user of this role belongs -- their "home" route. */
export function homePathFor(role: string | null | undefined): string {
  return isRole(role ?? null) ? ROLE_HOME[role as Role] : "/login"
}

export function isAdmin(role: string | null | undefined): boolean {
  return role === "super_admin" || role === "organization_admin"
}

export function logout() {
  localStorage.removeItem("sentinelx_logged_in")
  localStorage.removeItem("sentinelx_role")
  localStorage.removeItem("sentinelx_name")
  localStorage.removeItem("sentinelx_email")
  localStorage.removeItem("sentinelx_token")
  localStorage.removeItem("sentinelx_account_type")
}
