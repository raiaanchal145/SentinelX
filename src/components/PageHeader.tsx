import { ReactNode } from "react"

type PageHeaderProps = {
  title: string
  description: string
  action?: ReactNode
}

function PageHeader({
  title,
  description,
  action,
}: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>

      {action && (
        <div className="page-header-action">
          {action}
        </div>
      )}
    </div>
  )
}

export default PageHeader