import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, RefreshCw, ShieldCheck } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import ReadOnlyChip from "../../../components/shared/ReadOnlyChip"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Drawer from "../../../components/ui/Drawer"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import Tabs from "../../../components/ui/Tabs"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAddIncidentComment,
  apiAssignIncident,
  apiGetIncident,
  apiTransitionIncident,
  type IncidentDetailResponse,
  type IncidentLinkedEvent,
  type IncidentStatus,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import { ageLabel } from "../components/alertShared"
import IncidentNoteDialog from "../components/IncidentNoteDialog"
import IncidentTicketPanel from "../components/IncidentTicketPanel"
import IncidentTransitionDialog from "../components/IncidentTransitionDialog"
import { INCIDENT_STATUS_LABELS, timelineEntryLabel } from "../components/incidentShared"

/** Managed-mode oversight: read-only, shared entries only (the backend
 * already filters the timeline for these callers). */
function isReadOnlyCaller(me: ReturnType<typeof useMe>["me"]): boolean {
  if (!me) return false
  return me.role === "security_manager" || me.role === "organization_admin" || me.role === "it_developer"
}

function EventDrawer({ event, onClose }: { event: IncidentLinkedEvent | null; onClose: () => void }) {
  return (
    <Drawer open={event !== null} onClose={onClose} title={`Event ${event?.event_type ?? ""}`} side="right" widthClassName="w-96 max-w-[90vw]">
      {event && (
        <dl className="space-y-2 text-sm">
          <div>
            <dt className="text-xs text-fg-muted">Type</dt>
            <dd className="text-fg-primary">{event.event_type}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">Occurred</dt>
            <dd className="text-fg-primary">{event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "--"}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">User</dt>
            <dd className="text-fg-primary">{event.username ?? "--"}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">Source IP</dt>
            <dd className="font-mono text-fg-primary">{event.source_ip ?? "--"}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">Message</dt>
            <dd className="text-fg-primary">{event.message ?? "--"}</dd>
          </div>
        </dl>
      )}
    </Drawer>
  )
}

function IncidentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { me } = useMe()
  const toast = useToast()

  const [data, setData] = useState<IncidentDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [acting, setActing] = useState(false)

  const [transitionTarget, setTransitionTarget] = useState<string | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const [selectedEvent, setSelectedEvent] = useState<IncidentLinkedEvent | null>(null)

  const readOnly = isReadOnlyCaller(me)

  const load = useCallback(
    async function load() {
      if (!id) return
      setLoading(true)
      setError("")
      try {
        const res = await apiGetIncident(id)
        setData(res)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load the incident.")
      } finally {
        setLoading(false)
      }
    },
    [id],
  )

  useEffect(() => {
    load()
  }, [load])

  async function confirmTransition(payload: { reason?: string; resolution_summary?: string; parent_incident_id?: string }) {
    if (!id || !transitionTarget) return
    setActing(true)
    try {
      await apiTransitionIncident(id, { status: transitionTarget, ...payload })
      toast.show(`Incident moved to ${INCIDENT_STATUS_LABELS[transitionTarget as IncidentStatus] ?? transitionTarget}.`, { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not change the status.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function confirmNote(body: string, visibility: "internal" | "shared") {
    if (!id) return
    setActing(true)
    try {
      await apiAddIncidentComment(id, body, visibility)
      toast.show(visibility === "internal" ? "Internal note added." : "Shared note added.", { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not add the note.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function confirmAssign() {
    if (!id || !me) return
    setActing(true)
    try {
      await apiAssignIncident(id, { account_type: me.account_type === "admin" ? "admin" : "user", account_id: me.id })
      toast.show("Assigned to you.", { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not assign the incident.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton count={3} className="h-16 w-full" />
        <Skeleton count={4} className="h-10 w-full" />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="space-y-4">
        <EmptyState title="Could not load the incident" description={error} action={{ label: "Try again", onClick: load }} />
      </div>
    )
  }

  if (!data) return null

  const incident = data.incident
  const allowed = data.allowed_next_states ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <IconButton icon={ArrowLeft} label="Back to incidents" onClick={() => navigate("/soc/incidents")} />
        <p className="text-xs text-fg-muted">
          <Link to="/soc/incidents" className="hover:text-fg-primary">
            Incidents
          </Link>{" "}
          / <span className="text-fg-secondary">{incident.id.slice(0, 8)}…</span>
        </p>
      </div>

      {/* Header: identity + status + THE action buttons, rendered straight
          from the API's allowed_next_states (never a hard-coded map). */}
      <div className="rounded-card border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={incident.severity} showIcon />
              <Badge tone="neutral">{INCIDENT_STATUS_LABELS[incident.status] ?? incident.status}</Badge>
              {incident.priority && <Badge tone={incident.priority === "P1" ? "danger" : "brand"}>{incident.priority}</Badge>}
              <span className="text-xs text-fg-muted">Opened {ageLabel(incident.opened_at)} ago</span>
              {readOnly && (
                <span className="inline-flex items-center gap-1.5 rounded-pill border border-brand-500/20 bg-brand-500/10 px-2 py-0.5 text-[11px] font-medium text-brand-300">
                  <ShieldCheck size={11} aria-hidden="true" />
                  Handled by the SentinelX SOC team
                </span>
              )}
              {readOnly && <ReadOnlyChip />}
            </div>
            <h1 className="mt-2 text-lg font-semibold text-fg-primary">{incident.title}</h1>
            {incident.summary && <p className="mt-1 max-w-3xl text-sm text-fg-secondary">{incident.summary}</p>}
            {data.duplicate_of && (
              <p className="mt-1 text-xs text-fg-muted">
                Duplicate of{" "}
                <Link to={`/soc/incidents/${data.duplicate_of.id}`} className="text-brand-400 hover:text-brand-300">
                  {data.duplicate_of.title}
                </Link>
              </p>
            )}
            {incident.closure_reason && (
              <p className="mt-1 text-xs text-fg-muted">Closure reason: {incident.closure_reason}</p>
            )}
            {incident.resolution_summary && (
              <p className="mt-1 text-xs text-fg-muted">Resolution: {incident.resolution_summary}</p>
            )}
          </div>

          {!readOnly && (
            <div className="flex flex-wrap items-center gap-2">
              {!incident.assigned_account_id && (
                <Button variant="secondary" loading={acting} onClick={() => void confirmAssign()}>
                  Assign to me
                </Button>
              )}
              {allowed.map((target) => (
                <Button
                  key={target}
                  variant={target === "CLOSED" || target === "FALSE_POSITIVE" || target === "DUPLICATE" ? "danger" : "secondary"}
                  loading={acting}
                  onClick={() => setTransitionTarget(target)}
                >
                  {INCIDENT_STATUS_LABELS[target as IncidentStatus] ?? `Move to ${target}`}
                </Button>
              ))}
              <Button variant="ghost" onClick={() => setNoteOpen(true)}>
                Add note
              </Button>
            </div>
          )}
        </div>
      </div>

      <Tabs
        ariaLabel="Incident sections"
        tabs={[
          {
            id: "overview",
            label: "Overview",
            content: (
              <div className="grid gap-4 lg:grid-cols-2">
                <section aria-label="Affected assets" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Affected assets</h2>
                  {data.assets.length === 0 ? (
                    <p className="mt-2 text-xs text-fg-muted">No assets linked.</p>
                  ) : (
                    <ul className="mt-2 space-y-2">
                      {data.assets.map((asset) => (
                        <li key={asset.id} className="flex items-center justify-between text-sm">
                          <span className="text-fg-primary">
                            {asset.name}
                            {asset.hostname && <span className="ml-2 text-xs text-fg-muted">{asset.hostname}</span>}
                          </span>
                          <Badge tone="neutral">{asset.criticality}</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-label="Linked alerts" className="rounded-card border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold text-fg-primary">Linked alerts ({data.alerts.length})</h2>
                  {data.alerts.length === 0 ? (
                    <p className="mt-2 text-xs text-fg-muted">No alerts linked.</p>
                  ) : (
                    <ul className="mt-2 space-y-2">
                      {data.alerts.map((alert) => (
                        <li key={alert.id} className="flex items-center justify-between gap-2 text-sm">
                          <span className="min-w-0 truncate text-fg-primary" title={alert.title}>
                            {alert.title}
                          </span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            <SeverityBadge severity={alert.severity} />
                            <Badge tone="neutral">{alert.status}</Badge>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-label="Linked events" className="rounded-card border border-line bg-surface p-4 lg:col-span-2">
                  <h2 className="text-sm font-semibold text-fg-primary">Linked events ({data.events.length})</h2>
                  {data.events.length === 0 ? (
                    <p className="mt-2 text-xs text-fg-muted">No events linked.</p>
                  ) : (
                    <ul className="mt-2 divide-y divide-line/60">
                      {data.events.map((event) => (
                        <li key={event.id}>
                          <button
                            type="button"
                            onClick={() => setSelectedEvent(event)}
                            className="flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:text-fg-primary"
                          >
                            <span className="min-w-0 truncate">
                              <span className="font-mono text-xs text-fg-muted">{event.event_type}</span>{" "}
                              <span className="text-fg-secondary">{event.message ?? event.username ?? ""}</span>
                            </span>
                            <span className="shrink-0 text-xs text-fg-muted">
                              {event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "--"}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            ),
          },
          {
            id: "timeline",
            label: `Timeline (${data.timeline.length})`,
            content: (
              <ol className="space-y-0" aria-label="Incident timeline">
                {data.timeline.map((entry) => {
                  const internal = entry.entry_type === "comment" && entry.visibility !== "shared"
                  return (
                    <li key={entry.id} className="relative border-l border-line pl-4">
                      <div className="py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-fg-primary">{timelineEntryLabel(entry.entry_type)}</span>
                          {internal && <Badge tone="brand">Internal</Badge>}
                          <span className="text-xs text-fg-muted">
                            {entry.occurred_at ? new Date(entry.occurred_at).toLocaleString() : "--"} · {entry.actor_type}
                          </span>
                        </div>
                        <p className="mt-1 whitespace-pre-wrap text-sm text-fg-secondary">{entry.description}</p>
                      </div>
                    </li>
                  )
                })}
              </ol>
            ),
          },
          {
            id: "evidence",
            label: "Evidence",
            content: (
              <div className="rounded-card border border-dashed border-line bg-surface p-6 text-center">
                <p className="text-sm text-fg-muted">
                  Evidence attached to this incident will be listed here. Upload arrives in P15.
                </p>
              </div>
            ),
          },
          {
            id: "ticket",
            label: "Ticket",
            content: (
              <IncidentTicketPanel
                incident={incident}
                assetCriticality={data.assets[0]?.criticality ?? null}
                canWrite={!readOnly}
                onChanged={load}
              />
            ),
          },
          {
            id: "response",
            label: "Response actions",
            content: (
              <div className="space-y-3">
                <p className="text-xs text-fg-muted">
                  Automated response actions arrive in P19. The confirmation dialogs are live now -- the buttons stay
                  disabled until the backend exists.
                </p>
                <div className="flex flex-wrap gap-2">
                  {["Isolate asset", "Disable account", "Block IP"].map((action) => (
                    <Button
                      key={action}
                      variant="danger"
                      disabled
                      onClick={() =>
                        toast.show(`${action} requires the response backend (P19).`, { tone: "info" })
                      }
                    >
                      {action}
                    </Button>
                  ))}
                </div>
              </div>
            ),
          },
        ]}
      />

      {/* The typed-confirmation dialog for destructive transitions; also
          used for plain moves (with the fields hidden). */}
      {transitionTarget && (
        <IncidentTransitionDialog
          open
          onClose={() => setTransitionTarget(null)}
          onConfirm={(payload) => void confirmTransition(payload)}
          target={transitionTarget}
          incidentTitle={incident.title}
          loading={acting}
        />
      )}

      <IncidentNoteDialog open={noteOpen} onClose={() => setNoteOpen(false)} onConfirm={(body, vis) => void confirmNote(body, vis)} loading={acting} />

      <EventDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />

      {loading && data && (
        <div className="fixed bottom-4 right-4">
          <IconButton icon={RefreshCw} label="Refreshing" disabled />
        </div>
      )}
    </div>
  )
}

export default IncidentDetail
