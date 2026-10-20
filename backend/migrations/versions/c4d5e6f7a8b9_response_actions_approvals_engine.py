"""Response actions, tool governance and approvals (P19).

One migration for the permission - approval - evidence layer:

1. `approvals` gains the P19 columns: `requested_reason` /
   `decision_reason` (why it was asked, why it was decided -- reject
   without a reason is refused at the API), `expires_at` (24h clock on
   tool approvals; NULL keeps the legacy ticket_close rows
   evergreen-yet-pending exactly as the P13 gate sees them),
   `incident_id` (SET NULL) and `executed_at` (the worker job's
   once-only stamp).
2. `tool_call_logs` becomes the ledger for EVERY tool attempt, not
   only agent ones: `organization_id` (backfilled from agent_runs for
   pre-existing rows, then NOT NULL), `actor_type`/`actor_id` (who
   attempted; backfilled 'ai_agent'), `agent_run_id` widened to
   nullable (user/worker rows have none), `decision`
   (allow|needs_approval|deny -- backfilled from the old `allowed`
   column), `deny_reason`, `arguments_hash` and `incident_id`.
3. `organization_settings.low_risk_automation_enabled` (default
   false): OFF by default -- with it off, low-risk tools also go to
   needs_approval. Fail closed, same stance as ai_enabled.

The downgrade drops the new structures and widens nothing back: the
nullable agent_run_id / new NOT NULL columns are NOT reverted to their
old shapes because existing rows cannot be un-backfilled
("data is not restored", same stance as d5e6f7a8b9c0).

Revision ID: c4d5e6f7a8b9
Revises: b0c1d2e3f4a5
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c4d5e6f7a8b9"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None

# Reuse the existing actor_type enum; never create or drop it here.
actor_type_enum = postgresql.ENUM(name="actor_type", create_type=False)


def upgrade() -> None:
    # ---- approvals: reasons, expiry, incident link, execution stamp ----
    op.add_column("approvals", sa.Column("requested_reason", sa.Text(), nullable=True))
    op.add_column("approvals", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("approvals", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_approvals_expires_at", "approvals", ["expires_at"])
    op.add_column("approvals", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approvals",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_approvals_incident", "approvals", "incidents", ["incident_id"], ["id"], ondelete="SET NULL"
    )

    # ---- tool_call_logs: the evidence ledger for every attempt ----
    op.add_column(
        "tool_call_logs",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tool_call_logs", sa.Column("actor_type", actor_type_enum, nullable=True)
    )
    op.add_column(
        "tool_call_logs", sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_tool_call_logs_actor_id", "tool_call_logs", ["actor_id"])

    # Backfill pre-existing (agent-only) rows before tightening.
    op.execute(
        """
        UPDATE tool_call_logs t
        SET organization_id = ar.organization_id,
            actor_type = 'ai_agent',
            actor_id = ar.agent_id
        FROM agent_runs ar
        WHERE t.agent_run_id = ar.id
        """
    )
    op.alter_column("tool_call_logs", "organization_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_foreign_key(
        "fk_tool_call_logs_organization",
        "tool_call_logs",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_tool_call_logs_organization_id", "tool_call_logs", ["organization_id"])
    op.alter_column(
        "tool_call_logs",
        "actor_type",
        existing_type=actor_type_enum,
        nullable=False,
        postgresql_server_default="ai_agent",
    )
    # Drop the backfill-only default: new rows must always set it.
    op.alter_column("tool_call_logs", "actor_type", existing_type=actor_type_enum, server_default=None)
    op.alter_column("tool_call_logs", "agent_run_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    op.add_column(
        "tool_call_logs", sa.Column("decision", sa.String(length=20), nullable=True)
    )
    op.execute(
        """
        UPDATE tool_call_logs
        SET decision = CASE WHEN allowed THEN 'allow' ELSE 'deny' END
        """
    )
    op.alter_column("tool_call_logs", "decision", existing_type=sa.String(length=20), nullable=False, postgresql_server_default="allow")
    op.alter_column("tool_call_logs", "decision", existing_type=sa.String(length=20), server_default=None)

    op.add_column(
        "tool_call_logs", sa.Column("deny_reason", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "tool_call_logs", sa.Column("arguments_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "tool_call_logs",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_call_logs_incident",
        "tool_call_logs",
        "incidents",
        ["incident_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tool_call_logs_approval",
        "tool_call_logs",
        "approvals",
        ["approval_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tool_call_logs_approval_id", "tool_call_logs", ["approval_id"])

    # ---- organization_settings: the low-risk automation toggle ----
    op.add_column(
        "organization_settings",
        sa.Column(
            "low_risk_automation_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_settings", "low_risk_automation_enabled")

    op.drop_index("ix_tool_call_logs_approval_id", table_name="tool_call_logs")
    op.drop_constraint("fk_tool_call_logs_approval", "tool_call_logs", type_="foreignkey")
    op.drop_constraint("fk_tool_call_logs_incident", "tool_call_logs", type_="foreignkey")
    op.drop_column("tool_call_logs", "incident_id")
    op.drop_column("tool_call_logs", "arguments_hash")
    op.drop_column("tool_call_logs", "deny_reason")
    op.drop_column("tool_call_logs", "decision")
    op.drop_index("ix_tool_call_logs_organization_id", table_name="tool_call_logs")
    op.drop_constraint("fk_tool_call_logs_organization", "tool_call_logs", type_="foreignkey")
    op.alter_column("tool_call_logs", "organization_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.drop_column("tool_call_logs", "organization_id")
    op.drop_index("ix_tool_call_logs_actor_id", table_name="tool_call_logs")
    op.drop_column("tool_call_logs", "actor_id")
    op.drop_column("tool_call_logs", "actor_type")
    # agent_run_id stays nullable on downgrade -- the pre-existing
    # NOT NULL cannot justifiably be restored over rows backfilled
    # toward non-agent shapes.
    op.alter_column("tool_call_logs", "agent_run_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_constraint("fk_approvals_incident", "approvals", type_="foreignkey")
    op.drop_column("approvals", "incident_id")
    op.drop_column("approvals", "executed_at")
    op.drop_index("ix_approvals_expires_at", table_name="approvals")
    op.drop_column("approvals", "expires_at")
    op.drop_column("approvals", "decision_reason")
    op.drop_column("approvals", "requested_reason")
