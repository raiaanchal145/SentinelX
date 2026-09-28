"""All timestamps TIMESTAMPTZ (P15 time-zone unification).

Converts the 37 remaining TIMESTAMP WITHOUT TIME ZONE columns to
TIMESTAMPTZ. Zone assumption: Etc/UTC -- every naive column is populated
by Postgres now() and the database's TimeZone is Etc/UTC (and every
Python writer uses aware UTC), so existing wall-clock values ARE UTC
instants. `USING col AT TIME ZONE 'UTC'` interprets them as UTC and
stores the absolute instant; the downgrade reverses it symmetrically
(`AT TIME ZONE 'UTC'` on a timestamptz renders that instant's UTC
wall-clock back to naive), so downgrade(upgrade(x)) is identity and
upgrade(downgrade(x)) restores the original naive bytes exactly.

One migration for all 37 columns (one file, one head, no old migration
touched). Names referenced by older downgrades are not altered. Runs on
an empty database (ALTER on empty tables is trivial) and on populated
data (the USING clause rewrites every row in the same transaction).

See docs/DATA_DICTIONARY.md "Mixed time-zone handling" (resolved by
this migration) and docs/DECISIONS.md "All timestamps TIMESTAMPTZ".

Revision ID: b9d2e3f4a5c6
Revises: a8c1e5f7b9d0
Create Date: 2026-09-28
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "b9d2e3f4a5c6"
down_revision = "a8c1e5f7b9d0"
branch_labels = None
depends_on = None

# The naive columns, as (table, column). Verified against
# information_schema on the live database; the migration re-checks each
# one at runtime (see _columns_are_naive) so it fails loudly if the
# schema has drifted rather than silently altering something else.
NAIVE_COLUMNS: list[tuple[str, str]] = [
    ("admins", "created_at"),
    ("agent_runs", "started_at"),
    ("agents", "created_at"),
    ("ai_analyses", "created_at"),
    ("alerts", "created_at"),
    ("api_keys", "created_at"),
    ("approvals", "created_at"),
    ("assets", "created_at"),
    ("assignment_rules", "created_at"),
    ("audit_logs", "created_at"),
    ("correlation_rules", "created_at"),
    ("correlations", "created_at"),
    ("detection_rules", "created_at"),
    ("escalations", "created_at"),
    ("event_sources", "created_at"),
    ("evidence", "created_at"),
    ("incident_timeline", "occurred_at"),
    ("incidents", "opened_at"),
    ("invitations", "created_at"),
    ("notifications", "created_at"),
    ("organization_settings", "created_at"),
    ("organizations", "created_at"),
    ("reports", "created_at"),
    ("security_events", "ingested_at"),
    ("sessions", "created_at"),
    ("sla_policies", "created_at"),
    ("soc_organization_assignments", "created_at"),
    ("tasks", "created_at"),
    ("team_members", "created_at"),
    ("teams", "created_at"),
    ("ticket_assignments", "created_at"),
    ("ticket_comments", "created_at"),
    ("ticket_status_history", "changed_at"),
    ("tickets", "created_at"),
    ("tool_call_logs", "created_at"),
    ("users", "created_at"),
    ("verifications", "created_at"),
]

# The zone existing naive wall-clock values are in (see docstring).
ZONE = "UTC"


def _columns_are_naive() -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'timestamp without time zone'
            """
        )
    ).fetchall()
    found = {(r[0], r[1]) for r in rows}
    expected = set(NAIVE_COLUMNS)
    return found == expected


def upgrade() -> None:
    if not _columns_are_naive():
        raise RuntimeError(
            "The set of TIMESTAMP WITHOUT TIME ZONE columns does not match "
            "this migration's list -- the schema has drifted. Re-verify the "
            "list against information_schema before altering anything."
        )
    for table, column in NAIVE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE '{ZONE}'"
        )


def downgrade() -> None:
    for table, column in reversed(NAIVE_COLUMNS):
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE '{ZONE}'"
        )
