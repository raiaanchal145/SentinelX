import { ReactNode } from "react"

type DashboardCardProps = {
  title: string
  value?: string
  description: string
  icon?: ReactNode
}

function DashboardCard({
  title,
  value = "—",
  description,
  icon,
}: DashboardCardProps) {
  return (
    <div className="dashboard-card">

      <div className="dashboard-card-header">
        <p className="dashboard-card-title">
          {title}
        </p>

        {icon && (
          <div className="dashboard-card-icon">
            {icon}
          </div>
        )}
      </div>

      <p className="dashboard-card-value">
        {value}
      </p>

      <p className="dashboard-card-description">
        {description}
      </p>

    </div>
  )
}

export default DashboardCard