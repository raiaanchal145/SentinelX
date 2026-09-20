import { Navigate, Route, Routes } from "react-router-dom"

import Login from "./pages/Login"
import Register from "./pages/Register"
import VerifyEmail from "./pages/VerifyEmail"
import ForgotPassword from "./pages/ForgotPassword"
import ResetPassword from "./pages/ResetPassword"

import AdminDashboard from "./pages/AdminDashboard"
import OrganizationDashboard from "./pages/OrganizationDashboard"

import UserLayout from "./layouts/UserLayout"

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
import ManagerAudit from "./features/manager/pages/ManagerAudit"

import AuditorOverview from "./features/auditor/pages/AuditorOverview"
import AuditorAuditLogs from "./features/auditor/pages/AuditorAuditLogs"
import AuditorIncidents from "./features/auditor/pages/AuditorIncidents"
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
    SUPER ADMIN ACCESS

    Super Admin can access every protected page -- unchanged from before.
  */

  if (role === "super_admin") {
    return children
  }

  /*
    OTHER ROLE RESTRICTIONS

    A logged-in user hitting a route that isn't theirs is sent to THEIR
    OWN home instead of being bounced to /login (which they're already
    past). homePathFor() is the single source of truth for what "home"
    means for every role, shared with Login's post-auth redirect.
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
        path="/register"
        element={<Register />}
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
            ]}
          >
            <OrganizationDashboard />
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
        <Route path="/soc/alerts" element={<SocAlerts />} />
        <Route path="/soc/incidents" element={<SocIncidents />} />
        <Route path="/soc/incidents/:id" element={<IncidentDetail />} />
        <Route path="/soc/events" element={<SocEvents />} />
        <Route path="/soc/assets" element={<SocAssets />} />
        <Route path="/soc/reports" element={<SocReports />} />
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
        <Route path="/it/tickets" element={<ItTickets />} />
        <Route path="/it/tickets/:id" element={<TicketDetail />} />
        <Route path="/it/assets" element={<ItAssets />} />
        <Route path="/it/runbooks" element={<ItRunbooks />} />
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
        <Route path="/manager/incidents" element={<ManagerIncidents />} />
        <Route path="/manager/approvals" element={<ManagerApprovals />} />
        <Route path="/manager/reports" element={<ManagerReports />} />
        <Route path="/manager/assets" element={<ManagerAssets />} />
        <Route path="/manager/audit" element={<ManagerAudit />} />
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
        <Route path="/auditor/audit-logs" element={<AuditorAuditLogs />} />
        <Route path="/auditor/incidents" element={<AuditorIncidents />} />
        <Route path="/auditor/reports" element={<AuditorReports />} />
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
