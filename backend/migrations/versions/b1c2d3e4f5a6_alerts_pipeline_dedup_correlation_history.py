"""alerts pipeline: dedup keys, correlation explainability, alert history

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-09-25 00:00:00.000000

P10 alerts (docs/API_CONTRACT.md "Alerts"):

1. alerts -- P09's worker created none of these yet, so widening is
   safe (no rows to backfill):
   - kind ("detection" | "correlation"), rule_name, group_key,
     username, source_ip -- the correlation keys resolved from the
     supporting events (pattern hits group by one event, so the
     "same user/ip/asset" matching needs the resolved values);
   - dismissed_reason (required by /dismiss), polymorphic assignee
     (assigned_account_type/assigned_account_id: a platform SOC
     analyst admins row or an in-house soc_analyst users row);
   - dedup_key widened to 255 and UNIQUE per organization (partial,
     WHERE dedup_key IS NOT NULL) -- the dedup lock the worker folds
     repeat hits into; queue-path indexes for last_seen_at and the
     assignee filter; alert_events.occurred_at for stable ordering.
2. correlations -- title/severity/reasoning ("why these were
   grouped")/window/event_count/dedup_key (unique per organization)
   plus the same index convention.
3. detection_rules.dedup_window_seconds (default 900 = 15 minutes) --
   the per-rule dedup window, written by the existing built-in seeder.
4. alert_history -- the per-alert timeline (status changes,
   assignments, dismissals) written alongside the audit_logs entry.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1c2d3e4f5a6"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None

# The original pipeline migration (d1e2f3a4b5c6) created alerts with no
# dedup columns and no rows can exist yet (nothing wrote alerts before
# P10) -- widening is safe and the downgrade simply returns to that
# shape.


def upgrade() -> None:
    # ---- alerts -----------------------------------------------------
    op.add_column("alerts", sa.Column("rule_name", sa.String(150), nullable=True))
    op.add_column("alerts", sa.Column("kind", sa.String(20), nullable=False, server_default="detection"))
    op.add_column("alerts", sa.Column("group_key", sa.String(255), nullable=True))
    op.add_column("alerts", sa.Column("username", sa.String(150), nullable=True))
    op.add_column("alerts", sa.Column("source_ip", sa.String(64), nullable=True))
    op.add_column("alerts", sa.Column("dismissed_reason", sa.Text(), nullable=True))
    op.add_column("alerts", sa.Column("assigned_account_type", sa.String(10), nullable=True))
    op.add_column("alerts", sa.Column("assigned_account_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.alter_column("alerts", "dedup_key", existing_type=sa.String(150), type_=sa.String(255))

    op.create_index(
        "uq_alerts_org_dedup_key",
        "alerts",
        ["organization_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "ix_alerts_org_last_seen",
        "alerts",
        ["organization_id", sa.text("last_seen_at DESC")],
    )
    op.create_index("ix_alerts_assigned", "alerts", ["assigned_account_type", "assigned_account_id"])

    op.add_column(
        "alert_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ---- correlations ------------------------------------------------
    op.add_column("correlations", sa.Column("title", sa.String(250), nullable=False, server_default=""))
    op.add_column(
        "correlations",
        sa.Column("severity", postgresql.ENUM(name="event_severity", create_type=False), nullable=False, server_default="high"),
    )
    op.add_column("correlations", sa.Column("reasoning", sa.Text(), nullable=True))
    op.add_column("correlations", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("correlations", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("correlations", sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("correlations", sa.Column("dedup_key", sa.String(255), nullable=True))
    op.create_index(
        "uq_correlations_org_dedup_key",
        "correlations",
        ["organization_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )

    # ---- detection_rules ---------------------------------------------
    op.add_column(
        "detection_rules",
        sa.Column("dedup_window_seconds", sa.Integer(), nullable=False, server_default="900"),
    )

    # ---- correlation_rules -------------------------------------------
    # The seeding in app/alerting.py uses ON CONFLICT (name) DO UPDATE
    # for the built-in rule -- same requirement a9b0c1d2e3f4 already
    # gave detection_rules. Partial: a future per-organization rule may
    # reuse a built-in's name.
    op.create_index(
        "uq_correlation_rules_builtin_name",
        "correlation_rules",
        ["name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )

    # ---- alert_history ------------------------------------------------
    op.create_table(
        "alert_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("actor_type", postgresql.ENUM(name="actor_type", create_type=False), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status_from", postgresql.ENUM(name="alert_status", create_type=False), nullable=True),
        sa.Column("status_to", postgresql.ENUM(name="alert_status", create_type=False), nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_alert_history_alert_id", "alert_history", ["alert_id"])
    op.create_index("ix_alert_history_org_id", "alert_history", ["organization_id"])


def downgrade() -> None:
    op.drop_index("uq_correlation_rules_builtin_name", table_name="correlation_rules")
    op.drop_index("ix_alert_history_org_id", table_name="alert_history")
    op.drop_index("ix_alert_history_alert_id", table_name="alert_history")
    op.drop_table("alert_history")

    op.drop_column("detection_rules", "dedup_window_seconds")

    op.drop_index("uq_correlations_org_dedup_key", table_name="correlations")
    op.drop_column("correlations", "dedup_key")
    op.drop_column("correlations", "event_count")
    op.drop_column("correlations", "last_seen_at")
    op.drop_column("correlations", "first_seen_at")
    op.drop_column("correlations", "reasoning")
    op.drop_column("correlations", "severity")
    op.drop_column("correlations", "title")

    op.drop_column("alert_events", "occurred_at")
    op.drop_index("ix_alerts_assigned", table_name="alerts")
    op.drop_index("ix_alerts_org_last_seen", table_name="alerts")
    op.drop_index("uq_alerts_org_dedup_key", table_name="alerts")
    op.alter_column("alerts", "dedup_key", existing_type=sa.String(255), type_=sa.String(150))
    op.drop_column("alerts", "assigned_account_id")
    op.drop_column("alerts", "assigned_account_type")
    op.drop_column("alerts", "dismissed_reason")
    op.drop_column("alerts", "source_ip")
    op.drop_column("alerts", "username")
    op.drop_column("alerts", "group_key")
    op.drop_column("alerts", "kind")
    op.drop_column("alerts", "rule_name")
