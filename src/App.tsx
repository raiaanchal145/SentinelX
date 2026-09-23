import { Navigate, Route, Routes } from "react-router-dom"

import Login from "./pages/Login"
import VerifyEmail from "./pages/VerifyEmail"
import ForgotPassword from "./pages/ForgotPassword"
import ResetPassword from "./pages/ResetPassword"
import AcceptInvite from "./pages/AcceptInvite"
import OrganizationSuspended from "./pages/OrganizationSuspended"
import NoAccess from "./pages/NoAccess"

import AdminDashboard from "./pages/AdminDashboard"
import OrganizationDashboard from "./pages/OrganizationDashboard"

import SocOversightAdmin from "./features/admin/pages/SocOversight"
import ItOversightAdmin from "./features/admin/pages/ItOversight"
import Organizations from "./features/admin/pages/Organizations"
import OrganizationDetail from "./features/admin/pages/OrganizationDetail"
import SocTeam from "./features/admin/pages/SocTeam"
import SocQueue from "./features/admin/pages/SocQueue"
import OwnerDashboard from "./features/owner/pages/OwnerDashboard"
import OwnerMembers from "./features/owner/pages/OwnerMembers"
import OwnerTeams from "./features/owner/pages/OwnerTeams"
import OwnerAccess from "./features/owner/pages/OwnerAccess"
import OwnerAssets from "./features/owner/pages/OwnerAssets"
import OwnerEventSources from "./features/owner/pages/OwnerEventSources"
import OwnerSettings from "./features/owner/pages/OwnerSettings"

import UserLayout from "./layouts/UserLayout"
import ModuleGuard from "./components/ModuleGuard"

import SocOverview from "./features/soc/pages/SocOverview"
import SocAlerts from "./features/soc/pages/SocAlerts"
import SocIncidents from "./features/soc/pages/SocIncidents"
import IncidentDetail from "./features/soc/pages/IncidentDetail"
import SocEvents from "./features/soc/pages/SocEvents"
import SocAssets from "./features/soc/pages/SocAssets"
import SocReports from "./features/soc/pages/SocReports"

import ItMyTasks from "./features/it/pages/ItMyTasks"
import ItTickets from "./features/it/pages/ItTickets"
import TicketDetail from "./features/it/pages/TicketDetail"
import ItAssets from "./features/it/pages/ItAssets"
import ItRunbooks from "./features/it/pages/ItRunbooks"

import ManagerOverview from "./features/manager/pages/ManagerOverview"
import ManagerApprovals from "./features/manager/pages/ManagerApprovals"
import ManagerIncidents from "./features/manager/pages/ManagerIncidents"
import ManagerReports from "./features/manager/pages/ManagerReports"
import ManagerAssets from "./features/manager/pages/ManagerAssets"
import ManagerEventSources from "./features/manager/pages/ManagerEventSources"
import ManagerAudit from "./features/manager/pages/ManagerAudit"

import AuditorOverview from "./features/auditor/pages/AuditorOverview"
import AuditorAuditLogs from "./features/auditor/pages/AuditorAuditLogs"
import AuditorIncidents from "./features/auditor/pages/AuditorIncidents"
import AuditorAssets from "./features/auditor/pages/AuditorAssets"
import AuditorReports from "./features/auditor/pages/AuditorReports"

import { getSession, homePathFor } from "./lib/auth"

function ProtectedRoute({
  children,
  allowedRoles,
}: {
  children: React.ReactNode
  allowedRoles?: string[]
}) {
  const { loggedIn, role } = getSession()

  if (!loggedIn) {
    return (
      <Navigate
        to="/login"
        replace
      />
    )
  }

  /*
    ROLE RESTRICTIONS

    A logged-in user hitting a route that isn't theirs -- including
    super_admin hitting a /soc, /it, /manager or /auditor route -- is
    sent to THEIR OWN home instead of being bounced to /login (which
    they're already past) or, worse, rendered inside a layout with no
    matching nav for their role. homePathFor() is the single source of
    truth for what "home" means for every role, shared with Login's
    post-auth redirect.

    super_admin no longer gets a blanket bypass here: /admin and
    /organization-dashboard already list it in allowedRoles below, so
    this only changes behavior for the new user-side routes, which were
    never meant to be reachable by an admin account.
  */

  if (allowedRoles && !allowedRoles.includes(role ?? "")) {
    return (
      <Navigate
        to={homePathFor(role)}
        replace
      />
    )
  }

  return children
}

