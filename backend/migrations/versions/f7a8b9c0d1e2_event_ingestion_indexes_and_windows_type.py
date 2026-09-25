"""event ingestion: dedup unique index, query-path indexes, windows source type

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-24 00:00:00.000000

P07 event ingestion (docs/API_CONTRACT.md "Event ingestion"):

1. security_events gains a UNIQUE (organization_id, dedup_hash) index --
   the worker inserts with ON CONFLICT DO NOTHING against it, so
   replaying an identical batch adds no rows. dedup_hash stays nullable
   (Postgres UNIQUE treats NULLs as distinct; every ingested row is
   written with a hash, this only keeps the index future-proof). The
   older non-unique ix_security_events_dedup_hash stays for
   hash-only lookups; the older composite
   ix_security_events_org_occurred_at (ASC) stays so its own migration's
   downgrade keeps working untouched.

2. Query-path indexes for the events list API:
   - (organization_id, occurred_at DESC) keyset pagination on the
     timeline view;
   - (organization_id, severity, occurred_at) severity-filtered pages;
   - (organization_id, asset_id) asset-filtered pages.
   Measured against 100k rows -- see docs/reports/event-ingestion.md.

3. event_source_type gains 'windows' for the endpoint agent arriving in
   P21. Postgres cannot DROP a value from an enum, so the downgrade
   leaves it behind -- a harmless, documented remainder (nothing breaks;
   the column simply accepts a value the previous models.py didn't name).
"""

from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

TABLE = "security_events"


def upgrade() -> None:
    # The dedup unique index. Written as raw SQL so it also covers
    # pre-existing duplicate pairs explicitly rather than failing with a
    # opaque error: this is a new pipeline, but a partially-tested deploy
    # could have written duplicates (the non-unique index never stopped
    # them). Keep whichever row sorts first, newest otherwise.
    op.execute(
        """
        DELETE FROM {t} a
        USING {t} b
        WHERE a.organization_id = b.organization_id
          AND a.dedup_hash = b.dedup_hash
          AND a.ctid > b.ctid
        """.format(t=TABLE)
    )
    op.create_index(
        "uq_security_events_org_dedup_hash",
        TABLE,
        ["organization_id", "dedup_hash"],
        unique=True,
    )

    # Query-path indexes (partial: NULLed columns can't match a filter).
    op.create_index(
        "ix_security_events_org_occurred_at_desc",
        TABLE,
        [sa.text("organization_id"), sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_security_events_org_severity",
        TABLE,
        ["organization_id", "severity", "occurred_at"],
    )
    op.create_index(
        "ix_security_events_org_asset_id",
        TABLE,
        ["organization_id", "asset_id"],
    )

    # The P21 agent's source type.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE event_source_type ADD VALUE IF NOT EXISTS 'windows'")


def downgrade() -> None:
    op.drop_index("ix_security_events_org_asset_id", table_name=TABLE)
    op.drop_index("ix_security_events_org_severity", table_name=TABLE)
    op.drop_index("ix_security_events_org_occurred_at_desc", table_name=TABLE)
    op.drop_index("uq_security_events_org_dedup_hash", table_name=TABLE)
    # 'windows' stays in event_source_type: Postgres has no DROP VALUE.
    # See the module docstring -- the pre-f7a8b9c0d1e2 state is not
    # exactly restorable, and nothing depends on it being so.
