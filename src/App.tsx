import { Navigate, Route, Routes } from "react-router-dom"

import Login from "./pages/Login"
import Register from "./pages/Register"
import VerifyEmail from "./pages/VerifyEmail"
import ForgotPassword from "./pages/ForgotPassword"
import ResetPassword from "./pages/ResetPassword"

import AdminDashboard from "./pages/AdminDashboard"
import OrganizationDashboard from "./pages/OrganizationDashboard"
import SOCDashboard from "./pages/SocDashboard"
import ITDashboard from "./pages/ITDashboard"

function ProtectedRoute({
  children,
  allowedRoles,
}: {
  children: React.ReactNode
  allowedRoles?: string[]
}) {
  const loggedIn = localStorage.getItem(
    "sentinelx_logged_in",
  )

  const role = localStorage.getItem(
    "sentinelx_role",
  )

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

    Super Admin can access every protected page.
  */

  if (role === "super_admin") {
    return children
  }

  /*
    OTHER ROLE RESTRICTIONS
  */

  if (
    allowedRoles &&
    !allowedRoles.includes(role || "")
  ) {
    if (role === "soc_analyst") {
      return (
        <Navigate
          to="/soc-dashboard"
          replace
        />
      )
    }

    if (role === "it_developer") {
      return (
        <Navigate
          to="/it-dashboard"
          replace
        />
      )
    }

    return (
      <Navigate
        to="/login"
        replace
      />
    )
  }

  return children
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

      {/* SUPER ADMIN DASHBOARD */}

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

      {/* ORGANIZATION DASHBOARD */}

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

      {/* SOC DASHBOARD
          Super Admin + SOC Analyst
      */}

      <Route
        path="/soc-dashboard"
        element={
          <ProtectedRoute
            allowedRoles={[
              "super_admin",
              "soc_analyst",
            ]}
          >
            <SOCDashboard />
          </ProtectedRoute>
        }
      />

      {/* IT DASHBOARD
          Super Admin + IT Developer
      */}

      <Route
        path="/it-dashboard"
        element={
          <ProtectedRoute
            allowedRoles={[
              "super_admin",
              "it_developer",
            ]}
          >
            <ITDashboard />
          </ProtectedRoute>
        }
      />

      {/* UNKNOWN ROUTES */}

      <Route
        path="*"
        element={
          <Navigate
            to="/login"
            replace
          />
        }
      />

    </Routes>
  )
}

export default App
