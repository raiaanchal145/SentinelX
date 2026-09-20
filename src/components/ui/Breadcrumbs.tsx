import { Fragment } from "react"
import { ChevronRight } from "lucide-react"
import { Link } from "react-router-dom"

export type Crumb = { label: string; path?: string }

function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length === 0) return <span aria-hidden="true" />

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-fg-muted">
      {items.map((item, index) => {
        const isLast = index === items.length - 1

        return (
          <Fragment key={`${item.label}-${index}`}>
            {index > 0 && (
              <ChevronRight size={14} className="text-fg-faint" aria-hidden="true" />
            )}
            {item.path && !isLast ? (
              <Link to={item.path} className="transition hover:text-fg-primary">
                {item.label}
              </Link>
            ) : (
              <span
                aria-current={isLast ? "page" : undefined}
                className={isLast ? "font-medium text-fg-primary" : ""}
              >
                {item.label}
              </span>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}

export default Breadcrumbs