/** Logged-in users get sent home; anyone else lands on the login page. */
function CatchAllRoute() {
  const { loggedIn, role } = getSession()

  return (
    <Navigate
      to={loggedIn ? homePathFor(role) : "/login"}
      replace
    />
  )
}

function App() {
  return (
    <Routes>

      {/* DEFAULT */}

      <Route
        path="/"
        element={
          <Navigate
            to="/login"
            replace
          />
        }
      />

      {/* AUTHENTICATION */}

      <Route
        path="/login"
        element={<Login />}
      />

      <Route
        path="/verify-email"
        element={<VerifyEmail />}
      />

      <Route
        path="/forgot-password"
        element={<ForgotPassword />}
      />

      <Route
        path="/reset-password"
        element={<ResetPassword />}
      />

      <Route
        path="/accept-invite"
        element={<AcceptInvite />}
      />

      {/* ORGANIZATION STATUS SCREENS -- reachable with or without an
          active session (Login redirects here on
          organization_suspended/organization_archived; a later guard on
          protected routes will also redirect here if an
          already-logged-in session's organization changes status). */}

      <Route
        path="/organization-suspended"
        element={<OrganizationSuspended />}
      />

      <Route
        path="/no-access"
        element={<NoAccess />}
      />

      {/* PLATFORM ADMIN: ORGANIZATIONS (Prompt B section A -- super_admin's
          new home; see homePathFor() in lib/auth.ts) */}

      <Route
        path="/admin/organizations"
        element={
          <ProtectedRoute allowedRoles={["super_admin"]}>
            <Organizations />
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin/organizations/:id"
        element={
          <ProtectedRoute allowedRoles={["super_admin"]}>
            <OrganizationDetail />
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin/soc-team"
        element={
          <ProtectedRoute allowedRoles={["super_admin"]}>
            <SocTeam />
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin/soc-queue"
        element={
          <ProtectedRoute allowedRoles={["platform_soc_analyst"]}>
            <SocQueue />
          </ProtectedRoute>
        }
      />

      {/* ORGANIZATION OWNER (Prompt B section B -- organization_admin's new
          home; see homePathFor() in lib/auth.ts). Distinct from the
          legacy /organization-dashboard route below, kept as-is. */}

      <Route
        path="/organization"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerDashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/members"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerMembers />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/teams"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerTeams />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/access"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerAccess />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/assets"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerAssets />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/event-sources"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerEventSources />
          </ProtectedRoute>
        }
      />

      <Route
        path="/organization/settings"
        element={
          <ProtectedRoute allowedRoles={["organization_admin"]}>
            <OwnerSettings />
          </ProtectedRoute>
        }
      />

      {/* SUPER ADMIN DASHBOARD (admin side -- unchanged) */}

      <Route
        path="/admin"
        element={
          <ProtectedRoute
            allowedRoles={[
              "super_admin",
            ]}
          >
            <AdminDashboard />
          </ProtectedRoute>
        }
      />

      {/* ORGANIZATION DASHBOARD (admin side -- unchanged) */}

      <Route
        path="/organization-dashboard"
        element={
          <ProtectedRoute
            allowedRoles={[
              "super_admin",
              // Login already sends organization_admin here; without this,
              // removing the super_admin bypass above would leave them
              // stuck in a redirect loop back to this same route.
              "organization_admin",
            ]}
          >
            <OrganizationDashboard />
          </ProtectedRoute>
        }
      />

      {/* SOC / IT OVERSIGHT (admin side, P22 -- aggregates/workload/coverage/SLA
          rollups for super_admin and organization_admin; distinct from the
          analyst/IT-developer dashboards at /soc and /it) */}

      <Route
        path="/admin/soc-oversight"
        element={
          <ProtectedRoute allowedRoles={["super_admin", "organization_admin"]}>
            <SocOversightAdmin />
          </ProtectedRoute>
        }
      />

      <Route
        path="/admin/it-oversight"
        element={
          <ProtectedRoute allowedRoles={["super_admin", "organization_admin"]}>
            <ItOversightAdmin />
          </ProtectedRoute>
        }
      />

      {/* SOC ANALYST -- top navigation shell */}

      <Route
        element={
          <ProtectedRoute allowedRoles={["soc_analyst"]}>
            <UserLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/soc" element={<SocOverview />} />
        <Route path="/soc/alerts" element={<ModuleGuard module="soc"><SocAlerts /></ModuleGuard>} />
        <Route path="/soc/incidents" element={<ModuleGuard module="incidents"><SocIncidents /></ModuleGuard>} />
        <Route path="/soc/incidents/:id" element={<ModuleGuard module="incidents"><IncidentDetail /></ModuleGuard>} />
        <Route path="/soc/events" element={<ModuleGuard module="soc"><SocEvents /></ModuleGuard>} />
        <Route path="/soc/assets" element={<ModuleGuard module="assets"><SocAssets /></ModuleGuard>} />
        <Route path="/soc/reports" element={<ModuleGuard module="reports"><SocReports /></ModuleGuard>} />
      </Route>

      {/* IT / DEVELOPER -- top navigation shell */}

      <Route
        element={
          <ProtectedRoute allowedRoles={["it_developer"]}>
            <UserLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/it" element={<ItMyTasks />} />
        <Route path="/it/tickets" element={<ModuleGuard module="it_tickets"><ItTickets /></ModuleGuard>} />
        <Route path="/it/tickets/:id" element={<ModuleGuard module="it_tickets"><TicketDetail /></ModuleGuard>} />
        <Route path="/it/assets" element={<ModuleGuard module="assets"><ItAssets /></ModuleGuard>} />
        <Route path="/it/runbooks" element={<ModuleGuard module="it_tickets"><ItRunbooks /></ModuleGuard>} />
      </Route>

      {/* SECURITY MANAGER -- top navigation shell */}

      <Route
        element={
          <ProtectedRoute allowedRoles={["security_manager"]}>
            <UserLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/manager" element={<ManagerOverview />} />
        <Route path="/manager/incidents" element={<ModuleGuard module="incidents"><ManagerIncidents /></ModuleGuard>} />
        <Route path="/manager/approvals" element={<ModuleGuard module="approvals"><ManagerApprovals /></ModuleGuard>} />
        <Route path="/manager/reports" element={<ModuleGuard module="reports"><ManagerReports /></ModuleGuard>} />
        <Route path="/manager/assets" element={<ModuleGuard module="assets"><ManagerAssets /></ModuleGuard>} />
        <Route path="/manager/event-sources" element={<ManagerEventSources />} />
        <Route path="/manager/audit" element={<ModuleGuard module="audit_logs"><ManagerAudit /></ModuleGuard>} />
      </Route>

      {/* AUDITOR -- top navigation shell */}

      <Route
        element={
          <ProtectedRoute allowedRoles={["auditor"]}>
            <UserLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/auditor" element={<AuditorOverview />} />
        <Route path="/auditor/audit-logs" element={<ModuleGuard module="audit_logs"><AuditorAuditLogs /></ModuleGuard>} />
        <Route path="/auditor/incidents" element={<ModuleGuard module="incidents"><AuditorIncidents /></ModuleGuard>} />
        <Route path="/auditor/assets" element={<ModuleGuard module="assets"><AuditorAssets /></ModuleGuard>} />
        <Route path="/auditor/reports" element={<ModuleGuard module="reports"><AuditorReports /></ModuleGuard>} />
      </Route>

      {/* LEGACY URL REDIRECTS */}

      <Route
        path="/soc-dashboard"
        element={
          <Navigate
            to="/soc"
            replace
          />
        }
      />

      <Route
        path="/it-dashboard"
        element={
          <Navigate
            to="/it"
            replace
          />
        }
      />

      {/* UNKNOWN ROUTES */}

      <Route
        path="*"
        element={<CatchAllRoute />}
      />

    </Routes>
  )
}

export default App
