import { ReactNode } from "react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"

type Role =
  | "super_admin"
  | "organization_admin"
  | "soc_analyst"
  | "it_developer"

type AppLayoutProps = {
  children: ReactNode
}

function AppLayout({
  children,
}: AppLayoutProps) {
  const storedRole =
    localStorage.getItem("sentinelx_role")

  const role: Role =
    storedRole === "super_admin" ||
    storedRole === "organization_admin" ||
    storedRole === "soc_analyst" ||
    storedRole === "it_developer"
      ? storedRole
      : "soc_analyst"

  return (
    <div className="app-layout">

      <Sidebar role={role} />

      <main className="app-main">

        <Topbar />

        <div className="page-content">
          {children}
        </div>

      </main>

    </div>
  )
}

export default AppLayout