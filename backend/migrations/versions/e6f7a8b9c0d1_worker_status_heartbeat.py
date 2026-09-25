"""worker_status heartbeat table (single row, id=1)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-23 00:00:00.000000

The background worker (docs/DECISIONS.md -- Arq) upserts this row every
30 seconds so the API can report worker liveness from Postgres alone.
Downgrade drops the table; the heartbeat row is disposable by design.
"""

from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_name", sa.String(length=80), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("worker_status")
