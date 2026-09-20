import { useState } from "react"
import { Paperclip } from "lucide-react"
import Drawer from "../../../components/ui/Drawer"
import Badge from "../../../components/ui/Badge"
import Button from "../../../components/ui/Button"
import ProgressBar from "../../../components/ui/ProgressBar"
import SeverityBadge from "../../../components/SeverityBadge"
import CountdownChip from "../../../components/ui/CountdownChip"
import type { Asset, Ticket } from "../../../types"

type TaskDetailDrawerProps = {
  open: boolean
  onClose: () => void
  ticket: Ticket | null
  asset: Asset | undefined
  onToggleChecklistItem: (ticket: Ticket, itemId: string) => void
  onAddEvidence: (ticket: Ticket, fileName: string) => void
  onAddComment: (ticket: Ticket, body: string) => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Enter (or a card click) on a "My work" task opens this. Evidence attach
 * is a name-only mock -- no real file upload -- and comments post through
 * IT_ADD_COMMENT so they show up for SOC the same way SOC's own comments do. */
function TaskDetailDrawer({
  open,
  onClose,
  ticket,
  asset,
  onToggleChecklistItem,
  onAddEvidence,
  onAddComment,
}: TaskDetailDrawerProps) {
  const [fileName, setFileName] = useState("")
  const [commentBody, setCommentBody] = useState("")

  if (!ticket) return null

  const doneCount = ticket.checklist.filter((item) => item.done).length

  function handleAttach() {
    const name = fileName.trim()
    if (!name || !ticket) return
    onAddEvidence(ticket, name)
    setFileName("")
  }

  function handlePostComment() {
    const body = commentBody.trim()
    if (!body || !ticket) return
    onAddComment(ticket, body)
    setCommentBody("")
  }

  return (
    <Drawer open={open} onClose={onClose} title={ticket.title} side="right" widthClassName="w-full max-w-md">
      <div className="space-y-5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-fg-faint">{ticket.ticketNumber}</span>
          <SeverityBadge severity={ticket.severity} showIcon />
          <Badge tone="neutral">{ticket.status}</Badge>
          <CountdownChip dueAt={ticket.resolveDueAt} done={ticket.status === "RESOLVED" || ticket.status === "CLOSED"} />
        </div>

        {ticket.reopenReason && (
          <section className="rounded-control border border-danger/20 bg-danger/10 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-danger-fg">Returned by SOC</h3>
            <p className="mt-1 text-fg-secondary">{ticket.reopenReason}</p>
          </section>
        )}

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Summary</h3>
          <p className="mt-1 text-fg-secondary">{ticket.description}</p>
          <p className="mt-1 text-xs text-fg-muted">
            {asset?.hostname ?? "No asset on file"}
            {ticket.environment && <> &middot; {ticket.environment}</>}
          </p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Checklist</h3>
          <div className="mt-1">
            <ProgressBar value={doneCount} max={ticket.checklist.length} />
          </div>
          <ul className="mt-2 space-y-1.5">
            {ticket.checklist.map((item) => (
              <li key={item.id}>
                <label className="flex cursor-pointer items-start gap-2 rounded-control p-1.5 hover:bg-surface-hover">
                  <input
                    type="checkbox"
                    checked={item.done}
                    onChange={() => onToggleChecklistItem(ticket, item.id)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-line accent-brand-500"
                  />
                  <span className={item.done ? "text-fg-muted line-through" : "text-fg-secondary"}>{item.label}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>

        {ticket.recommendedSteps.length > 0 && (
          <section className="rounded-panel border border-brand-500/20 bg-brand-500/5 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-300">Recommended remediation</h3>
            <ul className="mt-1.5 list-disc space-y-1 pl-4 text-fg-secondary">
              {ticket.recommendedSteps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Evidence</h3>
          {ticket.evidence.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {ticket.evidence.map((item) => (
                <li key={item.id} className="flex items-center gap-2 text-xs text-fg-secondary">
                  <Paperclip size={12} className="text-fg-faint" aria-hidden="true" />
                  {item.fileName} <span className="text-fg-faint">({formatBytes(item.sizeBytes)})</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2 flex gap-2">
            <input
              type="text"
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              placeholder="e.g. patch-log.txt"
              aria-label="Evidence file name"
              className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
            <Button variant="secondary" onClick={handleAttach} disabled={!fileName.trim()}>
              Attach
            </Button>
          </div>
          <p className="mt-1 text-[11px] text-fg-faint">Mock attachment -- records a file name and size only.</p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Comments</h3>
          {ticket.comments.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {ticket.comments.map((comment) => (
                <li key={comment.id} className="rounded-control border border-line bg-surface-sunken p-2 text-xs">
                  <p className="flex items-center justify-between font-medium text-fg-primary">
                    {comment.authorName}
                    <span className="font-normal text-fg-faint">{new Date(comment.createdAt).toLocaleString()}</span>
                  </p>
                  <p className="mt-1 text-fg-secondary">{comment.body}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-fg-muted">No comments yet.</p>
          )}
          <div className="mt-2 space-y-2">
            <textarea
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="Add a comment for SOC..."
              rows={2}
              aria-label="Add a comment"
              className="w-full rounded-control border border-line bg-surface px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
            />
            <Button variant="secondary" className="w-full" onClick={handlePostComment} disabled={!commentBody.trim()}>
              Post comment
            </Button>
          </div>
        </section>
      </div>
    </Drawer>
  )
}

export default TaskDetailDrawer
