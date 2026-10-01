import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Paperclip } from "lucide-react"

import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import Drawer from "../../../components/ui/Drawer"
import SeverityBadge from "../../../components/SeverityBadge"
import CountdownChip from "../../../components/ui/CountdownChip"
import { useToast } from "../../../components/ui/Toast"
import {
  ApiError,
  apiAddTicketComment,
  apiGetTicket,
  apiTransitionTicket,
  apiUpdateTicketTask,
  apiUploadTicketEvidence,
  type TicketDetailResponse,
} from "../../../lib/api"
import { useMe } from "../../../lib/me"

import { formatBytes, TICKET_STATUS_LABELS } from "../itShared"

type TaskDetailDrawerProps = {
  open: boolean
  onClose: () => void
  /** The ticket id -- the drawer fetches its own fresh detail so the
   * checklist, comments and evidence are never stale. */
  ticketId: string | null
}

/** The IT developer's quick working drawer for one ticket: checklist
 * toggles, a shared comment, evidence upload with hash, and the
 * status actions the API allows (including "Submit for verification"
 * with its required fix summary). */
function TaskDetailDrawer({ open, onClose, ticketId }: TaskDetailDrawerProps) {
  const navigate = useNavigate()
  const { me } = useMe()
  const toast = useToast()

  const [data, setData] = useState<TicketDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [commentBody, setCommentBody] = useState("")
  const [fixSummary, setFixSummary] = useState("")

  const isIt = me?.role === "it_developer"

  const load = useCallback(
    async function load() {
      if (!ticketId) return
      setLoading(true)
      try {
        const res = await apiGetTicket(ticketId)
        setData(res)
      } catch (err) {
        toast.show(err instanceof ApiError ? err.message : "Could not load the ticket.", { tone: "danger" })
      } finally {
        setLoading(false)
      }
    },
    [ticketId, toast],
  )

  useEffect(() => {
    if (open && ticketId) {
      load()
    } else {
      setData(null)
    }
  }, [open, ticketId, load])

  if (!ticketId) return null

  const ticket = data?.ticket

  async function toggleTask(taskId: string, done: boolean) {
    if (!ticketId) return
    try {
      await apiUpdateTicketTask(ticketId, taskId, { status: done ? "completed" : "open" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update the task.", { tone: "danger" })
    }
  }

  async function submitForVerification() {
    if (!ticketId || !fixSummary.trim()) return
    setActing(true)
    try {
      await apiTransitionTicket(ticketId, { status: "verification", note: fixSummary.trim() })
      toast.show("Submitted for SOC verification.", { tone: "success" })
      setFixSummary("")
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not submit for verification.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function uploadEvidence(file: File) {
    if (!ticketId) return
    setActing(true)
    try {
      await apiUploadTicketEvidence(ticketId, file)
      toast.show("Evidence attached.", { tone: "success" })
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "The upload failed.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  async function postComment() {
    if (!ticketId || !commentBody.trim()) return
    setActing(true)
    try {
      await apiAddTicketComment(ticketId, commentBody.trim())
      setCommentBody("")
      load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not post the comment.", { tone: "danger" })
    } finally {
      setActing(false)
    }
  }

  const doneCount = data ? data.tasks.filter((t) => t.status === "completed").length : 0

  return (
    <Drawer open={open} onClose={onClose} title={ticket?.title ?? "Ticket"} side="right" widthClassName="w-full max-w-md">
      {loading && !data ? (
        <p className="text-sm text-fg-muted" role="status">
          Loading…
        </p>
      ) : !data || !ticket ? (
        <p className="text-sm text-fg-muted">The ticket could not be loaded.</p>
      ) : (
        <div className="space-y-5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-fg-faint">{ticket.ticket_number}</span>
            <SeverityBadge severity={ticket.severity} showIcon />
            <Badge tone="neutral">{TICKET_STATUS_LABELS[ticket.status] ?? ticket.status}</Badge>
            {ticket.priority && <Badge tone={ticket.priority === "P1" ? "danger" : "brand"}>{ticket.priority}</Badge>}
            <CountdownChip dueAt={ticket.sla?.resolve_due_at ?? null} done={ticket.status === "RESOLVED" || ticket.status === "CLOSED"} />
          </div>

          {ticket.description && <p className="text-fg-secondary">{ticket.description}</p>}

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
              Checklist ({doneCount}/{data.tasks.length})
            </h3>
            {data.tasks.length === 0 ? (
              <p className="mt-1 text-xs text-fg-muted">No tasks yet -- add them on the ticket page.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {data.tasks.map((task) => {
                  const done = task.status === "completed"
                  return (
                    <li key={task.id}>
                      <label className="flex cursor-pointer items-start gap-2 rounded-control p-1.5 hover:bg-surface-hover">
                        <input
                          type="checkbox"
                          checked={done}
                          disabled={!isIt}
                          onChange={(e) => void toggleTask(task.id, e.target.checked)}
                          className="mt-0.5 h-3.5 w-3.5 rounded border-line accent-brand-500"
                        />
                        <span className={done ? "text-fg-muted line-through" : "text-fg-secondary"}>{task.title}</span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          {isIt && ticket.status === "INVESTIGATING" && (
            <section className="rounded-panel border border-line bg-surface-sunken p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Submit for verification</h3>
              <label className="mt-2 block">
                <span className="mb-1 block text-xs font-medium text-fg-muted">Fix summary (required)</span>
                <textarea
                  value={fixSummary}
                  onChange={(e) => setFixSummary(e.target.value)}
                  rows={3}
                  aria-required="true"
                  placeholder="What was done, what fixed it, how you checked."
                  className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                />
              </label>
              <Button
                variant="primary"
                className="mt-2 w-full"
                loading={acting}
                disabled={!fixSummary.trim()}
                onClick={() => void submitForVerification()}
              >
                Submit for verification
              </Button>
            </section>
          )}

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Evidence</h3>
            {data.evidence.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {data.evidence.map((row) => (
                  <li key={row.id} className="flex items-center gap-2 text-xs text-fg-secondary">
                    <Paperclip size={12} className="text-fg-faint" aria-hidden="true" />
                    <span className="min-w-0 truncate">{row.filename ?? row.title}</span>
                    <span className="shrink-0 text-fg-faint">({formatBytes(row.size_bytes)})</span>
                  </li>
                ))}
              </ul>
            )}
            {isIt && (
              <label className="mt-2 block cursor-pointer text-xs text-brand-400 hover:text-brand-300">
                <input
                  type="file"
                  className="sr-only"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) void uploadEvidence(file)
                    e.target.value = ""
                  }}
                />
                Attach evidence (log/text, png/jpg, pdf, zip · 10 MB max)
              </label>
            )}
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Comments</h3>
            {data.comments.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {data.comments.map((comment) => (
                  <li key={comment.id} className="rounded-control border border-line bg-surface-sunken p-2 text-xs">
                    <p className="flex items-center justify-between font-medium text-fg-primary">
                      {comment.author_type === "admin" ? "Platform SOC" : "IT"}
                      <span className="font-normal text-fg-faint">
                        {comment.created_at ? new Date(comment.created_at).toLocaleString() : ""}
                      </span>
                    </p>
                    <p className="mt-1 text-fg-secondary">{comment.body}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-xs text-fg-muted">No comments yet.</p>
            )}
            {isIt && (
              <div className="mt-2 space-y-2">
                <textarea
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  placeholder="Add a comment for the SOC..."
                  rows={2}
                  aria-label="Add a comment"
                  className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
                />
                <Button variant="secondary" className="w-full" loading={acting} disabled={!commentBody.trim()} onClick={() => void postComment()}>
                  Post comment
                </Button>
              </div>
            )}
          </section>

          <Button variant="secondary" className="w-full" onClick={() => navigate(`/it/tickets/${ticket.id}`)}>
            Open the full ticket page
          </Button>
        </div>
      )}
    </Drawer>
  )
}

export default TaskDetailDrawer
