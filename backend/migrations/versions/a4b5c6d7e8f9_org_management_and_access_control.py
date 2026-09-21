"""org management, soc mode, invitations and layered access control

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-09-21 00:00:00.000000

Adds the platform/organization management layer on top of the existing
admin/organization/user schema:

  * admin_level gets a third value, platform_soc_analyst -- platform-side
    SOC staff, organization_id NULL like super_admin, assigned to
    specific (managed) organizations via soc_organization_assignments
    rather than by a foreign key.
  * organizations gets a real status/soc_mode/limits/approval lifecycle
    instead of the old free-text `status` column.
  * organization_modules / organization_role_access / user_access_overrides
    are the three narrowing layers the effective-access calculation in
    app/access.py reads, in that order.
  * invitations is the only path to create a member account, a
    platform-created owner account, or a platform_soc_analyst account.
  * soc_organization_assignments is which platform_soc_analyst admins
    can see which managed organizations.

Hand-written and hand-verified against a scratch Postgres 16 database,
matching the conventions of f2a3b4c5d6e7 (raw CREATE TYPE, a pg_enum()
helper referencing already-created types, explicit Column/constraint
objects -- never --autogenerate).

Existing accounts, organizations and logins are unaffected: every
existing organization gets soc_mode='managed', status='active' (its
existing value, now typed), created_via='self_signup', and all nine
module keys enabled -- nothing anyone could already do stops working.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


MODULE_KEYS = [
    "assets", "soc", "incidents", "it_tickets", "approvals",
    "ai_agents", "device_agents", "reports", "audit_logs",
]

ADMIN_LEVEL_CHECK_NEW = (
    "(admin_level IN ('super_admin', 'platform_soc_analyst') AND organization_id IS NULL) OR "
    "(admin_level = 'organization_admin' AND organization_id IS NOT NULL)"
)
ADMIN_LEVEL_CHECK_OLD = (
    "(admin_level = 'super_admin' AND organization_id IS NULL) OR "
    "(admin_level = 'organization_admin' AND organization_id IS NOT NULL)"
)


def pg_enum(name: str, values: list[str]) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # =====================================================================
    # PART 1: admin_level gets a third value. Postgres allows ALTER TYPE
    # ... ADD VALUE inside a transaction since PG 12, but not using that
    # new value in the same transaction that added it -- op.get_context()
    # .autocommit_block() is Alembic's documented way to run this
    # statement in its own committed block and resume a normal
    # transaction afterward for the rest of the migration (which never
    # touches the new value, so this is precautionary rather than
    # strictly required by the data below, but it's the safe way to do
    # it regardless).
    # =====================================================================
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE admin_level ADD VALUE IF NOT EXISTS 'platform_soc_analyst'")

    op.drop_constraint("ck_admins_level_matches_org", "admins", type_="check")
    op.create_check_constraint("ck_admins_level_matches_org", "admins", ADMIN_LEVEL_CHECK_NEW)

    # =====================================================================
    # PART 2: organization_status / soc_mode enum types, and the
    # organizations columns that use them plus the rest of the new
    # lifecycle/limit columns.
    # =====================================================================
    op.execute("CREATE TYPE organization_status AS ENUM ('pending', 'active', 'suspended', 'archived')")
    op.execute("CREATE TYPE soc_mode AS ENUM ('managed', 'in_house')")

    # organizations.status was a plain, always-'active'-in-practice
    # VARCHAR(30); every existing row casts cleanly onto the new enum's
    # 'active' member with no backfill needed.
    op.execute("ALTER TABLE organizations ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN status TYPE organization_status "
        "USING status::organization_status"
    )
    op.execute("ALTER TABLE organizations ALTER COLUMN status SET DEFAULT 'active'")
    op.create_index("ix_organizations_status", "organizations", ["status"])

    op.add_column(
        "organizations",
        sa.Column("soc_mode", pg_enum("soc_mode", ["managed", "in_house"]), nullable=False, server_default="managed"),
    )
    op.add_column("organizations", sa.Column("max_members", sa.Integer(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("created_via", sa.String(length=20), nullable=False, server_default="self_signup"),
    )
    op.add_column("organizations", sa.Column("approved_by_admin_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_organizations_approved_by_admin", "organizations", "admins",
        ["approved_by_admin_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("organizations", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("suspension_reason", sa.Text(), nullable=True))

    # =====================================================================
    # PART 3: organization_modules / organization_role_access /
    # user_access_overrides -- the three narrowing layers access.py reads.
    # =====================================================================
    op.create_table(
        "organization_modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "module_key", name="uq_organization_modules_org_key"),
    )
    op.create_index("ix_organization_modules_organization_id", "organization_modules", ["organization_id"])

    op.create_table(
        "organization_role_access",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("role", pg_enum("user_role", ["soc_analyst", "security_manager", "it_developer", "auditor"]), nullable=False),
        sa.Column("module_key", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "role", "module_key", name="uq_org_role_access_org_role_key"),
    )
    op.create_index("ix_organization_role_access_organization_id", "organization_role_access", ["organization_id"])

    op.create_table(
        "user_access_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=40), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("set_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["set_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "module_key", name="uq_user_access_overrides_user_key"),
    )
    op.create_index("ix_user_access_overrides_organization_id", "user_access_overrides", ["organization_id"])

    # =====================================================================
    # PART 4: invitations -- the only path to a member, platform-created
    # owner, or platform_soc_analyst account.
    # =====================================================================
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        # NULL only for kind == 'platform_soc'.
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("role", pg_enum("user_role", ["soc_analyst", "security_manager", "it_developer", "auditor"]), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("invited_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_account_type", sa.String(length=10), nullable=True),
        sa.Column("accepted_account_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invited_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_invitations_organization_id", "invitations", ["organization_id"])
    # One pending invitation per (organization_id, email) for a member/
    # owner invite ...
    op.create_index(
        "uq_invitations_pending_org_email", "invitations", ["organization_id", "email"],
        unique=True, postgresql_where=sa.text("status = 'pending' AND organization_id IS NOT NULL"),
    )
    # ... and, since platform_soc invitations have organization_id NULL,
    # one pending platform_soc invitation per email.
    op.create_index(
        "uq_invitations_pending_email_platform", "invitations", ["email"],
        unique=True, postgresql_where=sa.text("status = 'pending' AND organization_id IS NULL"),
    )

    # =====================================================================
    # PART 5: soc_organization_assignments -- which platform_soc_analyst
    # admins can see which managed organizations.
    # =====================================================================
    op.create_table(
        "soc_organization_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admin_id", "organization_id", name="uq_soc_org_assignments_admin_org"),
    )
    op.create_index("ix_soc_organization_assignments_admin_id", "soc_organization_assignments", ["admin_id"])
    op.create_index("ix_soc_organization_assignments_organization_id", "soc_organization_assignments", ["organization_id"])

    # =====================================================================
    # PART 6: pending_registrations gets an optional organization_industry
    # column, alongside the existing organization_name, so the simplified
    # (organization-owner-only) register form can carry an industry value
    # through to the Organization created in verify_email().
    # =====================================================================
    op.add_column(
        "pending_registrations",
        sa.Column("organization_industry", sa.String(length=120), nullable=True),
    )

    # =====================================================================
    # PART 7: backfill -- every existing organization gets every module
    # key enabled, so nothing anyone could already do regresses.
    # =====================================================================
    module_values_sql = ", ".join(f"('{key}')" for key in MODULE_KEYS)
    op.execute(f"""
        INSERT INTO organization_modules (id, organization_id, module_key, enabled, updated_at)
        SELECT gen_random_uuid(), o.id, m.key, true, now()
        FROM organizations o
        CROSS JOIN (VALUES {module_values_sql}) AS m(key)
    """)


def downgrade() -> None:
    # Reverse PART 7 is implicit in dropping organization_modules below.

    # Reverse PART 6
    op.drop_column("pending_registrations", "organization_industry")

    # Reverse PART 5
    op.drop_table("soc_organization_assignments")

    # Reverse PART 4
    op.drop_table("invitations")

    # Reverse PART 3
    op.drop_table("user_access_overrides")
    op.drop_table("organization_role_access")
    op.drop_table("organization_modules")

    # Reverse PART 2
    op.drop_column("organizations", "suspension_reason")
    op.drop_column("organizations", "suspended_at")
    op.drop_column("organizations", "approved_at")
    op.drop_constraint("fk_organizations_approved_by_admin", "organizations", type_="foreignkey")
    op.drop_column("organizations", "approved_by_admin_id")
    op.drop_column("organizations", "created_via")
    op.drop_column("organizations", "max_members")
    op.drop_column("organizations", "soc_mode")
    op.drop_index("ix_organizations_status", table_name="organizations")
    op.execute("ALTER TABLE organizations ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE organizations ALTER COLUMN status TYPE VARCHAR(30) USING status::text")
    op.execute("ALTER TABLE organizations ALTER COLUMN status SET DEFAULT 'active'")
    op.execute("DROP TYPE soc_mode")
    op.execute("DROP TYPE organization_status")

    # Reverse PART 1: remove platform_soc_analyst. Postgres has no ALTER
    # TYPE ... DROP VALUE, so -- same rename/recreate/cast/drop dance
    # f2a3b4c5d6e7 already uses for user_role -- narrow admin_level back
    # to its original two values. Any account actually using the removed
    # value has to go first: delete platform_soc_analyst admins (their
    # soc_organization_assignments rows are already gone with that table
    # above; account_emails has no FK, so it's cleaned up by hand) and
    # any platform_soc_analyst pending_registrations rows.
    op.execute("""
        DELETE FROM account_emails
        WHERE account_type = 'admin' AND account_id IN (
            SELECT id FROM admins WHERE admin_level = 'platform_soc_analyst'
        )
    """)
    op.execute("DELETE FROM admins WHERE admin_level = 'platform_soc_analyst'")
    op.execute("DELETE FROM pending_registrations WHERE admin_level = 'platform_soc_analyst'")

    op.drop_constraint("ck_admins_level_matches_org", "admins", type_="check")

    op.execute("ALTER TYPE admin_level RENAME TO admin_level_old")
    op.execute("CREATE TYPE admin_level AS ENUM ('super_admin', 'organization_admin')")

    op.execute("ALTER TABLE admins ALTER COLUMN admin_level DROP DEFAULT")
    op.execute("ALTER TABLE admins ALTER COLUMN admin_level TYPE admin_level USING admin_level::text::admin_level")
    op.execute("ALTER TABLE admins ALTER COLUMN admin_level SET DEFAULT 'organization_admin'")

    op.execute(
        "ALTER TABLE pending_registrations ALTER COLUMN admin_level TYPE admin_level "
        "USING admin_level::text::admin_level"
    )

    op.execute("DROP TYPE admin_level_old")

    op.create_check_constraint("ck_admins_level_matches_org", "admins", ADMIN_LEVEL_CHECK_OLD)
