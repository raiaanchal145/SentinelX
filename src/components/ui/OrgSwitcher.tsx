import { Building2, ChevronDown } from "lucide-react"
import DropdownMenu, { type DropdownMenuItem } from "./DropdownMenu"

type Org = { id: string; name: string }

type OrgSwitcherProps = {
  organizations: Org[]
  value: string | "all"
  onChange: (value: string | "all") => void
}

/** super_admin only -- organization_admin is pinned to one organization and
 * never sees this. */
function OrgSwitcher({ organizations, value, onChange }: OrgSwitcherProps) {
  const currentLabel = value === "all" ? "All organizations" : organizations.find((o) => o.id === value)?.name ?? "All organizations"

  const items: DropdownMenuItem[] = [
    { key: "all", label: "All organizations", onSelect: () => onChange("all") },
    ...organizations.map((org) => ({ key: org.id, label: org.name, onSelect: () => onChange(org.id) })),
  ]

  return (
    <DropdownMenu
      label="Switch organization"
      align="left"
      items={items}
      trigger={
        <span className="flex items-center gap-2 rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-secondary hover:border-line-strong">
          <Building2 size={14} className="text-fg-muted" aria-hidden="true" />
          {currentLabel}
          <ChevronDown size={14} className="text-fg-muted" aria-hidden="true" />
        </span>
      }
    />
  )
}

export default OrgSwitcher
