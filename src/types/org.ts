export type Organization = { id: string; name: string }

export type Team = { id: string; organizationId: string; name: string }

export type UserRole = "soc_analyst" | "security_manager" | "it_developer" | "auditor"

export type AppUser = {
  id: string
  organizationId: string
  teamId: string | null
  name: string
  role: UserRole
}
