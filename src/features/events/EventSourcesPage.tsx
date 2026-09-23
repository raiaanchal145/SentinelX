import { useCallback, useEffect, useState } from "react"
import { Copy, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react"

import Badge from "../../components/ui/Badge"
import Button from "../../components/ui/Button"
import ConfirmDialog from "../../components/ui/ConfirmDialog"
import DataTable, { type DataTableColumn } from "../../components/ui/DataTable"
import Dialog from "../../components/ui/Dialog"
import Drawer from "../../components/ui/Drawer"
import EmptyState from "../../components/EmptyState"
import Skeleton from "../../components/ui/Skeleton"
import { useToast } from "../../components/ui/Toast"

import {
  apiCreateEventSource,
  apiCreateEventSourceKey,
  apiDisableEventSource,
  apiListEventSourceKeys,
  apiListEventSources,
  apiRevokeEventSourceKey,
  ApiError,
  type EventSourceKeyRow,
  type EventSourceRow,
} from "../../lib/api"

/**
 * The one Event sources screen (organization owner + security manager
 * write; soc_analyst/auditor read-only -- the backend's per-row
 * can_manage is the authority, same pattern as AssetsPage).
 *
 * The API key's full value is shown ONCE, in its own dialog with an
 * explicit warning, and never retrievable again -- the backend stores
 * only the SHA-256 hash and a short prefix.
 */

const SOURCE_TYPES = [
  { value: "linux_auth", label: "Linux auth log" },
  { value: "application", label: "Application" },
  { value: "docker", label: "Docker" },
  { value: "network", label: "Network" },
  { value: "custom_json", label: "Custom JSON feed" },
] as const

const SOURCE_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  SOURCE_TYPES.map((t) => [t.value, t.label]),
)

function formatDate(value: string | null): string {
  if (!value) return "Never"
  return new Date(value).toLocaleString()
}

type CreateDialogProps = {
  open: boolean
  onClose: () => void
  onCreated: (source: EventSourceRow) => void
}

function CreateSourceDialog({ open, onClose, onCreated }: CreateDialogProps) {
  const [name, setName] = useState("")
  const [sourceType, setSourceType] = useState<string>("linux_auth")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setName("")
      setSourceType("linux_auth")
      setError(null)
    }
  }, [open])

  const submit = async () => {
    if (!name.trim()) {
      setError("A name is required.")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await apiCreateEventSource({ name: name.trim(), source_type: sourceType })
      onCreated(created)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the event source.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New event source"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting ? "Creating..." : "Create source"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? (
          <p className="rounded-control border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger-fg">{error}</p>
        ) : null}
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-fg-primary">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. docker collector on web-1"
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus:border-brand-400"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-fg-primary">Type</span>
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="w-full rounded-control border border-line bg-surface px-3 py-2 text-sm text-fg-primary outline-none focus:border-brand-400"
          >
            {SOURCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-fg-muted">
          A source starts enabled. Create an API key for it afterwards -- the key is what a collector authenticates with.
        </p>
      </div>
    </Dialog>
  )
}

/** Copy-key-once dialog: the ONLY place the full key is ever displayed. */
function KeyCreatedDialog({
  source,
  keyRow,
  onClose,
}: {
  source: EventSourceRow | null
  keyRow: EventSourceKeyRow | null
  onClose: () => void
}) {
  const toast = useToast()
  const open = Boolean(source && keyRow?.key)
  const fullKey = keyRow?.key ?? ""

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fullKey)
      toast.show("Key copied to your clipboard.", { tone: "success" })
    } catch {
      toast.show("Copy failed -- select the key text and copy it manually.", { tone: "danger" })
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="API key created"
      footer={
        <>
          <Button variant="ghost" onClick={copy}>
            <span className="flex items-center gap-2">
              <Copy size={14} /> Copy key
            </span>
          </Button>
          <Button onClick={onClose}>I&apos;ve stored it safely</Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="rounded-control border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger-fg">
          <strong>Copy it now.</strong> This is the only time the full key is ever shown -- SentinelX stores only its
          SHA-256 hash, and it cannot be retrieved again. Anyone with this key can submit events as{" "}
          <strong>{source?.name}</strong>.
        </p>
        <code className="block break-all rounded-control border border-line bg-surface-sunken px-3 py-2 font-mono text-xs text-fg-primary">
          {fullKey}
        </code>
        <p className="text-xs text-fg-muted">
          Prefix for later identification: <span className="font-mono">{keyRow?.prefix}</span>. Send it as{" "}
          <span className="font-mono">Authorization: Bearer &lt;key&gt;</span>.
        </p>
      </div>
    </Dialog>
  )
}

