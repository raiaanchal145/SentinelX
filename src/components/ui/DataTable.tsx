import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react"
import Skeleton from "./Skeleton"

export type DataTableColumn<T> = {
  key: string
  header: string
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number
  width?: string
}

type DataTableProps<T> = {
  columns: DataTableColumn<T>[]
  rows: T[]
  getRowId: (row: T) => string
  ariaLabel: string
  loading?: boolean
  emptyState?: ReactNode
  onRowActivate?: (row: T) => void
  rowHref?: (row: T) => string | undefined
  /** Called for every keydown on a focused row, after the built-in
   * Up/Down/Enter handling -- use it for row-level hotkeys like "a" to
   * acknowledge, "d" to dismiss. */
  onRowKeyDown?: (row: T, event: KeyboardEvent<HTMLTableRowElement>) => void
}

/** Sticky header, sortable columns, keyboard row navigation (Up/Down + Enter),
 * skeleton loading, and an empty-state slot. Sorting/selection are held
 * locally; callers pass already-filtered rows. */
function DataTable<T>({
  columns,
  rows,
  getRowId,
  ariaLabel,
  loading = false,
  emptyState,
  onRowActivate,
  rowHref,
  onRowKeyDown,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
  const [focusedIndex, setFocusedIndex] = useState(0)
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([])

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows
    const column = columns.find((c) => c.key === sortKey)
    if (!column?.sortValue) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = column.sortValue!(a)
      const bv = column.sortValue!(b)
      if (av < bv) return sortDir === "asc" ? -1 : 1
      if (av > bv) return sortDir === "asc" ? 1 : -1
      return 0
    })
    return copy
  }, [rows, sortKey, sortDir, columns])

  function toggleSort(column: DataTableColumn<T>) {
    if (!column.sortValue) return
    if (sortKey === column.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(column.key)
      setSortDir("asc")
    }
  }

  function handleRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, index: number, row: T) {
    if (event.key === "ArrowDown") {
      event.preventDefault()
      const next = Math.min(index + 1, sortedRows.length - 1)
      setFocusedIndex(next)
      rowRefs.current[next]?.focus()
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      const prev = Math.max(index - 1, 0)
      setFocusedIndex(prev)
      rowRefs.current[prev]?.focus()
    } else if (event.key === "Enter") {
      onRowActivate?.(row)
    }
    onRowKeyDown?.(row, event)
  }

  if (loading) {
    return (
      <div className="overflow-hidden rounded-card border border-line">
        <div className="space-y-3 bg-surface p-4">
          <Skeleton count={5} className="h-9 w-full" />
        </div>
      </div>
    )
  }

  if (sortedRows.length === 0) {
    return <>{emptyState}</>
  }

  return (
    <div className="overflow-auto rounded-card border border-line">
      <table className="w-full min-w-[640px] border-collapse text-sm" aria-label={ariaLabel}>
        <thead className="sticky top-0 z-10 bg-surface-sunken">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width }}
                className="border-b border-line px-3 py-2.5 text-left text-xs font-semibold text-fg-muted"
              >
                {column.sortValue ? (
                  <button
                    type="button"
                    onClick={() => toggleSort(column)}
                    className="flex items-center gap-1 hover:text-fg-primary"
                  >
                    {column.header}
                    {sortKey === column.key ? (
                      sortDir === "asc" ? (
                        <ArrowUp size={12} aria-hidden="true" />
                      ) : (
                        <ArrowDown size={12} aria-hidden="true" />
                      )
                    ) : (
                      <ChevronsUpDown size={12} className="opacity-40" aria-hidden="true" />
                    )}
                  </button>
                ) : (
                  column.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, index) => {
            const href = rowHref?.(row)
            return (
              <tr
                key={getRowId(row)}
                ref={(el) => {
                  rowRefs.current[index] = el
                }}
                tabIndex={index === focusedIndex ? 0 : -1}
                onFocus={() => setFocusedIndex(index)}
                onKeyDown={(event) => handleRowKeyDown(event, index, row)}
                onClick={() => (href ? undefined : onRowActivate?.(row))}
                className="border-b border-line/60 last:border-0 transition hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
              >
                {columns.map((column) => (
                  <td key={column.key} className="px-3 py-2.5 align-middle text-fg-secondary">
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default DataTable
