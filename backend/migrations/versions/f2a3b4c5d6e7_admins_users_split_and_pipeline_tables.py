"""split admins/users and add the full detection-to-remediation pipeline

Revision ID: f2a3b4c5d6e7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-20 00:00:00.000000

This migration was written by hand (no --autogenerate) and hand-verified
by translating it into raw SQL and running it end to end -- including a
downgrade and a second upgrade -- against a scratch Postgres database,
since this sandbox cannot install sqlalchemy/alembic itself to run the
real thing. See the PR/commit message for the exact verification steps
and the ones still to run on a real dev machine.

WHAT THIS DOES
1. Splits `users` into `admins` (super_admin / organization_admin) and a
   narrower `users` (soc_analyst / security_manager / it_developer /
   auditor). Existing admin-role rows are moved out of `users` and into
   `admins` before the `user_role` enum is narrowed.
2. Adds `account_emails`, the table that enforces "one email, one
   account, whichever table it's in" -- see the model docstring on
   AccountEmail for why a table instead of an app-only check.
3. Adds every table for the Event -> Alert -> Incident -> Ticket ->
   Remediation -> Verification -> Close pipeline, plus the AI-agent,
   evidence, audit, reporting and notification tables around it.

Do NOT hand-edit the four migrations before this one. Pull this with
`alembic upgrade head` only -- never `alembic revision --autogenerate`
against these models (see backend/README.md).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Enum types created up front (user_role is handled later, in-place, once
# the admin-role rows have been moved out of `users` -- see PART 5 below).
# ---------------------------------------------------------------------------

NEW_ENUMS = [
    ("admin_level", ["super_admin", "organization_admin"]),
    ("actor_type", ["admin", "user", "ai_agent", "system"]),
    ("event_source_type", ["linux_auth", "application", "docker", "network", "custom_json", "test"]),
    ("event_severity", ["critical", "high", "medium", "low", "info"]),
    ("detection_rule_type", ["threshold", "sequence", "pattern", "statistical"]),
    ("alert_status", ["new", "triaged", "investigating", "dismissed", "converted"]),
    ("incident_status", [
        "NEW", "TRIAGED", "INVESTIGATING", "CONTAINMENT", "REMEDIATION",
        "VERIFICATION", "RESOLVED", "CLOSED", "FALSE_POSITIVE", "DUPLICATE",
        "ESCALATED", "REOPENED",
    ]),
    ("ticket_status", [
        "OPEN", "TRIAGED", "ASSIGNED", "ACKNOWLEDGED", "INVESTIGATING",
        "REMEDIATION", "VERIFICATION", "RESOLVED", "CLOSED",
    ]),
    ("task_status", ["open", "in_progress", "completed", "blocked"]),
    ("approval_risk_level", ["read_only", "low", "high"]),
    ("approval_status", ["pending", "approved", "rejected", "expired"]),
    ("verification_result", ["verified", "failed", "reopened"]),
    ("evidence_type", ["log", "file", "screenshot", "note", "command_output"]),
    ("agent_type", ["triage", "context", "threat_analysis", "incident", "report", "orchestrator"]),
    ("notification_channel", ["in_app", "email"]),
    ("report_type", ["incident", "management", "sla", "audit"]),
]


def pg_enum(name: str, values: list[str]) -> postgresql.ENUM:
    """A reference to an enum type this migration already created via raw
    SQL (see NEW_ENUMS) -- create_type=False so op.create_table doesn't
    try (and fail) to create it again."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # =====================================================================
    # PART 1: new enum types
    # =====================================================================
    for name, values in NEW_ENUMS:
        values_sql = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({values_sql})")

    event_severity = pg_enum("event_severity", dict(NEW_ENUMS)["event_severity"])
    actor_type = pg_enum("actor_type", dict(NEW_ENUMS)["actor_type"])

    # =====================================================================
    # PART 2: admins
    # =====================================================================
    op.create_table(
        "admins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("admin_level", pg_enum("admin_level", ["super_admin", "organization_admin"]),
                   nullable=False, server_default="organization_admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_code", sa.String(length=10), nullable=True),
        sa.Column("verification_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("password_reset_code", sa.String(length=10), nullable=True),
        sa.Column("password_reset_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint(
            "(admin_level = 'super_admin' AND organization_id IS NULL) OR "
            "(admin_level = 'organization_admin' AND organization_id IS NOT NULL)",
            name="ck_admins_level_matches_org",
        ),
    )

    # organizations.created_by_admin_id -- circular with admins, so it's an
    # ALTER on the already-existing table rather than a column at create time.
    op.add_column("organizations", sa.Column("created_by_admin_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_organizations_created_by_admin", "organizations", "admins",
        ["created_by_admin_id"], ["id"], ondelete="SET NULL",
    )

    # =====================================================================
    # PART 3: account_emails -- cross-table ("admins" + "users") email
    # uniqueness. Postgres has no cross-table UNIQUE constraint, so every
    # admin/user insert also writes a row here, in the same transaction;
    # the register endpoint checks/reserves the email here first, which
    # also makes the cross-table check race-safe under concurrent signups.
    # =====================================================================
    op.create_table(
        "account_emails",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=10), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("email"),
    )

    # =====================================================================
    # PART 4: teams / team_members / organization_settings / event_sources /
    # api_keys / sessions -- access, org config and collector auth
    # =====================================================================
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_organization_id", "teams", ["organization_id"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_in_team", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    op.create_table(
        "organization_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("security_policy", postgresql.JSONB(), nullable=True),
        sa.Column("notification_prefs", postgresql.JSONB(), nullable=True),
        sa.Column("auto_ticket_threshold", event_severity, nullable=True),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )

    op.create_table(
        "event_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("source_type", pg_enum("event_source_type", dict(NEW_ENUMS)["event_source_type"]), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_sources_organization_id", "event_sources", ["organization_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_source_id", sa.Uuid(), nullable=True),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_source_id"], ["event_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=10), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])

    # =====================================================================
    # PART 5: assets -- new columns + asset_tags
    # =====================================================================
    op.add_column("assets", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_assets_team", "assets", "teams", ["team_id"], ["id"], ondelete="SET NULL")
    op.add_column("assets", sa.Column("operating_system", sa.String(length=120), nullable=True))
    op.add_column("assets", sa.Column("location", sa.String(length=150), nullable=True))
    op.add_column("assets", sa.Column("environment", sa.String(length=60), nullable=True))
    op.add_column("assets", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_assets_owner_user", "assets", "users", ["owner_user_id"], ["id"], ondelete="SET NULL")
    op.add_column("assets", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_assets_organization_id", "assets", ["organization_id"])

    op.create_table(
        "asset_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "tag", name="uq_asset_tags_asset_tag"),
    )
    op.create_index("ix_asset_tags_asset_id", "asset_tags", ["asset_id"])

    # =====================================================================
    # PART 6: event pipeline -- security_events, detection_rules, alerts,
    # correlation_rules/correlations
    # =====================================================================
    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_source_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("severity", event_severity, nullable=False, server_default="info"),
        sa.Column("username", sa.String(length=150), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("dedup_hash", sa.String(length=64), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("normalized_data", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_source_id"], ["event_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_events_event_source_id", "security_events", ["event_source_id"])
    op.create_index("ix_security_events_dedup_hash", "security_events", ["dedup_hash"])
    op.create_index("ix_security_events_org_occurred_at", "security_events", ["organization_id", "occurred_at"])

    op.create_table(
        "detection_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_type", pg_enum("detection_rule_type", dict(NEW_ENUMS)["detection_rule_type"]), nullable=False),
        sa.Column("condition", postgresql.JSONB(), nullable=False),
        sa.Column("severity", event_severity, nullable=False, server_default="medium"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mitre_technique", sa.String(length=20), nullable=True),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detection_rules_organization_id", "detection_rules", ["organization_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("detection_rule_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("severity", event_severity, nullable=False, server_default="medium"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", pg_enum("alert_status", dict(NEW_ENUMS)["alert_status"]), nullable=False, server_default="new"),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dedup_key", sa.String(length=150), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["detection_rule_id"], ["detection_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_dedup_key", "alerts", ["dedup_key"])
    op.create_index("ix_alerts_org_status", "alerts", ["organization_id", "status"])

    op.create_table(
        "alert_events",
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["security_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id", "event_id"),
    )

    op.create_table(
        "correlation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("time_window_seconds", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_correlation_rules_organization_id", "correlation_rules", ["organization_id"])

    op.create_table(
        "correlations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_rule_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["correlation_rule_id"], ["correlation_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_correlations_organization_id", "correlations", ["organization_id"])

    op.create_table(
        "correlation_alerts",
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["correlation_id"], ["correlations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("correlation_id", "alert_id"),
    )

    # =====================================================================
    # PART 7: incidents + link tables + timeline
    # =====================================================================
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("severity", event_severity, nullable=False, server_default="medium"),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", pg_enum("incident_status", dict(NEW_ENUMS)["incident_status"]), nullable=False, server_default="NEW"),
        sa.Column("primary_asset_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_type", actor_type, nullable=False, server_default="system"),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["correlation_id"], ["correlations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_org_status", "incidents", ["organization_id", "status"])

    op.create_table(
        "incident_alerts",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("incident_id", "alert_id"),
    )
    op.create_table(
        "incident_events",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["security_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("incident_id", "event_id"),
    )
    op.create_table(
        "incident_assets",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("incident_id", "asset_id"),
    )

    op.create_table(
        "incident_timeline",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("entry_type", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("actor_type", actor_type, nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incident_timeline_incident_id", "incident_timeline", ["incident_id"])

    # =====================================================================
    # PART 8: sla_policies / tickets + assignment/comment/status history /
    # tasks / assignment_rules / escalations
    # =====================================================================
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("acknowledge_minutes", sa.Integer(), nullable=False),
        sa.Column("resolve_minutes", sa.Integer(), nullable=False),
        sa.Column("business_hours_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "priority", name="uq_sla_policies_org_priority"),
    )
    op.create_index("ix_sla_policies_organization_id", "sla_policies", ["organization_id"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_number", sa.String(length=30), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("severity", event_severity, nullable=False, server_default="medium"),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("status", pg_enum("ticket_status", dict(NEW_ENUMS)["ticket_status"]), nullable=False, server_default="OPEN"),
        sa.Column("assigned_team_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("sla_policy_id", sa.Uuid(), nullable=True),
        sa.Column("ack_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolve_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_breached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sla_policy_id"], ["sla_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "ticket_number", name="uq_tickets_org_number"),
    )
    op.create_index("ix_tickets_org_status", "tickets", ["organization_id", "status"])
    op.create_index("ix_tickets_assigned_user", "tickets", ["assigned_user_id"])
    op.create_index("ix_tickets_resolve_due_at", "tickets", ["resolve_due_at"])

    op.create_table(
        "ticket_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_team_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_by_type", actor_type, nullable=True),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_assignments_ticket_id", "ticket_assignments", ["ticket_id"])

    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("author_type", actor_type, nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_comments_ticket_id", "ticket_comments", ["ticket_id"])

    op.create_table(
        "ticket_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", pg_enum("ticket_status", dict(NEW_ENUMS)["ticket_status"]), nullable=True),
        sa.Column("to_status", pg_enum("ticket_status", dict(NEW_ENUMS)["ticket_status"]), nullable=False),
        sa.Column("changed_by_type", actor_type, nullable=True),
        sa.Column("changed_by_id", sa.Uuid(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_status_history_ticket_id", "ticket_status_history", ["ticket_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", pg_enum("task_status", dict(NEW_ENUMS)["task_status"]), nullable=False, server_default="open"),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_ticket_id", "tasks", ["ticket_id"])

    op.create_table(
        "assignment_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("match_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("assign_to_team_id", sa.Uuid(), nullable=True),
        sa.Column("priority_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assign_to_team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignment_rules_organization_id", "assignment_rules", ["organization_id"])

    op.create_table(
        "escalations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("escalated_from", sa.Uuid(), nullable=True),
        sa.Column("escalated_to_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["escalated_from"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["escalated_to_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ticket_id IS NOT NULL OR incident_id IS NOT NULL", name="ck_escalations_has_target"),
    )
    op.create_index("ix_escalations_ticket_id", "escalations", ["ticket_id"])
    op.create_index("ix_escalations_incident_id", "escalations", ["incident_id"])

    # =====================================================================
    # PART 9: approvals / evidence / verifications
    # =====================================================================
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_type", actor_type, nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("action_payload", postgresql.JSONB(), nullable=False),
        sa.Column("risk_level", pg_enum("approval_risk_level", dict(NEW_ENUMS)["approval_risk_level"]), nullable=False),
        sa.Column("status", pg_enum("approval_status", dict(NEW_ENUMS)["approval_status"]), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_organization_id", "approvals", ["organization_id"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_type", pg_enum("evidence_type", dict(NEW_ENUMS)["evidence_type"]), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_ref", sa.String(length=500), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("added_by_type", actor_type, nullable=False),
        sa.Column("added_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        # RESTRICT: evidence is part of the record of an incident and
        # shouldn't silently vanish if the incident row is ever deleted.
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_organization_id", "evidence", ["organization_id"])

    op.create_table(
        "verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("verified_by_type", actor_type, nullable=False),
        sa.Column("verified_by_id", sa.Uuid(), nullable=True),
        sa.Column("method", sa.String(length=120), nullable=True),
        sa.Column("result", pg_enum("verification_result", dict(NEW_ENUMS)["verification_result"]), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verifications_ticket_id", "verifications", ["ticket_id"])

    # =====================================================================
    # PART 10: AI agent layer
    # =====================================================================
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("agent_type", pg_enum("agent_type", dict(NEW_ENUMS)["agent_type"]), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("system_prompt_version", sa.String(length=30), nullable=True),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        # RESTRICT: an agent's definition shouldn't be deletable out from
        # under its run history.
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_organization_id", "agent_runs", ["organization_id"])
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])

    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("recommended_actions", postgresql.JSONB(), nullable=True),
        sa.Column("severity_suggestion", event_severity, nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_analyses_organization_id", "ai_analyses", ["organization_id"])
    op.create_index("ix_ai_analyses_agent_run_id", "ai_analyses", ["agent_run_id"])

    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=True),
        sa.Column("risk_level", pg_enum("approval_risk_level", dict(NEW_ENUMS)["approval_risk_level"]), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_call_logs_agent_run_id", "tool_call_logs", ["agent_run_id"])

    # =====================================================================
    # PART 11: notifications / audit_logs / reports / system_metrics_daily
    # =====================================================================
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_type", actor_type, nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("channel", pg_enum("notification_channel", dict(NEW_ENUMS)["notification_channel"]), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("related_type", sa.String(length=40), nullable=True),
        sa.Column("related_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"])
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        # RESTRICT: append-only audit trail -- an organization row can't
        # take its audit history down with it.
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_org_created_at", "audit_logs", ["organization_id", "created_at"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", pg_enum("report_type", dict(NEW_ENUMS)["report_type"]), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_by_type", actor_type, nullable=False, server_default="system"),
        sa.Column("generated_by_id", sa.Uuid(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column("file_ref", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_organization_id", "reports", ["organization_id"])

    op.create_table(
        "system_metrics_daily",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mttd_seconds", sa.Integer(), nullable=True),
        sa.Column("mtta_seconds", sa.Integer(), nullable=True),
        sa.Column("mttr_seconds", sa.Integer(), nullable=True),
        sa.Column("alert_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("incident_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sla_compliance_pct", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "date"),
    )

    # =====================================================================
    # PART 12: DATA MIGRATION -- move super_admin/organization_admin rows
    # out of `users` and into `admins`, before the user_role enum is
    # narrowed. Also repairs two dev-data edge cases: an
    # organization_admin left with no organization, and (further below,
    # after the move) any remaining plain user left with no organization
    # once the admin rows are gone -- both get a fresh personal
    # organization rather than blocking the migration.
    # =====================================================================

    # 12a. Give every org-less organization_admin a personal org first --
    # the CHECK constraint on admins requires organization_admin rows to
    # have one. gen_random_uuid() is evaluated once per CTE row, so the
    # same id is used in both the insert and the update below.
    op.execute("""
        WITH missing AS (
            SELECT id AS user_id, name, gen_random_uuid() AS new_org_id
            FROM users
            WHERE role = 'organization_admin' AND organization_id IS NULL
        ),
        ins AS (
            INSERT INTO organizations (id, name, status, created_at)
            SELECT new_org_id, COALESCE(NULLIF(name, ''), 'Organization') || ' (auto-created)', 'active', now()
            FROM missing
            RETURNING id
        )
        UPDATE users u SET organization_id = m.new_org_id
        FROM missing m
        WHERE u.id = m.user_id
    """)

    # 12b. Copy super_admin / organization_admin rows into admins.
    # super_admin always gets organization_id NULL, per the platform rule
    # that only organization_admin accounts are org-scoped.
    op.execute("""
        INSERT INTO admins (
            id, organization_id, name, email, password_hash, admin_level,
            is_active, is_verified, verification_code, verification_code_expires_at,
            failed_login_attempts, password_reset_code, password_reset_code_expires_at,
            created_at
        )
        SELECT
            id,
            CASE WHEN role = 'super_admin' THEN NULL ELSE organization_id END,
            name, email, password_hash,
            CASE WHEN role = 'super_admin' THEN 'super_admin' ELSE 'organization_admin' END::admin_level,
            is_active, is_verified, verification_code, verification_code_expires_at,
            failed_login_attempts, password_reset_code, password_reset_code_expires_at,
            created_at
        FROM users
        WHERE role IN ('super_admin', 'organization_admin')
    """)

    # 12c. Backfill account_emails for every existing admin and user.
    op.execute("INSERT INTO account_emails (email, account_type, account_id) SELECT email, 'admin', id FROM admins")
    op.execute("""
        INSERT INTO account_emails (email, account_type, account_id)
        SELECT email, 'user', id FROM users WHERE role NOT IN ('super_admin', 'organization_admin')
    """)

    # 12d. Remove the migrated rows from users.
    op.execute("DELETE FROM users WHERE role IN ('super_admin', 'organization_admin')")

    # =====================================================================
    # PART 13: pending_registrations -- new columns for the admin/user split
    # =====================================================================
    op.alter_column("pending_registrations", "role", nullable=True)
    op.add_column("pending_registrations", sa.Column("account_type", sa.String(length=10), nullable=False, server_default="user"))
    op.add_column("pending_registrations", sa.Column("admin_level", pg_enum("admin_level", ["super_admin", "organization_admin"]), nullable=True))
    op.add_column("pending_registrations", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_pending_registrations_organization", "pending_registrations", "organizations",
        ["organization_id"], ["id"], ondelete="CASCADE",
    )
    op.add_column("pending_registrations", sa.Column("organization_name", sa.String(length=200), nullable=True))

    # =====================================================================
    # PART 14: narrow user_role (drop super_admin/organization_admin, add
    # security_manager) -- safe now that no row in users or
    # pending_registrations still holds either removed value. Postgres has
    # no ALTER TYPE ... DROP VALUE, so this is the standard
    # rename-recreate-cast-drop dance, applied to both columns that use it.
    # =====================================================================
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")
    op.execute("CREATE TYPE user_role AS ENUM ('soc_analyst', 'security_manager', 'it_developer', 'auditor')")

    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'soc_analyst'")

    op.execute("ALTER TABLE pending_registrations ALTER COLUMN role TYPE user_role USING role::text::user_role")

    op.execute("DROP TYPE user_role_old")

    op.create_check_constraint(
        "ck_pending_registrations_type_matches_fields",
        "pending_registrations",
        "(account_type = 'admin' AND admin_level IS NOT NULL AND role IS NULL) OR "
        "(account_type = 'user' AND role IS NOT NULL AND admin_level IS NULL)",
    )

    # =====================================================================
    # PART 15: users -- organization_id NOT NULL (with backfill), team_id,
    # last_login_at
    # =====================================================================
    op.execute("""
        WITH missing AS (
            SELECT id AS user_id, name, gen_random_uuid() AS new_org_id
            FROM users
            WHERE organization_id IS NULL
        ),
        ins AS (
            INSERT INTO organizations (id, name, status, created_at)
            SELECT new_org_id, COALESCE(NULLIF(name, ''), 'Organization') || ' (auto-created)', 'active', now()
            FROM missing
            RETURNING id
        )
        UPDATE users u SET organization_id = m.new_org_id
        FROM missing m
        WHERE u.id = m.user_id
    """)
    op.alter_column("users", "organization_id", nullable=False)

    op.add_column("users", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_users_team", "users", "teams", ["team_id"], ["id"], ondelete="SET NULL")
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Reverse PART 15
    op.drop_column("users", "last_login_at")
    op.drop_constraint("fk_users_team", "users", type_="foreignkey")
    op.drop_column("users", "team_id")
    op.alter_column("users", "organization_id", nullable=True)

    # Reverse PART 14 / PART 13's CHECK constraint: restore the original
    # 5-value user_role enum. Any row that ended up with the new
    # 'security_manager' value has no equivalent in the old enum --
    # remapped to soc_analyst so the cast can succeed (documented, lossy,
    # but keeps the downgrade itself from failing outright).
    op.drop_constraint("ck_pending_registrations_type_matches_fields", "pending_registrations", type_="check")

    op.execute("UPDATE users SET role = 'soc_analyst' WHERE role = 'security_manager'")
    op.execute("UPDATE pending_registrations SET role = 'soc_analyst' WHERE role = 'security_manager'")

    op.execute("ALTER TYPE user_role RENAME TO user_role_new")
    op.execute("CREATE TYPE user_role AS ENUM ('super_admin', 'organization_admin', 'soc_analyst', 'it_developer', 'auditor')")

    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'soc_analyst'")

    # pending_registrations.role is about to become NOT NULL again; fill
    # any NULL (admin-type) rows with a placeholder so both the cast and
    # the NOT NULL constraint succeed.
    op.execute("UPDATE pending_registrations SET role = 'soc_analyst' WHERE role IS NULL")
    op.execute("ALTER TABLE pending_registrations ALTER COLUMN role TYPE user_role USING role::text::user_role")

    op.execute("DROP TYPE user_role_new")

    # Reverse PART 13
    op.alter_column("pending_registrations", "role", nullable=False)
    op.drop_column("pending_registrations", "organization_name")
    op.drop_constraint("fk_pending_registrations_organization", "pending_registrations", type_="foreignkey")
    op.drop_column("pending_registrations", "organization_id")
    op.drop_column("pending_registrations", "admin_level")
    op.drop_column("pending_registrations", "account_type")

    # Reverse PART 12: move admins back into users, drop account_emails rows
    op.execute("""
        INSERT INTO users (
            id, organization_id, name, email, password_hash, role, is_active,
            is_verified, verification_code, verification_code_expires_at,
            failed_login_attempts, password_reset_code, password_reset_code_expires_at,
            created_at
        )
        SELECT
            id, organization_id, name, email, password_hash,
            CASE WHEN admin_level = 'super_admin' THEN 'super_admin' ELSE 'organization_admin' END::user_role,
            is_active, is_verified, verification_code, verification_code_expires_at,
            failed_login_attempts, password_reset_code, password_reset_code_expires_at,
            created_at
        FROM admins
    """)
    op.execute("DELETE FROM account_emails")
    op.execute("DELETE FROM admins")

    # Reverse PARTS 6-11: drop every new pipeline table, in exact reverse
    # creation order (each was created after everything it references, so
    # this order is FK-safe without needing CASCADE).
    for table in [
        "system_metrics_daily", "reports", "audit_logs", "notifications",
        "tool_call_logs", "ai_analyses", "agent_runs", "agents",
        "verifications", "evidence", "approvals",
        "escalations", "assignment_rules", "tasks", "ticket_status_history",
        "ticket_comments", "ticket_assignments", "tickets", "sla_policies",
        "incident_timeline", "incident_assets", "incident_events", "incident_alerts",
        "incidents", "correlation_alerts", "correlations", "correlation_rules",
        "alert_events", "alerts", "detection_rules", "security_events",
        "asset_tags",
    ]:
        op.drop_table(table)

    # Reverse PART 5: assets new columns
    op.drop_column("assets", "last_seen_at")
    op.drop_constraint("fk_assets_owner_user", "assets", type_="foreignkey")
    op.drop_column("assets", "owner_user_id")
    op.drop_column("assets", "environment")
    op.drop_column("assets", "location")
    op.drop_column("assets", "operating_system")
    op.drop_constraint("fk_assets_team", "assets", type_="foreignkey")
    op.drop_column("assets", "team_id")
    op.drop_index("ix_assets_organization_id", table_name="assets")

    # Reverse PART 4
    for table in ["sessions", "api_keys", "event_sources", "organization_settings", "team_members", "teams"]:
        op.drop_table(table)

    # Reverse PART 3
    op.drop_table("account_emails")

    # Reverse PART 2
    op.drop_constraint("fk_organizations_created_by_admin", "organizations", type_="foreignkey")
    op.drop_column("organizations", "created_by_admin_id")
    op.drop_table("admins")

    # Reverse PART 1
    for name, _values in reversed(NEW_ENUMS):
        op.execute(f"DROP TYPE {name}")
