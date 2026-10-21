"""Admin oversight query indexes (P22).

Adds standalone time-range indexes on:
1. `security_events(occurred_at)`: Accelerates cross-organization aggregate
   hourly rollups (date_trunc('hour', occurred_at)) for platform overview.
2. `alerts(created_at)`: Accelerates platform-wide alert aggregation and top-rule
   false-positive rate queries over 24h/7d/30d windows.
3. `incidents(opened_at)`: Accelerates platform-wide incident aggregation over time ranges.

Revision ID: e8f9a0b1c2d3
Revises: d6e7f8a9b0c1
Create Date: 2026-10-21
"""

from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_security_events_occurred_at", "security_events", ["occurred_at"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_index("ix_incidents_opened_at", "incidents", ["opened_at"])


def downgrade() -> None:
    op.drop_index("ix_incidents_opened_at", table_name="incidents")
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_index("ix_security_events_occurred_at", table_name="security_events")

