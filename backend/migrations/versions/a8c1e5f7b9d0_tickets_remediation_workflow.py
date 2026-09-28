"""Tickets remediation workflow (P13).

Revision ID: a8c1e5f7b9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-09-27

- tickets.asset_id (FK -> assets, ON DELETE SET NULL): auto-creation dedups
  on (incident, asset) and the priority formula needs the asset's
  criticality; tickets previously reached assets only through incidents.
- tickets.sla_at_risk: worker-stamped (>=80% of the window elapsed), kept
  separate from sla_breached so the UI can show a third state.
- organization_settings.auto_ticket_min_confidence: the confidence half of
  the auto-creation threshold (the severity half already existed as
  auto_ticket_threshold, nullable = "feature off" for both halves).
- SLA policy backfill: every organization with no sla_policies rows gets
  the P1..P4 defaults (docs/DECISIONS.md "Default SLA policies").
"""
from alembic import op
import sqlalchemy as sa

revision = "a8c1e5f7b9d0"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None

# The default policies written for every organization missing them --
# kept in one place so docs/API_CONTRACT.md and the seeding code can
# reference the same table.
DEFAULT_SLA_MINUTES = {
    "P1": (15, 240),
    "P2": (30, 480),
    "P3": (60, 1440),
    "P4": (240, 4320),
}


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("asset_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tickets_asset_id", "tickets", "assets", ["asset_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_tickets_asset_id", "tickets", ["asset_id"])

    op.add_column(
        "tickets",
        sa.Column("sla_at_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "organization_settings",
        sa.Column("auto_ticket_min_confidence", sa.Float(), nullable=True),
    )

    # Backfill default SLA policies for organizations that have none
    # (existing orgs; new orgs are seeded at creation by the API layer).
    conn = op.get_bind()
    org_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM organizations"))]
    for org_id in org_ids:
        has_any = conn.execute(
            sa.text("SELECT 1 FROM sla_policies WHERE organization_id = :org LIMIT 1"),
            {"org": org_id},
        ).scalar()
        if has_any:
            continue
        for priority, (ack, resolve) in DEFAULT_SLA_MINUTES.items():
            conn.execute(
                sa.text(
                    "INSERT INTO sla_policies (id, organization_id, priority, "
                    "acknowledge_minutes, resolve_minutes, business_hours_only) "
                    "VALUES (gen_random_uuid(), :org, :priority, :ack, :resolve, false)"
                ),
                {"org": org_id, "priority": priority, "ack": ack, "resolve": resolve},
            )


def downgrade() -> None:
    op.drop_column("organization_settings", "auto_ticket_min_confidence")
    op.drop_column("tickets", "sla_at_risk")
    op.drop_index("ix_tickets_asset_id", table_name="tickets")
    # Name preserved for older downgrades' references (docs/CONVENTIONS.md).
    op.drop_constraint("fk_tickets_asset_id", "tickets", type_="foreignkey")
    op.drop_column("tickets", "asset_id")
