import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Download, Paperclip, RefreshCw, Upload } from "lucide-react"

import EmptyState from "../../../components/EmptyState"
import ReadOnlyChip from "../../../components/shared/ReadOnlyChip"
import SeverityBadge from "../../../components/SeverityBadge"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Dialog from "../../../components/ui/Dialog"
import IconButton from "../../../components/ui/IconButton"
import Skeleton from "../../../components/ui/Skeleton"
import Tabs from "../../../components/ui/Tabs"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAddTicketComment,
  apiCreateTicketTask,
  apiDeleteTicketTask,
  apiDownloadTicketEvidence,
  apiGetTicket,
  apiTransitionTicket,
  apiUpdateTicketTask,
  apiUploadTicketEvidence,
  type TicketDetailResponse,
  type TicketEvidenceRow,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import { formatBytes, slaBadgeTone, slaStateLabel, TICKET_STATUS_LABELS } from "../itShared"

/** Which transitions are the IT hand-off or a real status move (all get
 * the plain transition dialog); none of the ticket transitions need a
 * typed confirmation -- that lives on incidents and SOC closes. */
function transitionLabel(target: string): string {
  return TICKET_STATUS_LABELS[target] ?? target
}

function EvidenceUploadForm({
  ticketId,
  onUploaded,
  onCancel,
}: {
  ticketId: string
  onUploaded: () => void
  onCancel: () => void
}) {
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState("")
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleUpload() {
    if (!file) return
    setUploading(true)
    try {
      await apiUploadTicketEvidence(ticketId, file, { title: title.trim() || undefined })
      toast.show("Evidence attached.", { tone: "success" })
      onUploaded()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "The upload failed.", { tone: "danger" })
    } finally {
      setUploading(false)
    }
  }

  return (
    <form
      className="space-y-3 rounded-card border border-line bg-surface p-3"
      onSubmit={(e) => {
        e.preventDefault()
        void handleUpload()
      }}
    >
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-fg-muted">File (required)</span>
        <input
          ref={inputRef}
          type="file"
          required
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="w-full text-xs text-fg-secondary file:mr-2 file:rounded-control file:border file:border-line file:bg-surface file:px-2 file:py-1 file:text-xs file:text-fg-secondary"
        />
      </label>
      <p className="text-[11px] text-fg-faint">
        Allowed: logs/text, screenshots (png/jpg), pdf, zip (max 10 MB). The file is hashed (SHA-256) and the hash is
        shown with the evidence row.
      </p>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-fg-muted">Title (optional)</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Defaults to the filename"
          className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        />
      </label>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={uploading} disabled={!file}>
          Upload
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function EvidenceList({
  ticketId,
  evidence,
  onChanged,
  canWrite,
}: {
  ticketId: string
  evidence: TicketEvidenceRow[]
  onChanged: () => void
  canWrite: boolean
}) {
  const toast = useToast()
  const [showUpload, setShowUpload] = useState(false)
  const [downloading, setDownloading] = useState<string | null>(null)

  async function handleDownload(row: TicketEvidenceRow) {
    setDownloading(row.id)
    try {
      await apiDownloadTicketEvidence(ticketId, row.id, row.filename ?? "evidence.bin")
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "The download failed.", { tone: "danger" })
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div className="space-y-2">
      {evidence.length === 0 ? (
        <p className="text-xs text-fg-muted">No evidence attached yet.</p>
      ) : (
        <ul className="divide-y divide-line/60 rounded-card border border-line bg-surface">
          {evidence.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-sm font-medium text-fg-primary">
                  <Paperclip size={13} className="text-fg-faint" aria-hidden="true" />
                  <span className="truncate">{row.filename ?? row.title}</span>
                  <Badge tone="neutral">{row.evidence_type}</Badge>
                </p>
                <p className="mt-0.5 truncate font-mono text-[11px] text-fg-faint" title={row.sha256 ?? undefined}>
                  sha256 {row.sha256 ?? "--"} &middot; {formatBytes(row.size_bytes)}
                </p>
              </div>
              <Button
                variant="secondary"
                icon={<Download size={13} />}
                loading={downloading === row.id}
                onClick={() => void handleDownload(row)}
              >
                Download
              </Button>
            </li>
          ))}
        </ul>
      )}
      {canWrite && !showUpload && (
        <Button variant="primary" icon={<Upload size={13} />} onClick={() => setShowUpload(true)}>
          Attach evidence
        </Button>
      )}
      {canWrite && showUpload && (
        <EvidenceUploadForm ticketId={ticketId} onUploaded={() => { setShowUpload(false); onChanged() }} onCancel={() => setShowUpload(false)} />
      )}
    </div>
  )
}

function TicketDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { me } = useMe()
  const toast = useToast()

  const [data, setData] = useState<TicketDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [acting, setActing] = useState(false)

  const [transitionTarget, setTransitionTarget] = useState<string | null>(null)
  const [fixSummary, setFixSummary] = useState("")

  const load = useCallback(
    async function load() {
      if (!id) return
      setLoading(true)
      setError("")
      try {
        const res = await apiGetTicket(id)
        setData(res)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load the ticket.")
      } finally {
        setLoading(false)
      }
    },
    [id],
  )

  useEffect(() => {
    load()
  }, [load])

  const ticket = data?.ticket
  const allowed = data?.allowed_next_states ?? []
  const isIt = me?.role === "it_developer"

  async function confirmTransition() {
    if (!id || !transitionTarget) return
    setActing(true)
    try {
      await apiTransitionTicket(id, { status: transitionTarget.toLowerCase(), note: fixSummary.trim() || undefined })
      toast.show(`Ticket moved to ${transitionLabel(transitionTarget)}.`, { tone: "success" })
      setTransitionTarget(null)
      setFixSummary("")
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not change the status.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function toggleTask(taskId: string, done: boolean) {
    if (!id || !ticket) return
    try {
      await apiUpdateTicketTask(id, taskId, { status: done ? "completed" : "open" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update the task.", { tone: "danger" })
    }
  }

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton count={2} className="h-16 w-full" />
        <Skeleton count={4} className="h-10 w-full" />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="space-y-4">
        <EmptyState title="Could not load the ticket" description={error} action={{ label: "Try again", onClick: load }} />
      </div>
    )
  }

  if (!data || !ticket) return null

  const doneCount = data.tasks.filter((t) => t.status === "completed").length
  const slaState = ticket.sla?.state ?? "none"

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <IconButton icon={ArrowLeft} label="Back to tickets" onClick={() => navigate("/it/tickets")} />
        <p className="text-xs text-fg-muted">
          <Link to="/it/tickets" className="hover:text-fg-primary">
            Tickets
          </Link>{" "}
          / <span className="text-fg-secondary">{ticket.ticket_number}</span>
        </p>
      </div>

      {/* Header: identity + SLA + THE action buttons, rendered straight
          from the API's allowed_next_states (never hard-coded). */}
      <div className="rounded-card border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={ticket.severity} showIcon />
              <Badge tone="neutral">{TICKET_STATUS_LABELS[ticket.status] ?? ticket.status}</Badge>
              {ticket.priority && <Badge tone={ticket.priority === "P1" ? "danger" : "brand"}>{ticket.priority}</Badge>}
              <Badge tone={slaBadgeTone(slaState)}>{slaStateLabel(slaState)}</Badge>
              {!isIt && <ReadOnlyChip />}
            </div>
            <h1 className="mt-2 text-lg font-semibold text-fg-primary">{ticket.title}</h1>
            {ticket.description && <p className="mt-1 max-w-3xl text-sm text-fg-secondary">{ticket.description}</p>}
            {data.incident && (
              <p className="mt-1 text-xs text-fg-muted">
                Incident:{" "}
                <Link to="/soc/incidents" className="text-brand-400 hover:text-brand-300">
                  {data.incident.title}
                </Link>
              </p>
            )}
          </div>

          {allowed.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {allowed.map((target) => (
                <Button
                  key={target}
                  variant={target === "VERIFICATION" ? "primary" : "secondary"}
                  loading={acting}
                  onClick={() => setTransitionTarget(target)}
                >
                  {target === "VERIFICATION" ? "Submit for verification" : transitionLabel(target)}
                </Button>
              ))}
            </div>
          )}
        </div>
      </div>

      <Tabs
        ariaLabel="Ticket sections"
        tabs={[
          {
            id: "checklist",
            label: `Checklist (${doneCount}/${data.tasks.length})`,
            content: (
              <div className="space-y-3">
                {isIt && isWorkingStatusPublic(ticket.status) && (
                  <AddTaskForm
                    ticketId={ticket.id}
                    onAdded={() => {
                      load()
                    }}
                  />
                )}
                {data.tasks.length === 0 ? (
                  <p className="text-xs text-fg-muted">
                    No tasks yet.{isIt ? " Add the steps this remediation needs -- the SOC sees them on verification." : ""}
                  </p>
                ) : (
                  <ul className="divide-y divide-line/60 rounded-card border border-line bg-surface">
                    {data.tasks.map((task) => {
                      const done = task.status === "completed"
                      return (
                        <li key={task.id} className="flex items-center justify-between gap-2 p-3">
                          <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-2">
                            <input
                              type="checkbox"
                              checked={done}
                              disabled={!isIt}
                              onChange={(e) => void toggleTask(task.id, e.target.checked)}
                              className="mt-0.5 h-3.5 w-3.5 rounded border-line accent-brand-500"
                            />
                            <span className="min-w-0">
                              <span className={`block truncate text-sm ${done ? "text-fg-muted line-through" : "text-fg-primary"}`}>
                                {task.title}
                              </span>
                              {task.due_at && <span className="text-[11px] text-fg-faint">Due {new Date(task.due_at).toLocaleDateString()}</span>}
                            </span>
                          </label>
                          {isIt && (
                            <Button
                              variant="ghost"
                              onClick={() => {
                                if (!id) return
                                void apiDeleteTicketTask(id, task.id)
                                  .then(load)
                                  .catch((err: unknown) =>
                                    toast.show(err instanceof ApiError ? err.message : "Could not delete the task.", { tone: "danger" }),
                                  )
                              }}
                            >
                              Remove
                            </Button>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            ),
          },
          {
            id: "comments",
            label: `Comments (${data.comments.length})`,
            content: (
              <TicketComments ticketId={ticket.id} comments={data.comments} canWrite={isIt} onChanged={load} />
            ),
          },
          {
            id: "evidence",
            label: `Evidence (${data.evidence.length})`,
            content: (
              <EvidenceList ticketId={ticket.id} evidence={data.evidence} onChanged={load} canWrite={isIt} />
            ),
          },
          {
            id: "context",
            label: "Incident context",
            content: (
              <div className="space-y-2 rounded-card border border-line bg-surface p-4 text-sm">
                {data.incident ? (
                  <>
                    <p className="text-fg-primary">{data.incident.title}</p>
                    <p className="text-xs text-fg-muted">
                      Status {TICKET_STATUS_LABELS[data.incident.status] ?? data.incident.status}. This view shows the
                      incident's shared entries only -- the SOC's internal notes are not part of the IT view.
                    </p>
                    <Link
                      to="/soc/incidents"
                      className="inline-block text-xs text-brand-400 hover:text-brand-300"
                    >
                      Open the incident queue
                    </Link>
                  </>
                ) : (
                  <p className="text-xs text-fg-muted">This ticket is not linked to an incident.</p>
                )}
                <ul className="space-y-1 text-xs text-fg-muted">
                  {data.assignments.length > 0 && (
                    <li>
                      Assigned{" "}
                      {data.assignments[0].assigned_user_id
                        ? "to an IT developer"
                        : data.assignments[0].assigned_team_id
                          ? "to a team"
                          : ""}{" "}
                      {data.assignments[0].reason ? `-- ${data.assignments[0].reason}` : ""}
                    </li>
                  )}
                  {data.verifications.length > 0 && (
                    <li>
                      Last verification: {data.verifications[0].result}{" "}
                      {data.verifications[0].notes ? `-- ${data.verifications[0].notes}` : ""}
                    </li>
                  )}
                  {data.status_history.length > 0 && (
                    <li>
                      {data.status_history.length} status change{data.status_history.length === 1 ? "" : "s"} recorded.
                    </li>
                  )}
                </ul>
              </div>
            ),
          },
        ]}
      />

      {/* The transition dialog: "Submit for verification" REQUIRES a fix
          summary (its own Dialog, since the confirm must stay disabled
          while the summary is empty); other moves treat it as an
          optional note. */}
      {transitionTarget && (
        <Dialog
          open
          onClose={() => {
            setTransitionTarget(null)
            setFixSummary("")
          }}
          title={transitionTarget === "VERIFICATION" ? "Submit for verification" : `Move to ${transitionLabel(transitionTarget)}`}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setTransitionTarget(null)
                  setFixSummary("")
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => void confirmTransition()}
                disabled={acting || (transitionTarget === "VERIFICATION" && !fixSummary.trim())}
                loading={acting}
              >
                {transitionTarget === "VERIFICATION" ? "Submit" : "Move"}
              </Button>
            </>
          }
        >
          <p>
            {transitionTarget === "VERIFICATION"
              ? `Hands ${ticket.ticket_number} to the SOC for verification -- the resolve clock keeps running.`
              : `Moves ${ticket.ticket_number} to ${transitionLabel(transitionTarget)}.`}
          </p>
          <label className="mt-3 block">
            <span className="mb-1 block text-xs font-medium text-fg-muted">
              {transitionTarget === "VERIFICATION" ? "Fix summary (required)" : "Note (optional)"}
            </span>
            <textarea
              value={fixSummary}
              onChange={(e) => setFixSummary(e.target.value)}
              rows={3}
              aria-required={transitionTarget === "VERIFICATION"}
              placeholder={transitionTarget === "VERIFICATION" ? "What was done, what fixed it, how you checked." : "Anything the SOC should know."}
              className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
          </label>
        </Dialog>
      )}

      {loading && data && (
        <div className="fixed bottom-4 right-4">
          <IconButton icon={RefreshCw} label="Refreshing" disabled />
        </div>
      )}
    </div>
  )
}

function isWorkingStatusPublic(status: string): boolean {
  return status === "INVESTIGATING" || status === "REMEDIATION" || status === "OPEN" || status === "ASSIGNED" || status === "TRIAGED" || status === "ACKNOWLEDGED"
}

function AddTaskForm({ ticketId, onAdded }: { ticketId: string; onAdded: () => void }) {
  const toast = useToast()
  const [title, setTitle] = useState("")
  const [adding, setAdding] = useState(false)

  async function handleAdd() {
    if (!title.trim()) return
    setAdding(true)
    try {
      await apiCreateTicketTask(ticketId, { title: title.trim() })
      setTitle("")
      onAdded()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not add the task.", { tone: "danger" })
    } finally {
      setAdding(false)
    }
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        void handleAdd()
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Add a checklist step..."
        aria-label="New task title"
        className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
      />
      <Button type="submit" variant="secondary" loading={adding} disabled={!title.trim()}>
        Add
      </Button>
    </form>
  )
}

function TicketComments({
  ticketId,
  comments,
  canWrite,
  onChanged,
}: {
  ticketId: string
  comments: TicketDetailResponse["comments"]
  canWrite: boolean
  onChanged: () => void
}) {
  const toast = useToast()
  const [body, setBody] = useState("")
  const [posting, setPosting] = useState(false)

  async function handlePost() {
    if (!body.trim()) return
    setPosting(true)
    try {
      await apiAddTicketComment(ticketId, body.trim())
      setBody("")
      onChanged()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not post the comment.", { tone: "danger" })
    } finally {
      setPosting(false)
    }
  }

  return (
    <div className="space-y-3">
      {comments.length === 0 ? (
        <p className="text-xs text-fg-muted">No comments yet.</p>
      ) : (
        <ul className="space-y-2">
          {comments.map((comment) => (
            <li key={comment.id} className="rounded-card border border-line bg-surface p-3 text-sm">
              <p className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-muted">
                <span className="font-medium text-fg-primary">
                  {comment.author_type === "admin" ? "Platform SOC" : "IT"}
                </span>
                <span>{comment.created_at ? new Date(comment.created_at).toLocaleString() : "--"}</span>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-fg-secondary">{comment.body}</p>
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            void handlePost()
          }}
        >
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            placeholder="Add a comment for the SOC..."
            aria-label="Add a comment"
            className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
          />
          <Button type="submit" variant="secondary" loading={posting} disabled={!body.trim()}>
            Post comment
          </Button>
        </form>
      )}
    </div>
  )
}

export default TicketDetail
