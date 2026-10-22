import {
  type FormEvent,
  useEffect,
  useState,
} from "react"
import { useNavigate } from "react-router-dom"
import {
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Laptop,
  LogOut,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  User as UserIcon,
} from "lucide-react"

import Sidebar from "../components/Sidebar"
import Topbar from "../components/Topbar"
import { usePageChrome } from "../layouts/UserLayout"
import Badge from "../components/ui/Badge"
import Button from "../components/ui/Button"
import {
  apiChangePassword,
  apiGetProfile,
  apiGetSessions,
  apiRevokeAllSessions,
  apiRevokeSession,
  apiSend2faCode,
  apiToggle2fa,
  apiUpdateProfile,
  ApiError,
  type SessionItem,
  type UserProfile,
} from "../lib/api"
import { getSession, logout, roleLabel } from "../lib/auth"

export default function ProfilePage() {
  const navigate = useNavigate()
  const session = getSession()
  const currentRole = session.role || ""
  const isSidebarLayout =
    currentRole === "super_admin" ||
    currentRole === "platform_soc_analyst" ||
    currentRole === "organization_admin"

  // If in UserLayout, set breadcrumbs
  usePageChrome(
    isSidebarLayout
      ? []
      : [{ label: "Account Profile", path: "/profile" }],
  )

  // Profile data
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [profileLoading, setProfileLoading] = useState(true)
  const [profileError, setProfileError] = useState("")
  const [nameInput, setNameInput] = useState("")
  const [isEditingName, setIsEditingName] = useState(false)
  const [savingName, setSavingName] = useState(false)
  const [profileSuccessMsg, setProfileSuccessMsg] = useState("")

  // Change Password state
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [revokeOthers, setRevokeOthers] = useState(true)
  const [showOldPass, setShowOldPass] = useState(false)
  const [showNewPass, setShowNewPass] = useState(false)
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [passwordError, setPasswordError] = useState("")
  const [passwordSuccess, setPasswordSuccess] = useState("")

  // Two-Factor state
  const [twoFactorStep, setTwoFactorStep] = useState<"idle" | "verify">("idle")
  const [twoFactorTargetState, setTwoFactorTargetState] = useState<boolean>(true)
  const [twoFactorCode, setTwoFactorCode] = useState("")
  const [twoFactorLoading, setTwoFactorLoading] = useState(false)
  const [twoFactorError, setTwoFactorError] = useState("")
  const [twoFactorSuccess, setTwoFactorSuccess] = useState("")

  // Sessions state
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [sessionsError, setSessionsError] = useState("")
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokingAll, setRevokingAll] = useState(false)

  // Load Profile and Sessions
  const loadProfile = async () => {
    try {
      setProfileLoading(true)
      const data = await apiGetProfile()
      setProfile(data)
      setNameInput(data.name)
      setProfileError("")
    } catch (err) {
      if (err instanceof ApiError) {
        setProfileError(err.message)
      } else {
        setProfileError("Failed to load profile details.")
      }
    } finally {
      setProfileLoading(false)
    }
  }

  const loadSessions = async () => {
    try {
      setSessionsLoading(true)
      const res = await apiGetSessions()
      setSessions(res.sessions || [])
      setSessionsError("")
    } catch (err) {
      if (err instanceof ApiError) {
        setSessionsError(err.message)
      } else {
        setSessionsError("Failed to load active sessions.")
      }
    } finally {
      setSessionsLoading(false)
    }
  }

  useEffect(() => {
    loadProfile()
    loadSessions()
  }, [])

  // Save Name
  const handleSaveName = async () => {
    const trimmed = nameInput.trim()
    if (!trimmed) {
      setProfileError("Name cannot be empty.")
      return
    }
    setSavingName(true)
    setProfileError("")
    setProfileSuccessMsg("")
    try {
      const updated = await apiUpdateProfile(trimmed)
      setProfile(updated)
      setIsEditingName(false)
      setProfileSuccessMsg("Profile name updated successfully.")
      localStorage.setItem("sentinelx_name", updated.name)
      window.dispatchEvent(new Event("sentinelx_auth_change"))
    } catch (err) {
      if (err instanceof ApiError) {
        setProfileError(err.message)
      } else {
        setProfileError("Failed to update profile.")
      }
    } finally {
      setSavingName(false)
    }
  }

  // Change Password
  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault()
    setPasswordError("")
    setPasswordSuccess("")

    if (newPassword.length < 6) {
      setPasswordError("New password must be at least 6 characters.")
      return
    }

    if (newPassword !== confirmPassword) {
      setPasswordError("New passwords do not match.")
      return
    }

    if (newPassword === oldPassword) {
      setPasswordError("New password must be different from your current password.")
      return
    }

    setPasswordLoading(true)
    try {
      const res = await apiChangePassword({
        old_password: oldPassword,
        new_password: newPassword,
        revoke_other_sessions: revokeOthers,
      })
      setPasswordSuccess(res.message || "Password updated successfully.")
      setOldPassword("")
      setNewPassword("")
      setConfirmPassword("")
      // Reload sessions list
      loadSessions()
    } catch (err) {
      if (err instanceof ApiError) {
        setPasswordError(err.message)
      } else {
        setPasswordError("Failed to change password. Please verify current password.")
      }
    } finally {
      setPasswordLoading(false)
    }
  }

  // Start 2FA toggle flow
  const handleInitiate2fa = async (enable: boolean) => {
    setTwoFactorError("")
    setTwoFactorSuccess("")
    setTwoFactorCode("")
    setTwoFactorTargetState(enable)
    setTwoFactorLoading(true)

    try {
      await apiSend2faCode()
      setTwoFactorStep("verify")
      setTwoFactorSuccess(`A 6-digit verification code has been sent to ${profile?.email}.`)
    } catch (err) {
      if (err instanceof ApiError) {
        setTwoFactorError(err.message)
      } else {
        setTwoFactorError("Failed to generate 2FA verification code.")
      }
    } finally {
      setTwoFactorLoading(false)
    }
  }

  // Confirm 2FA code
  const handleConfirm2fa = async (e: FormEvent) => {
    e.preventDefault()
    setTwoFactorError("")
    const code = twoFactorCode.trim()
    if (code.length !== 6) {
      setTwoFactorError("Please enter a valid 6-digit verification code.")
      return
    }

    setTwoFactorLoading(true)
    try {
      const res = await apiToggle2fa(twoFactorTargetState, code)
      setTwoFactorSuccess(res.message)
      setTwoFactorStep("idle")
      setTwoFactorCode("")
      if (profile) {
        setProfile({ ...profile, two_factor_enabled: res.two_factor_enabled })
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setTwoFactorError(err.message)
      } else {
        setTwoFactorError("Incorrect or expired verification code.")
      }
    } finally {
      setTwoFactorLoading(false)
    }
  }

  // Revoke single session
  const handleRevokeSession = async (sessionId: string) => {
    setRevokingId(sessionId)
    setSessionsError("")
    try {
      await apiRevokeSession(sessionId)
      await loadSessions()
    } catch (err) {
      if (err instanceof ApiError) {
        setSessionsError(err.message)
      } else {
        setSessionsError("Failed to revoke session.")
      }
    } finally {
      setRevokingId(null)
    }
  }

  // Revoke all other sessions
  const handleRevokeAll = async () => {
    setRevokingAll(true)
    setSessionsError("")
    try {
      await apiRevokeAllSessions(true)
      await loadSessions()
    } catch (err) {
      if (err instanceof ApiError) {
        setSessionsError(err.message)
      } else {
        setSessionsError("Failed to revoke all other sessions.")
      }
    } finally {
      setRevokingAll(false)
    }
  }

  const content = (
    <div className="mx-auto max-w-5xl space-y-8">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-fg-primary sm:text-3xl">
          Account Profile & Security
        </h1>
        <p className="mt-1 text-sm text-fg-muted">
          Manage your account information, authentication methods, active sessions, and security credentials.
        </p>
      </div>

      {profileLoading && (
        <div className="rounded-2xl border border-line bg-surface p-12 text-center text-sm text-fg-muted">
          <RefreshCw className="mx-auto mb-2 animate-spin text-brand-400" size={24} />
          Loading your profile...
        </div>
      )}

      {profile && (
        <>
          {/* Card 1: Personal & Organization Info */}
          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
            <div className="border-b border-line px-6 py-4 bg-surface-sunken">
              <div className="flex items-center gap-2.5">
                <div className="rounded-control bg-brand-500/10 p-2 text-brand-400">
                  <UserIcon size={18} aria-hidden="true" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-fg-primary">Personal Information</h2>
                  <p className="text-xs text-fg-muted">Your identity and organization membership details.</p>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-6">
              {profileSuccessMsg && (
                <div className="flex items-center gap-2 rounded-xl border border-success/20 bg-success/10 px-4 py-3 text-xs text-success-fg">
                  <CheckCircle2 size={16} />
                  <span>{profileSuccessMsg}</span>
                </div>
              )}
              {profileError && (
                <div className="flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-xs text-danger-fg">
                  <ShieldAlert size={16} />
                  <span>{profileError}</span>
                </div>
              )}

              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                {/* Full Name */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Full Name</label>
                  {isEditingName ? (
                    <div className="mt-1.5 flex items-center gap-2">
                      <input
                        type="text"
                        value={nameInput}
                        onChange={(e) => setNameInput(e.target.value)}
                        className="w-full rounded-control border border-line bg-surface-sunken px-3 py-2 text-sm text-fg-primary outline-none focus:border-brand-500"
                        autoFocus
                      />
                      <Button
                        variant="primary"
                        onClick={handleSaveName}
                        loading={savingName}
                        className="shrink-0"
                      >
                        Save
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setNameInput(profile.name)
                          setIsEditingName(false)
                        }}
                        disabled={savingName}
                        className="shrink-0"
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="mt-1.5 flex items-center justify-between rounded-control border border-line/60 bg-surface-sunken px-3.5 py-2.5 text-sm text-fg-primary">
                      <span className="font-medium">{profile.name}</span>
                      <button
                        type="button"
                        onClick={() => setIsEditingName(true)}
                        className="text-xs font-semibold text-brand-400 hover:text-brand-300 transition"
                      >
                        Edit
                      </button>
                    </div>
                  )}
                </div>

                {/* Email Address */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Email Address</label>
                  <div className="mt-1.5 flex items-center justify-between rounded-control border border-line/60 bg-surface-sunken px-3.5 py-2.5 text-sm text-fg-primary">
                    <span className="text-fg-subtle">{profile.email}</span>
                    <Badge tone="success">Verified</Badge>
                  </div>
                </div>

                {/* Role & Access */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Assigned Role</label>
                  <div className="mt-1.5 flex items-center gap-2 rounded-control border border-line/60 bg-surface-sunken px-3.5 py-2.5 text-sm">
                    <Badge tone="brand">{roleLabel(profile.role)}</Badge>
                    <span className="text-xs text-fg-muted font-mono">{profile.role}</span>
                  </div>
                </div>

                {/* Organization */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Organization</label>
                  <div className="mt-1.5 rounded-control border border-line/60 bg-surface-sunken px-3.5 py-2.5 text-sm text-fg-primary">
                    {profile.organization_name ? (
                      <span className="font-medium">{profile.organization_name}</span>
                    ) : (
                      <span className="text-fg-muted italic">Platform Scoped (No Single Tenant)</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Card 2: Two-Factor Authentication (2FA) */}
          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
            <div className="border-b border-line px-6 py-4 bg-surface-sunken">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="rounded-control bg-brand-500/10 p-2 text-brand-400">
                    <ShieldCheck size={18} aria-hidden="true" />
                  </div>
                  <div>
                    <h2 className="text-base font-semibold text-fg-primary">Two-Factor Authentication (2FA)</h2>
                    <p className="text-xs text-fg-muted">Protect your account using one-time verification security codes sent to your email.</p>
                  </div>
                </div>
                <div>
                  {profile.two_factor_enabled ? (
                    <Badge tone="success">2FA Enabled</Badge>
                  ) : (
                    <Badge tone="neutral">2FA Disabled</Badge>
                  )}
                </div>
              </div>
            </div>

            <div className="p-6 space-y-4">
              {twoFactorSuccess && (
                <div className="flex items-center gap-2 rounded-xl border border-success/20 bg-success/10 px-4 py-3 text-xs text-success-fg">
                  <CheckCircle2 size={16} />
                  <span>{twoFactorSuccess}</span>
                </div>
              )}
              {twoFactorError && (
                <div className="flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-xs text-danger-fg">
                  <ShieldAlert size={16} />
                  <span>{twoFactorError}</span>
                </div>
              )}

              {twoFactorStep === "idle" ? (
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-xl border border-line bg-surface-sunken p-4">
                  <div>
                    <p className="text-sm font-medium text-fg-primary">
                      {profile.two_factor_enabled
                        ? "Two-factor authentication is active on your account."
                        : "Two-factor authentication is currently inactive."}
                    </p>
                    <p className="mt-0.5 text-xs text-fg-muted">
                      {profile.two_factor_enabled
                        ? "Whenever you log in, SentinelX will require a 6-digit confirmation code sent to your email."
                        : "Add an extra layer of defense against unauthorized logins by enabling email-based 2FA."}
                    </p>
                  </div>
                  <Button
                    variant={profile.two_factor_enabled ? "danger" : "primary"}
                    onClick={() => handleInitiate2fa(!profile.two_factor_enabled)}
                    loading={twoFactorLoading}
                    className="shrink-0"
                  >
                    {profile.two_factor_enabled ? "Disable 2FA" : "Enable 2FA"}
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleConfirm2fa} className="rounded-xl border border-line bg-surface-sunken p-5 space-y-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-fg-primary">
                    <KeyRound size={16} className="text-brand-400" />
                    <span>Enter 6-digit security code</span>
                  </div>
                  <p className="text-xs text-fg-muted">
                    We just sent a one-time verification code to <span className="font-medium text-fg-primary">{profile.email}</span>.
                    Please enter the code to confirm {twoFactorTargetState ? "enabling" : "disabling"} 2FA.
                  </p>
                  <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                    <input
                      type="text"
                      maxLength={6}
                      pattern="[0-9]{6}"
                      inputMode="numeric"
                      autoFocus
                      value={twoFactorCode}
                      onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      placeholder="123456"
                      className="w-full sm:w-48 text-center text-xl tracking-[0.3em] font-mono rounded-control border border-line bg-surface px-3 py-2 text-fg-primary outline-none focus:border-brand-500"
                      required
                    />
                    <Button
                      type="submit"
                      variant="primary"
                      loading={twoFactorLoading}
                      disabled={twoFactorCode.trim().length !== 6}
                    >
                      Verify and Confirm
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setTwoFactorStep("idle")
                        setTwoFactorError("")
                        setTwoFactorCode("")
                      }}
                      disabled={twoFactorLoading}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </section>

          {/* Card 3: Change Password */}
          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
            <div className="border-b border-line px-6 py-4 bg-surface-sunken">
              <div className="flex items-center gap-2.5">
                <div className="rounded-control bg-brand-500/10 p-2 text-brand-400">
                  <KeyRound size={18} aria-hidden="true" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-fg-primary">Change Password</h2>
                  <p className="text-xs text-fg-muted">Ensure your account uses a strong, unique password with at least 6 characters.</p>
                </div>
              </div>
            </div>

            <form onSubmit={handleChangePassword} className="p-6 space-y-5">
              {passwordSuccess && (
                <div className="flex items-center gap-2 rounded-xl border border-success/20 bg-success/10 px-4 py-3 text-xs text-success-fg">
                  <CheckCircle2 size={16} />
                  <span>{passwordSuccess}</span>
                </div>
              )}
              {passwordError && (
                <div className="flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-xs text-danger-fg">
                  <ShieldAlert size={16} />
                  <span>{passwordError}</span>
                </div>
              )}

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
                {/* Current Password */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Current Password</label>
                  <div className="relative mt-1.5">
                    <input
                      type={showOldPass ? "text" : "password"}
                      value={oldPassword}
                      onChange={(e) => setOldPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full rounded-control border border-line bg-surface-sunken px-3.5 py-2.5 pr-10 text-sm text-fg-primary outline-none focus:border-brand-500"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowOldPass(!showOldPass)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-primary"
                    >
                      {showOldPass ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                {/* New Password */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">New Password</label>
                  <div className="relative mt-1.5">
                    <input
                      type={showNewPass ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="At least 6 characters"
                      className="w-full rounded-control border border-line bg-surface-sunken px-3.5 py-2.5 pr-10 text-sm text-fg-primary outline-none focus:border-brand-500"
                      required
                      minLength={6}
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPass(!showNewPass)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-primary"
                    >
                      {showNewPass ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                {/* Confirm New Password */}
                <div>
                  <label className="block text-xs font-medium text-fg-secondary">Confirm New Password</label>
                  <div className="mt-1.5">
                    <input
                      type={showNewPass ? "text" : "password"}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Re-enter new password"
                      className="w-full rounded-control border border-line bg-surface-sunken px-3.5 py-2.5 text-sm text-fg-primary outline-none focus:border-brand-500"
                      required
                      minLength={6}
                    />
                  </div>
                </div>
              </div>

              {/* Revoke other sessions checkbox */}
              <div className="flex items-center gap-2.5 pt-1">
                <input
                  type="checkbox"
                  id="revoke-others-check"
                  checked={revokeOthers}
                  onChange={(e) => setRevokeOthers(e.target.checked)}
                  className="rounded border-line text-brand-500 focus:ring-brand-500"
                />
                <label htmlFor="revoke-others-check" className="text-xs text-fg-subtle select-none cursor-pointer">
                  Sign out of all other active sessions and devices immediately
                </label>
              </div>

              <div className="flex justify-end pt-2">
                <Button
                  type="submit"
                  variant="primary"
                  loading={passwordLoading}
                  disabled={!oldPassword || !newPassword || !confirmPassword}
                >
                  Update Password
                </Button>
              </div>
            </form>
          </section>

          {/* Card 4: Active Sessions List */}
          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-line px-6 py-4 bg-surface-sunken">
              <div className="flex items-center gap-2.5">
                <div className="rounded-control bg-brand-500/10 p-2 text-brand-400">
                  <Laptop size={18} aria-hidden="true" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-fg-primary">Active Sessions</h2>
                  <p className="text-xs text-fg-muted">Devices and browsers currently signed into your SentinelX account.</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={loadSessions}
                  loading={sessionsLoading}
                  className="text-xs px-2.5 py-1.5"
                >
                  <RefreshCw size={13} className={sessionsLoading ? "animate-spin" : ""} />
                  <span>Refresh</span>
                </Button>
                {sessions.filter((s) => !s.is_current).length > 0 && (
                  <Button
                    variant="danger"
                    onClick={handleRevokeAll}
                    loading={revokingAll}
                    className="text-xs px-3 py-1.5"
                  >
                    <LogOut size={13} />
                    <span>Sign out all others</span>
                  </Button>
                )}
              </div>
            </div>

            <div className="p-6">
              {sessionsError && (
                <div className="mb-4 flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-xs text-danger-fg">
                  <ShieldAlert size={16} />
                  <span>{sessionsError}</span>
                </div>
              )}

              {sessionsLoading && sessions.length === 0 ? (
                <div className="py-8 text-center text-xs text-fg-muted">
                  Loading active sessions...
                </div>
              ) : sessions.length === 0 ? (
                <div className="py-8 text-center text-xs text-fg-muted">
                  No active sessions found.
                </div>
              ) : (
                <div className="divide-y divide-line/60 overflow-hidden rounded-xl border border-line">
                  {sessions.map((sess) => {
                    const isMobile = sess.device.toLowerCase().includes("iphone") || sess.device.toLowerCase().includes("android")
                    return (
                      <div
                        key={sess.id}
                        className={`flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 transition ${
                          sess.is_current ? "bg-brand-500/5" : "bg-surface hover:bg-surface-hover/50"
                        }`}
                      >
                        <div className="flex items-center gap-3.5">
                          <div className={`rounded-panel p-2.5 ${sess.is_current ? "bg-brand-500/10 text-brand-400" : "bg-surface-sunken text-fg-muted"}`}>
                            {isMobile ? <Smartphone size={20} /> : <Laptop size={20} />}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-semibold text-fg-primary">{sess.device}</p>
                              {sess.is_current ? (
                                <Badge tone="success">Current Session</Badge>
                              ) : (
                                <Badge tone="neutral">Active</Badge>
                              )}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
                              <span>IP: <span className="font-mono text-fg-subtle">{sess.ip}</span></span>
                              {sess.last_seen_at && (
                                <span>Last seen: {new Date(sess.last_seen_at).toLocaleString()}</span>
                              )}
                            </div>
                          </div>
                        </div>

                        <div>
                          {sess.is_current ? (
                            <Button
                              variant="ghost"
                              onClick={() => {
                                logout()
                                navigate("/login")
                              }}
                              className="text-xs text-fg-muted hover:text-danger-fg"
                            >
                              <LogOut size={13} />
                              <span>Sign out this device</span>
                            </Button>
                          ) : (
                            <Button
                              variant="secondary"
                              onClick={() => handleRevokeSession(sess.id)}
                              loading={revokingId === sess.id}
                              className="text-xs text-danger-fg hover:border-danger/40"
                            >
                              <LogOut size={13} />
                              <span>Sign out</span>
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )

  if (isSidebarLayout) {
    return (
      <div className="flex min-h-screen bg-canvas">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <Topbar />
          <main className="p-6 lg:p-8 flex-1">{content}</main>
        </div>
      </div>
    )
  }

  return <div className="p-4 lg:p-8">{content}</div>
}
