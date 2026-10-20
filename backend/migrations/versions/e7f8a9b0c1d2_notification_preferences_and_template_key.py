"""Notification preferences + template keys (P16 notifications).

Two changes, one migration:

1. `notification_preferences` -- one row per (account, event_key)
   carrying the in_app/email booleans. Rows are opt-OUT: the service
   treats a missing row as "all channels on" (docs/DECISIONS.md
   "Notification preferences are opt-out defaults-on"), so existing
   accounts need no backfill and the table starts empty.
2. `notifications.template_key` -- the event key that produced the
   row (e.g. "ticket.assigned"), so the frontend can render icons and
   the preferences page can name what it silences.

Revision ID: e7f8a9b0c1d2
Revises: b9d2e3f4a5c6
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7f8a9b0c1d2"
down_revision = "b9d2e3f4a5c6"
branch_labels = None
depends_on = None

PREF_TABLE = "notification_preferences"


def upgrade() -> None:
    op.create_table(
        PREF_TABLE,
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        # Polymorphic account reference (admins | users), like
        # notifications.recipient_id -- no FK by design. References the
        # SHARED actor_type enum (models.ActorType); create_type=False
        # (the house pattern) or CREATE TYPE fails on the existing enum.
        sa.Column(
            "account_type",
            postgresql.ENUM(
                "admin",
                "user",
                "ai_agent",
                "system",
                name="actor_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("account_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=80), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_notification_preferences_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_type",
            "account_id",
            "event_key",
            name="uq_notification_preferences_account_event",
        ),
    )
    op.create_index(
        "ix_notification_preferences_account",
        PREF_TABLE,
        ["account_type", "account_id"],
    )

    op.add_column(
        "notifications",
        sa.Column("template_key", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "template_key")
    op.drop_index("ix_notification_preferences_account", table_name=PREF_TABLE)
    op.drop_table(PREF_TABLE)
