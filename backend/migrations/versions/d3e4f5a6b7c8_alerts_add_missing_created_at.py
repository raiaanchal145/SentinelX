"""alerts.created_at: add the column the model always had

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-26 00:00:00.000000

Drift repair, not a feature: `models.Alert` has always defined
`created_at` (server_default now()), but no migration in the chain ever
added the column -- f2a3b4c5d6e7 created `alerts` without it and
b1c2d3e4f5a6 restored every other P10 column EXCEPT this one. Any
query touching `alerts.created_at` (the list endpoint's row shaping)
failed with `asyncpg.exceptions.UndefinedColumnError` on a migrated
database. The pytest fixture never caught it because it builds the
schema with `Base.metadata.create_all` (models as truth) rather than
alembic -- see docs/DECISIONS.md.

- Type: plain TIMESTAMP (no time zone), matching the model's
  `sa.DateTime()` and every other created_at column in the schema --
  a TIMESTAMPTZ here would re-create the exact model/DB drift this
  migration fixes.
- No backfill needed: the server_default fills existing rows with the
  migration timestamp, which is the honest value for an audit column
  that never existed.
- downgrade simply drops the column again.
"""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("alerts", "created_at")
