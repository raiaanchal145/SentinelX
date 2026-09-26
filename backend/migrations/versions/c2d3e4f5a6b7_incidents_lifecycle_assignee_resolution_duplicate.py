"""incidents lifecycle: assignee, resolution summary, closure reason, duplicate parent

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-26 00:00:00.000000

The incidents milestone (docs/API_CONTRACT.md "Incidents"): the tables
already exist from the pipeline migration (d1e2f3a4b5c6) but no API
wrote incident rows yet, so widening is safe -- there are no rows to
backfill and the downgrade simply returns to the pipeline shape.

1. incidents --
   - assigned_account_type/assigned_account_id: polymorphic assignee,
     the same shape alerts got in P10 (a platform SOC analyst admins
     row or an in-house soc_analyst users row), with the matching
     queue index;
   - resolution_summary (required by the transition to CLOSED),
   - closure_reason (required by FALSE_POSITIVE and DUPLICATE),
   - duplicate_of_id (self-FK -- DUPLICATE names its parent incident;
     SET NULL so deleting an organization's rows in tests never
     cascades into a broken reference on merge unmerge... the parent
     can't be deleted through the API anyway, CASCADE handles org
     removal through incidents.organization_id's own FK);
2. no enum changes: IncidentStatus already carries every state the
   lifecycle needs (models.py -- CONTAINMENT/VERIFICATION are the
   enum's own names for the lifecycle's contained/pending-verification
   states, stored uppercase via values_callable).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("assigned_account_type", sa.String(10), nullable=True))
    op.add_column("incidents", sa.Column("assigned_account_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("incidents", sa.Column("resolution_summary", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("closure_reason", sa.Text(), nullable=True))
    op.add_column(
        "incidents",
        sa.Column(
            "duplicate_of_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="SET NULL", use_alter=True, name="fk_incidents_duplicate_of"),
            nullable=True,
        ),
    )
    op.create_index("ix_incidents_assigned", "incidents", ["assigned_account_type", "assigned_account_id"])
    op.create_index(
        "ix_incidents_org_opened",
        "incidents",
        ["organization_id", sa.text("opened_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_org_opened", table_name="incidents")
    op.drop_index("ix_incidents_assigned", table_name="incidents")
    # use_alter was needed only because the self-FK cycles the table's
    # own create; dropping the column directly is fine.
    op.drop_column("incidents", "duplicate_of_id")
    op.drop_column("incidents", "closure_reason")
    op.drop_column("incidents", "resolution_summary")
    op.drop_column("incidents", "assigned_account_id")
    op.drop_column("incidents", "assigned_account_type")
