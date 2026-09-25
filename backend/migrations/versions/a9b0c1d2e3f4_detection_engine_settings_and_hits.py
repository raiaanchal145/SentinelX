"""detection engine: organization_rule_settings, rule_hits, unique built-in names

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-09-25 00:00:00.000000

P23 detection engine (docs/API_CONTRACT.md "Detection rules"):

1. organization_rule_settings -- one row per (organization, rule)
   enable/disable of a BUILT-IN rule (organization_id NULL). Absence of
   a row means "use the rule row's own enabled flag"; the API only
   writes rows for explicit overrides. ondelete CASCADE both ways --
   deleting an organization or (hypothetically) a rule removes its
   settings; no orphans.

2. rule_hits -- the detection engine's output record (rule, org, group
   key, contributing event ids, window start/end). This is what P10's
   alert pipeline will read; chosen over a queue message because hits
   need queryable history with their contributing event ids and window,
   not fire-and-forget delivery. event_ids is JSONB (uuid strings)
   rather than an association table: a hit's event list is written once
   and never joined from the event side -- the read path is always
   "hits for an organization", never "which hits did this event
   contribute to" (dedup_hash already covers the event-side lookup).

3. Partial unique index on detection_rules.name WHERE organization_id
   IS NULL -- built-in rules are seeded idempotently by name at worker
   startup; the index makes the seed's ON CONFLICT DO UPDATE safe
   against double-seeding and race. Per-organization custom rules (P24)
   may reuse a built-in's name, so the index is partial.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a9b0c1d2e3f4"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

# The older f2a3b4c5d6e7 migration creates detection_rules; its own
# downgrade drops the whole table, so nothing here needs preserving.


def upgrade() -> None:
    op.create_table(
        "organization_rule_settings",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("detection_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by_admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True),
        sa.PrimaryKeyConstraint("organization_id", "rule_id"),
    )
    op.create_index(
        "ix_organization_rule_settings_rule_id",
        "organization_rule_settings",
        ["rule_id"],
    )

    op.create_table(
        "rule_hits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("detection_rules.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_name", sa.String(150), nullable=False),
        sa.Column("severity", postgresql.ENUM(name="event_severity", create_type=False), nullable=False),
        sa.Column("group_key", sa.String(255), nullable=False),
        sa.Column("event_ids", postgresql.JSONB, nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_rule_hits_org_created",
        "rule_hits",
        ["organization_id", sa.text("created_at DESC")],
    )

    op.create_index(
        "uq_detection_rules_builtin_name",
        "detection_rules",
        ["name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_detection_rules_builtin_name", table_name="detection_rules")
    op.drop_index("ix_rule_hits_org_created", table_name="rule_hits")
    op.drop_table("rule_hits")
    op.drop_index("ix_organization_rule_settings_rule_id", table_name="organization_rule_settings")
    op.drop_table("organization_rule_settings")