/** Keys drawer for one source: list + create + revoke. */
function KeysDrawer({
  source,
  open,
  onClose,
  onKeyCreated,
}: {
  source: EventSourceRow | null
  open: boolean
  onClose: () => void
  onKeyCreated: (source: EventSourceRow, keyRow: EventSourceKeyRow) => void
}) {
  const toast = useToast()
  const [keys, setKeys] = useState<EventSourceKeyRow[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [revoking, setRevoking] = useState<EventSourceKeyRow | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    if (!source) return
    setLoading(true)
    try {
      const resp = await apiListEventSourceKeys(source.id)
      setKeys(resp.keys)
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not load the keys.", { tone: "danger" })
    } finally {
      setLoading(false)
    }
  }, [source, toast])

  useEffect(() => {
    if (open && source) void load()
  }, [open, source, load])

  if (!source) return null

  const createKey = async () => {
    setCreating(true)
    try {
      const keyRow = await apiCreateEventSourceKey(source.id)
      onKeyCreated(source, keyRow)
      await load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not create the key.", { tone: "danger" })
    } finally {
      setCreating(false)
    }
  }

  const revokeKey = async () => {
    if (!revoking) return
    try {
      await apiRevokeEventSourceKey(source.id, revoking.id)
      toast.show(`Key ${revoking.prefix} revoked.`, { tone: "success" })
      await load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not revoke the key.", { tone: "danger" })
    } finally {
      setRevoking(null)
    }
  }

  return (
    <>
      <Drawer open={open} onClose={onClose} title={`API keys -- ${source.name}`}>
        <div className="space-y-4">
          <p className="text-sm text-fg-muted">
            Collectors authenticate with <span className="font-mono">Authorization: Bearer sx_...</span>. A new key is
            shown once at creation; existing keys only ever appear here by prefix.
          </p>
          <Button onClick={createKey} disabled={creating}>
            <span className="flex items-center gap-2">
              <KeyRound size={14} /> {creating ? "Generating..." : "Create new key"}
            </span>
          </Button>

          {loading && !keys ? (
            <div className="space-y-2">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : keys && keys.length > 0 ? (
            <ul className="space-y-2">
              {keys.map((k) => (
                <li key={k.id} className="flex items-center justify-between gap-3 rounded-control border border-line bg-surface px-3 py-2">
                  <div className="min-w-0">
                    <p className="font-mono text-sm text-fg-primary">{k.prefix}...</p>
                    <p className="text-xs text-fg-muted">
                      Created {formatDate(k.created_at)} · Last used {formatDate(k.last_used_at)}
                    </p>
                  </div>
                  {k.revoked ? (
                    <Badge tone="danger">Revoked</Badge>
                  ) : (
                    <Button variant="ghost" onClick={() => setRevoking(k)}>
                      <span className="flex items-center gap-2 text-danger-fg">
                        <Trash2 size={14} /> Revoke
                      </span>
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-control border border-line bg-surface px-3 py-4 text-sm text-fg-muted">
              No keys yet -- create one so a collector can start sending events.
            </p>
          )}
        </div>
      </Drawer>

      <ConfirmDialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        onConfirm={revokeKey}
        title={`Revoke key ${revoking?.prefix ?? ""}...?`}
        impact={`Collectors using this key stop authenticating immediately. This cannot be undone -- create a new key instead of revoking one you still need.`}
        confirmLabel="Revoke key"
      />
    </>
  )
}

export default function EventSourcesPage({ title = "Event sources" }: { title?: string }) {
  const toast = useToast()
  const [sources, setSources] = useState<EventSourceRow[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [keysSource, setKeysSource] = useState<EventSourceRow | null>(null)
  const [disabling, setDisabling] = useState<EventSourceRow | null>(null)
  const [createdKey, setCreatedKey] = useState<{ source: EventSourceRow; keyRow: EventSourceKeyRow } | null>(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const resp = await apiListEventSources()
      setSources(resp.event_sources)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load event sources.")
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const canManage = sources?.[0]?.can_manage ?? false
  const canManageRow = (row: EventSourceRow) => row.can_manage

  const disable = async () => {
    if (!disabling) return
    try {
      await apiDisableEventSource(disabling.id)
      toast.show(`"${disabling.name}" disabled -- its keys stop working.`, { tone: "success" })
      await load()
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not disable the source.", { tone: "danger" })
    } finally {
      setDisabling(null)
    }
  }

  const columns: DataTableColumn<EventSourceRow>[] = [
    { key: "name", header: "Name", render: (r) => <span className="font-medium text-fg-primary">{r.name}</span>, sortValue: (r) => r.name },
    {
      key: "type",
      header: "Type",
      render: (r) => SOURCE_TYPE_LABELS[r.source_type] ?? r.source_type,
      sortValue: (r) => r.source_type,
    },
    {
      key: "status",
      header: "Status",
      render: (r) =>
        r.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="danger">Disabled</Badge>,
      sortValue: (r) => (r.enabled ? "a" : "b"),
    },
    { key: "last_event", header: "Last event", render: (r) => formatDate(r.last_event_at), sortValue: (r) => r.last_event_at ?? "" },
    {
      key: "actions",
      header: "",
      render: (r) =>
        canManageRow(r) ? (
          <span className="flex items-center justify-end gap-1">
            <Button variant="ghost" onClick={(e) => { e.stopPropagation(); setKeysSource(r) }}>
              <span className="flex items-center gap-1.5 text-xs">
                <KeyRound size={13} /> Keys
              </span>
            </Button>
            {r.enabled ? (
              <Button
                variant="ghost"
                onClick={(e) => {
                  e.stopPropagation()
                  setDisabling(r)
                }}
              >
                <span className="text-xs text-danger-fg">Disable</span>
              </Button>
            ) : null}
          </span>
        ) : (
          <Badge>Read-only</Badge>
        ),
    },
  ]

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg-primary">{title}</h1>
          <p className="mt-0.5 text-sm text-fg-muted">
            Where events come from: register a collector and mint it an API key. Keys are shown once, hashed at rest.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => void load()} aria-label="Reload event sources">
            <RefreshCw size={15} />
          </Button>
          {canManage ? (
            <Button onClick={() => setCreateOpen(true)}>
              <span className="flex items-center gap-2">
                <Plus size={15} /> New source
              </span>
            </Button>
          ) : null}
        </div>
      </div>

      {loadError ? (
        <EmptyState
          title="Couldn't load event sources"
          description={loadError}
          action={{ label: "Retry", onClick: () => void load() }}
        />
      ) : (
        <DataTable
          ariaLabel="Event sources"
          columns={columns}
          rows={sources ?? []}
          getRowId={(r) => r.id}
          loading={sources === null}
          onRowActivate={(r) => setKeysSource(r)}
          emptyState={
            <EmptyState
              title="No event sources yet"
              description={
                canManage
                  ? "Register your first source (a linux auth log, an app, docker...) and create its API key -- ingestion points here."
                  : "Nothing registered yet. Ask the organization owner or a security manager."
              }
              action={canManage ? { label: "New source", onClick: () => setCreateOpen(true) } : undefined}
            />
          }
        />
      )}

      <CreateSourceDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(created) => {
          toast.show("Event source created.", { tone: "success" })
          void load().then(() => setKeysSource(created))
        }}
      />

      <KeysDrawer
        source={keysSource}
        open={Boolean(keysSource)}
        onClose={() => setKeysSource(null)}
        onKeyCreated={(source, keyRow) => setCreatedKey({ source, keyRow })}
      />

      <KeyCreatedDialog source={createdKey?.source ?? null} keyRow={createdKey?.keyRow ?? null} onClose={() => setCreatedKey(null)} />

      <ConfirmDialog
        open={Boolean(disabling)}
        onClose={() => setDisabling(null)}
        onConfirm={disable}
        title={`Disable "${disabling?.name ?? ""}"?`}
        impact="All of its API keys stop authenticating immediately, and no new events are accepted from it. History keeps the source's identity."
        confirmLabel="Disable source"
      />
    </div>
  )
}
