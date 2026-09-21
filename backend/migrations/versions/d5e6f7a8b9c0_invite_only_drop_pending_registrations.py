"""invite-only: drop pending_registrations, remove organization_status 'pending'

Revision ID: d5e6f7a8b9c0
Revises: b8c9d0e1f2a3
Create Date: 2026-09-21 00:00:00.000000

SentinelX becomes invite-only (docs/DECISIONS.md): accounts are created
only by accepting an invitation, and organizations are created ACTIVE by
the platform admin together with the owner's invitation. That removes:

1. The `pending_registrations` table. Any rows in it are registration
   attempts that were never verified; with self-signup gone there is no
   flow that can ever consume them, so any unexpired registration codes
   they hold are simply DISCARDED -- nobody can finish those signups, and
   the emails they reserved are freed for future invitations.

2. The `pending` value of the `organization_status` enum. Postgres enum
   values cannot be dropped in place, so the type is rebuilt: create a
   new type without the value, ALTER the column to the new type, drop
   the old type. Before the column is moved, every `pending`
   organization is converted to `active` (this is a no-op on any database
   where none exist -- the dev database had zero; the count is printed
   to the migration log either way).

Downgrade recreates the empty structures (the table with its columns and
check constraint, the enum with all four original values). No data is
restored -- pending registrations were discarded, and converted
organizations stay active.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Convert any pending organizations to active BEFORE the enum
    # value disappears. The count is logged so the operator sees exactly
    # what was converted.
    # ------------------------------------------------------------------
    from sqlalchemy import text
    conn = op.get_bind()
    pending_total = conn.execute(
        text("SELECT count(*) FROM organizations WHERE status = 'pending'")
    ).scalar() or 0
    print(f"[invite-only migration] organizations with status='pending' to convert: {pending_total}")

    op.execute("UPDATE organizations SET status = 'active' WHERE status = 'pending'")

    # ------------------------------------------------------------------
    # 2. Rebuild organization_status without 'pending'. Postgres cannot
    # DROP VALUE from an enum; the type is renamed, a new one created,
    # the column altered, and the old type dropped. The index on status
    # is dropped first (ALTER COLUMN TYPE would rewrite it anyway, but
    # dropping/recreating keeps the operation explicit) and recreated.
    # ------------------------------------------------------------------
    # The column's server default ('active'::organization_status) can't be
    # cast automatically across the type swap -- drop it first, restore
    # it after against the new type.
    op.execute("ALTER TABLE organizations ALTER COLUMN status DROP DEFAULT")
    op.execute("DROP INDEX IF EXISTS ix_organizations_status")
    op.execute("ALTER TYPE organization_status RENAME TO organization_status_old")
    op.execute("CREATE TYPE organization_status AS ENUM ('active', 'suspended', 'archived')")
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN status TYPE organization_status "
        "USING status::text::organization_status"
    )
    op.execute("DROP TYPE organization_status_old")
    op.execute("ALTER TABLE organizations ALTER COLUMN status SET DEFAULT 'active'::organization_status")
    op.create_index("ix_organizations_status", "organizations", ["status"])

    # ------------------------------------------------------------------
    # 3. Drop the registration staging table. Unexpired codes it held are
    # discarded by design -- the registration flow no longer exists.
    # ------------------------------------------------------------------
    op.drop_table("pending_registrations")


def downgrade() -> None:
    # Recreate the structures; data is NOT restored (see module docstring).
    # The two enum-typed columns REFERENCE the existing user_role/
    # admin_level types -- postgresql.ENUM(..., create_type=False) means
    # "this type already exists, just use it" (a plain sa.Enum would try
    # to CREATE the type again -> DuplicateObjectError). Same helper
    # pattern as the a4b5c6d7e8f9 migration's pg_enum().
    user_role_enum = PG_ENUM(name="user_role", create_type=False)
    admin_level_enum = PG_ENUM(name="admin_level", create_type=False)

    op.create_table(
        "pending_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=10), nullable=False, server_default="user"),
        sa.Column("role", user_role_enum, nullable=True),
        sa.Column("admin_level", admin_level_enum, nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("organization_name", sa.String(length=200), nullable=True),
        sa.Column("organization_industry", sa.String(length=120), nullable=True),
        sa.Column("verification_code", sa.String(length=10), nullable=False),
        sa.Column("verification_code_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint(
            "(account_type = 'admin' AND admin_level IS NOT NULL AND role IS NULL) OR "
            "(account_type = 'user' AND role IS NOT NULL AND admin_level IS NULL)",
            name="ck_pending_registrations_type_matches_fields",
        ),
    )

    # Restore the 'pending' enum value the same way it was removed
    # (default dropped, type rebuilt, default restored).
    op.execute("ALTER TABLE organizations ALTER COLUMN status DROP DEFAULT")
    op.execute("DROP INDEX IF EXISTS ix_organizations_status")
    op.execute("ALTER TYPE organization_status RENAME TO organization_status_new")
    op.execute(
        "CREATE TYPE organization_status AS ENUM ('pending', 'active', 'suspended', 'archived')"
    )
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN status TYPE organization_status "
        "USING status::text::organization_status"
    )
    op.execute("DROP TYPE organization_status_new")
    op.execute("ALTER TABLE organizations ALTER COLUMN status SET DEFAULT 'active'::organization_status")
    op.create_index("ix_organizations_status", "organizations", ["status"])
